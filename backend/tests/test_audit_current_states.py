from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.audit_current_states import (
    PROJECTION_VERSION,
    audit_return_marker_from_original_data,
    rebuild_audit_current_state_projections,
)
from backend.app.db import Base
from backend.app.models import (
    Asset,
    AssetObservation,
    AuditCurrentState,
    AuditCurrentStateProjection,
    AuditMatchReason,
    AuditMatchStrategy,
    AuditReturnMarkerCategory,
    CostCenter,
    CostCenterStatus,
    ImportBatch,
    ImportBatchStatus,
    ImportSource,
    ObservationEvent,
    ReconciliationCase,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(CostCenter(code="190", name="Operations", status=CostCenterStatus.ACTIVE))
        session.commit()
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def raw_l(value: object | None) -> dict[str, object]:
    return {"source_sheet": "Physical", "source_row": 4, "cells": [{"column": 12, "header": None, "value": value}]}


def add_resolved_audit(
    db: Session, *, code: str, report_date: date, marker: object | None, asset: Asset | None = None
) -> Asset:
    center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
    assert center is not None
    asset = asset or Asset(original_code=code, normalized_code=code)
    db.add(asset)
    db.flush()
    batch = ImportBatch(
        source=ImportSource.AUDIT,
        cost_center_id=center.id,
        report_date=report_date,
        status=ImportBatchStatus.COMPLETED,
        original_filename=f"{code}-{report_date}.xlsx",
        sha256=f"{len(list(db.scalars(select(ImportBatch.id)))) + 1:064x}",
        row_count=1,
    )
    db.add(batch)
    db.flush()
    observation = AssetObservation(
        import_batch_id=batch.id,
        source=ImportSource.AUDIT,
        event=ObservationEvent.SNAPSHOT,
        observed_on=report_date,
        cost_center_id=center.id,
        original_data=raw_l(marker),
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
    db.flush()
    return asset


@pytest.mark.parametrize(
    ("raw", "category"),
    [
        ("VOLVI\u00d3", AuditReturnMarkerCategory.RECOGNIZED_RETURN),
        ("VOLVI�", AuditReturnMarkerCategory.RECOGNIZED_RETURN),
        ("DEVOLVIO", AuditReturnMarkerCategory.RECOGNIZED_RETURN),
        ("DEVOLVI\u00d3", AuditReturnMarkerCategory.RECOGNIZED_RETURN),
        ("DEVOLVI�", AuditReturnMarkerCategory.RECOGNIZED_RETURN),
        ("VOLVI\u00d3 4", AuditReturnMarkerCategory.AMBIGUOUS_RETURN),
        ("VOLVI� 4", AuditReturnMarkerCategory.AMBIGUOUS_RETURN),
        (None, AuditReturnMarkerCategory.UNMARKED_UNKNOWN),
        ("", AuditReturnMarkerCategory.UNMARKED_UNKNOWN),
    ],
)
def test_column_l_marker_interpretation_is_exact_and_preserves_raw_value(raw: object | None, category: AuditReturnMarkerCategory) -> None:
    original_data = raw_l(raw)
    marker = audit_return_marker_from_original_data(original_data)
    assert marker.category is category
    assert marker.raw_value == raw
    assert original_data["cells"][0]["value"] == raw


def test_recognized_marker_projects_returned_with_raw_provenance(db: Session) -> None:
    asset = add_resolved_audit(db, code="A-1", report_date=date(2026, 6, 27), marker="DEVOLVIO")
    counts = rebuild_audit_current_state_projections(db)
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert counts == {"found": 0, "returned": 1, "review_required": 0}
    assert projection is not None
    assert projection.state is AuditCurrentState.RETURNED
    assert projection.marker_category is AuditReturnMarkerCategory.RECOGNIZED_RETURN
    assert projection.marker_raw_value == "DEVOLVIO"
    assert projection.marker_column == 12
    assert projection.projection_version == PROJECTION_VERSION
    assert projection.reason == "authorized_post_audit_column_l_return_marker"
    source = db.get(AssetObservation, projection.audit_observation_id)
    assert source is not None and source.original_data["cells"][0]["value"] == "DEVOLVIO"


def test_later_audit_date_overrides_earlier_return(db: Session) -> None:
    asset = add_resolved_audit(db, code="A-2", report_date=date(2026, 6, 27), marker="VOLVI�")
    add_resolved_audit(db, code="A-2-later", asset=asset, report_date=date(2026, 6, 28), marker=None)
    rebuild_audit_current_state_projections(db)
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert projection is not None and projection.state is AuditCurrentState.FOUND


@pytest.mark.parametrize(
    ("first_marker", "second_marker", "expected_state"),
    [
        (None, "VOLVI� 4", AuditCurrentState.REVIEW_REQUIRED),
        ("VOLVI� 4", "DEVOLVI�", AuditCurrentState.RETURNED),
    ],
)
def test_same_report_date_uses_authorized_marker_rank(
    db: Session, first_marker: object | None, second_marker: object | None, expected_state: AuditCurrentState
) -> None:
    asset = add_resolved_audit(db, code="A-3", report_date=date(2026, 6, 28), marker=first_marker)
    add_resolved_audit(db, code="A-3-ranked", asset=asset, report_date=date(2026, 6, 28), marker=second_marker)
    rebuild_audit_current_state_projections(db)
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert projection is not None and projection.state is expected_state


@pytest.mark.parametrize("older_marker", [None, "DEVOLVIO"])
def test_later_ambiguous_marker_replaces_older_proven_state(db: Session, older_marker: object | None) -> None:
    asset = add_resolved_audit(db, code="A-ambiguous", report_date=date(2026, 6, 27), marker=older_marker)
    add_resolved_audit(db, code="A-ambiguous-later", asset=asset, report_date=date(2026, 6, 28), marker="VOLVI� 4")
    counts = rebuild_audit_current_state_projections(db)
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert counts == {"found": 0, "returned": 0, "review_required": 1}
    assert projection is not None
    assert projection.state is AuditCurrentState.REVIEW_REQUIRED
    assert projection.marker_category is AuditReturnMarkerCategory.AMBIGUOUS_RETURN
    assert projection.marker_raw_value == "VOLVI� 4"
    assert projection.reason == "ambiguous_column_l_return_marker_requires_review"


def test_repeated_rows_are_one_projection_and_rebuild_is_idempotent(db: Session) -> None:
    asset = add_resolved_audit(db, code="A-4", report_date=date(2026, 6, 27), marker=None)
    add_resolved_audit(db, code="A-4-repeat", asset=asset, report_date=date(2026, 6, 27), marker=None)
    assert rebuild_audit_current_state_projections(db) == {"found": 1, "returned": 0, "review_required": 0}
    db.flush()
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert projection is not None
    first_id = projection.id
    assert rebuild_audit_current_state_projections(db) == {"found": 1, "returned": 0, "review_required": 0}
    db.flush()
    assert db.scalar(select(AuditCurrentStateProjection.id).where(AuditCurrentStateProjection.asset_id == asset.id)) == first_id
    assert len(list(db.scalars(select(AuditCurrentStateProjection)))) == 1


def test_ambiguous_marker_projects_review_without_found_or_returned_counts(db: Session) -> None:
    asset = add_resolved_audit(db, code="A-5", report_date=date(2026, 6, 27), marker="VOLVI� 4")
    center = db.scalar(select(CostCenter).where(CostCenter.code == "190"))
    assert center is not None
    batch = ImportBatch(source=ImportSource.AUDIT, cost_center_id=center.id, report_date=date(2026, 6, 27), status=ImportBatchStatus.COMPLETED, original_filename="unresolved.xlsx", sha256="f" * 64, row_count=1)
    db.add(batch)
    db.flush()
    observation = AssetObservation(import_batch_id=batch.id, source=ImportSource.AUDIT, event=ObservationEvent.SNAPSHOT, observed_on=batch.report_date, cost_center_id=center.id, original_data=raw_l("VOLVI�"), quantity=Decimal("1"))
    db.add(observation)
    db.flush()
    db.add(ReconciliationCase(audit_observation_id=observation.id, cost_center_id=center.id, match_reason=AuditMatchReason.MISSING_IDENTIFIER))
    db.flush()
    assert rebuild_audit_current_state_projections(db) == {"found": 0, "returned": 0, "review_required": 1}
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert projection is not None and projection.state is AuditCurrentState.REVIEW_REQUIRED
    assert len(list(db.scalars(select(AuditCurrentStateProjection)))) == 1


def test_projection_constraints_require_one_asset_center_and_column_l(db: Session) -> None:
    asset = add_resolved_audit(db, code="A-6", report_date=date(2026, 6, 27), marker=None)
    rebuild_audit_current_state_projections(db)
    db.commit()
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert projection is not None
    projection.marker_column = 11
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    projection = db.scalar(select(AuditCurrentStateProjection).where(AuditCurrentStateProjection.asset_id == asset.id))
    assert projection is not None
    projection.state = AuditCurrentState.RETURNED
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
