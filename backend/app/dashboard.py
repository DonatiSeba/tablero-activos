"""Viewer-safe dashboard and operational read contracts.

These endpoints deliberately aggregate immutable evidence and derived projections
on the server.  They never return workbook cells, notes, storage information,
or file digests.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, case, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from .auth import require_viewer
from .db import get_db
from .models import (
    Asset,
    AssetObservation,
    AuditCurrentState,
    AuditCurrentStateProjection,
    CostCenter,
    ImportBatch,
    ImportBatchStatus,
    ImportSource,
    ReconciliationCase,
    User,
)

router = APIRouter(tags=["dashboard and operations"])

MAX_PAGE_SIZE = 100
MAX_OFFSET = 10_000
WARNING_CODES = frozenset({"divergent_cost_center_names", "missing_asset_code"})
REVIEW_CATEGORIES = frozenset({"unresolved_identifier", "review_required_return"})


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise HTTPException(status_code=422, detail=f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if not 0 <= offset <= MAX_OFFSET:
        raise HTTPException(status_code=422, detail=f"offset must be between 0 and {MAX_OFFSET}")
    return limit, offset


def _safe_label(value: Any) -> str | None:
    """Expose only bounded single-line labels from the three known system fields."""
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value[:255] if value else None


def _system_cell(observation: AssetObservation, header: str) -> str | None:
    cells = observation.original_data.get("cells") if isinstance(observation.original_data, dict) else None
    if not isinstance(cells, list):
        return None
    for cell in cells:
        if isinstance(cell, dict) and cell.get("header") == header:
            return _safe_label(cell.get("value"))
    return None


def _latest_batches(db: Session, cost_center_code: str | None = None) -> dict[tuple[object, ImportSource], ImportBatch]:
    """Choose completed evidence by report date, then UUID solely as a stable tie-breaker."""
    statement = (
        select(ImportBatch, CostCenter.code)
        .join(CostCenter, CostCenter.id == ImportBatch.cost_center_id)
        .where(
            ImportBatch.status == ImportBatchStatus.COMPLETED,
            ImportBatch.source.in_((ImportSource.SYSTEM, ImportSource.AUDIT)),
        )
        .order_by(CostCenter.code, ImportBatch.source, ImportBatch.report_date.desc(), ImportBatch.id.desc())
    )
    if cost_center_code is not None:
        statement = statement.where(CostCenter.code == cost_center_code)
    selected: dict[tuple[object, ImportSource], ImportBatch] = {}
    for batch, _code in db.execute(statement):
        selected.setdefault((batch.cost_center_id, batch.source), batch)
    return selected


def _source_contract(batch: ImportBatch | None, source: ImportSource) -> dict[str, object]:
    if batch is None:
        return {"source": source.value, "available": False, "batch_id": None, "report_date": None}
    return {
        "source": source.value,
        "available": True,
        "batch_id": str(batch.id),
        "report_date": batch.report_date.isoformat(),
    }


def _freshness(system: ImportBatch | None, audit: ImportBatch | None) -> dict[str, object]:
    if system is None and audit is None:
        return {"warning": True, "status": "missing_both", "message": "System and audit evidence are unavailable."}
    if system is None:
        return {"warning": True, "status": "missing_system", "message": "System evidence is unavailable."}
    if audit is None:
        return {"warning": True, "status": "missing_audit", "message": "Audit evidence is unavailable."}
    if system.report_date != audit.report_date:
        return {
            "warning": True,
            "status": "report_dates_differ",
            "message": "System and audit report dates differ; they are not a shared cutoff.",
        }
    return {"warning": False, "status": "same_report_date", "message": None}


def _summary_metrics(db: Session, system: ImportBatch | None, audit: ImportBatch | None) -> dict[str, int | None]:
    system_asset_ids: set[object] | None = None
    if system is not None:
        system_asset_ids = set(
            db.scalars(
                select(AssetObservation.asset_id).where(
                    AssetObservation.import_batch_id == system.id,
                    AssetObservation.asset_id.is_not(None),
                )
            )
        )

    unresolved_count: int | None = None
    projection_states: dict[object, AuditCurrentState] = {}
    if audit is not None:
        unresolved_count = int(
            db.scalar(
                select(func.count())
                .select_from(ReconciliationCase)
                .join(AssetObservation, AssetObservation.id == ReconciliationCase.audit_observation_id)
                .where(
                    AssetObservation.import_batch_id == audit.id,
                    ReconciliationCase.candidate_asset_id.is_(None),
                )
            )
            or 0
        )
        for asset_id, state in db.execute(
            select(AuditCurrentStateProjection.asset_id, AuditCurrentStateProjection.state)
            .join(AssetObservation, AssetObservation.id == AuditCurrentStateProjection.audit_observation_id)
            .where(AssetObservation.import_batch_id == audit.id)
        ):
            projection_states[asset_id] = state

    if system_asset_ids is None or audit is None:
        return {
            "current_system_distinct_asset_count": len(system_asset_ids) if system_asset_ids is not None else None,
            "found_count": None,
            "returned_count": None,
            "review_required_count": None,
            "unresolved_audit_case_count": unresolved_count,
            "pending_not_accounted_count": None,
        }

    scoped_states = {asset_id: state for asset_id, state in projection_states.items() if asset_id in system_asset_ids}
    found = sum(state is AuditCurrentState.FOUND for state in scoped_states.values())
    returned = sum(state is AuditCurrentState.RETURNED for state in scoped_states.values())
    review_required = sum(state is AuditCurrentState.REVIEW_REQUIRED for state in scoped_states.values())
    accounted_ids = {
        asset_id
        for asset_id, state in scoped_states.items()
        if state in (AuditCurrentState.FOUND, AuditCurrentState.RETURNED)
    }
    return {
        "current_system_distinct_asset_count": len(system_asset_ids),
        "found_count": found,
        "returned_count": returned,
        "review_required_count": review_required,
        "unresolved_audit_case_count": unresolved_count,
        "pending_not_accounted_count": len(system_asset_ids - accounted_ids),
    }


@router.get("/api/dashboard/summaries")
def dashboard_summaries(
    cost_center_code: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = MAX_PAGE_SIZE,
    offset: Annotated[int, Query()] = 0,
    db: Session = Depends(get_db),
    _user: User = Depends(require_viewer),
) -> dict[str, object]:
    """Return per-cost-center KPIs without pretending system and audit share a cutoff."""
    limit, offset = _page(limit, offset)
    code = cost_center_code.strip() if cost_center_code else None
    centers_statement = select(CostCenter).order_by(CostCenter.code)
    if code:
        centers_statement = centers_statement.where(CostCenter.code == code)
    total_count = int(db.scalar(select(func.count()).select_from(centers_statement.subquery())) or 0)
    centers = list(db.scalars(centers_statement.offset(offset).limit(limit + 1)))
    has_more = len(centers) > limit
    centers = centers[:limit]
    batches = _latest_batches(db, code)
    summaries = []
    for center in centers:
        system = batches.get((center.id, ImportSource.SYSTEM))
        audit = batches.get((center.id, ImportSource.AUDIT))
        summaries.append(
            {
                "cost_center": {"code": center.code, "name": center.name},
                "latest_sources": {"system": _source_contract(system, ImportSource.SYSTEM), "audit": _source_contract(audit, ImportSource.AUDIT)},
                "freshness": _freshness(system, audit),
                "metrics": _summary_metrics(db, system, audit),
            }
        )
    return {
        "selection_rule": "Completed batches: greatest report_date, then greatest batch UUID only as a stable selection tie-breaker, never chronology.",
        "metric_scope": "Status and pending metrics are distinct assets in the selected system batch; audit states are projections whose provenance is the selected audit batch.",
        "summaries": summaries,
        "page": {"limit": limit, "offset": offset, "has_more": has_more, "total_count": total_count},
    }


@router.get("/api/dashboard/system-drilldown")
def system_drilldown(
    cost_center_code: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query()] = MAX_PAGE_SIZE,
    offset: Annotated[int, Query()] = 0,
    db: Session = Depends(get_db),
    _user: User = Depends(require_viewer),
) -> dict[str, object]:
    """Return one bounded page of server-calculated Rubro/Categoría/Producto leaves.

    Pagination applies to the deterministic depth-first leaf order (rubro,
    category, then product); parent groups contain only leaves in the requested
    page. Counts remain calculated on the server over each complete leaf group.
    """
    limit, offset = _page(limit, offset)
    page = {"limit": limit, "offset": offset, "has_more": False, "total_count": 0}
    code = cost_center_code.strip()
    center = db.scalar(select(CostCenter).where(CostCenter.code == code))
    if center is None:
        return {"cost_center": None, "source": _source_contract(None, ImportSource.SYSTEM), "groups": [], "page": page}
    batch = _latest_batches(db, code).get((center.id, ImportSource.SYSTEM))
    if batch is None:
        return {
            "cost_center": {"code": center.code, "name": center.name},
            "source": _source_contract(None, ImportSource.SYSTEM),
            "groups": [],
            "page": page,
        }

    grouped: dict[tuple[str | None, str | None, str | None], dict[str, Any]] = {}
    observations = db.scalars(
        select(AssetObservation).where(AssetObservation.import_batch_id == batch.id).order_by(AssetObservation.id)
    )
    for observation in observations:
        key = (
            _system_cell(observation, "Rubro"),
            _system_cell(observation, "Categoría"),
            _system_cell(observation, "Producto"),
        )
        item = grouped.setdefault(key, {"observation_count": 0, "asset_ids": set(), "statuses": defaultdict(int)})
        item["observation_count"] += 1
        if observation.asset_id is not None:
            item["asset_ids"].add(observation.asset_id)
        item["statuses"][_safe_label(observation.reported_status)] += 1

    def label_order(value: str | None) -> tuple[bool, str]:
        return (value is not None, (value or "").casefold())

    ordered_keys = sorted(grouped, key=lambda key: tuple(label_order(value) for value in key))
    page["total_count"] = len(ordered_keys)
    page_keys = ordered_keys[offset : offset + limit + 1]
    page["has_more"] = len(page_keys) > limit

    rubros: dict[str | None, dict[str | None, list[tuple[str | None, dict[str, Any]]]]] = defaultdict(lambda: defaultdict(list))
    for rubro, category, product in page_keys[:limit]:
        rubros[rubro][category].append((product, grouped[(rubro, category, product)]))

    groups = []
    for rubro in sorted(rubros, key=label_order):
        categories = []
        for category in sorted(rubros[rubro], key=label_order):
            products = []
            for product, values in sorted(rubros[rubro][category], key=lambda item: label_order(item[0])):
                products.append(
                    {
                        "product": product,
                        "observation_count": values["observation_count"],
                        "distinct_asset_count": len(values["asset_ids"]),
                        "status_counts": [
                            {"status": status, "count": count}
                            for status, count in sorted(values["statuses"].items(), key=lambda item: label_order(item[0]))
                        ],
                    }
                )
            categories.append({"category": category, "products": products})
        groups.append({"rubro": rubro, "categories": categories})
    return {
        "cost_center": {"code": center.code, "name": center.name},
        "source": _source_contract(batch, ImportSource.SYSTEM),
        "groups": groups,
        "page": page,
    }


def _warning_counts(batch: ImportBatch) -> dict[str, int]:
    metadata = batch.metadata_json if isinstance(batch.metadata_json, dict) else {}
    warnings = metadata.get("warnings")
    counts: defaultdict[str, int] = defaultdict(int)
    if not isinstance(warnings, list):
        return {}
    for warning in warnings:
        if not isinstance(warning, dict) or warning.get("code") not in WARNING_CODES:
            continue
        raw_count = warning.get("row_count", 1)
        if isinstance(raw_count, int) and raw_count >= 0:
            counts[warning["code"]] += raw_count
    return dict(sorted(counts.items()))


@router.get("/api/operations/import-history")
def import_history(
    source: ImportSource | None = None,
    cost_center_code: Annotated[str | None, Query()] = None,
    status: ImportBatchStatus | None = None,
    limit: Annotated[int, Query()] = 50,
    offset: Annotated[int, Query()] = 0,
    db: Session = Depends(get_db),
    _user: User = Depends(require_viewer),
) -> dict[str, object]:
    """Return bounded safe batch metadata; evidence filenames, hashes, and paths stay private."""
    limit, offset = _page(limit, offset)
    statement = select(ImportBatch, CostCenter, User.display_name).join(CostCenter, CostCenter.id == ImportBatch.cost_center_id).outerjoin(User, User.id == ImportBatch.imported_by_user_id)
    if source is not None:
        statement = statement.where(ImportBatch.source == source)
    if cost_center_code:
        statement = statement.where(CostCenter.code == cost_center_code.strip())
    if status is not None:
        statement = statement.where(ImportBatch.status == status)
    total_count = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(db.execute(statement.order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc()).offset(offset).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    batch_ids = [batch.id for batch, _center, _display_name in rows if batch.source is ImportSource.AUDIT]
    processing: dict[object, dict[str, int]] = {}
    if batch_ids:
        for batch_id, case_count, unresolved_count in db.execute(
            select(
                AssetObservation.import_batch_id,
                func.count(ReconciliationCase.id),
                func.sum(case((ReconciliationCase.candidate_asset_id.is_(None), 1), else_=0)),
            )
            .join(ReconciliationCase, ReconciliationCase.audit_observation_id == AssetObservation.id)
            .where(AssetObservation.import_batch_id.in_(batch_ids))
            .group_by(AssetObservation.import_batch_id)
        ):
            processing[batch_id] = {"reconciliation_case_count": int(case_count), "unresolved_case_count": int(unresolved_count or 0)}
    items = []
    for batch, center, display_name in rows:
        items.append(
            {
                "batch_id": str(batch.id),
                "source": batch.source.value,
                "cost_center": {"code": center.code, "name": center.name},
                "report_date": batch.report_date.isoformat(),
                "imported_at": batch.created_at.isoformat(),
                "imported_by_display_name": display_name,
                "row_count": batch.row_count,
                "status": batch.status.value,
                "warning_counts": _warning_counts(batch),
                "processing_counts": processing.get(batch.id, {}),
            }
        )
    return {"items": items, "page": {"limit": limit, "offset": offset, "has_more": has_more, "total_count": total_count}}


@router.get("/api/operations/review-queue")
def review_queue(
    cost_center_code: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = 50,
    offset: Annotated[int, Query()] = 0,
    db: Session = Depends(get_db),
    _user: User = Depends(require_viewer),
) -> dict[str, object]:
    """Return unresolved identifiers and current ambiguous return inferences; no resolution command exists here."""
    limit, offset = _page(limit, offset)
    if category is not None and category not in REVIEW_CATEGORIES:
        raise HTTPException(status_code=422, detail="category must be unresolved_identifier or review_required_return")
    code = cost_center_code.strip() if cost_center_code else None
    unresolved = (
        select(
            literal("unresolved_identifier").label("category"),
            ReconciliationCase.id.label("item_id"),
            CostCenter.code.label("cost_center_code"),
            CostCenter.name.label("cost_center_name"),
            literal(None).label("asset_id"),
            literal(None).label("asset_code"),
            ImportBatch.id.label("batch_id"),
            ImportBatch.report_date.label("report_date"),
            cast(ReconciliationCase.match_reason, String).label("reason"),
        )
        .join(AssetObservation, AssetObservation.id == ReconciliationCase.audit_observation_id)
        .join(ImportBatch, ImportBatch.id == AssetObservation.import_batch_id)
        .join(CostCenter, CostCenter.id == ReconciliationCase.cost_center_id)
        .where(ReconciliationCase.candidate_asset_id.is_(None), ImportBatch.status == ImportBatchStatus.COMPLETED)
    )
    return_reviews = (
        select(
            literal("review_required_return").label("category"),
            AuditCurrentStateProjection.id.label("item_id"),
            CostCenter.code.label("cost_center_code"),
            CostCenter.name.label("cost_center_name"),
            Asset.id.label("asset_id"),
            Asset.original_code.label("asset_code"),
            ImportBatch.id.label("batch_id"),
            ImportBatch.report_date.label("report_date"),
            AuditCurrentStateProjection.reason.label("reason"),
        )
        .join(Asset, Asset.id == AuditCurrentStateProjection.asset_id)
        .join(CostCenter, CostCenter.id == AuditCurrentStateProjection.cost_center_id)
        .join(AssetObservation, AssetObservation.id == AuditCurrentStateProjection.audit_observation_id)
        .join(ImportBatch, ImportBatch.id == AssetObservation.import_batch_id)
        .where(AuditCurrentStateProjection.state == AuditCurrentState.REVIEW_REQUIRED, ImportBatch.status == ImportBatchStatus.COMPLETED)
    )
    if code:
        unresolved = unresolved.where(CostCenter.code == code)
        return_reviews = return_reviews.where(CostCenter.code == code)
    unresolved_count = int(db.scalar(select(func.count()).select_from(unresolved.subquery())) or 0)
    return_review_count = int(db.scalar(select(func.count()).select_from(return_reviews.subquery())) or 0)
    selected = []
    if category in (None, "unresolved_identifier"):
        selected.append(unresolved)
    if category in (None, "review_required_return"):
        selected.append(return_reviews)
    queue = union_all(*selected).subquery()
    total_count = int(db.scalar(select(func.count()).select_from(queue)) or 0)
    rows = list(db.execute(select(queue).order_by(queue.c.report_date.desc(), queue.c.category, queue.c.item_id).offset(offset).limit(limit + 1)).mappings())
    has_more = len(rows) > limit
    items = []
    for row in rows[:limit]:
        item = {
            "id": str(row["item_id"]),
            "category": row["category"],
            "cost_center": {"code": row["cost_center_code"], "name": row["cost_center_name"]},
            "asset": None if row["asset_id"] is None else {"id": str(row["asset_id"]), "code": _safe_label(row["asset_code"])},
            "source": {"source": "audit", "batch_id": str(row["batch_id"]), "report_date": row["report_date"].isoformat()},
            "reason": row["reason"].value if hasattr(row["reason"], "value") else row["reason"],
        }
        if row["category"] == "review_required_return":
            item["inference"] = "Authorized audit column-L return inference; not a warehouse receipt."
        items.append(item)
    return {
        "items": items,
        "queue_counts": {
            "unresolved_identifier": unresolved_count,
            "review_required_return": return_review_count,
            "total": unresolved_count + return_review_count,
        },
        "page": {"limit": limit, "offset": offset, "has_more": has_more, "total_count": total_count},
    }
