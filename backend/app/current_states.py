"""Read-only access to the derived physical-audit current-state projection."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_viewer
from .db import get_db
from .models import Asset, AssetObservation, AuditCurrentStateProjection, CostCenter, ImportBatch, User

router = APIRouter(prefix="/api/current-states", tags=["current states"])


@router.get("")
def list_current_states(
    cost_center_code: Annotated[str | None, Query()] = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_viewer),
) -> dict[str, object]:
    """Return reproducible derived states without exposing full audit source rows."""
    statement = (
        select(AuditCurrentStateProjection, Asset, CostCenter, AssetObservation, ImportBatch)
        .join(Asset, Asset.id == AuditCurrentStateProjection.asset_id)
        .join(CostCenter, CostCenter.id == AuditCurrentStateProjection.cost_center_id)
        .join(AssetObservation, AssetObservation.id == AuditCurrentStateProjection.audit_observation_id)
        .join(ImportBatch, ImportBatch.id == AssetObservation.import_batch_id)
        .order_by(CostCenter.code, Asset.original_code)
    )
    if cost_center_code is not None:
        statement = statement.where(CostCenter.code == cost_center_code.strip())
    states = []
    for projection, asset, center, _observation, batch in db.execute(statement):
        states.append(
            {
                "asset_id": str(asset.id),
                "asset_code": asset.original_code,
                "cost_center": {"code": center.code, "name": center.name},
                "state": projection.state.value,
                "reason": projection.reason,
                "marker": {
                    "column": projection.marker_column,
                    "category": projection.marker_category.value,
                    "raw_value": projection.marker_raw_value,
                },
                "source_audit_observation_id": str(projection.audit_observation_id),
                "source_report_date": batch.report_date.isoformat(),
                "projection_version": projection.projection_version,
            }
        )
    return {"states": states}
