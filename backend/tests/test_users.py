import asyncio
import json
from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import password_hasher
from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models import AuditLog, User, UserRole, UserSession


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
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_user(
    factory: sessionmaker[Session],
    username: str,
    *,
    role: UserRole,
    password: str = "correct horse battery staple",
    active: bool = True,
    must_change_password: bool = False,
) -> User:
    with factory() as db:
        user = User(
            username=username,
            email=f"{username}@example.test",
            display_name=username.title(),
            password_hash=password_hasher.hash(password),
            role=role,
            is_active=active,
            must_change_password=must_change_password,
        )
        db.add(user)
        db.commit()
        return user


async def login(client: httpx.AsyncClient, username: str, password: str = "correct horse battery staple") -> httpx.Response:
    return await client.post("/api/auth/login", json={"username": username, "password": password})


def test_user_list_is_admin_only_paginated_and_never_exposes_hashes(database: sessionmaker[Session]) -> None:
    add_user(database, "admin", role=UserRole.ADMIN)
    add_user(database, "viewer", role=UserRole.VIEWER)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as viewer:
            assert (await login(viewer, "viewer")).status_code == 200
            denied = await viewer.get("/api/users")
            assert denied.status_code == 403
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as admin:
            assert (await login(admin, "admin")).status_code == 200
            response = await admin.get("/api/users", params={"limit": 1, "offset": 1})
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 2
            assert body["limit"] == 1
            assert body["offset"] == 1
            assert len(body["items"]) == 1
            assert "password_hash" not in json.dumps(body)
            assert "temporary_password" not in json.dumps(body)

    asyncio.run(exercise())
    with database() as db:
        denial = db.scalar(select(AuditLog).where(AuditLog.action == "auth.authorization_denied"))
        assert denial is not None


def test_create_returns_one_temporary_password_hashes_it_and_conflicts_on_duplicates(
    database: sessionmaker[Session],
) -> None:
    add_user(database, "admin", role=UserRole.ADMIN)

    async def exercise() -> tuple[dict[str, object], httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            payload = {
                "username": "created",
                "email": "created@example.test",
                "display_name": "Created User",
                "role": "editor",
            }
            created = await client.post("/api/users", json=payload)
            assert created.status_code == 201
            duplicate = await client.post("/api/users", json={**payload, "email": "other@example.test"})
            return created.json(), duplicate

    body, duplicate = asyncio.run(exercise())
    temporary_password = body["temporary_password"]
    assert isinstance(temporary_password, str) and len(temporary_password) >= 12
    assert body["must_change_password"] is True
    assert body["role"] == "editor"
    assert "password_hash" not in body
    assert duplicate.status_code == 409

    with database() as db:
        created = db.scalar(select(User).where(User.username == "created"))
        assert created is not None
        assert created.password_hash.startswith("$argon2id$")
        assert password_hasher.verify(created.password_hash, temporary_password)
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action.like("users.%"))))
        serialized_logs = json.dumps([log.details for log in logs])
        assert temporary_password not in serialized_logs
        assert "password" not in serialized_logs
        assert {log.action for log in logs} == {"users.created", "users.create_denied"}


def test_update_profile_role_and_last_admin_guards_are_audited(database: sessionmaker[Session]) -> None:
    first = add_user(database, "first-admin", role=UserRole.ADMIN)
    second = add_user(database, "second-admin", role=UserRole.ADMIN)
    viewer = add_user(database, "viewer", role=UserRole.VIEWER)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "first-admin")).status_code == 200
            updated = await client.patch(
                f"/api/users/{viewer.id}",
                json={"display_name": "Updated Viewer", "role": "editor"},
            )
            assert updated.status_code == 200
            assert updated.json()["display_name"] == "Updated Viewer"
            assert updated.json()["role"] == "editor"

            self_demotion = await client.patch(f"/api/users/{first.id}", json={"role": "viewer"})
            assert self_demotion.status_code == 409
            demote_other = await client.patch(f"/api/users/{second.id}", json={"role": "viewer"})
            assert demote_other.status_code == 200
            self_disable = await client.post(f"/api/users/{first.id}/disable")
            assert self_disable.status_code == 409

    asyncio.run(exercise())
    with database() as db:
        assert db.get(User, first.id).role is UserRole.ADMIN
        assert db.get(User, first.id).is_active is True
        assert db.get(User, second.id).role is UserRole.VIEWER
        reasons = [log.details["reason"] for log in db.scalars(select(AuditLog).where(AuditLog.action.like("users.%_denied")))]
        assert "self_demotion" in reasons
        assert "self_disable" in reasons


def test_cannot_disable_or_demote_the_only_active_admin(database: sessionmaker[Session]) -> None:
    actor = add_user(database, "actor", role=UserRole.ADMIN)
    only_other_active_admin = add_user(database, "only-other", role=UserRole.ADMIN)
    add_user(database, "inactive-admin", role=UserRole.ADMIN, active=False)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "actor")).status_code == 200
            assert (await client.post(f"/api/users/{only_other_active_admin.id}/disable")).status_code == 200
            assert (await client.patch(f"/api/users/{actor.id}", json={"role": "editor"})).status_code == 409

    asyncio.run(exercise())
    with database() as db:
        persisted_actor = db.get(User, actor.id)
        assert persisted_actor is not None and persisted_actor.role is UserRole.ADMIN and persisted_actor.is_active
        assert db.scalar(select(AuditLog).where(AuditLog.action == "users.update_denied")).details == {
            "reason": "self_demotion"
        }


def test_disable_revokes_sessions_and_enable_restores_login(database: sessionmaker[Session]) -> None:
    add_user(database, "admin", role=UserRole.ADMIN)
    target = add_user(database, "target", role=UserRole.VIEWER)

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as target_client:
            assert (await login(target_client, "target")).status_code == 200
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as admin:
                assert (await login(admin, "admin")).status_code == 200
                disabled = await admin.post(f"/api/users/{target.id}/disable")
                assert disabled.status_code == 200 and disabled.json()["is_active"] is False
                assert (await target_client.get("/api/auth/me")).status_code == 401
                enabled = await admin.post(f"/api/users/{target.id}/enable")
                assert enabled.status_code == 200 and enabled.json()["is_active"] is True
            assert (await login(target_client, "target")).status_code == 200

    asyncio.run(exercise())
    with database() as db:
        sessions = list(db.scalars(select(UserSession).where(UserSession.user_id == target.id).order_by(UserSession.created_at)))
        assert len(sessions) == 2
        assert sessions[0].revoked_at is not None
        assert sessions[1].revoked_at is None


def test_reset_forces_change_and_change_revokes_other_sessions_without_leaking_secrets(
    database: sessionmaker[Session],
) -> None:
    add_user(database, "admin", role=UserRole.ADMIN)
    target = add_user(database, "target", role=UserRole.VIEWER)
    new_password = "new correct horse battery staple"

    async def exercise() -> str:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as existing:
            assert (await login(existing, "target")).status_code == 200
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as admin:
                assert (await login(admin, "admin")).status_code == 200
                reset = await admin.post(f"/api/users/{target.id}/reset-password")
                assert reset.status_code == 200
                reset_body = reset.json()
                assert reset_body["must_change_password"] is True
                temporary_password = reset_body["temporary_password"]
            assert (await existing.get("/api/auth/me")).status_code == 401

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as primary, httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as secondary:
            assert (await login(primary, "target", temporary_password)).status_code == 200
            assert (await login(secondary, "target", temporary_password)).status_code == 200
            assert (await primary.get("/api/auth/me")).json()["must_change_password"] is True
            forced = await primary.get("/api/dashboard/summaries")
            assert forced.status_code == 403
            assert forced.json() == {"detail": "Password change required"}

            wrong = await primary.post(
                "/api/auth/change-password",
                json={"current_password": "wrong password", "new_password": new_password},
            )
            assert wrong.status_code == 400
            changed = await primary.post(
                "/api/auth/change-password",
                json={"current_password": temporary_password, "new_password": new_password},
            )
            assert changed.status_code == 200
            assert changed.json()["must_change_password"] is False
            assert (await primary.get("/api/dashboard/summaries")).status_code == 200
            assert (await secondary.get("/api/auth/me")).status_code == 401

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as fresh:
            assert (await login(fresh, "target", temporary_password)).status_code == 401
            assert (await login(fresh, "target", new_password)).status_code == 200
        return temporary_password

    temporary_password = asyncio.run(exercise())
    with database() as db:
        persisted = db.get(User, target.id)
        assert persisted is not None and persisted.must_change_password is False
        assert password_hasher.verify(persisted.password_hash, new_password)
        security_logs = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(
                        (
                            "users.password_reset",
                            "auth.password_change_required",
                            "auth.password_change_denied",
                            "auth.password_changed",
                        )
                    )
                )
            )
        )
        assert {log.action for log in security_logs} == {
            "users.password_reset",
            "auth.password_change_required",
            "auth.password_change_denied",
            "auth.password_changed",
        }
        details = json.dumps([log.details for log in security_logs])
        assert temporary_password not in details
        assert new_password not in details
