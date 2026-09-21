import asyncio
from collections.abc import Generator
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, event, literal, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import password_hasher
from backend.app.dashboard import _ordered_distinct_categories, _ordered_distinct_rubros
from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models import (
    Asset,
    AssetObservation,
    AuditCurrentState,
    AuditCurrentStateProjection,
    AuditMatchReason,
    AuditMatchStrategy,
    AuditReturnMarkerCategory,
    CostCenter,
    ImportBatch,
    ImportBatchStatus,
    ImportSource,
    ObservationEvent,
    ReconciliationCase,
    User,
    UserRole,
)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-that-is-long-enough-for-signing")
    monkeypatch.setenv("APP_ENV", "development")
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


def _batch(db: Session, center: CostCenter, source: ImportSource, report_date: date, suffix: int, metadata: dict | None = None) -> ImportBatch:
    batch = ImportBatch(
        source=source,
        cost_center_id=center.id,
        report_date=report_date,
        status=ImportBatchStatus.COMPLETED,
        original_filename="private.xlsx",
        sha256=f"{suffix:064x}",
        storage_path="private/path.xlsx",
        row_count=2,
        metadata_json=metadata,
    )
    db.add(batch)
    db.flush()
    return batch


def _system_data(rubro: str | None, category: str | None, product: str | None) -> dict:
    return {
        "cells": [
            {"column": 1, "header": "Rubro", "value": rubro},
            {"column": 2, "header": "Categoría", "value": category},
            {"column": 3, "header": "Producto", "value": product},
            {"column": 9, "header": "OBSERVACIONES", "value": "must never be returned"},
        ]
    }


def populate(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        viewer = User(username="viewer", email="viewer@example.test", display_name="Viewer", password_hash=password_hasher.hash("password"), role=UserRole.VIEWER)
        center = CostCenter(code="190", name="Operations")
        db.add_all((viewer, center))
        db.flush()
        asset_a = Asset(original_code="A-1", normalized_code="A-1")
        asset_b = Asset(original_code="B-1", normalized_code="B-1")
        audit_only_asset = Asset(original_code="C-1", normalized_code="C-1")
        db.add_all((asset_a, asset_b, audit_only_asset))
        db.flush()
        _batch(db, center, ImportSource.SYSTEM, date(2026, 6, 1), 1)
        system = _batch(
            db,
            center,
            ImportSource.SYSTEM,
            date(2026, 6, 30),
            2,
            {"warnings": [{"code": "missing_asset_code", "row_count": 1}, {"code": "untrusted raw note", "row_count": 99}]},
        )
        audit = _batch(db, center, ImportSource.AUDIT, date(2026, 6, 29), 3)
        db.add_all(
            (
                AssetObservation(import_batch_id=system.id, source=ImportSource.SYSTEM, event=ObservationEvent.SNAPSHOT, observed_on=system.report_date, asset_id=asset_a.id, cost_center_id=center.id, original_data=_system_data("IT", "Laptop", "ThinkPad"), reported_status="Active", quantity=Decimal("1")),
                AssetObservation(import_batch_id=system.id, source=ImportSource.SYSTEM, event=ObservationEvent.SNAPSHOT, observed_on=system.report_date, asset_id=asset_b.id, cost_center_id=center.id, original_data=_system_data("IT", "Laptop", "ThinkPad"), reported_status="Retired", quantity=Decimal("1")),
            )
        )
        audit_a = AssetObservation(import_batch_id=audit.id, source=ImportSource.AUDIT, event=ObservationEvent.SNAPSHOT, observed_on=audit.report_date, cost_center_id=center.id, original_data={"cells": []}, quantity=Decimal("1"))
        audit_b = AssetObservation(import_batch_id=audit.id, source=ImportSource.AUDIT, event=ObservationEvent.SNAPSHOT, observed_on=audit.report_date, cost_center_id=center.id, original_data={"cells": []}, quantity=Decimal("1"))
        unresolved = AssetObservation(import_batch_id=audit.id, source=ImportSource.AUDIT, event=ObservationEvent.SNAPSHOT, observed_on=audit.report_date, cost_center_id=center.id, original_data={"cells": []}, quantity=Decimal("1"))
        audit_only = AssetObservation(import_batch_id=audit.id, source=ImportSource.AUDIT, event=ObservationEvent.SNAPSHOT, observed_on=audit.report_date, cost_center_id=center.id, original_data={"cells": []}, quantity=Decimal("1"))
        db.add_all((audit_a, audit_b, unresolved, audit_only))
        db.flush()
        db.add_all(
            (
                ReconciliationCase(audit_observation_id=audit_a.id, cost_center_id=center.id, candidate_asset_id=asset_a.id, match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE),
                ReconciliationCase(audit_observation_id=audit_b.id, cost_center_id=center.id, candidate_asset_id=asset_b.id, match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE),
                ReconciliationCase(audit_observation_id=unresolved.id, cost_center_id=center.id, match_reason=AuditMatchReason.AMBIGUOUS_NORMALIZED_CANDIDATE),
                ReconciliationCase(audit_observation_id=audit_only.id, cost_center_id=center.id, candidate_asset_id=audit_only_asset.id, match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE),
                AuditCurrentStateProjection(asset_id=asset_a.id, cost_center_id=center.id, audit_observation_id=audit_a.id, state=AuditCurrentState.FOUND, marker_category=AuditReturnMarkerCategory.UNMARKED_UNKNOWN, marker_column=12, reason="resolved_audit_presence_without_recognized_return_marker", projection_version="audit_l_return_v1"),
                AuditCurrentStateProjection(asset_id=asset_b.id, cost_center_id=center.id, audit_observation_id=audit_b.id, state=AuditCurrentState.REVIEW_REQUIRED, marker_category=AuditReturnMarkerCategory.AMBIGUOUS_RETURN, marker_column=12, reason="ambiguous_column_l_return_marker_requires_review", projection_version="audit_l_return_v1"),
            )
        )
        db.commit()


async def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def test_dashboard_contracts_aggregate_server_data_and_redact_evidence(database: sessionmaker[Session]) -> None:
    populate(database)

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        api = await client()
        try:
            denied = await api.get("/api/dashboard/summaries")
            login = await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})
            assert login.status_code == 200
            return (
                denied,
                await api.get("/api/dashboard/summaries?cost_center_code=190"),
                await api.get("/api/dashboard/system-drilldown?cost_center_code=190"),
                await api.get("/api/operations/import-history?limit=1"),
                await api.get("/api/operations/review-queue?limit=1"),
            )
        finally:
            await api.aclose()

    denied, summaries, drilldown, history, queue = asyncio.run(exercise())
    assert denied.status_code == 401
    assert summaries.status_code == drilldown.status_code == history.status_code == queue.status_code == 200
    summary = summaries.json()["summaries"][0]
    assert summary["freshness"]["status"] == "report_dates_differ"
    assert summary["freshness"]["warning"] is True
    assert summary["latest_sources"]["system"]["report_date"] == "2026-06-30"
    assert summary["latest_sources"]["audit"]["report_date"] == "2026-06-29"
    assert summary["metrics"] == {
        "current_system_distinct_asset_count": 2,
        "found_count": 1,
        "returned_count": 0,
        "review_required_count": 1,
        "unresolved_audit_case_count": 1,
        "audit_only_matched_asset_count": 1,
        "not_in_management_system_for_cost_center_count": 2,
        "pending_not_accounted_count": 1,
    }
    assert summary["executive_metrics"] == {
        "system_count": 2,
        "found_in_cost_center_count": 1,
        "returned_count": 0,
        "accounted_count": 1,
        "difference_count": 1,
        "coverage_percent": 50.0,
    }
    assert summary["operational_issues"] == {
        "physical_patrimonial_difference_count": 1,
        "system_update_required_return_count": 0,
        "system_data_quality_omission_count": 1,
        "review_required_count": 1,
        "unresolved_audit_case_count": 1,
        "not_in_management_system_for_cost_center_count": 2,
    }
    donut = summary["charts"]["general_status_donut"]
    assert donut["available"] is True
    assert donut["segments"] == [
        {"key": "found_in_cost_center", "value": 1},
        {"key": "returned", "value": 0},
        {"key": "difference", "value": 1},
    ]
    assert donut["source_freshness"]["freshness"] == summary["freshness"]
    assert donut["source_freshness"]["sources"] == summary["latest_sources"]
    assert summary["charts"]["time_evolution"]["available"] is False
    assert summary["charts"]["time_evolution"]["reason"] == "fewer_than_two_comparable_snapshots"
    assert summary["charts"]["time_evolution"]["points"] == []
    product = drilldown.json()["groups"][0]["categories"][0]["products"][0]
    assert drilldown.json()["page"] == {"limit": 100, "offset": 0, "has_more": False, "total_count": 1}
    assert product["distinct_asset_count"] == 2
    assert product["status_counts"] == [{"status": "Active", "count": 1}, {"status": "Retired", "count": 1}]
    assert product["reconciliation_metrics"] == summary["executive_metrics"]
    primary_chart = drilldown.json()["charts"]["primary_stacked_bar"]
    assert primary_chart["items"] == [{"rubro": "IT", "category": "Laptop", **summary["executive_metrics"]}]
    assert primary_chart["source_freshness"] == donut["source_freshness"]
    assert drilldown.json()["charts"]["general_status_donut"]["source_freshness"] == donut["source_freshness"]
    assert "OBSERVACIONES" not in str(drilldown.json())
    import_item = history.json()["items"][0]
    assert set(import_item) == {"batch_id", "source", "cost_center", "report_date", "imported_at", "imported_by_display_name", "row_count", "status", "warning_counts", "processing_counts"}
    assert "sha256" not in str(history.json()) and "storage_path" not in str(history.json()) and "private.xlsx" not in str(history.json())
    assert queue.json()["queue_counts"] == {"unresolved_identifier": 1, "review_required_return": 1, "total": 2}
    assert queue.json()["page"]["has_more"] is True


def test_dashboard_counts_selected_system_omissions_without_other_cost_center_disclosure(database: sessionmaker[Session]) -> None:
    populate(database)
    with database() as db:
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        audit = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.AUDIT)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        audit_only_asset = db.scalar(select(Asset).where(Asset.original_code == "C-1"))
        other_center = CostCenter(code="191", name="Other cost center")
        db.add(other_center)
        db.flush()
        other_system = _batch(db, other_center, ImportSource.SYSTEM, date(2026, 6, 30), 4)
        db.add(
            AssetObservation(
                import_batch_id=other_system.id,
                source=ImportSource.SYSTEM,
                event=ObservationEvent.SNAPSHOT,
                observed_on=other_system.report_date,
                asset_id=audit_only_asset.id,
                cost_center_id=other_center.id,
                original_data=_system_data("Other", "Other", "Other"),
                quantity=Decimal("9"),
            )
        )
        duplicate_observation = AssetObservation(
            import_batch_id=audit.id,
            source=ImportSource.AUDIT,
            event=ObservationEvent.SNAPSHOT,
            observed_on=audit.report_date,
            cost_center_id=center.id,
            original_data={"cells": []},
            quantity=Decimal("9"),
        )
        db.add(duplicate_observation)
        db.flush()
        db.add(
            ReconciliationCase(
                audit_observation_id=duplicate_observation.id,
                cost_center_id=center.id,
                candidate_asset_id=audit_only_asset.id,
                match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE,
            )
        )
        db.commit()

    async def exercise() -> httpx.Response:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return await api.get("/api/dashboard/summaries?cost_center_code=190")
        finally:
            await api.aclose()

    response = asyncio.run(exercise())
    assert response.status_code == 200
    summary = response.json()["summaries"][0]
    assert summary["cost_center"] == {"code": "190", "name": "Operations"}
    assert "Other cost center" not in str(summary)
    assert summary["metrics"]["audit_only_matched_asset_count"] == 1
    assert summary["metrics"]["unresolved_audit_case_count"] == 1
    assert summary["metrics"]["not_in_management_system_for_cost_center_count"] == 2
    assert summary["operational_issues"]["not_in_management_system_for_cost_center_count"] == 2


def test_dashboard_omission_count_is_unavailable_when_a_selected_source_is_missing(database: sessionmaker[Session]) -> None:
    populate(database)
    with database() as db:
        audit_only_center = CostCenter(code="191", name="Audit only")
        system_only_center = CostCenter(code="192", name="System only")
        db.add_all((audit_only_center, system_only_center))
        db.flush()
        audit = _batch(db, audit_only_center, ImportSource.AUDIT, date(2026, 7, 1), 4)
        observation = AssetObservation(
            import_batch_id=audit.id,
            source=ImportSource.AUDIT,
            event=ObservationEvent.SNAPSHOT,
            observed_on=audit.report_date,
            cost_center_id=audit_only_center.id,
            original_data={"cells": []},
            quantity=Decimal("9"),
        )
        system = _batch(db, system_only_center, ImportSource.SYSTEM, date(2026, 7, 1), 5)
        db.add_all((observation, AssetObservation(
            import_batch_id=system.id,
            source=ImportSource.SYSTEM,
            event=ObservationEvent.SNAPSHOT,
            observed_on=system.report_date,
            cost_center_id=system_only_center.id,
            original_data=_system_data("System", "System", "System"),
            quantity=Decimal("9"),
        )))
        db.flush()
        db.add(ReconciliationCase(audit_observation_id=observation.id, cost_center_id=audit_only_center.id, match_reason=AuditMatchReason.MISSING_IDENTIFIER))
        db.commit()

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return (
                await api.get("/api/dashboard/summaries?cost_center_code=191"),
                await api.get("/api/dashboard/summaries?cost_center_code=192"),
            )
        finally:
            await api.aclose()

    audit_only, system_only = asyncio.run(exercise())
    assert audit_only.status_code == system_only.status_code == 200
    for response in (audit_only, system_only):
        summary = response.json()["summaries"][0]
        assert summary["metrics"]["not_in_management_system_for_cost_center_count"] is None
        assert summary["operational_issues"]["not_in_management_system_for_cost_center_count"] is None


def test_read_pagination_filters_and_empty_drilldown_are_bounded(database: sessionmaker[Session]) -> None:
    populate(database)

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return (
                await api.get("/api/operations/import-history?source=audit&limit=1&offset=0"),
                await api.get("/api/operations/review-queue?category=unresolved_identifier&limit=1&offset=1"),
                await api.get("/api/dashboard/system-drilldown?cost_center_code=missing"),
            )
        finally:
            await api.aclose()

    history, queue, empty = asyncio.run(exercise())
    assert history.status_code == queue.status_code == empty.status_code == 200
    assert history.json()["items"][0]["source"] == "audit"
    assert queue.json()["items"] == []
    assert queue.json()["queue_counts"]["total"] == 2
    empty_payload = empty.json()
    assert empty_payload["cost_center"] is None
    for chart in empty_payload["charts"].values():
        assert chart["source_freshness"]["freshness"]["status"] == "missing_both"
        assert chart["source_freshness"]["sources"]["system"]["report_date"] is None
        assert chart["source_freshness"]["sources"]["audit"]["report_date"] is None



def test_system_drilldown_scopes_explicit_null_category_and_product_labels(database: sessionmaker[Session]) -> None:
    populate(database)
    with database() as db:
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        system = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.SYSTEM)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        audit = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.AUDIT)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        null_category_asset = Asset(original_code="NULL-CATEGORY", normalized_code="NULL-CATEGORY")
        null_product_asset = Asset(original_code="NULL-PRODUCT", normalized_code="NULL-PRODUCT")
        db.add_all((null_category_asset, null_product_asset))
        db.flush()
        db.add_all(
            (
                AssetObservation(
                    import_batch_id=system.id,
                    source=ImportSource.SYSTEM,
                    event=ObservationEvent.SNAPSHOT,
                    observed_on=system.report_date,
                    asset_id=null_category_asset.id,
                    cost_center_id=center.id,
                    original_data=_system_data("IT", None, "Uncategorized product"),
                    quantity=Decimal("1"),
                ),
                AssetObservation(
                    import_batch_id=system.id,
                    source=ImportSource.SYSTEM,
                    event=ObservationEvent.SNAPSHOT,
                    observed_on=system.report_date,
                    asset_id=null_product_asset.id,
                    cost_center_id=center.id,
                    original_data=_system_data("IT", "Laptop", None),
                    quantity=Decimal("1"),
                ),
            )
        )
        null_category_audit = AssetObservation(
            import_batch_id=audit.id,
            source=ImportSource.AUDIT,
            event=ObservationEvent.SNAPSHOT,
            observed_on=audit.report_date,
            cost_center_id=center.id,
            original_data={"cells": []},
            quantity=Decimal("1"),
        )
        null_product_audit = AssetObservation(
            import_batch_id=audit.id,
            source=ImportSource.AUDIT,
            event=ObservationEvent.SNAPSHOT,
            observed_on=audit.report_date,
            cost_center_id=center.id,
            original_data={"cells": []},
            quantity=Decimal("1"),
        )
        db.add_all((null_category_audit, null_product_audit))
        db.flush()
        db.add_all(
            (
                ReconciliationCase(
                    audit_observation_id=null_category_audit.id,
                    cost_center_id=center.id,
                    candidate_asset_id=null_category_asset.id,
                    match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE,
                ),
                ReconciliationCase(
                    audit_observation_id=null_product_audit.id,
                    cost_center_id=center.id,
                    candidate_asset_id=null_product_asset.id,
                    match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE,
                ),
                AuditCurrentStateProjection(
                    asset_id=null_category_asset.id,
                    cost_center_id=center.id,
                    audit_observation_id=null_category_audit.id,
                    state=AuditCurrentState.FOUND,
                    marker_category=AuditReturnMarkerCategory.UNMARKED_UNKNOWN,
                    marker_column=12,
                    reason="resolved_audit_presence_without_recognized_return_marker",
                    projection_version="audit_l_return_v1",
                ),
                AuditCurrentStateProjection(
                    asset_id=null_product_asset.id,
                    cost_center_id=center.id,
                    audit_observation_id=null_product_audit.id,
                    state=AuditCurrentState.RETURNED,
                    marker_category=AuditReturnMarkerCategory.RECOGNIZED_RETURN,
                    marker_column=12,
                    reason="recognized_column_l_return_marker",
                    projection_version="audit_l_return_v1",
                ),
            )
        )
        db.commit()

    async def exercise() -> httpx.Response:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return await api.get("/api/dashboard/system-drilldown?cost_center_code=190")
        finally:
            await api.aclose()

    response = asyncio.run(exercise())
    assert response.status_code == 200
    groups = response.json()["groups"]
    it_group = next(group for group in groups if group["rubro"] == "IT")
    null_category = next(category for category in it_group["categories"] if category["category"] is None)
    assert null_category["reconciliation_metrics"] == {
        "system_count": 1,
        "found_in_cost_center_count": 1,
        "returned_count": 0,
        "accounted_count": 1,
        "difference_count": 0,
        "coverage_percent": 100.0,
    }
    assert null_category["products"][0]["reconciliation_metrics"] == null_category["reconciliation_metrics"]
    laptop = next(category for category in it_group["categories"] if category["category"] == "Laptop")
    null_product = next(product for product in laptop["products"] if product["product"] is None)
    assert null_product["reconciliation_metrics"] == {
        "system_count": 1,
        "found_in_cost_center_count": 0,
        "returned_count": 1,
        "accounted_count": 1,
        "difference_count": 0,
        "coverage_percent": 100.0,
    }
    chart_items = response.json()["charts"]["primary_stacked_bar"]["items"]
    assert next(item for item in chart_items if item["category"] is None) == {
        "rubro": "IT",
        "category": None,
        **null_category["reconciliation_metrics"],
    }


def test_dashboard_time_evolution_excludes_undated_audit_return_inferences(database: sessionmaker[Session]) -> None:
    populate(database)
    with database() as db:
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        assets = list(db.scalars(select(Asset).order_by(Asset.original_code)))
        for sequence, report_date in enumerate((date(2026, 6, 10), date(2026, 6, 20)), start=10):
            system = _batch(db, center, ImportSource.SYSTEM, report_date, sequence)
            audit = _batch(db, center, ImportSource.AUDIT, report_date, sequence + 20)
            for asset_number, asset in enumerate(assets):
                db.add(
                    AssetObservation(
                        import_batch_id=system.id,
                        source=ImportSource.SYSTEM,
                        event=ObservationEvent.SNAPSHOT,
                        observed_on=report_date,
                        asset_id=asset.id,
                        cost_center_id=center.id,
                        original_data=_system_data("IT", "Laptop", "ThinkPad"),
                        quantity=Decimal("1"),
                    )
                )
                observation = AssetObservation(
                    import_batch_id=audit.id,
                    source=ImportSource.AUDIT,
                    event=ObservationEvent.SNAPSHOT,
                    observed_on=report_date,
                    cost_center_id=center.id,
                    original_data={
                        "cells": [{"column": 12, "header": "L", "value": "DEVOLVIO"}]
                        if report_date == date(2026, 6, 10) and asset_number == 0
                        else []
                    },
                    quantity=Decimal("1"),
                )
                db.add(observation)
                db.flush()
                db.add(
                    ReconciliationCase(
                        audit_observation_id=observation.id,
                        cost_center_id=center.id,
                        candidate_asset_id=asset.id,
                        match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE,
                    )
                )
        db.commit()

    async def exercise() -> httpx.Response:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return await api.get("/api/dashboard/summaries?cost_center_code=190")
        finally:
            await api.aclose()

    response = asyncio.run(exercise())
    assert response.status_code == 200
    evolution = response.json()["summaries"][0]["charts"]["time_evolution"]
    assert evolution["available"] is True
    assert evolution["points"] == [
        {
            "report_date": "2026-06-10",
            "system_count": 3,
            "found_in_cost_center_count": 3,
            "audit_snapshot_difference_count": 0,
        },
        {
            "report_date": "2026-06-20",
            "system_count": 3,
            "found_in_cost_center_count": 3,
            "audit_snapshot_difference_count": 0,
        },
    ]
    assert evolution["return_evolution"] == {
        "available": False,
        "reason": "return_event_time_evidence_unavailable",
        "points": [],
    }


def test_system_drilldown_paginates_high_cardinality_leaf_groups_before_nesting(database: sessionmaker[Session]) -> None:
    populate(database)
    with database() as db:
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        batch = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.SYSTEM)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        db.add_all(
            AssetObservation(
                import_batch_id=batch.id,
                source=ImportSource.SYSTEM,
                event=ObservationEvent.SNAPSHOT,
                observed_on=batch.report_date,
                cost_center_id=center.id,
                original_data=_system_data("IT", "Laptop", f"Product-{number:03}"),
                reported_status="Active",
                quantity=Decimal("1"),
            )
            for number in range(102)
        )
        db.commit()

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return (
                await api.get("/api/dashboard/system-drilldown?cost_center_code=190&limit=2&offset=0"),
                await api.get("/api/dashboard/system-drilldown?cost_center_code=190&limit=1&offset=102"),
                await api.get("/api/dashboard/system-drilldown?cost_center_code=190&limit=101"),
                await api.get("/api/dashboard/system-drilldown?cost_center_code=190&offset=10001"),
            )
        finally:
            await api.aclose()

    first_page, last_page, over_limit, over_offset = asyncio.run(exercise())
    assert first_page.status_code == last_page.status_code == 200
    assert over_limit.status_code == over_offset.status_code == 422
    assert first_page.json()["page"] == {"limit": 2, "offset": 0, "has_more": True, "total_count": 103}
    first_products = first_page.json()["groups"][0]["categories"][0]["products"]
    assert [product["product"] for product in first_products] == ["Product-000", "Product-001"]
    assert last_page.json()["page"] == {"limit": 1, "offset": 102, "has_more": False, "total_count": 103}
    assert last_page.json()["groups"] == [
        {
            "rubro": "IT",
            "reconciliation_metrics": {
                "system_count": 2,
                "found_in_cost_center_count": 1,
                "returned_count": 0,
                "accounted_count": 1,
                "difference_count": 1,
                "coverage_percent": 50.0,
            },
            "categories": [
                {
                    "category": "Laptop",
                    "reconciliation_metrics": {
                        "system_count": 2,
                        "found_in_cost_center_count": 1,
                        "returned_count": 0,
                        "accounted_count": 1,
                        "difference_count": 1,
                        "coverage_percent": 50.0,
                    },
                    "products": [
                        {
                            "product": "ThinkPad",
                            "observation_count": 2,
                            "distinct_asset_count": 2,
                            "status_counts": [{"status": "Active", "count": 1}, {"status": "Retired", "count": 1}],
                            "reconciliation_metrics": {
                                "system_count": 2,
                                "found_in_cost_center_count": 1,
                                "returned_count": 0,
                                "accounted_count": 1,
                                "difference_count": 1,
                                "coverage_percent": 50.0,
                            },
                        }
                    ],
                }
            ],
        }
    ]


def test_hierarchy_options_compile_with_distinct_inside_postgresql_ordering_queries() -> None:
    rubro_rows = select(literal("rubro").label("rubro")).subquery("rubro_rows")
    category_rows = select(literal("rubro").label("rubro"), literal("category").label("category")).subquery("category_rows")

    rubro_sql = " ".join(
        str(
            _ordered_distinct_rubros(rubro_rows).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )
    category_sql = " ".join(
        str(
            _ordered_distinct_categories(category_rows, "rubro").compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )

    assert rubro_sql.startswith("SELECT anon_1.rubro FROM (SELECT DISTINCT rubro_rows.rubro AS rubro")
    assert "ORDER BY anon_1.rubro IS NOT NULL, lower(anon_1.rubro), anon_1.rubro" in rubro_sql
    assert category_sql.startswith("SELECT anon_1.category FROM (SELECT DISTINCT category_rows.category AS category")
    assert "category_rows.rubro IS NOT DISTINCT FROM 'rubro'" in category_sql
    assert "ORDER BY anon_1.category IS NOT NULL, lower(anon_1.category), anon_1.category" in category_sql


def test_rubro_reconciliation_chart_selects_and_isolates_complete_category_metrics(database: sessionmaker[Session]) -> None:
    populate(database)
    special_rubro = "Operations & Field/Δ"
    with database() as db:
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        system = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.SYSTEM)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        audit = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.AUDIT)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )

        def add_reconciled_asset(code: str, rubro: str | None, category: str | None, state: AuditCurrentState) -> None:
            asset = Asset(original_code=code, normalized_code=code)
            db.add(asset)
            db.flush()
            db.add(
                AssetObservation(
                    import_batch_id=system.id,
                    source=ImportSource.SYSTEM,
                    event=ObservationEvent.SNAPSHOT,
                    observed_on=system.report_date,
                    asset_id=asset.id,
                    cost_center_id=center.id,
                    original_data=_system_data(rubro, category, "Product"),
                    quantity=Decimal("1"),
                )
            )
            observation = AssetObservation(
                import_batch_id=audit.id,
                source=ImportSource.AUDIT,
                event=ObservationEvent.SNAPSHOT,
                observed_on=audit.report_date,
                cost_center_id=center.id,
                original_data={"cells": []},
                quantity=Decimal("1"),
            )
            db.add(observation)
            db.flush()
            db.add_all(
                (
                    ReconciliationCase(
                        audit_observation_id=observation.id,
                        cost_center_id=center.id,
                        candidate_asset_id=asset.id,
                        match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE,
                    ),
                    AuditCurrentStateProjection(
                        asset_id=asset.id,
                        cost_center_id=center.id,
                        audit_observation_id=observation.id,
                        state=state,
                        marker_category=(
                            AuditReturnMarkerCategory.RECOGNIZED_RETURN
                            if state == AuditCurrentState.RETURNED
                            else AuditReturnMarkerCategory.UNMARKED_UNKNOWN
                        ),
                        marker_column=12,
                        reason="test",
                        projection_version="audit_l_return_v1",
                    ),
                )
            )

        add_reconciled_asset("SPECIAL", special_rubro, "Encoded category", AuditCurrentState.FOUND)
        add_reconciled_asset("NULL-RUBRO", None, None, AuditCurrentState.RETURNED)
        db.commit()

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return (
                await api.get("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190"),
                await api.get("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190&rubro="),
                await api.get("/api/dashboard/rubro-reconciliation-chart", params={"cost_center_code": "190", "rubro": special_rubro}),
                await api.get("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190&rubro=IT"),
                await api.get("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190&rubro=missing"),
            )
        finally:
            await api.aclose()

    omitted, explicit_null, decoded, it_chart, invalid = asyncio.run(exercise())
    assert all(response.status_code == 200 for response in (omitted, explicit_null, decoded, it_chart, invalid))
    expected_null_selection = {"value": None, "label": "Sin rubro asignado"}
    assert omitted.json()["rubro_options"] == [
        expected_null_selection,
        {"value": "IT", "label": "IT"},
        {"value": special_rubro, "label": special_rubro},
    ]
    assert omitted.json()["selected_rubro"] == explicit_null.json()["selected_rubro"] == expected_null_selection
    assert explicit_null.json()["category_chart"] == {
        "available": True,
        "reason": None,
        "series": [
            {"key": "found_in_cost_center_count", "label": "found_in_cost_center"},
            {"key": "returned_count", "label": "returned"},
            {"key": "difference_count", "label": "difference"},
        ],
        "items": [
            {
                "category": None,
                "category_label": "Sin categoría asignada",
                "found_in_cost_center_count": 0,
                "returned_count": 1,
                "difference_count": 0,
            }
        ],
        "source_freshness": explicit_null.json()["category_chart"]["source_freshness"],
    }
    assert decoded.json()["selected_rubro"] == {"value": special_rubro, "label": special_rubro}
    assert decoded.json()["category_chart"]["items"] == [
        {
            "category": "Encoded category",
            "category_label": "Encoded category",
            "found_in_cost_center_count": 1,
            "returned_count": 0,
            "difference_count": 0,
        }
    ]
    assert it_chart.json()["category_chart"]["items"] == [
        {
            "category": "Laptop",
            "category_label": "Laptop",
            "found_in_cost_center_count": 1,
            "returned_count": 0,
            "difference_count": 1,
        }
    ]
    assert invalid.json()["category_chart"]["available"] is False
    assert invalid.json()["category_chart"]["reason"] == "invalid_rubro_selection"
    assert invalid.json()["category_chart"]["items"] == []


def test_rubro_reconciliation_chart_reports_missing_sources_and_complete_high_cardinality_categories(database: sessionmaker[Session]) -> None:
    populate(database)
    with database() as db:
        missing_system_center = CostCenter(code="191", name="Audit only")
        missing_audit_center = CostCenter(code="192", name="System only")
        db.add_all((missing_system_center, missing_audit_center))
        db.flush()
        _batch(db, missing_system_center, ImportSource.AUDIT, date(2026, 7, 1), 10)
        system_only = _batch(db, missing_audit_center, ImportSource.SYSTEM, date(2026, 7, 1), 11)
        db.add(
            AssetObservation(
                import_batch_id=system_only.id,
                source=ImportSource.SYSTEM,
                event=ObservationEvent.SNAPSHOT,
                observed_on=system_only.report_date,
                cost_center_id=missing_audit_center.id,
                original_data=_system_data("Only system", "System category", "Product"),
                quantity=Decimal("1"),
            )
        )
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        system = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.SYSTEM)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        db.add_all(
            AssetObservation(
                import_batch_id=system.id,
                source=ImportSource.SYSTEM,
                event=ObservationEvent.SNAPSHOT,
                observed_on=system.report_date,
                cost_center_id=center.id,
                original_data=_system_data("IT", f"Category-{number:03}", "Product"),
                quantity=Decimal("1"),
            )
            for number in range(102)
        )
        db.commit()

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return (
                await api.get("/api/dashboard/rubro-reconciliation-chart?cost_center_code=191"),
                await api.get("/api/dashboard/rubro-reconciliation-chart?cost_center_code=192"),
                await api.get("/api/dashboard/rubro-reconciliation-chart?cost_center_code=190&rubro=IT"),
            )
        finally:
            await api.aclose()

    missing_system, missing_audit, high_cardinality = asyncio.run(exercise())
    assert missing_system.status_code == missing_audit.status_code == high_cardinality.status_code == 200
    assert missing_system.json()["rubro_options"] == []
    assert missing_system.json()["category_options"] == []
    assert missing_system.json()["category_chart"]["reason"] == "missing_system_evidence"
    assert missing_system.json()["product_chart"]["reason"] == "missing_system_evidence"
    assert missing_audit.json()["category_chart"]["reason"] == "missing_audit_evidence"
    assert missing_audit.json()["selected_category"] == {"value": "System category", "label": "System category"}
    assert missing_audit.json()["category_chart"]["items"] == [
        {
            "category": "System category",
            "category_label": "System category",
            "found_in_cost_center_count": None,
            "returned_count": None,
            "difference_count": None,
        }
    ]
    chart = high_cardinality.json()["category_chart"]
    assert chart["available"] is True
    assert chart["reason"] is None
    assert len(chart["items"]) == 103
    assert chart["items"][0]["category"] == "Category-000"
    assert chart["items"][-1]["category"] == "Laptop"
    assert "page" not in high_cardinality.json()
    assert missing_audit.json()["product_chart"] == {
        "available": False,
        "reason": "missing_audit_evidence",
        "series": [
            {"key": "found_in_cost_center_count", "label": "found_in_cost_center"},
            {"key": "returned_count", "label": "returned"},
            {"key": "difference_count", "label": "difference"},
        ],
        "items": [
            {
                "product": "Product",
                "product_label": "Product",
                "found_in_cost_center_count": None,
                "returned_count": None,
                "difference_count": None,
            }
        ],
        "source_freshness": missing_audit.json()["product_chart"]["source_freshness"],
        "page": {"limit": 50, "offset": 0, "has_more": False, "total_count": 1},
    }


def test_rubro_chart_category_selection_and_product_pagination_are_server_owned(database: sessionmaker[Session]) -> None:
    populate(database)
    with database() as db:
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        system = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.SYSTEM)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        audit = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.AUDIT)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )

        def add_asset(code: str, category: str | None, product: str, state: AuditCurrentState, duplicate: bool = False) -> None:
            asset = Asset(original_code=code, normalized_code=code)
            db.add(asset)
            db.flush()
            observation = AssetObservation(
                import_batch_id=system.id,
                source=ImportSource.SYSTEM,
                event=ObservationEvent.SNAPSHOT,
                observed_on=system.report_date,
                asset_id=asset.id,
                cost_center_id=center.id,
                original_data=_system_data("IT", category, product),
                quantity=Decimal("1"),
            )
            db.add(observation)
            if duplicate:
                db.add(
                    AssetObservation(
                        import_batch_id=system.id,
                        source=ImportSource.SYSTEM,
                        event=ObservationEvent.SNAPSHOT,
                        observed_on=system.report_date,
                        asset_id=asset.id,
                        cost_center_id=center.id,
                        original_data=_system_data("IT", category, product),
                        quantity=Decimal("1"),
                    )
                )
            audit_observation = AssetObservation(
                import_batch_id=audit.id,
                source=ImportSource.AUDIT,
                event=ObservationEvent.SNAPSHOT,
                observed_on=audit.report_date,
                cost_center_id=center.id,
                original_data={"cells": []},
                quantity=Decimal("1"),
            )
            db.add(audit_observation)
            db.flush()
            db.add_all(
                (
                    ReconciliationCase(
                        audit_observation_id=audit_observation.id,
                        cost_center_id=center.id,
                        candidate_asset_id=asset.id,
                        match_strategy=AuditMatchStrategy.EXACT_ORIGINAL_CODE,
                    ),
                    AuditCurrentStateProjection(
                        asset_id=asset.id,
                        cost_center_id=center.id,
                        audit_observation_id=audit_observation.id,
                        state=state,
                        marker_category=(
                            AuditReturnMarkerCategory.RECOGNIZED_RETURN
                            if state == AuditCurrentState.RETURNED
                            else AuditReturnMarkerCategory.UNMARKED_UNKNOWN
                        ),
                        marker_column=12,
                        reason="test",
                        projection_version="audit_l_return_v1",
                    ),
                )
            )

        add_asset("NULL-CATEGORY", None, "Unassigned", AuditCurrentState.RETURNED)
        add_asset("SAFE-PRODUCT", "Named & Δ", "Product / & Δ", AuditCurrentState.FOUND, duplicate=True)
        add_asset("SECOND-PRODUCT", "Named & Δ", "Second", AuditCurrentState.RETURNED)
        db.commit()

    async def request(**params: str | int) -> httpx.Response:
        api = await client()
        try:
            assert (await api.post("/api/auth/login", json={"username": "viewer", "password": "password"})).status_code == 200
            return await api.get("/api/dashboard/rubro-reconciliation-chart", params={"cost_center_code": "190", "rubro": "IT", **params})
        finally:
            await api.aclose()

    omitted, explicit_null, named, invalid, invalid_limit, invalid_offset = (
        asyncio.run(request()),
        asyncio.run(request(category="")),
        asyncio.run(request(category="Named & Δ")),
        asyncio.run(request(category="missing & / Δ")),
        asyncio.run(request(product_limit=101)),
        asyncio.run(request(product_offset=10_001)),
    )
    assert all(response.status_code == 200 for response in (omitted, explicit_null, named, invalid))
    null_option = {"value": None, "label": "Sin categoría asignada"}
    assert omitted.json()["category_options"] == [null_option, {"value": "Laptop", "label": "Laptop"}, {"value": "Named & Δ", "label": "Named & Δ"}]
    assert omitted.json()["selected_category"] == explicit_null.json()["selected_category"] == null_option
    assert omitted.json()["product_chart"]["items"] == [
        {
            "product": "Unassigned",
            "product_label": "Unassigned",
            "found_in_cost_center_count": 0,
            "returned_count": 1,
            "difference_count": 0,
        }
    ]
    assert named.json()["selected_category"] == {"value": "Named & Δ", "label": "Named & Δ"}
    assert named.json()["product_chart"]["items"] == [
        {
            "product": "Product / & Δ",
            "product_label": "Product / & Δ",
            "found_in_cost_center_count": 1,
            "returned_count": 0,
            "difference_count": 0,
        },
        {
            "product": "Second",
            "product_label": "Second",
            "found_in_cost_center_count": 0,
            "returned_count": 1,
            "difference_count": 0,
        },
    ]
    assert invalid_limit.status_code == invalid_offset.status_code == 422
    assert invalid.json()["selected_category"] == {"value": "missing & / Δ", "label": "missing & / Δ"}
    assert invalid.json()["category_chart"]["available"] is True
    assert invalid.json()["product_chart"]["reason"] == "invalid_category_selection"
    assert invalid.json()["product_chart"]["items"] == []

    with database() as db:
        center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
        system = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.cost_center_id == center.id, ImportBatch.source == ImportSource.SYSTEM)
            .order_by(ImportBatch.report_date.desc(), ImportBatch.id.desc())
        )
        db.add_all(
            AssetObservation(
                import_batch_id=system.id,
                source=ImportSource.SYSTEM,
                event=ObservationEvent.SNAPSHOT,
                observed_on=system.report_date,
                cost_center_id=center.id,
                original_data=_system_data("IT", "High cardinality", f"Product-{number:03}"),
                quantity=Decimal("1"),
            )
            for number in range(102)
        )
        db.commit()

    statement_count = 0

    def count_statements(*_args: object) -> None:
        nonlocal statement_count
        statement_count += 1

    engine = database.kw["bind"]
    event.listen(engine, "before_cursor_execute", count_statements)
    try:
        first_page = asyncio.run(request(category="High cardinality", product_limit=2, product_offset=0))
        first_count = statement_count
        statement_count = 0
        last_page = asyncio.run(request(category="High cardinality", product_limit=1, product_offset=101))
        last_count = statement_count
    finally:
        event.remove(engine, "before_cursor_execute", count_statements)

    assert first_page.status_code == last_page.status_code == 200
    assert first_page.json()["product_chart"]["page"] == {"limit": 2, "offset": 0, "has_more": True, "total_count": 102}
    assert [item["product"] for item in first_page.json()["product_chart"]["items"]] == ["Product-000", "Product-001"]
    assert last_page.json()["product_chart"]["page"] == {"limit": 1, "offset": 101, "has_more": False, "total_count": 102}
    assert last_page.json()["product_chart"]["items"][0]["product"] == "Product-101"
    assert first_count == last_count == 11
