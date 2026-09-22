import asyncio
import uuid
from collections.abc import Generator
from datetime import date

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import password_hasher
from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models import AuditLog, CostCenter, CostCenterStatus, User, UserRole


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-long-enough-for-signing")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "3600")
    engine = __import__("sqlalchemy").create_engine(
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


def add_user(factory: sessionmaker[Session], username: str, role: UserRole) -> User:
    with factory() as db:
        user = User(
            username=username,
            email=f"{username}@example.test",
            display_name=username.title(),
            password_hash=password_hasher.hash("correct horse battery staple"),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user


async def login(client: httpx.AsyncClient, username: str) -> httpx.Response:
    return await client.post(
        "/api/auth/login",
        json={"username": username, "password": "correct horse battery staple"},
    )


def test_admin_creates_and_updates_normalized_management_fields_with_audit_logs(
    database: sessionmaker[Session],
) -> None:
    admin = add_user(database, "admin", UserRole.ADMIN)

    async def exercise() -> tuple[dict[str, object], dict[str, object]]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            created_response = await client.post(
                "/api/cost-centers",
                json={
                    "code": "  CC-200  ",
                    "name": "  Field Operations  ",
                    "start_date": "2026-01-01",
                    "end_date": "2026-12-31",
                },
            )
            assert created_response.status_code == 201
            created = created_response.json()
            updated_response = await client.patch(
                f"/api/cost-centers/{created['id']}",
                json={
                    "code": "  CC-201 ",
                    "name": " Renamed Operations ",
                    "status": "inactive",
                    "start_date": "2026-02-01",
                    "end_date": None,
                },
            )
            assert updated_response.status_code == 200
            return created, updated_response.json()

    created, updated = asyncio.run(exercise())
    assert created["code"] == "CC-200"
    assert created["name"] == "Field Operations"
    assert created["status"] == "active"
    assert updated == {
        **created,
        "code": "CC-201",
        "name": "Renamed Operations",
        "status": "inactive",
        "start_date": "2026-02-01",
        "end_date": None,
        "updated_at": updated["updated_at"],
    }

    with database() as db:
        center = db.get(CostCenter, uuid.UUID(str(created["id"])))
        assert center is not None
        assert center.code == "CC-201"
        assert center.name == "Renamed Operations"
        assert center.status is CostCenterStatus.INACTIVE
        assert center.start_date == date(2026, 2, 1)
        assert center.end_date is None
        logs = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.action.in_(("cost_centers.created", "cost_centers.updated")))
                .order_by(AuditLog.created_at)
            )
        )
        assert [log.action for log in logs] == ["cost_centers.created", "cost_centers.updated"]
        assert all(log.user_id == admin.id and log.target_id == center.id for log in logs)
        assert logs[1].details == {
            "fields": ["code", "end_date", "name", "start_date", "status"]
        }


def test_editor_and_admin_can_list_with_active_filter_but_viewer_cannot(
    database: sessionmaker[Session],
) -> None:
    add_user(database, "admin", UserRole.ADMIN)
    add_user(database, "editor", UserRole.EDITOR)
    add_user(database, "viewer", UserRole.VIEWER)
    with database() as db:
        db.add_all(
            (
                CostCenter(code="A-100", name="Active", status=CostCenterStatus.ACTIVE),
                CostCenter(code="I-100", name="Inactive", status=CostCenterStatus.INACTIVE),
            )
        )
        db.commit()

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        for username in ("admin", "editor"):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                assert (await login(client, username)).status_code == 200
                all_centers = await client.get("/api/cost-centers")
                assert all_centers.status_code == 200
                assert [item["code"] for item in all_centers.json()] == ["A-100", "I-100"]
                active = await client.get("/api/cost-centers", params={"active_only": "true"})
                assert active.status_code == 200
                assert [item["code"] for item in active.json()] == ["A-100"]

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as viewer:
            assert (await login(viewer, "viewer")).status_code == 200
            denied = await viewer.get("/api/cost-centers", params={"active_only": "true"})
            assert denied.status_code == 403
            assert denied.json() == {"detail": "Insufficient privileges"}

    asyncio.run(exercise())
    with database() as db:
        denial = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "auth.authorization_denied",
                AuditLog.user_id == select(User.id).where(User.username == "viewer").scalar_subquery(),
            )
        )
        assert denial is not None
        assert denial.details == {"required_role": "editor", "actual_role": "viewer"}


def test_only_admin_can_mutate_cost_centers(database: sessionmaker[Session]) -> None:
    add_user(database, "editor", UserRole.EDITOR)
    add_user(database, "viewer", UserRole.VIEWER)
    with database() as db:
        center = CostCenter(code="LOCKED", name="Locked")
        db.add(center)
        db.commit()
        center_id = center.id

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        for username in ("editor", "viewer"):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                assert (await login(client, username)).status_code == 200
                created = await client.post(
                    "/api/cost-centers",
                    json={"code": f"{username}-center", "name": username},
                )
                updated = await client.patch(
                    f"/api/cost-centers/{center_id}",
                    json={"name": f"Changed by {username}"},
                )
                assert created.status_code == 403
                assert updated.status_code == 403

    asyncio.run(exercise())
    with database() as db:
        assert db.get(CostCenter, center_id).name == "Locked"
        assert db.scalar(select(CostCenter).where(CostCenter.code == "editor-center")) is None
        denials = list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.authorization_denied")))
        assert len(denials) == 4
        assert all(log.details["required_role"] == "admin" for log in denials)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"code": "   ", "name": "Valid"}, "value must not be blank"),
        ({"code": "VALID", "name": "   "}, "value must not be blank"),
        ({"code": "VALID", "name": "Valid", "status": "retired"}, "status must be active or inactive"),
        (
            {"code": "VALID", "name": "Valid", "start_date": "2026-02-02", "end_date": "2026-02-01"},
            "end_date must be on or after start_date",
        ),
    ],
)
def test_create_rejects_blank_invalid_status_and_invalid_dates_with_stable_errors(
    database: sessionmaker[Session], payload: dict[str, object], message: str
) -> None:
    add_user(database, "admin", UserRole.ADMIN)

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            return await client.post("/api/cost-centers", json=payload)

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == f"Value error, {message}"
    with database() as db:
        assert db.scalar(select(CostCenter)) is None


def test_empty_patch_is_rejected_with_denial_audit(database: sessionmaker[Session]) -> None:
    admin = add_user(database, "admin", UserRole.ADMIN)
    with database() as db:
        center = CostCenter(code="CC-EMPTY", name="Unchanged")
        db.add(center)
        db.commit()
        center_id = center.id

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            return await client.patch(f"/api/cost-centers/{center_id}", json={})

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.json() == {"detail": "At least one management field is required"}
    with database() as db:
        center = db.get(CostCenter, center_id)
        assert center is not None
        assert center.name == "Unchanged"
        logs = list(db.scalars(select(AuditLog).where(AuditLog.target_id == center_id)))
        assert [(log.action, log.user_id, log.details) for log in logs] == [
            ("cost_centers.update_denied", admin.id, {"reason": "no_changes"})
        ]


@pytest.mark.parametrize("field", ["code", "name", "status"])
def test_patch_rejects_explicit_null_for_required_fields(
    database: sessionmaker[Session], field: str
) -> None:
    admin = add_user(database, "admin", UserRole.ADMIN)
    with database() as db:
        center = CostCenter(code="CC-NULL", name="Required Values")
        db.add(center)
        db.commit()
        center_id = center.id

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            return await client.patch(f"/api/cost-centers/{center_id}", json={field: None})

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.json() == {"detail": "Code, name, and status cannot be null"}
    with database() as db:
        center = db.get(CostCenter, center_id)
        assert center is not None
        assert (center.code, center.name, center.status) == (
            "CC-NULL",
            "Required Values",
            CostCenterStatus.ACTIVE,
        )
        denial = db.scalar(select(AuditLog).where(AuditLog.target_id == center_id))
        assert denial is not None
        assert denial.action == "cost_centers.update_denied"
        assert denial.user_id == admin.id
        assert denial.details == {"reason": "null_required_field"}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"code": "   "}, "value must not be blank"),
        ({"name": "   "}, "value must not be blank"),
        ({"status": "retired"}, "status must be active or inactive"),
    ],
)
def test_patch_rejects_blank_and_invalid_values(
    database: sessionmaker[Session], payload: dict[str, object], message: str
) -> None:
    add_user(database, "admin", UserRole.ADMIN)
    with database() as db:
        center = CostCenter(code="CC-VALID", name="Valid")
        db.add(center)
        db.commit()
        center_id = center.id

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            return await client.patch(f"/api/cost-centers/{center_id}", json=payload)

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == f"Value error, {message}"
    with database() as db:
        center = db.get(CostCenter, center_id)
        assert center is not None
        assert (center.code, center.name, center.status) == (
            "CC-VALID",
            "Valid",
            CostCenterStatus.ACTIVE,
        )
        assert db.scalar(select(AuditLog).where(AuditLog.target_id == center_id)) is None


def test_patch_rejects_missing_cost_center_with_denial_audit(
    database: sessionmaker[Session],
) -> None:
    admin = add_user(database, "admin", UserRole.ADMIN)
    missing_id = uuid.uuid4()

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            return await client.patch(
                f"/api/cost-centers/{missing_id}",
                json={"name": "Missing"},
            )

    response = asyncio.run(exercise())
    assert response.status_code == 404
    assert response.json() == {"detail": "Cost center not found"}
    with database() as db:
        denial = db.scalar(select(AuditLog).where(AuditLog.target_id == missing_id))
        assert denial is not None
        assert denial.action == "cost_centers.update_denied"
        assert denial.user_id == admin.id
        assert denial.details == {"reason": "not_found"}


def test_patch_rejects_semantic_same_values_without_update_audit(
    database: sessionmaker[Session],
) -> None:
    admin = add_user(database, "admin", UserRole.ADMIN)
    with database() as db:
        center = CostCenter(
            code="CC-SAME",
            name="Same Values",
            status=CostCenterStatus.ACTIVE,
            start_date=date(2026, 1, 1),
            end_date=None,
        )
        db.add(center)
        db.commit()
        center_id = center.id

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            return await client.patch(
                f"/api/cost-centers/{center_id}",
                json={
                    "code": "  CC-SAME  ",
                    "name": "  Same Values  ",
                    "status": "active",
                    "start_date": "2026-01-01",
                    "end_date": None,
                },
            )

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.json() == {"detail": "At least one management field is required"}
    with database() as db:
        center = db.get(CostCenter, center_id)
        assert center is not None
        assert (center.code, center.name, center.status, center.start_date, center.end_date) == (
            "CC-SAME",
            "Same Values",
            CostCenterStatus.ACTIVE,
            date(2026, 1, 1),
            None,
        )
        logs = list(db.scalars(select(AuditLog).where(AuditLog.target_id == center_id)))
        assert [(log.action, log.user_id, log.details) for log in logs] == [
            ("cost_centers.update_denied", admin.id, {"reason": "no_changes"})
        ]


def test_duplicate_codes_and_update_date_ranges_are_rejected_without_partial_changes(
    database: sessionmaker[Session],
) -> None:
    add_user(database, "admin", UserRole.ADMIN)
    with database() as db:
        first = CostCenter(code="CC-1", name="First")
        second = CostCenter(
            code="CC-2",
            name="Second",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        db.add_all((first, second))
        db.commit()
        second_id = second.id

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            assert (await login(client, "admin")).status_code == 200
            duplicate_create = await client.post(
                "/api/cost-centers",
                json={"code": "  CC-1 ", "name": "Duplicate"},
            )
            assert duplicate_create.status_code == 409
            assert duplicate_create.json() == {"detail": "Cost center code already exists"}

            duplicate_update = await client.patch(
                f"/api/cost-centers/{second_id}",
                json={"code": " CC-1 ", "name": "Should not persist"},
            )
            assert duplicate_update.status_code == 409
            assert duplicate_update.json() == {"detail": "Cost center code already exists"}

            invalid_dates = await client.patch(
                f"/api/cost-centers/{second_id}",
                json={"name": "Also should not persist", "start_date": "2027-01-01"},
            )
            assert invalid_dates.status_code == 422
            assert invalid_dates.json() == {"detail": "end_date must be on or after start_date"}

    asyncio.run(exercise())
    with database() as db:
        second = db.get(CostCenter, second_id)
        assert second is not None
        assert second.code == "CC-2"
        assert second.name == "Second"
        assert second.start_date == date(2026, 1, 1)
        denied = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.action.like("cost_centers.%_denied"))
                .order_by(AuditLog.created_at)
            )
        )
        assert [log.details["reason"] for log in denied] == [
            "duplicate_code",
            "duplicate_code",
            "invalid_date_range",
        ]
