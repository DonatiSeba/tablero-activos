"""Authorized ingestion of immutable system-report evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit_current_states import rebuild_audit_current_state_projections
from .audit_imports import match_audit_identifier, parse_audit_report
from .auth import require_editor, write_audit_log
from .db import get_db
from .models import (
    Asset,
    AssetObservation,
    AuditMatchReason,
    AuditMatchStrategy,
    CostCenter,
    CostCenterStatus,
    ImportBatch,
    ImportBatchStatus,
    ImportSource,
    ObservationEvent,
    ReconciliationCase,
    User,
)
from .system_imports import (
    ImportValidationError,
    StorageIntegrityError,
    normalize_asset_code,
    original_asset_code,
    parse_report_date,
    parse_system_report,
    read_upload_content,
    sha256_hex,
    store_original_file,
)

router = APIRouter(prefix="/api/imports", tags=["imports"])


def _reject_import(
    db: Session, request: Request, user: User, *, code: str, detail: str, status_code: int, source: str = "system"
) -> None:
    """Commit a value-minimized rejection audit before returning its client error."""
    write_audit_log(
        db,
        request,
        action=f"imports.{source}_rejected",
        target_entity="import",
        user_id=user.id,
        details={"reason": code},
    )
    db.commit()
    raise HTTPException(status_code=status_code, detail=detail)


def _resolve_active_cost_center(
    db: Session,
    request: Request,
    user: User,
    code: str,
    *,
    source: str,
) -> CostCenter:
    """Resolve an explicitly selected center without mutating center lifecycle state."""
    cost_center = db.scalar(select(CostCenter).where(CostCenter.code == code))
    if cost_center is None:
        _reject_import(
            db,
            request,
            user,
            code="unknown_cost_center",
            detail="cost_center_code does not exist",
            status_code=422,
            source=source,
        )
    if cost_center.status is not CostCenterStatus.ACTIVE:
        _reject_import(
            db,
            request,
            user,
            code="inactive_cost_center",
            detail="cost_center_code is inactive",
            status_code=422,
            source=source,
        )
    return cost_center


def _asset_for_exact_code(db: Session, cache: dict[str, Asset], original_code: str, row: dict[str, object]) -> Asset:
    """Associate only on exact original source code; normalized values are never queried."""
    asset = cache.get(original_code)
    if asset is None:
        asset = db.scalar(select(Asset).where(Asset.original_code == original_code))
        if asset is None:
            asset = Asset(
                original_code=original_code,
                normalized_code=normalize_asset_code(original_code),
                description=str(row["Producto"]) if row["Producto"] is not None else None,
                category=str(row["Categoría"]) if row["Categoría"] is not None else None,
            )
            db.add(asset)
            db.flush()
        cache[original_code] = asset
    return asset


@router.post("/system", status_code=status.HTTP_201_CREATED)
def import_system_report(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    report_date: Annotated[str | None, Form()] = None,
    cost_center_code: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
) -> dict[str, object]:
    """Persist one validated CC190-style report as immutable system evidence."""
    if file is None:
        _reject_import(db, request, user, code="missing_file", detail="multipart field file is required", status_code=400)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        _reject_import(db, request, user, code="invalid_file_type", detail="file must have a .xlsx filename", status_code=400)
    try:
        parsed_date = parse_report_date(report_date)
        if cost_center_code is None or not cost_center_code.strip():
            raise ImportValidationError("missing_cost_center_code", "cost_center_code is required")
        selected_cost_center_code = cost_center_code.strip()
    except ImportValidationError as error:
        _reject_import(db, request, user, code=error.code, detail=error.detail, status_code=422)

    cost_center = _resolve_active_cost_center(
        db, request, user, selected_cost_center_code, source="system"
    )

    try:
        content = read_upload_content(file.file)
        if not content:
            raise ImportValidationError("missing_file", "uploaded file is empty")
        report = parse_system_report(content)
    except ImportValidationError as error:
        _reject_import(db, request, user, code=error.code, detail=error.detail, status_code=422)
    except OSError:
        _reject_import(db, request, user, code="upload_read_error", detail="could not read uploaded file", status_code=422)

    digest = sha256_hex(content)
    if db.scalar(select(ImportBatch.id).where(ImportBatch.sha256 == digest)) is not None:
        _reject_import(db, request, user, code="duplicate_sha256", detail="this file content was already imported", status_code=409)

    try:
        if report.cost_center_code != selected_cost_center_code:
            _reject_import(
                db,
                request,
                user,
                code="cost_center_mismatch",
                detail="workbook Nro. CC does not match cost_center_code",
                status_code=422,
            )

        observed_names = report.observed_cost_center_names
        if not observed_names:
            _reject_import(
                db,
                request,
                user,
                code="blank_cost_center_name",
                detail="at least one Centro de Costo value is required",
                status_code=422,
            )
        warnings: list[dict[str, object]] = []
        differing_names = [name for name in observed_names if name != cost_center.name]
        if differing_names:
            warnings.append(
                {
                    "code": "divergent_cost_center_names",
                    "observed_names": list(observed_names),
                    "stored_name": cost_center.name,
                }
            )

        missing_asset_code_rows = sum(
            1 for row in report.rows if not original_asset_code(row.named_values["Cód. Ident."]).strip()
        )
        if missing_asset_code_rows:
            warnings.append({"code": "missing_asset_code", "row_count": missing_asset_code_rows})

        storage_path, _ = store_original_file(content, digest)
        batch = ImportBatch(
            source=ImportSource.SYSTEM,
            cost_center_id=cost_center.id,
            report_date=parsed_date,
            status=ImportBatchStatus.COMPLETED,
            original_filename=file.filename,
            sha256=digest,
            storage_path=storage_path,
            row_count=len(report.rows),
            metadata_json={"warnings": warnings} if warnings else None,
            imported_by_user_id=user.id,
        )
        db.add(batch)
        db.flush()
        assets: dict[str, Asset] = {}
        for row in report.rows:
            named_values = row.named_values
            original_code = original_asset_code(named_values["Cód. Ident."])
            asset = None
            if original_code.strip():
                asset = _asset_for_exact_code(db, assets, original_code, named_values)
            db.add(
                AssetObservation(
                    import_batch_id=batch.id,
                    source=ImportSource.SYSTEM,
                    event=ObservationEvent.SNAPSHOT,
                    observed_on=parsed_date,
                    asset_id=asset.id if asset is not None else None,
                    cost_center_id=cost_center.id,
                    original_data=row.original_data,
                    reported_status=str(named_values["Estado"]) if named_values["Estado"] is not None else None,
                    quantity=Decimal("1"),
                )
            )
        write_audit_log(
            db,
            request,
            action="imports.system_accepted",
            target_entity="import_batch",
            target_id=batch.id,
            user_id=user.id,
            details={"row_count": len(report.rows)},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate_exists = db.scalar(select(ImportBatch.id).where(ImportBatch.sha256 == digest)) is not None
        if duplicate_exists:
            _reject_import(db, request, user, code="duplicate_sha256", detail="this file content was already imported", status_code=409)
        _reject_import(
            db,
            request,
            user,
            code="database_integrity_error",
            detail="could not persist import evidence because of a database constraint",
            status_code=409,
        )
    except StorageIntegrityError:
        db.rollback()
        _reject_import(
            db,
            request,
            user,
            code="storage_integrity_failure",
            detail="stored evidence integrity could not be verified",
            status_code=503,
        )
    except OSError:
        db.rollback()
        _reject_import(db, request, user, code="storage_failure", detail="could not store the original file", status_code=503)
    except Exception:
        db.rollback()
        raise

    return {
        "id": str(batch.id),
        "source": batch.source.value,
        "status": batch.status.value,
        "report_date": batch.report_date.isoformat(),
        "cost_center": {"code": cost_center.code, "name": cost_center.name},
        "row_count": batch.row_count,
        "warnings": warnings,
    }


@router.post("/audit", status_code=status.HTTP_201_CREATED)
def import_audit_report(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    report_date: Annotated[str | None, Form()] = None,
    cost_center_code: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
) -> dict[str, object]:
    """Persist physical-audit source evidence and one derived case per row."""
    if file is None:
        _reject_import(db, request, user, code="missing_file", detail="multipart field file is required", status_code=400, source="audit")
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        _reject_import(db, request, user, code="invalid_file_type", detail="file must have a .xlsx filename", status_code=400, source="audit")
    try:
        parsed_date = parse_report_date(report_date)
        if cost_center_code is None or not cost_center_code.strip():
            raise ImportValidationError("missing_cost_center_code", "cost_center_code is required")
        selected_cost_center_code = cost_center_code.strip()
    except ImportValidationError as error:
        _reject_import(db, request, user, code=error.code, detail=error.detail, status_code=422, source="audit")

    cost_center = _resolve_active_cost_center(
        db, request, user, selected_cost_center_code, source="audit"
    )

    try:
        content = read_upload_content(file.file)
        if not content:
            raise ImportValidationError("missing_file", "uploaded file is empty")
        report = parse_audit_report(content)
    except ImportValidationError as error:
        _reject_import(db, request, user, code=error.code, detail=error.detail, status_code=422, source="audit")
    except OSError:
        _reject_import(db, request, user, code="upload_read_error", detail="could not read uploaded file", status_code=422, source="audit")

    digest = sha256_hex(content)
    if db.scalar(select(ImportBatch.id).where(ImportBatch.sha256 == digest)) is not None:
        _reject_import(db, request, user, code="duplicate_sha256", detail="this file content was already imported", status_code=409, source="audit")

    try:
        storage_path, _ = store_original_file(content, digest)
        batch = ImportBatch(
            source=ImportSource.AUDIT,
            cost_center_id=cost_center.id,
            report_date=parsed_date,
            status=ImportBatchStatus.COMPLETED,
            original_filename=file.filename,
            sha256=digest,
            storage_path=storage_path,
            row_count=len(report.rows),
            imported_by_user_id=user.id,
        )
        db.add(batch)
        db.flush()
        counts: dict[str, int] = {strategy.value: 0 for strategy in AuditMatchStrategy}
        counts.update({reason.value: 0 for reason in AuditMatchReason})
        for row in report.rows:
            observation = AssetObservation(
                import_batch_id=batch.id,
                source=ImportSource.AUDIT,
                # Audit condition fields are evidence, not return/found semantics.
                event=ObservationEvent.SNAPSHOT,
                observed_on=parsed_date,
                asset_id=None,
                cost_center_id=cost_center.id,
                original_data=row.original_data,
                reported_status=str(row.named_values["FUNCIONAMIENTO"]) if row.named_values["FUNCIONAMIENTO"] is not None else None,
                quantity=row.quantity,
            )
            db.add(observation)
            db.flush()
            match = match_audit_identifier(db, row.identifier)
            if match.strategy is not None:
                counts[match.strategy.value] += 1
            else:
                assert match.reason is not None
                counts[match.reason.value] += 1
            db.add(
                ReconciliationCase(
                    audit_observation_id=observation.id,
                    cost_center_id=cost_center.id,
                    candidate_asset_id=match.candidate_asset.id if match.candidate_asset is not None else None,
                    match_strategy=match.strategy,
                    match_reason=match.reason,
                )
            )
        warnings = [
            {"code": reason.value, "row_count": counts[reason.value]}
            for reason in AuditMatchReason
            if counts[reason.value]
        ]
        current_state_counts = rebuild_audit_current_state_projections(db)
        write_audit_log(
            db,
            request,
            action="imports.audit_accepted",
            target_entity="import_batch",
            target_id=batch.id,
            user_id=user.id,
            details={"row_count": len(report.rows), "match_counts": counts, "current_state_counts": current_state_counts},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate_exists = db.scalar(select(ImportBatch.id).where(ImportBatch.sha256 == digest)) is not None
        if duplicate_exists:
            _reject_import(db, request, user, code="duplicate_sha256", detail="this file content was already imported", status_code=409, source="audit")
        _reject_import(db, request, user, code="database_integrity_error", detail="could not persist import evidence because of a database constraint", status_code=409, source="audit")
    except StorageIntegrityError:
        db.rollback()
        _reject_import(db, request, user, code="storage_integrity_failure", detail="stored evidence integrity could not be verified", status_code=503, source="audit")
    except OSError:
        db.rollback()
        _reject_import(db, request, user, code="storage_failure", detail="could not store the original file", status_code=503, source="audit")

    return {
        "id": str(batch.id),
        "source": batch.source.value,
        "status": batch.status.value,
        "report_date": batch.report_date.isoformat(),
        "cost_center": {"code": cost_center.code, "name": cost_center.name},
        "row_count": batch.row_count,
        "match_counts": counts,
        "current_state_counts": current_state_counts,
        "warnings": warnings,
    }
