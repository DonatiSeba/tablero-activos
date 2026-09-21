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
from sqlalchemy.orm import Session, aliased

from .auth import require_viewer
from .db import get_db
from .models import (
    Asset,
    AssetObservation,
    AuditCurrentState,
    AuditCurrentStateProjection,
    AuditReturnMarkerCategory,
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
# This sentinel distinguishes an omitted hierarchy dimension from an explicit SQL NULL label.
_DIMENSION_OMITTED = object()


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


def _latest_batches(db: Session, cost_center_ids: list[object]) -> dict[tuple[object, ImportSource], ImportBatch]:
    """Select only the latest two source batches for the already bounded center page."""
    if not cost_center_ids:
        return {}
    ranked = (
        select(
            ImportBatch.id.label("batch_id"),
            func.row_number()
            .over(
                partition_by=(ImportBatch.cost_center_id, ImportBatch.source),
                order_by=(ImportBatch.report_date.desc(), ImportBatch.id.desc()),
            )
            .label("rank"),
        )
        .where(
            ImportBatch.cost_center_id.in_(cost_center_ids),
            ImportBatch.status == ImportBatchStatus.COMPLETED,
            ImportBatch.source.in_((ImportSource.SYSTEM, ImportSource.AUDIT)),
        )
        .subquery()
    )
    rows = db.scalars(
        select(ImportBatch)
        .join(ranked, ranked.c.batch_id == ImportBatch.id)
        .where(ranked.c.rank == 1)
    )
    return {(batch.cost_center_id, batch.source): batch for batch in rows}


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


def _system_asset_ids(batch: ImportBatch) -> Any:
    """A database-side distinct asset scope for one selected system snapshot."""
    return (
        select(AssetObservation.asset_id.label("asset_id"))
        .where(
            AssetObservation.import_batch_id == batch.id,
            AssetObservation.asset_id.is_not(None),
        )
        .distinct()
        .subquery()
    )


def _count(db: Session, statement: Any) -> int:
    return int(db.scalar(statement) or 0)


def _unresolved_audit_case_count(db: Session, batch: ImportBatch | None) -> int | None:
    if batch is None:
        return None
    return _count(
        db,
        select(func.count())
        .select_from(ReconciliationCase)
        .join(AssetObservation, AssetObservation.id == ReconciliationCase.audit_observation_id)
        .where(
            AssetObservation.import_batch_id == batch.id,
            ReconciliationCase.candidate_asset_id.is_(None),
        ),
    )


def _not_in_management_system_for_cost_center_count(
    audit_only_matched_asset_count: int | None,
    unresolved_audit_case_count: int | None,
) -> int | None:
    """Compose the review total only when both selected-source evidence sets exist."""
    if audit_only_matched_asset_count is None or unresolved_audit_case_count is None:
        return None
    return audit_only_matched_asset_count + unresolved_audit_case_count


def _summary_metrics_for_assets(
    db: Session,
    system_asset_ids: Any | None,
    audit: ImportBatch | None,
) -> dict[str, int | None]:
    """Aggregate a database-side system scope without materializing asset IDs."""
    if system_asset_ids is None:
        unresolved = _unresolved_audit_case_count(db, audit)
        return {
            "current_system_distinct_asset_count": None,
            "found_count": None,
            "returned_count": None,
            "review_required_count": None,
            "unresolved_audit_case_count": unresolved,
            "audit_only_matched_asset_count": None,
            "not_in_management_system_for_cost_center_count": _not_in_management_system_for_cost_center_count(None, unresolved),
            "pending_not_accounted_count": None,
        }

    system_count = _count(db, select(func.count()).select_from(system_asset_ids))
    if audit is None:
        return {
            "current_system_distinct_asset_count": system_count,
            "found_count": None,
            "returned_count": None,
            "review_required_count": None,
            "unresolved_audit_case_count": None,
            "audit_only_matched_asset_count": None,
            "not_in_management_system_for_cost_center_count": None,
            "pending_not_accounted_count": None,
        }

    system_ids = select(system_asset_ids.c.asset_id)
    state_scope = (
        select(
            AuditCurrentStateProjection.asset_id.label("asset_id"),
            AuditCurrentStateProjection.state.label("state"),
        )
        .join(AssetObservation, AssetObservation.id == AuditCurrentStateProjection.audit_observation_id)
        .where(
            AssetObservation.import_batch_id == audit.id,
            AuditCurrentStateProjection.asset_id.in_(system_ids),
        )
        .subquery()
    )

    def state_count(state: AuditCurrentState) -> int:
        return _count(
            db,
            select(func.count(func.distinct(state_scope.c.asset_id)))
            .where(state_scope.c.state == state),
        )

    found = state_count(AuditCurrentState.FOUND)
    returned = state_count(AuditCurrentState.RETURNED)
    review_required = state_count(AuditCurrentState.REVIEW_REQUIRED)
    audit_only = _count(
        db,
        select(func.count(func.distinct(ReconciliationCase.candidate_asset_id)))
        .select_from(ReconciliationCase)
        .join(AssetObservation, AssetObservation.id == ReconciliationCase.audit_observation_id)
        .where(
            AssetObservation.import_batch_id == audit.id,
            ReconciliationCase.candidate_asset_id.is_not(None),
            ReconciliationCase.candidate_asset_id.not_in(system_ids),
        ),
    )
    unresolved = _unresolved_audit_case_count(db, audit)
    return {
        "current_system_distinct_asset_count": system_count,
        "found_count": found,
        "returned_count": returned,
        "review_required_count": review_required,
        "unresolved_audit_case_count": unresolved,
        "audit_only_matched_asset_count": audit_only,
        "not_in_management_system_for_cost_center_count": _not_in_management_system_for_cost_center_count(audit_only, unresolved),
        "pending_not_accounted_count": system_count - found - returned,
    }


def _summary_metrics(db: Session, system: ImportBatch | None, audit: ImportBatch | None) -> dict[str, int | None]:
    return _summary_metrics_for_assets(db, None if system is None else _system_asset_ids(system), audit)


def _executive_metrics(metrics: dict[str, int | None]) -> dict[str, int | float | None]:
    """Expose the documented KPI names without making the client derive them."""
    system = metrics["current_system_distinct_asset_count"]
    found = metrics["found_count"]
    returned = metrics["returned_count"]
    difference = metrics["pending_not_accounted_count"]
    accounted = None if found is None or returned is None else found + returned
    coverage = None if system is None or accounted is None or system == 0 else round((accounted / system) * 100, 2)
    return {
        "system_count": system,
        "found_in_cost_center_count": found,
        "returned_count": returned,
        "accounted_count": accounted,
        "difference_count": difference,
        "coverage_percent": coverage,
    }


def _operational_issues(metrics: dict[str, int | None]) -> dict[str, int | None]:
    """Keep physical exposure distinct from system-data-quality omissions."""
    return {
        "physical_patrimonial_difference_count": metrics["pending_not_accounted_count"],
        "system_update_required_return_count": metrics["returned_count"],
        "system_data_quality_omission_count": metrics["audit_only_matched_asset_count"],
        "review_required_count": metrics["review_required_count"],
        "unresolved_audit_case_count": metrics["unresolved_audit_case_count"],
        "not_in_management_system_for_cost_center_count": metrics["not_in_management_system_for_cost_center_count"],
    }


def _source_freshness(system: ImportBatch | None, audit: ImportBatch | None) -> dict[str, object]:
    """Chart-owned evidence context; clients must not compare source dates."""
    return {
        "sources": {
            "system": _source_contract(system, ImportSource.SYSTEM),
            "audit": _source_contract(audit, ImportSource.AUDIT),
        },
        "freshness": _freshness(system, audit),
        "report_date_semantics": "Report dates are source snapshot dates. Freshness and shared-cutoff status are determined by the server.",
    }


def _general_status_donut(executive_metrics: dict[str, int | float | None], source_freshness: dict[str, object]) -> dict[str, object]:
    if executive_metrics["accounted_count"] is None:
        return {
            "available": False,
            "reason": "system_and_audit_evidence_required",
            "segments": [],
            "source_freshness": source_freshness,
        }
    return {
        "available": True,
        "semantics": "Mutually exclusive selected-system assets: found in cost center, authorized audit-L return inference, and pending difference.",
        "segments": [
            {"key": "found_in_cost_center", "value": executive_metrics["found_in_cost_center_count"]},
            {"key": "returned", "value": executive_metrics["returned_count"]},
            {"key": "difference", "value": executive_metrics["difference_count"]},
        ],
        "source_freshness": source_freshness,
    }


def _comparable_snapshot_pairs(db: Session, center: CostCenter) -> list[tuple[ImportBatch, ImportBatch]]:
    """Select at most one bounded, deterministic pair for each shared report date."""
    system = aliased(ImportBatch)
    audit = aliased(ImportBatch)
    newer_system = aliased(ImportBatch)
    newer_audit = aliased(ImportBatch)
    statement = (
        select(system, audit)
        .join(
            audit,
            (audit.cost_center_id == system.cost_center_id)
            & (audit.report_date == system.report_date)
            & (audit.source == ImportSource.AUDIT)
            & (audit.status == ImportBatchStatus.COMPLETED),
        )
        .where(
            system.cost_center_id == center.id,
            system.source == ImportSource.SYSTEM,
            system.status == ImportBatchStatus.COMPLETED,
            ~select(newer_system.id)
            .where(
                newer_system.cost_center_id == system.cost_center_id,
                newer_system.source == ImportSource.SYSTEM,
                newer_system.status == ImportBatchStatus.COMPLETED,
                newer_system.report_date == system.report_date,
                newer_system.id > system.id,
            )
            .exists(),
            ~select(newer_audit.id)
            .where(
                newer_audit.cost_center_id == audit.cost_center_id,
                newer_audit.source == ImportSource.AUDIT,
                newer_audit.status == ImportBatchStatus.COMPLETED,
                newer_audit.report_date == audit.report_date,
                newer_audit.id > audit.id,
            )
            .exists(),
        )
        .order_by(system.report_date.desc())
        .limit(MAX_PAGE_SIZE + 1)
    )
    return list(reversed(db.execute(statement).all()))


def _snapshot_time_metrics(db: Session, system: ImportBatch, audit: ImportBatch) -> dict[str, int]:
    """Time points use dated snapshot presence only, never undated audit-L returns."""
    system_ids = _system_asset_ids(system)
    system_count = _count(db, select(func.count()).select_from(system_ids))
    found = _count(
        db,
        select(func.count(func.distinct(ReconciliationCase.candidate_asset_id)))
        .select_from(ReconciliationCase)
        .join(AssetObservation, AssetObservation.id == ReconciliationCase.audit_observation_id)
        .where(
            AssetObservation.import_batch_id == audit.id,
            ReconciliationCase.candidate_asset_id.in_(select(system_ids.c.asset_id)),
        ),
    )
    return {
        "system_count": system_count,
        "found_in_cost_center_count": found,
        "audit_snapshot_difference_count": system_count - found,
    }


def _time_evolution(db: Session, center: CostCenter) -> dict[str, object]:
    pairs = _comparable_snapshot_pairs(db, center)
    if len(pairs) < 2:
        return {
            "available": False,
            "reason": "fewer_than_two_comparable_snapshots",
            "comparison_rule": "Comparable snapshots require completed system and audit batches for the same cost center and report date.",
            "points": [],
            "return_evolution": {
                "available": False,
                "reason": "return_event_time_evidence_unavailable",
                "points": [],
            },
        }
    return {
        "available": True,
        "semantics": "Dated system and audit snapshot presence. Audit-L return inferences are excluded because their event time is not evidenced.",
        "comparison_rule": "Completed system and audit batches for the same cost center and report date; batch UUID is only a deterministic tie-breaker.",
        "points": [
            {"report_date": system.report_date.isoformat(), **_snapshot_time_metrics(db, system, audit)}
            for system, audit in pairs
        ],
        "return_evolution": {
            "available": False,
            "reason": "return_event_time_evidence_unavailable",
            "points": [],
        },
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
    batches = _latest_batches(db, [center.id for center in centers])
    summaries = []
    for center in centers:
        system = batches.get((center.id, ImportSource.SYSTEM))
        audit = batches.get((center.id, ImportSource.AUDIT))
        metrics = _summary_metrics(db, system, audit)
        executive_metrics = _executive_metrics(metrics)
        summaries.append(
            {
                "cost_center": {"code": center.code, "name": center.name},
                "latest_sources": {"system": _source_contract(system, ImportSource.SYSTEM), "audit": _source_contract(audit, ImportSource.AUDIT)},
                "freshness": _freshness(system, audit),
                "metrics": metrics,
                "executive_metrics": executive_metrics,
                "operational_issues": _operational_issues(metrics),
                "charts": {
                    "general_status_donut": _general_status_donut(executive_metrics, _source_freshness(system, audit)),
                    "time_evolution": _time_evolution(db, center),
                },
            }
        )
    return {
        "selection_rule": "Completed batches: greatest report_date, then greatest batch UUID only as a stable selection tie-breaker, never chronology.",
        "metric_scope": "Status and pending metrics are distinct assets in the selected system batch; audit states are projections whose provenance is the selected audit batch. Executive KPI and chart values are calculated only on the server.",
        "summaries": summaries,
        "page": {"limit": limit, "offset": offset, "has_more": has_more, "total_count": total_count},
    }


def _system_label(db: Session, header: str) -> Any:
    """Extract one known system label in SQL while retaining source JSON privately."""
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        cells = func.json_each(AssetObservation.original_data, "$.cells").table_valued("key", "value").alias(f"{header}_cells")
        value = func.json_extract(cells.c.value, "$.value")
        matches_header = func.json_extract(cells.c.value, "$.header") == header
    else:
        cells = func.jsonb_array_elements(AssetObservation.original_data["cells"]).table_valued("value").alias(f"{header}_cells")
        value = func.jsonb_extract_path_text(cells.c.value, "value")
        matches_header = func.jsonb_extract_path_text(cells.c.value, "header") == header
    return (
        select(func.substr(func.trim(value), 1, 255))
        .where(matches_header)
        .correlate(AssetObservation)
        .scalar_subquery()
    )


def _system_leaf_rows(db: Session, batch: ImportBatch) -> Any:
    return (
        select(
            AssetObservation.id.label("observation_id"),
            AssetObservation.asset_id.label("asset_id"),
            AssetObservation.reported_status.label("reported_status"),
            _system_label(db, "Rubro").label("rubro"),
            _system_label(db, "Categoría").label("category"),
            _system_label(db, "Producto").label("product"),
        )
        .where(AssetObservation.import_batch_id == batch.id)
        .subquery()
    )


def _label_order_columns(rows: Any) -> tuple[Any, ...]:
    return (
        rows.c.rubro.is_not(None),
        func.lower(rows.c.rubro),
        rows.c.category.is_not(None),
        func.lower(rows.c.category),
        rows.c.product.is_not(None),
        func.lower(rows.c.product),
    )


def _label_option(value: str | None, null_label: str) -> dict[str, str | None]:
    return {"value": value, "label": null_label if value is None else value}


def _ordered_distinct_rubros(leaf_rows: Any) -> Any:
    """Select distinct rubros before applying their display ordering."""
    distinct_rubros = select(leaf_rows.c.rubro.label("rubro")).distinct().subquery()
    return select(distinct_rubros.c.rubro).order_by(
        distinct_rubros.c.rubro.is_not(None),
        func.lower(distinct_rubros.c.rubro),
        distinct_rubros.c.rubro,
    )


def _ordered_distinct_categories(leaf_rows: Any, rubro: str | None) -> Any:
    """Select distinct selected-rubro categories before display ordering."""
    categories = (
        select(leaf_rows.c.category.label("category"))
        .where(leaf_rows.c.rubro.is_not_distinct_from(rubro))
        .distinct()
        .subquery()
    )
    return select(categories.c.category).order_by(
        categories.c.category.is_not(None),
        func.lower(categories.c.category),
        categories.c.category,
    )


def _rubro_category_chart_items(
    db: Session,
    leaf_rows: Any,
    rubro: str | None,
    audit: ImportBatch | None,
) -> list[dict[str, object]]:
    """Aggregate every selected-rubro category in SQL without product pagination."""
    selected_rows = (
        select(leaf_rows.c.category, leaf_rows.c.asset_id)
        .where(leaf_rows.c.rubro.is_not_distinct_from(rubro))
        .subquery()
    )
    categories = select(selected_rows.c.category).distinct().subquery()
    category_assets = (
        select(selected_rows.c.category, selected_rows.c.asset_id)
        .where(selected_rows.c.asset_id.is_not(None))
        .distinct()
        .subquery()
    )
    category_join = categories.outerjoin(
        category_assets,
        categories.c.category.is_not_distinct_from(category_assets.c.category),
    )
    if audit is None:
        rows = db.execute(
            select(
                categories.c.category,
                func.count(func.distinct(category_assets.c.asset_id)).label("system_count"),
            )
            .select_from(category_join)
            .group_by(categories.c.category)
            .order_by(
                categories.c.category.is_not(None),
                func.lower(categories.c.category),
                categories.c.category,
            )
        ).mappings()
        return [
            {
                "category": row["category"],
                "category_label": "Sin categoría asignada" if row["category"] is None else row["category"],
                "found_in_cost_center_count": None,
                "returned_count": None,
                "difference_count": None,
            }
            for row in rows
        ]

    audit_states = (
        select(
            AuditCurrentStateProjection.asset_id.label("asset_id"),
            AuditCurrentStateProjection.state.label("state"),
        )
        .join(AssetObservation, AssetObservation.id == AuditCurrentStateProjection.audit_observation_id)
        .where(AssetObservation.import_batch_id == audit.id)
        .subquery()
    )
    rows = db.execute(
        select(
            categories.c.category,
            func.count(func.distinct(category_assets.c.asset_id)).label("system_count"),
            func.count(
                func.distinct(
                    case(
                        (audit_states.c.state == AuditCurrentState.FOUND, category_assets.c.asset_id),
                        else_=None,
                    )
                )
            ).label("found_count"),
            func.count(
                func.distinct(
                    case(
                        (audit_states.c.state == AuditCurrentState.RETURNED, category_assets.c.asset_id),
                        else_=None,
                    )
                )
            ).label("returned_count"),
        )
        .select_from(category_join.outerjoin(audit_states, audit_states.c.asset_id == category_assets.c.asset_id))
        .group_by(categories.c.category)
        .order_by(
            categories.c.category.is_not(None),
            func.lower(categories.c.category),
            categories.c.category,
        )
    ).mappings()
    return [
        {
            "category": row["category"],
            "category_label": "Sin categoría asignada" if row["category"] is None else row["category"],
            "found_in_cost_center_count": int(row["found_count"]),
            "returned_count": int(row["returned_count"]),
            "difference_count": int(row["system_count"]) - int(row["found_count"]) - int(row["returned_count"]),
        }
        for row in rows
    ]


def _category_product_chart_items(
    db: Session,
    leaf_rows: Any,
    rubro: str | None,
    category: str | None,
    audit: ImportBatch | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], dict[str, int | bool]]:
    """Aggregate the complete selected hierarchy in SQL, then paginate product groups."""
    selected_rows = (
        select(leaf_rows.c.product, leaf_rows.c.asset_id)
        .where(
            leaf_rows.c.rubro.is_not_distinct_from(rubro),
            leaf_rows.c.category.is_not_distinct_from(category),
        )
        .subquery()
    )
    products = select(selected_rows.c.product.label("product")).distinct().subquery()
    product_assets = (
        select(selected_rows.c.product, selected_rows.c.asset_id)
        .where(selected_rows.c.asset_id.is_not(None))
        .distinct()
        .subquery()
    )
    product_join = products.outerjoin(
        product_assets,
        products.c.product.is_not_distinct_from(product_assets.c.product),
    )
    page = {
        "limit": limit,
        "offset": offset,
        "has_more": False,
        "total_count": _count(db, select(func.count()).select_from(products)),
    }
    if audit is None:
        rows = db.execute(
            select(products.c.product)
            .select_from(product_join)
            .group_by(products.c.product)
            .order_by(products.c.product.is_not(None), func.lower(products.c.product), products.c.product)
            .offset(offset)
            .limit(limit)
        ).mappings()
        items = [
            {
                "product": row["product"],
                "product_label": "Sin producto asignado" if row["product"] is None else row["product"],
                "found_in_cost_center_count": None,
                "returned_count": None,
                "difference_count": None,
            }
            for row in rows
        ]
    else:
        audit_states = (
            select(
                AuditCurrentStateProjection.asset_id.label("asset_id"),
                AuditCurrentStateProjection.state.label("state"),
            )
            .join(AssetObservation, AssetObservation.id == AuditCurrentStateProjection.audit_observation_id)
            .where(AssetObservation.import_batch_id == audit.id)
            .subquery()
        )
        rows = db.execute(
            select(
                products.c.product,
                func.count(func.distinct(product_assets.c.asset_id)).label("system_count"),
                func.count(
                    func.distinct(
                        case(
                            (audit_states.c.state == AuditCurrentState.FOUND, product_assets.c.asset_id),
                            else_=None,
                        )
                    )
                ).label("found_count"),
                func.count(
                    func.distinct(
                        case(
                            (audit_states.c.state == AuditCurrentState.RETURNED, product_assets.c.asset_id),
                            else_=None,
                        )
                    )
                ).label("returned_count"),
            )
            .select_from(product_join.outerjoin(audit_states, audit_states.c.asset_id == product_assets.c.asset_id))
            .group_by(products.c.product)
            .order_by(products.c.product.is_not(None), func.lower(products.c.product), products.c.product)
            .offset(offset)
            .limit(limit)
        ).mappings()
        items = [
            {
                "product": row["product"],
                "product_label": "Sin producto asignado" if row["product"] is None else row["product"],
                "found_in_cost_center_count": int(row["found_count"]),
                "returned_count": int(row["returned_count"]),
                "difference_count": int(row["system_count"]) - int(row["found_count"]) - int(row["returned_count"]),
            }
            for row in rows
        ]
    page["has_more"] = offset + len(items) < page["total_count"]
    return items, page


@router.get("/api/dashboard/rubro-reconciliation-chart")
def rubro_reconciliation_chart(
    cost_center_code: Annotated[str, Query(min_length=1)],
    rubro: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    product_limit: Annotated[int, Query()] = 50,
    product_offset: Annotated[int, Query()] = 0,
    db: Session = Depends(get_db),
    _user: User = Depends(require_viewer),
) -> dict[str, object]:
    """Return a complete category chart and one bounded selected-category product chart."""
    product_limit, product_offset = _page(product_limit, product_offset)
    product_page = {"limit": product_limit, "offset": product_offset, "has_more": False, "total_count": 0}
    code = cost_center_code.strip()
    center = db.scalar(select(CostCenter).where(CostCenter.code == code))
    series = [
        {"key": "found_in_cost_center_count", "label": "found_in_cost_center"},
        {"key": "returned_count", "label": "returned"},
        {"key": "difference_count", "label": "difference"},
    ]

    def product_chart(reason: str) -> dict[str, object]:
        return {
            "available": False,
            "reason": reason,
            "series": series,
            "items": [],
            "source_freshness": source_freshness,
            "page": product_page,
        }

    if center is None:
        source_freshness = _source_freshness(None, None)
        return {
            "cost_center": None,
            "source": _source_contract(None, ImportSource.SYSTEM),
            "audit_source": _source_contract(None, ImportSource.AUDIT),
            "rubro_options": [],
            "selected_rubro": None,
            "category_options": [],
            "selected_category": None,
            "category_chart": {
                "available": False,
                "reason": "cost_center_not_found",
                "series": series,
                "items": [],
                "source_freshness": source_freshness,
            },
            "product_chart": product_chart("cost_center_not_found"),
        }

    batches = _latest_batches(db, [center.id])
    system = batches.get((center.id, ImportSource.SYSTEM))
    audit = batches.get((center.id, ImportSource.AUDIT))
    source_freshness = _source_freshness(system, audit)
    response = {
        "cost_center": {"code": center.code, "name": center.name},
        "source": _source_contract(system, ImportSource.SYSTEM),
        "audit_source": _source_contract(audit, ImportSource.AUDIT),
        "rubro_options": [],
        "selected_rubro": None,
        "category_options": [],
        "selected_category": None,
        "category_chart": {
            "available": False,
            "reason": "missing_system_evidence",
            "series": series,
            "items": [],
            "source_freshness": source_freshness,
        },
        "product_chart": product_chart("missing_system_evidence"),
    }
    if system is None:
        return response

    leaf_rows = _system_leaf_rows(db, system)
    rubro_values = list(db.scalars(_ordered_distinct_rubros(leaf_rows)))
    options = [_label_option(value, "Sin rubro asignado") for value in rubro_values]
    response["rubro_options"] = options
    if not options:
        response["category_chart"]["reason"] = "empty_rubro"
        response["product_chart"] = product_chart("empty_rubro")
        return response

    selected_rubro = options[0]["value"] if rubro is None else (None if rubro == "" else rubro)
    response["selected_rubro"] = _label_option(selected_rubro, "Sin rubro asignado")
    if selected_rubro not in rubro_values:
        response["category_chart"]["reason"] = "invalid_rubro_selection"
        response["product_chart"] = product_chart("invalid_rubro_selection")
        return response

    category_values = list(db.scalars(_ordered_distinct_categories(leaf_rows, selected_rubro)))
    category_options = [_label_option(value, "Sin categoría asignada") for value in category_values]
    response["category_options"] = category_options
    selected_category = category_options[0]["value"] if category is None and category_options else (None if category == "" else category)
    response["selected_category"] = _label_option(selected_category, "Sin categoría asignada")

    items = _rubro_category_chart_items(db, leaf_rows, selected_rubro, audit)
    response["category_chart"]["items"] = items
    if not items:
        response["category_chart"]["reason"] = "empty_rubro"
    elif audit is None:
        response["category_chart"]["reason"] = "missing_audit_evidence"
    else:
        response["category_chart"]["available"] = True
        response["category_chart"]["reason"] = None

    if selected_category not in category_values:
        response["product_chart"] = product_chart("invalid_category_selection")
        return response

    product_items, product_page = _category_product_chart_items(
        db,
        leaf_rows,
        selected_rubro,
        selected_category,
        audit,
        product_limit,
        product_offset,
    )
    response["product_chart"] = {
        "available": audit is not None,
        "reason": None if audit is not None else "missing_audit_evidence",
        "series": series,
        "items": product_items,
        "source_freshness": source_freshness,
        "page": product_page,
    }
    return response


@router.get("/api/dashboard/system-drilldown")
def system_drilldown(
    cost_center_code: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query()] = MAX_PAGE_SIZE,
    offset: Annotated[int, Query()] = 0,
    db: Session = Depends(get_db),
    _user: User = Depends(require_viewer),
) -> dict[str, object]:
    """Return a SQL-paginated Rubro/Categoría/Producto leaf page and chart data."""
    limit, offset = _page(limit, offset)
    page = {"limit": limit, "offset": offset, "has_more": False, "total_count": 0}
    code = cost_center_code.strip()
    center = db.scalar(select(CostCenter).where(CostCenter.code == code))
    empty_primary_chart = {
        "available": False,
        "reason": "system_and_audit_evidence_required",
        "scope": "Categories represented by the requested drill-down leaf page.",
        "series": [],
        "items": [],
    }
    if center is None:
        source_freshness = _source_freshness(None, None)
        return {
            "cost_center": None,
            "source": _source_contract(None, ImportSource.SYSTEM),
            "audit_source": _source_contract(None, ImportSource.AUDIT),
            "groups": [],
            "charts": {
                "primary_stacked_bar": {**empty_primary_chart, "source_freshness": source_freshness},
                "general_status_donut": _general_status_donut(_executive_metrics(_summary_metrics(db, None, None)), source_freshness),
            },
            "page": page,
        }

    batches = _latest_batches(db, [center.id])
    batch = batches.get((center.id, ImportSource.SYSTEM))
    audit = batches.get((center.id, ImportSource.AUDIT))
    source_freshness = _source_freshness(batch, audit)
    if batch is None:
        return {
            "cost_center": {"code": center.code, "name": center.name},
            "source": _source_contract(None, ImportSource.SYSTEM),
            "audit_source": _source_contract(audit, ImportSource.AUDIT),
            "groups": [],
            "charts": {
                "primary_stacked_bar": {**empty_primary_chart, "source_freshness": source_freshness},
                "general_status_donut": _general_status_donut(_executive_metrics(_summary_metrics(db, None, audit)), source_freshness),
            },
            "page": page,
        }

    leaf_rows = _system_leaf_rows(db, batch)
    leaves = (
        select(
            leaf_rows.c.rubro,
            leaf_rows.c.category,
            leaf_rows.c.product,
            func.count().label("observation_count"),
            func.count(func.distinct(leaf_rows.c.asset_id)).label("distinct_asset_count"),
        )
        .select_from(leaf_rows)
        .group_by(leaf_rows.c.rubro, leaf_rows.c.category, leaf_rows.c.product)
        .subquery()
    )
    page["total_count"] = _count(db, select(func.count()).select_from(leaves))
    page_leaves = (
        select(leaves)
        .order_by(*_label_order_columns(leaves))
        .offset(offset)
        .limit(limit + 1)
        .subquery()
    )
    leaf_page = list(db.execute(select(page_leaves).order_by(*_label_order_columns(page_leaves))).mappings())
    page["has_more"] = len(leaf_page) > limit
    leaf_page = leaf_page[:limit]

    status_rows = db.execute(
        select(
            page_leaves.c.rubro,
            page_leaves.c.category,
            page_leaves.c.product,
            leaf_rows.c.reported_status,
            func.count().label("count"),
        )
        .select_from(
            page_leaves.join(
                leaf_rows,
                leaf_rows.c.rubro.is_not_distinct_from(page_leaves.c.rubro)
                & leaf_rows.c.category.is_not_distinct_from(page_leaves.c.category)
                & leaf_rows.c.product.is_not_distinct_from(page_leaves.c.product),
            )
        )
        .group_by(page_leaves.c.rubro, page_leaves.c.category, page_leaves.c.product, leaf_rows.c.reported_status)
    )
    statuses: defaultdict[tuple[str | None, str | None, str | None], list[dict[str, object]]] = defaultdict(list)
    for row in status_rows.mappings():
        key = (row["rubro"], row["category"], row["product"])
        statuses[key].append({"status": _safe_label(row["reported_status"]), "count": int(row["count"])})

    def asset_scope(
        rubro: str | None,
        category: str | None | object = _DIMENSION_OMITTED,
        product: str | None | object = _DIMENSION_OMITTED,
    ) -> Any:
        conditions = [leaf_rows.c.rubro.is_not_distinct_from(rubro), leaf_rows.c.asset_id.is_not(None)]
        if category is not _DIMENSION_OMITTED:
            conditions.append(leaf_rows.c.category.is_not_distinct_from(category))
        if product is not _DIMENSION_OMITTED:
            conditions.append(leaf_rows.c.product.is_not_distinct_from(product))
        return select(leaf_rows.c.asset_id.label("asset_id")).where(*conditions).distinct().subquery()

    def reconciliation_metrics(
        rubro: str | None,
        category: str | None | object = _DIMENSION_OMITTED,
        product: str | None | object = _DIMENSION_OMITTED,
    ) -> dict[str, int | float | None]:
        return _executive_metrics(_summary_metrics_for_assets(db, asset_scope(rubro, category, product), audit))

    grouped: defaultdict[str | None, defaultdict[str | None, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    chart_items: list[dict[str, object]] = []
    chart_categories: set[tuple[str | None, str | None]] = set()
    for leaf in leaf_page:
        rubro, category, product = leaf["rubro"], leaf["category"], leaf["product"]
        if (rubro, category) not in chart_categories:
            chart_categories.add((rubro, category))
            chart_items.append({"rubro": rubro, "category": category, **reconciliation_metrics(rubro, category)})
        grouped[rubro][category].append(
            {
                "product": product,
                "observation_count": int(leaf["observation_count"]),
                "distinct_asset_count": int(leaf["distinct_asset_count"]),
                "status_counts": sorted(statuses[(rubro, category, product)], key=lambda item: ((item["status"] is not None), (item["status"] or "").casefold())),
                "reconciliation_metrics": reconciliation_metrics(rubro, category, product),
            }
        )

    groups = []
    for rubro in sorted(grouped, key=lambda value: (value is not None, (value or "").casefold())):
        categories = []
        for category in sorted(grouped[rubro], key=lambda value: (value is not None, (value or "").casefold())):
            categories.append(
                {
                    "category": category,
                    "reconciliation_metrics": reconciliation_metrics(rubro, category),
                    "products": sorted(grouped[rubro][category], key=lambda item: ((item["product"] is not None), (item["product"] or "").casefold())),
                }
            )
        groups.append({"rubro": rubro, "reconciliation_metrics": reconciliation_metrics(rubro), "categories": categories})

    overall_metrics = _summary_metrics(db, batch, audit)
    executive_metrics = _executive_metrics(overall_metrics)
    primary_chart = {
        "available": executive_metrics["accounted_count"] is not None,
        "reason": None if executive_metrics["accounted_count"] is not None else "system_and_audit_evidence_required",
        "scope": "Categories represented by the requested drill-down leaf page; each category metric covers its complete selected system group.",
        "series": [
            {"key": "found_in_cost_center_count", "label": "found_in_cost_center"},
            {"key": "returned_count", "label": "returned"},
            {"key": "difference_count", "label": "difference"},
        ],
        "items": chart_items,
        "source_freshness": source_freshness,
    }
    return {
        "cost_center": {"code": center.code, "name": center.name},
        "source": _source_contract(batch, ImportSource.SYSTEM),
        "audit_source": _source_contract(audit, ImportSource.AUDIT),
        "executive_metrics": executive_metrics,
        "operational_issues": _operational_issues(overall_metrics),
        "groups": groups,
        "charts": {"primary_stacked_bar": primary_chart, "general_status_donut": _general_status_donut(executive_metrics, source_freshness)},
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
