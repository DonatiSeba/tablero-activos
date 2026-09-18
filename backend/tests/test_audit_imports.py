import asyncio
from collections.abc import Generator
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import imports as imports_api
from backend.app.audit_imports import AUDIT_HEADERS, match_audit_identifier, parse_audit_report
from backend.app.auth import password_hasher
from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models import (
    Asset,
    AssetAlias,
    AssetObservation,
    AuditMatchReason,
    AuditMatchStrategy,
    CostCenter,
    CostCenterStatus,
    ImportBatch,
    ReconciliationCase,
    User,
    UserRole,
)
from backend.app.system_imports import ImportValidationError, normalize_asset_code


def workbook_bytes(
    rows_by_sheet: dict[str, list[list[object]]], headers: list[str] | None = None, reference_sheet: bool = False
) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, rows in rows_by_sheet.items():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(["Physical audit"])
        sheet.append([])
        sheet.append(headers or list(AUDIT_HEADERS))
        for row in rows:
            sheet.append(row)
    if reference_sheet:
        reference = workbook.create_sheet("Activos en sistema BG reference")
        reference.append(["Bridge reference only"])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-long-enough-for-signing")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "3600")
    monkeypatch.setenv("IMPORT_STORAGE_PATH", str(tmp_path / "imports"))
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def add_user_and_center(factory: sessionmaker[Session], role: UserRole = UserRole.EDITOR) -> None:
    with factory() as db:
        db.add_all(
            [
                User(
                    username="audit-user", email="audit@example.test", display_name="Audit User",
                    password_hash=password_hasher.hash("correct horse battery staple"), role=role, is_active=True,
                ),
                CostCenter(code="190", name="Operations", status=CostCenterStatus.ACTIVE),
            ]
        )
        db.commit()


async def client() -> httpx.AsyncClient:
    result = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    login = await result.post("/api/auth/login", json={"username": "audit-user", "password": "correct horse battery staple"})
    assert login.status_code == 200
    return result


def test_audit_parser_requires_row_three_a_to_k_and_preserves_l_and_source_position() -> None:
    content = workbook_bytes(
        {"Physical 1": [[2, " Asset  01 ", "machine", "brand", "model", "works", "good", "private note", "yes", "190", "190", ""]]},
        reference_sheet=True,
    )
    report = parse_audit_report(content)
    row = report.rows[0]
    assert report.sheet_names == ("Physical 1",)
    assert row.quantity == 2
    assert row.identifier == " Asset  01 "
    assert row.original_data["source_sheet"] == "Physical 1"
    assert row.original_data["source_row"] == 4
    assert row.original_data["cells"][11] == {"column": 12, "header": None, "value": None}

    malformed_headers = list(AUDIT_HEADERS)
    malformed_headers[4] = "MODELO"
    with pytest.raises(ImportValidationError) as malformed:
        parse_audit_report(workbook_bytes({"Attempted audit": [[1] * 11]}, malformed_headers))
    assert malformed.value.code == "invalid_audit_layout"
    with pytest.raises(ImportValidationError) as duplicate:
        parse_audit_report(workbook_bytes({"Attempted audit": [[1] * 12]}, list(AUDIT_HEADERS) + ["CANTIDAD"]))
    assert duplicate.value.code == "invalid_audit_layout"
    with pytest.raises(ImportValidationError) as absent:
        parse_audit_report(workbook_bytes({}, reference_sheet=True))
    assert absent.value.code == "no_audit_sheets"


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "1", True, None])
def test_audit_parser_rejects_non_positive_or_non_numeric_quantities(quantity: object) -> None:
    with pytest.raises(ImportValidationError) as invalid:
        parse_audit_report(workbook_bytes({"Physical": [[quantity, None, "machine"] + [None] * 8]}))
    assert invalid.value.code == "invalid_quantity"


def test_audit_parser_skips_fully_blank_tail_rows() -> None:
    report = parse_audit_report(
        workbook_bytes({"Physical": [[1, "AUDIT-01", "machine"] + [None] * 8, [None] * 11]})
    )
    assert len(report.rows) == 1
    assert report.rows[0].original_data["source_row"] == 4


def test_matching_is_exact_then_unique_normalized_only(database: sessionmaker[Session]) -> None:
    with database() as db:
        exact = Asset(original_code="A B", normalized_code=normalize_asset_code("A B"), description="do not search description")
        normalized = Asset(original_code="C D", normalized_code=normalize_asset_code("C D"))
        duplicate_one = Asset(original_code="D E", normalized_code=normalize_asset_code("D E"))
        duplicate_two = Asset(original_code="DE", normalized_code=normalize_asset_code("D E"))
        db.add_all([exact, normalized, duplicate_one, duplicate_two])
        db.commit()
        assert match_audit_identifier(db, "A B").strategy is AuditMatchStrategy.EXACT_ORIGINAL_CODE
        unique = match_audit_identifier(db, " C  D ")
        assert unique.candidate_asset is normalized
        assert unique.strategy is AuditMatchStrategy.NORMALIZED_CODE
        assert match_audit_identifier(db, " D E ").reason is AuditMatchReason.AMBIGUOUS_NORMALIZED_CANDIDATE
        assert match_audit_identifier(db, "not present").reason is AuditMatchReason.NO_NORMALIZED_CANDIDATE
        assert match_audit_identifier(db, " ").reason is AuditMatchReason.MISSING_IDENTIFIER
        assert match_audit_identifier(db, "A-B").reason is AuditMatchReason.NO_NORMALIZED_CANDIDATE


def test_editor_audit_import_creates_one_case_per_row_without_source_mutation(database: sessionmaker[Session], tmp_path: Path) -> None:
    add_user_and_center(database)
    with database() as db:
        db.add_all(
            [
                Asset(original_code="EXACT", normalized_code="EXACT"),
                Asset(original_code="Norm Code", normalized_code="NORMCODE"),
                Asset(original_code="dup code", normalized_code="DUPCODE"),
                Asset(original_code="DUPCODE", normalized_code="DUPCODE"),
            ]
        )
        db.commit()
    content = workbook_bytes(
        {"Physical": [
            [2, "EXACT", "machine", "brand", "model", "works", "good", "secret note", "yes", "190", "190", None],
            [1, " Norm Code ", "machine", "brand", "model", "fails", "bad", "secret note", "yes", "190", "190", None],
            [1, "DUP CODE", "machine", "brand", "model", "works", "good", "secret note", "yes", "190", "190", None],
            [1, None, "machine", "brand", "model", "works", "good", "secret note", "yes", "190", "190", None],
        ]},
        reference_sheet=True,
    )

    async def submit() -> httpx.Response:
        active = await client()
        try:
            return await active.post(
                "/api/imports/audit", files={"file": ("physical.xlsx", content)},
                data={"report_date": "2026-06-27", "cost_center_code": "190"},
            )
        finally:
            await active.aclose()

    response = asyncio.run(submit())
    assert response.status_code == 201
    assert response.json()["match_counts"] == {
        "exact_original_code": 1, "normalized_code": 1, "missing_identifier": 1,
        "no_normalized_candidate": 0, "ambiguous_normalized_candidate": 1,
    }
    assert "secret note" not in response.text
    with database() as db:
        observations = list(db.scalars(select(AssetObservation).where(AssetObservation.source == "audit")))
        cases = list(db.scalars(select(ReconciliationCase)))
        batch = db.scalar(select(ImportBatch).where(ImportBatch.source == "audit"))
        assert len(observations) == len(cases) == 4
        assert len(list(db.scalars(select(Asset)))) == 4
        assert list(db.scalars(select(AssetAlias))) == []
        assert all(observation.asset_id is None for observation in observations)
        assert sorted(str(case.match_strategy.value if case.match_strategy else case.match_reason.value) for case in cases) == [
            "ambiguous_normalized_candidate", "exact_original_code", "missing_identifier", "normalized_code"
        ]
        assert observations[0].quantity == 2
        assert observations[0].original_data["cells"][7]["value"] == "secret note"
        assert (tmp_path / "imports" / batch.storage_path).read_bytes() == content


def test_audit_import_rejects_unknown_center_duplicates_and_viewers_without_notes(database: sessionmaker[Session]) -> None:
    add_user_and_center(database)
    content = workbook_bytes({"Physical": [[1, "ID", "machine", "brand", "model", "works", "good", "private note", "yes", "190", "190"]]})

    async def submit(data: dict[str, str]) -> httpx.Response:
        active = await client()
        try:
            return await active.post("/api/imports/audit", files={"file": ("physical.xlsx", content)}, data=data)
        finally:
            await active.aclose()

    unknown = asyncio.run(submit({"report_date": "2026-06-27", "cost_center_code": "missing"}))
    assert unknown.status_code == 422 and "private note" not in unknown.text
    accepted = asyncio.run(submit({"report_date": "2026-06-27", "cost_center_code": "190"}))
    duplicate = asyncio.run(submit({"report_date": "2026-06-27", "cost_center_code": "190"}))
    assert accepted.status_code == 201 and duplicate.status_code == 409
    with database() as db:
        assert db.scalar(select(ImportBatch).where(ImportBatch.source == "audit")) is not None


def test_audit_body_limit_rejects_before_multipart_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    parser_calls: list[bool] = []
    monkeypatch.setenv("IMPORT_MAX_UPLOAD_BYTES", "1")
    monkeypatch.setattr(imports_api, "parse_audit_report", lambda _: parser_calls.append(True))

    async def submit() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as active:
            return await active.post("/api/imports/audit", content=b"xx")

    response = asyncio.run(submit())
    assert response.status_code == 413
    assert parser_calls == []


def test_audit_import_requires_editor(database: sessionmaker[Session]) -> None:
    add_user_and_center(database, UserRole.VIEWER)
    content = workbook_bytes({"Physical": [[1] + [None] * 10]})

    async def submit() -> httpx.Response:
        active = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        try:
            await active.post("/api/auth/login", json={"username": "audit-user", "password": "correct horse battery staple"})
            return await active.post("/api/imports/audit", files={"file": ("physical.xlsx", content)}, data={"report_date": "2026-06-27", "cost_center_code": "190"})
        finally:
            await active.aclose()

    assert asyncio.run(submit()).status_code == 403


def test_audit_case_constraints_and_evidence_immutability_after_migration(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(Path(__file__).resolve().parents[2] / "backend" / "alembic.ini"))
    database_path = tmp_path / "audit.sqlite"
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    with engine.begin() as db:
        db.execute(text("INSERT INTO cost_centers (id, code, name, status) VALUES ('0000000000000000000000000000000000', '190', 'Operations', 'active')"))
        db.execute(text("INSERT INTO import_batches (id, source, cost_center_id, report_date, status, original_filename, sha256, row_count) VALUES ('0000000000000000000000000000000001', 'audit', '0000000000000000000000000000000000', '2026-06-27', 'completed', 'audit.xlsx', :sha, 1)"), {"sha": "a" * 64})
        db.execute(text("INSERT INTO asset_observations (id, import_batch_id, source, event, observed_on, original_data, quantity) VALUES ('0000000000000000000000000000000002', '0000000000000000000000000000000001', 'audit', 'snapshot', '2026-06-27', '{}', 1)"))
        db.execute(text("INSERT INTO reconciliation_cases (id, audit_observation_id, cost_center_id, match_reason) VALUES ('0000000000000000000000000000000003', '0000000000000000000000000000000002', '0000000000000000000000000000000000', 'missing_identifier')"))
        with pytest.raises(IntegrityError):
            db.execute(text("INSERT INTO reconciliation_cases (id, audit_observation_id, cost_center_id, match_strategy, match_reason) VALUES ('0000000000000000000000000000000004', '0000000000000000000000000000000002', '0000000000000000000000000000000000', 'normalized_code', 'missing_identifier')"))
        with pytest.raises(IntegrityError, match="immutable"):
            db.execute(text("UPDATE asset_observations SET quantity = 2 WHERE id = '0000000000000000000000000000000002'"))
    engine.dispose()
