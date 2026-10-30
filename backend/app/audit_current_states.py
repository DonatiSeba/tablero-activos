"""Derived current-state projection for authorized physical-audit column-L markers.

This module reads only persisted positional source cells.  It intentionally does
not create return batches or observations: column L is an annotation on an
immutable audit snapshot, not a separate receipt record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import null, select
from sqlalchemy.orm import Session

from .audit_imports import BG_DIRECT_FILL_SIGNATURE_KEY, _is_bg_return_fill_signature
from .models import (
    AssetObservation,
    AuditCurrentState,
    AuditCurrentStateProjection,
    AuditMarkerSource,
    AuditReturnMarkerCategory,
    ImportBatch,
    ImportSource,
    ReconciliationCase,
)

PROJECTION_VERSION = "audit_l_return_v1"
BG_PROJECTION_VERSION = "bg_direct_fill_return_v1"
MARKER_COLUMN = 12
# The supplied workbook stores accented forms as U+00D3.  U+FFFD forms are
# retained solely for compatibility with the user-supplied rendered variants;
# no broader text normalization is performed.
RECOGNIZED_RETURN_MARKERS = frozenset({"VOLVI\u00d3", "DEVOLVIO", "DEVOLVI\u00d3", "VOLVI�", "DEVOLVI�"})
AMBIGUOUS_RETURN_MARKERS = frozenset({"VOLVI\u00d3 4", "VOLVI� 4"})


@dataclass(frozen=True)
class AuditReturnMarker:
    """The non-mutating interpretation of persisted audit marker evidence."""

    raw_value: Any | None
    category: AuditReturnMarkerCategory
    source: AuditMarkerSource
    column: int | None


def audit_return_marker_from_original_data(original_data: dict[str, Any]) -> AuditReturnMarker:
    """Read BG direct-fill evidence or a raw column-L value without rewriting it."""
    fill_signature = original_data.get(BG_DIRECT_FILL_SIGNATURE_KEY)
    if isinstance(fill_signature, list):
        category = (
            AuditReturnMarkerCategory.BG_DIRECT_FILL_RETURN
            if _is_bg_return_fill_signature(fill_signature)
            else AuditReturnMarkerCategory.BG_DIRECT_FILL_PENDING
        )
        return AuditReturnMarker(fill_signature, category, AuditMarkerSource.BG_ROW_DIRECT_FILL, None)

    raw_value: Any | None = None
    cells = original_data.get("cells")
    if isinstance(cells, list):
        for cell in cells:
            if isinstance(cell, dict) and cell.get("column") == MARKER_COLUMN:
                raw_value = cell.get("value")
                break
    if isinstance(raw_value, str) and raw_value in RECOGNIZED_RETURN_MARKERS:
        return AuditReturnMarker(raw_value, AuditReturnMarkerCategory.RECOGNIZED_RETURN, AuditMarkerSource.COLUMN_L_VALUE, MARKER_COLUMN)
    if isinstance(raw_value, str) and raw_value in AMBIGUOUS_RETURN_MARKERS:
        return AuditReturnMarker(raw_value, AuditReturnMarkerCategory.AMBIGUOUS_RETURN, AuditMarkerSource.COLUMN_L_VALUE, MARKER_COLUMN)
    return AuditReturnMarker(raw_value, AuditReturnMarkerCategory.UNMARKED_UNKNOWN, AuditMarkerSource.COLUMN_L_VALUE, MARKER_COLUMN)


def _projection_values(marker: AuditReturnMarker) -> tuple[AuditCurrentState, str, str]:
    if marker.category is AuditReturnMarkerCategory.RECOGNIZED_RETURN:
        return AuditCurrentState.RETURNED, "authorized_post_audit_column_l_return_marker", PROJECTION_VERSION
    if marker.category is AuditReturnMarkerCategory.AMBIGUOUS_RETURN:
        return AuditCurrentState.REVIEW_REQUIRED, "ambiguous_column_l_return_marker_requires_review", PROJECTION_VERSION
    if marker.category is AuditReturnMarkerCategory.BG_DIRECT_FILL_RETURN:
        return AuditCurrentState.RETURNED, "confirmed_bg_direct_fill_return_marker", BG_PROJECTION_VERSION
    if marker.category is AuditReturnMarkerCategory.BG_DIRECT_FILL_PENDING:
        return AuditCurrentState.PENDING, "bg_row_without_confirmed_return_fill_pending", BG_PROJECTION_VERSION
    return AuditCurrentState.FOUND, "resolved_audit_presence_without_recognized_return_marker", PROJECTION_VERSION


def _marker_rank(marker: AuditReturnMarker) -> int:
    """Return the authorized same-report-date marker rank, not event time."""
    return {
        AuditReturnMarkerCategory.UNMARKED_UNKNOWN: 0,
        AuditReturnMarkerCategory.BG_DIRECT_FILL_PENDING: 0,
        AuditReturnMarkerCategory.AMBIGUOUS_RETURN: 1,
        AuditReturnMarkerCategory.RECOGNIZED_RETURN: 2,
        AuditReturnMarkerCategory.BG_DIRECT_FILL_RETURN: 2,
    }[marker.category]


def _is_current_state_candidate(observation: AssetObservation, batch: ImportBatch) -> bool:
    """Exclude manual evidence from mixed workbooks' exclusive state projection."""
    metadata = batch.metadata_json
    historical_found = metadata.get("historical_found") if isinstance(metadata, dict) else None
    if isinstance(historical_found, dict) and historical_found.get("available") is True:
        return BG_DIRECT_FILL_SIGNATURE_KEY in observation.original_data
    # Legacy physical-audit-only workbooks intentionally retain their column-L behavior.
    return True


def rebuild_audit_current_state_projections(db: Session) -> dict[str, int]:
    """Recompute one current classification per resolved asset and cost center.

    Mixed workbooks contribute only BG evidence; their manual observations are
    historical-found evidence rather than competing current-state inputs.
    Legacy physical-audit-only workbooks retain their column-L interpretation.
    Later report dates win. On an equal report date, this authorized marker
    interpretation ranks recognized returns over ambiguous markers over
    ordinary unmarked presence; it is not measured event time. The final
    observation-ID comparison is only a stable provenance tie-breaker.
    """
    rows = db.execute(
        select(ReconciliationCase, AssetObservation, ImportBatch)
        .join(AssetObservation, AssetObservation.id == ReconciliationCase.audit_observation_id)
        .join(ImportBatch, ImportBatch.id == AssetObservation.import_batch_id)
        .where(
            ReconciliationCase.candidate_asset_id.is_not(None),
            AssetObservation.source == ImportSource.AUDIT,
            ImportBatch.source == ImportSource.AUDIT,
        )
    ).all()

    candidates: dict[tuple[object, object], tuple[ReconciliationCase, AssetObservation, ImportBatch, AuditReturnMarker]] = {}
    for case, observation, batch in rows:
        if not _is_current_state_candidate(observation, batch):
            continue
        marker = audit_return_marker_from_original_data(observation.original_data)
        assert case.candidate_asset_id is not None
        key = (case.candidate_asset_id, case.cost_center_id)
        existing = candidates.get(key)
        if existing is None:
            candidates[key] = (case, observation, batch, marker)
            continue
        _, existing_observation, existing_batch, existing_marker = existing
        candidate_rank = (batch.report_date, _marker_rank(marker), str(observation.id))
        existing_rank = (existing_batch.report_date, _marker_rank(existing_marker), str(existing_observation.id))
        if candidate_rank > existing_rank:
            candidates[key] = (case, observation, batch, marker)

    existing_projections = {
        (projection.asset_id, projection.cost_center_id): projection
        for projection in db.scalars(select(AuditCurrentStateProjection))
    }
    for key, projection in existing_projections.items():
        if key not in candidates:
            db.delete(projection)

    # Preserve the historical physical-audit response shape unless a BG row
    # actually contributes the new pending state.
    state_counts = {state.value: 0 for state in AuditCurrentState if state is not AuditCurrentState.PENDING}
    for key, (case, observation, _batch, marker) in candidates.items():
        state, reason, projection_version = _projection_values(marker)
        state_counts.setdefault(state.value, 0)
        state_counts[state.value] += 1
        values = {
            "audit_observation_id": observation.id,
            "state": state,
            "marker_category": marker.category,
            "marker_source": marker.source,
            "marker_raw_value": marker.raw_value,
            # ``None`` would invoke the legacy ORM default of 12 on INSERT.
            # Use SQL NULL for BG evidence, whose marker is a row fill not a cell.
            "marker_column": null() if marker.column is None else marker.column,
            "reason": reason,
            "projection_version": projection_version,
        }
        projection = existing_projections.get(key)
        if projection is None:
            db.add(
                AuditCurrentStateProjection(
                    asset_id=case.candidate_asset_id,
                    cost_center_id=case.cost_center_id,
                    **values,
                )
            )
        else:
            for field, value in values.items():
                if field == "marker_column" and marker.column is None:
                    if projection.marker_column is not None:
                        projection.marker_column = None
                elif getattr(projection, field) != value:
                    setattr(projection, field, value)
    return state_counts
