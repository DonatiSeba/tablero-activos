"""Local authentication, server-side authorization, and security audit helpers."""

from __future__ import annotations

import ipaddress
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, User, UserRole, UserSession

SESSION_COOKIE_NAME = "asset_session"
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60
password_hasher = PasswordHasher(type=Type.ID)
# A valid Argon2id hash is always verified for unknown usernames to make the
# expensive password-verification path independent of account existence.
DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$J1fiTuqWnD1qhlUDxdQalQ$T/AZ0P3lIfqmv+3k26G2qEbpNEXAsmnAmmN1RZdzEag"
router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: UserRole


def _environment() -> str:
    return os.environ.get("APP_ENV", "production").strip().lower()


def _session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    return secret


def _session_ttl_seconds() -> int:
    try:
        value = int(os.environ.get("SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)))
    except ValueError as error:
        raise RuntimeError("SESSION_TTL_SECONDS must be a positive integer") from error
    if value <= 0:
        raise RuntimeError("SESSION_TTL_SECONDS must be a positive integer")
    return value


def validate_session_configuration() -> None:
    """Validate cookie-signing settings before starting to serve requests."""
    _session_secret()
    _session_ttl_seconds()


@lru_cache(maxsize=1)
def _signer(secret: str) -> TimestampSigner:
    return TimestampSigner(secret, salt="asset-reconciliation.session.v1")


def _signed_session_id(session_id: uuid.UUID) -> str:
    return _signer(_session_secret()).sign(str(session_id).encode("ascii")).decode("ascii")


def _read_signed_session_id(cookie_value: str) -> uuid.UUID | None:
    try:
        value = _signer(_session_secret()).unsign(cookie_value, max_age=_session_ttl_seconds())
        return uuid.UUID(value.decode("ascii"))
    except (BadSignature, SignatureExpired, UnicodeDecodeError, ValueError):
        return None


def _request_ip(request: Request) -> str | None:
    """Return a directly connected, syntactically valid client address only."""
    if request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


def write_audit_log(
    db: Session,
    request: Request,
    *,
    action: str,
    target_entity: str,
    target_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    details: dict[str, object] | None = None,
) -> None:
    """Stage an audit record in the caller's transaction without storing secrets."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            target_entity=target_entity,
            target_id=target_id,
            details=details,
            ip_address=_request_ip(request),
        )
    )


def write_denial_audit_log(
    db: Session,
    request: Request,
    *,
    action: str,
    target_entity: str,
    user_id: uuid.UUID,
    details: dict[str, object],
) -> None:
    """Commit authorization-denial evidence without committing the caller session."""
    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as audit_db:
        write_audit_log(
            audit_db,
            request,
            action=action,
            target_entity=target_entity,
            user_id=user_id,
            details=details,
        )
        audit_db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:  # SQLite returns naive values in isolated tests.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= _now()


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    """Resolve a signed cookie to an unrevoked session and active database user."""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie:
        raise _unauthorized()
    session_id = _read_signed_session_id(cookie)
    if session_id is None:
        raise _unauthorized()

    result = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.id == session_id)
    ).one_or_none()
    if result is None:
        raise _unauthorized()
    auth_session, user = result
    if auth_session.revoked_at is not None or _is_expired(auth_session.expires_at) or not user.is_active:
        raise _unauthorized()
    request.state.auth_session = auth_session
    return user


def require_role(required_role: UserRole):
    """Build a server-side role dependency and audit authorization denials once."""
    allowed_roles = {
        UserRole.VIEWER: {UserRole.VIEWER, UserRole.EDITOR, UserRole.ADMIN},
        UserRole.EDITOR: {UserRole.EDITOR, UserRole.ADMIN},
        UserRole.ADMIN: {UserRole.ADMIN},
    }[required_role]

    def dependency(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if user.role not in allowed_roles:
            write_denial_audit_log(
                db,
                request,
                action="auth.authorization_denied",
                target_entity="role",
                user_id=user.id,
                details={"required_role": required_role.value, "actual_role": user.role.value},
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
        return user

    return dependency


require_viewer = require_role(UserRole.VIEWER)
require_editor = require_role(UserRole.EDITOR)
require_admin = require_role(UserRole.ADMIN)


@router.post("/login", response_model=CurrentUserResponse)
def login(credentials: LoginRequest, request: Request, response: Response, db: Annotated[Session, Depends(get_db)]) -> User:
    # Direct invocation is also protected when a test or embedding skips lifespan.
    validate_session_configuration()
    user = db.scalar(select(User).where(User.username == credentials.username))
    try:
        valid_password = password_hasher.verify(
            user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
            credentials.password,
        )
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        valid_password = False

    if user is None or not valid_password or not user.is_active:
        write_audit_log(
            db,
            request,
            action="auth.login_failed",
            target_entity="user",
            user_id=user.id if user is not None else None,
            details={"username": credentials.username},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(credentials.password)
    auth_session = UserSession(user_id=user.id, expires_at=_now() + timedelta(seconds=_session_ttl_seconds()))
    db.add(auth_session)
    write_audit_log(db, request, action="auth.login", target_entity="user", target_id=user.id, user_id=user.id)
    db.commit()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=_signed_session_id(auth_session.id),
        max_age=_session_ttl_seconds(),
        httponly=True,
        secure=_environment() != "development",
        samesite="lax",
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    auth_session: UserSession = request.state.auth_session
    auth_session.revoked_at = _now()
    write_audit_log(db, request, action="auth.logout", target_entity="user", target_id=user.id, user_id=user.id)
    db.commit()
    response.delete_cookie(key=SESSION_COOKIE_NAME, httponly=True, secure=_environment() != "development", samesite="lax", path="/")


@router.get("/me", response_model=CurrentUserResponse)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user
