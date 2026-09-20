"""ADMIN-only user lifecycle contracts; users are deactivated, never deleted."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import password_hasher, require_admin, write_audit_log
from .db import get_db
from .models import User, UserRole, UserSession

router = APIRouter(prefix="/api/users", tags=["users"])
TEMPORARY_PASSWORD_BYTES = 18


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class UserWithTemporaryPasswordResponse(UserResponse):
    temporary_password: str


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=1, max_length=320)
    display_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.VIEWER

    @field_validator("username", "email", "display_name")
    @classmethod
    def strip_required_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, min_length=1, max_length=320)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None

    @field_validator("username", "email", "display_name")
    @classmethod
    def strip_optional_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _temporary_password() -> str:
    """Generate a URL-safe one-time credential from the OS CSPRNG."""
    return secrets.token_urlsafe(TEMPORARY_PASSWORD_BYTES)


def _locked_active_admins(db: Session) -> list[User]:
    """Serialize administrator-reducing changes on PostgreSQL.

    Every state-changing user endpoint acquires these rows in a stable order.
    At READ COMMITTED, a concurrent waiter sees the preceding committed role or
    activation change before evaluating the last-admin invariant. SQLite omits
    FOR UPDATE, which keeps isolated compatibility tests functional.
    """
    return list(
        db.scalars(
            select(User)
            .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
    )


def _locked_user(db: Session, user_id: uuid.UUID) -> User | None:
    return db.scalar(select(User).where(User.id == user_id).with_for_update())


def _audit_denial(
    db: Session,
    request: Request,
    actor: User,
    *,
    action: str,
    target_id: uuid.UUID | None,
    reason: str,
    status_code: int,
    detail: str,
) -> None:
    write_audit_log(
        db,
        request,
        action=action,
        target_entity="user",
        target_id=target_id,
        user_id=actor.id,
        details={"reason": reason},
    )
    db.commit()
    raise HTTPException(status_code=status_code, detail=detail)


def _duplicate_field(db: Session, *, username: str, email: str, excluded_id: uuid.UUID | None = None) -> str | None:
    username_query = select(User.id).where(User.username == username)
    email_query = select(User.id).where(User.email == email)
    if excluded_id is not None:
        username_query = username_query.where(User.id != excluded_id)
        email_query = email_query.where(User.id != excluded_id)
    if db.scalar(username_query.limit(1)) is not None:
        return "username"
    if db.scalar(email_query.limit(1)) is not None:
        return "email"
    return None


def _integrity_conflict(db: Session, request: Request, actor: User, target_id: uuid.UUID | None, action: str) -> None:
    db.rollback()
    _audit_denial(
        db,
        request,
        actor,
        action=action,
        target_id=target_id,
        reason="duplicate_username_or_email",
        status_code=status.HTTP_409_CONFLICT,
        detail="Username or email already exists",
    )


def _revoke_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


@router.get("", response_model=UserListResponse)
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> UserListResponse:
    total = int(db.scalar(select(func.count()).select_from(User)) or 0)
    users = list(db.scalars(select(User).order_by(User.username, User.id).limit(limit).offset(offset)))
    return UserListResponse(items=[UserResponse.model_validate(user) for user in users], total=total, limit=limit, offset=offset)


@router.post("", response_model=UserWithTemporaryPasswordResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    _locked_active_admins(db)
    duplicate = _duplicate_field(db, username=payload.username, email=payload.email)
    if duplicate is not None:
        _audit_denial(
            db,
            request,
            actor,
            action="users.create_denied",
            target_id=None,
            reason=f"duplicate_{duplicate}",
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{duplicate.capitalize()} already exists",
        )

    temporary_password = _temporary_password()
    user = User(
        username=payload.username,
        email=payload.email,
        display_name=payload.display_name,
        password_hash=password_hasher.hash(temporary_password),
        role=payload.role,
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    try:
        db.flush()
        write_audit_log(
            db,
            request,
            action="users.created",
            target_entity="user",
            target_id=user.id,
            user_id=actor.id,
            details={"role": user.role.value},
        )
        db.commit()
    except IntegrityError:
        _integrity_conflict(db, request, actor, None, "users.create_denied")

    response = UserResponse.model_validate(user).model_dump()
    response["temporary_password"] = temporary_password
    return response


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> User:
    active_admins = _locked_active_admins(db)
    target = _locked_user(db, user_id)
    if target is None:
        _audit_denial(
            db,
            request,
            actor,
            action="users.update_denied",
            target_id=user_id,
            reason="not_found",
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        _audit_denial(
            db,
            request,
            actor,
            action="users.update_denied",
            target_id=user_id,
            reason="no_changes",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one profile or role field is required",
        )
    if any(value is None for value in changes.values()):
        _audit_denial(
            db,
            request,
            actor,
            action="users.update_denied",
            target_id=user_id,
            reason="null_field",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="User fields cannot be null",
        )

    requested_role = changes.get("role", target.role)
    if target.id == actor.id and requested_role != UserRole.ADMIN:
        _audit_denial(
            db,
            request,
            actor,
            action="users.update_denied",
            target_id=user_id,
            reason="self_demotion",
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrators cannot demote themselves",
        )
    if target.is_active and target.role == UserRole.ADMIN and requested_role != UserRole.ADMIN and len(active_admins) <= 1:
        _audit_denial(
            db,
            request,
            actor,
            action="users.update_denied",
            target_id=user_id,
            reason="last_active_admin",
            status_code=status.HTTP_409_CONFLICT,
            detail="At least one active administrator is required",
        )

    username = changes.get("username", target.username)
    email = changes.get("email", target.email)
    duplicate = _duplicate_field(db, username=username, email=email, excluded_id=target.id)
    if duplicate is not None:
        _audit_denial(
            db,
            request,
            actor,
            action="users.update_denied",
            target_id=user_id,
            reason=f"duplicate_{duplicate}",
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{duplicate.capitalize()} already exists",
        )

    for field, value in changes.items():
        setattr(target, field, value)
    try:
        db.flush()
        write_audit_log(
            db,
            request,
            action="users.updated",
            target_entity="user",
            target_id=target.id,
            user_id=actor.id,
            details={"fields": sorted(changes)},
        )
        db.commit()
    except IntegrityError:
        _integrity_conflict(db, request, actor, target.id, "users.update_denied")
    return target


@router.post("/{user_id}/disable", response_model=UserResponse)
def disable_user(
    user_id: uuid.UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> User:
    active_admins = _locked_active_admins(db)
    target = _locked_user(db, user_id)
    if target is None:
        _audit_denial(db, request, actor, action="users.disable_denied", target_id=user_id, reason="not_found", status_code=404, detail="User not found")
    if target.id == actor.id:
        _audit_denial(db, request, actor, action="users.disable_denied", target_id=user_id, reason="self_disable", status_code=409, detail="Administrators cannot disable themselves")
    if target.is_active and target.role == UserRole.ADMIN and len(active_admins) <= 1:
        _audit_denial(db, request, actor, action="users.disable_denied", target_id=user_id, reason="last_active_admin", status_code=409, detail="At least one active administrator is required")

    target.is_active = False
    _revoke_sessions(db, target.id)
    write_audit_log(db, request, action="users.disabled", target_entity="user", target_id=target.id, user_id=actor.id)
    db.commit()
    return target


@router.post("/{user_id}/enable", response_model=UserResponse)
def enable_user(
    user_id: uuid.UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> User:
    _locked_active_admins(db)
    target = _locked_user(db, user_id)
    if target is None:
        _audit_denial(db, request, actor, action="users.enable_denied", target_id=user_id, reason="not_found", status_code=404, detail="User not found")
    target.is_active = True
    write_audit_log(db, request, action="users.enabled", target_entity="user", target_id=target.id, user_id=actor.id)
    db.commit()
    return target


@router.post("/{user_id}/reset-password", response_model=UserWithTemporaryPasswordResponse)
def reset_password(
    user_id: uuid.UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    _locked_active_admins(db)
    target = _locked_user(db, user_id)
    if target is None:
        _audit_denial(db, request, actor, action="users.password_reset_denied", target_id=user_id, reason="not_found", status_code=404, detail="User not found")

    temporary_password = _temporary_password()
    target.password_hash = password_hasher.hash(temporary_password)
    target.must_change_password = True
    _revoke_sessions(db, target.id)
    write_audit_log(
        db,
        request,
        action="users.password_reset",
        target_entity="user",
        target_id=target.id,
        user_id=actor.id,
    )
    db.commit()
    response = UserResponse.model_validate(target).model_dump()
    response["temporary_password"] = temporary_password
    return response
