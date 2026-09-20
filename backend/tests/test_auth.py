import asyncio
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import Depends, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from starlette.requests import Request
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import auth
from backend.app.auth import DUMMY_PASSWORD_HASH, password_hasher, require_admin
from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models import AuditLog, User, UserRole, UserSession


@app.get("/_test/admin-only")
def admin_only(user: User = Depends(require_admin)) -> dict[str, str]:
    return {"username": user.username}


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-long-enough-for-signing")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "3600")
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_user(factory: sessionmaker[Session], *, role: UserRole = UserRole.VIEWER, active: bool = True) -> User:
    user = User(
        username="alice",
        email="alice@example.test",
        display_name="Alice",
        password_hash=password_hasher.hash("correct horse battery staple"),
        role=role,
        is_active=active,
    )
    with factory() as db:
        db.add(user)
        db.commit()
        return user


def test_login_me_and_logout_use_argon2id_signed_database_session(database: sessionmaker[Session]) -> None:
    user = add_user(database)
    assert user.password_hash.startswith("$argon2id$")

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            login = await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse battery staple"})
            assert login.status_code == 200
            assert login.json() == {
                "id": str(user.id),
                "username": "alice",
                "display_name": "Alice",
                "role": "viewer",
                "must_change_password": False,
            }
            assert "HttpOnly" in login.headers["set-cookie"]
            assert "SameSite=lax" in login.headers["set-cookie"]
            assert "Secure" not in login.headers["set-cookie"]

            assert (await client.get("/api/auth/me")).json()["username"] == "alice"
            logout = await client.post("/api/auth/logout")
            assert logout.status_code == 204
            assert (await client.get("/api/auth/me")).status_code == 401

    asyncio.run(exercise())

    with database() as db:
        session = db.scalar(select(UserSession))
        assert session is not None and session.revoked_at is not None
        actions = list(db.scalars(select(AuditLog.action).order_by(AuditLog.created_at)))
        assert "auth.login" in actions
        assert "auth.logout" in actions


def test_login_uses_secure_cookie_outside_development(
    database: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    add_user(database)
    monkeypatch.setenv("APP_ENV", "production")

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            return await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse battery staple"})

    response = asyncio.run(exercise())
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_login_rejects_bad_password_and_writes_audit_record(database: sessionmaker[Session]) -> None:
    add_user(database)
    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})

    response = asyncio.run(exercise())
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    with database() as db:
        assert db.scalar(select(AuditLog.action)) == "auth.login_failed"


def test_unknown_username_uses_argon2_dummy_hash(database: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    verified_hashes: list[str] = []

    class PasswordVerifier:
        @staticmethod
        def verify(password_hash: str, _: str) -> bool:
            verified_hashes.append(password_hash)
            return False

    monkeypatch.setattr(auth, "password_hasher", PasswordVerifier())

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/api/auth/login", json={"username": "nobody", "password": "not-a-password"})

    response = asyncio.run(exercise())
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert verified_hashes == [DUMMY_PASSWORD_HASH]


def test_login_with_invalid_session_secret_persists_no_state(
    database: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    add_user(database)
    monkeypatch.delenv("SESSION_SECRET")

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse battery staple"})

    response = asyncio.run(exercise())
    assert response.status_code == 500
    with database() as db:
        assert db.scalar(select(UserSession)) is None
        assert db.scalar(select(AuditLog)) is None


@pytest.mark.parametrize("secret", [None, "too-short"])
def test_startup_rejects_invalid_session_secret(monkeypatch: pytest.MonkeyPatch, secret: str | None) -> None:
    if secret is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", secret)

    async def start() -> None:
        async with app.router.lifespan_context(app):
            pytest.fail("The application accepted an invalid session configuration")

    with pytest.raises(RuntimeError, match="SESSION_SECRET must contain at least 32 characters"):
        asyncio.run(start())


def test_each_request_rechecks_active_user_and_database_session(database: sessionmaker[Session]) -> None:
    user = add_user(database)
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse battery staple"})).status_code == 200
            with database() as db:
                persisted = db.get(User, user.id)
                assert persisted is not None
                persisted.is_active = False
                db.commit()
            assert (await client.get("/api/auth/me")).status_code == 401

    asyncio.run(exercise())


def test_change_password_locks_and_refreshes_reset_state_before_mutation(
    database: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = add_user(database)
    with database() as setup_db:
        auth_session = UserSession(
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        setup_db.add(auth_session)
        setup_db.commit()
        session_id = auth_session.id

    with database() as stale_db:
        stale_user = stale_db.get(User, user.id)
        stale_session = stale_db.get(UserSession, session_id)
        assert stale_user is not None and stale_session is not None

        temporary_password = "temporary reset credential"
        with database() as reset_db:
            reset_user = reset_db.get(User, user.id)
            reset_session = reset_db.get(UserSession, session_id)
            assert reset_user is not None and reset_session is not None
            reset_hash = password_hasher.hash(temporary_password)
            reset_user.password_hash = reset_hash
            reset_user.must_change_password = True
            reset_session.revoked_at = datetime.now(timezone.utc)
            reset_db.commit()

        verified_hashes: list[str] = []

        class RecordingPasswordHasher:
            @staticmethod
            def verify(password_hash: str, password: str) -> bool:
                verified_hashes.append(password_hash)
                return password_hasher.verify(password_hash, password)

            @staticmethod
            def hash(password: str) -> str:
                return password_hasher.hash(password)

        class RecordingSession:
            def __init__(self, session: Session) -> None:
                self.session = session
                self.lock_queries: list[tuple[str, bool]] = []

            def scalar(self, statement):
                sql = str(statement.compile(dialect=postgresql.dialect()))
                populate_existing = bool(statement.get_execution_options().get("populate_existing"))
                self.lock_queries.append((sql, populate_existing))
                return self.session.scalar(statement)

            def __getattr__(self, name: str):
                return getattr(self.session, name)

        monkeypatch.setattr(auth, "password_hasher", RecordingPasswordHasher())
        recording_db = RecordingSession(stale_db)
        request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 50000)})
        request.state.auth_session = stale_session

        with pytest.raises(HTTPException) as denied:
            auth.change_password(
                credentials=auth.ChangePasswordRequest(
                    current_password="correct horse battery staple",
                    new_password="new correct horse battery staple",
                ),
                request=request,
                db=recording_db,
                user=stale_user,
            )

        assert denied.value.status_code == 401
        assert verified_hashes == [reset_hash]
        assert len(recording_db.lock_queries) == 2
        assert all("FOR UPDATE" in sql for sql, _ in recording_db.lock_queries)
        assert all(populate_existing for _, populate_existing in recording_db.lock_queries)

    with database() as verification_db:
        persisted_user = verification_db.get(User, user.id)
        persisted_session = verification_db.get(UserSession, session_id)
        assert persisted_user is not None and persisted_session is not None
        assert persisted_user.must_change_password is True
        assert password_hasher.verify(persisted_user.password_hash, temporary_password)
        assert persisted_session.revoked_at is not None


def test_denied_authorization_audit_uses_an_isolated_transaction(database: sessionmaker[Session]) -> None:
    viewer = add_user(database, role=UserRole.VIEWER)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 50000)})

    with database() as db:
        db.add(
            User(
                username="uncommitted",
                email="uncommitted@example.test",
                display_name="Uncommitted",
                password_hash=password_hasher.hash("uncommitted password"),
            )
        )
        with pytest.raises(HTTPException) as denied:
            require_admin(request=request, db=db, user=viewer)
        assert denied.value.status_code == 403
        db.rollback()

    with database() as db:
        assert db.scalar(select(User).where(User.username == "uncommitted")) is None
        denied_events = list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.authorization_denied")))
        assert len(denied_events) == 1


def test_admin_dependency_denies_viewer_and_audits_once(database: sessionmaker[Session]) -> None:
    add_user(database, role=UserRole.VIEWER)
    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await client.post("/api/auth/login", json={"username": "alice", "password": "correct horse battery staple"})).status_code == 200
            return await client.get("/_test/admin-only")

    denied = asyncio.run(exercise())
    assert denied.status_code == 403
    with database() as db:
        denied_events = list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.authorization_denied")))
        assert len(denied_events) == 1
        assert denied_events[0].details == {"required_role": "admin", "actual_role": "viewer"}
