"""Protected cost-center management contracts for authorized importers."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_admin, require_editor, write_audit_log
from .db import get_db
from .models import CostCenter, CostCenterStatus, User

router = APIRouter(prefix="/api/cost-centers", tags=["cost centers"])


class CostCenterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: CostCenterStatus
    start_date: date | None
    end_date: date | None
    created_at: datetime
    updated_at: datetime


class CostCenterCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    status: CostCenterStatus = CostCenterStatus.ACTIVE
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def trim_required_values(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("value must not be blank")
        return value

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: object) -> object:
        if isinstance(value, CostCenterStatus):
            return value
        if value not in (CostCenterStatus.ACTIVE.value, CostCenterStatus.INACTIVE.value):
            raise ValueError("status must be active or inactive")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> CostCenterCreateRequest:
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class CostCenterUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: CostCenterStatus | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("code", "name", mode="before")
    @classmethod
    def trim_optional_values(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("value must not be blank")
        return value

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: object) -> object:
        if value is None or isinstance(value, CostCenterStatus):
            return value
        if value not in (CostCenterStatus.ACTIVE.value, CostCenterStatus.INACTIVE.value):
            raise ValueError("status must be active or inactive")
        return value


def _audit_denial(
    db: Session,
    request: Request,
    actor: User,
    *,
    action: str,
    target_id: uuid.UUID | None,
    reason: str,
    status_code: int,
    detail: str,
) -> None:
    write_audit_log(
        db,
        request,
        action=action,
        target_entity="cost_center",
        target_id=target_id,
        user_id=actor.id,
        details={"reason": reason},
    )
    db.commit()
    raise HTTPException(status_code=status_code, detail=detail)


def _duplicate_code(db: Session, code: str, excluded_id: uuid.UUID | None = None) -> bool:
    statement = select(CostCenter.id).where(CostCenter.code == code)
    if excluded_id is not None:
        statement = statement.where(CostCenter.id != excluded_id)
    return db.scalar(statement.limit(1)) is not None


def _integrity_conflict(
    db: Session,
    request: Request,
    actor: User,
    *,
    action: str,
    target_id: uuid.UUID | None,
) -> None:
    db.rollback()
    _audit_denial(
        db,
        request,
        actor,
        action=action,
        target_id=target_id,
        reason="duplicate_code",
        status_code=status.HTTP_409_CONFLICT,
        detail="Cost center code already exists",
    )


@router.get("", response_model=list[CostCenterResponse])
def list_cost_centers(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_editor)],
    active_only: Annotated[bool, Query()] = False,
) -> list[CostCenter]:
    """List centers available to import operators, optionally excluding inactive ones."""
    statement = select(CostCenter).order_by(CostCenter.code, CostCenter.id)
    if active_only:
        statement = statement.where(CostCenter.status == CostCenterStatus.ACTIVE)
    return list(db.scalars(statement))


@router.post("", response_model=CostCenterResponse, status_code=status.HTTP_201_CREATED)
def create_cost_center(
    payload: CostCenterCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> CostCenter:
    if _duplicate_code(db, payload.code):
        _audit_denial(
            db,
            request,
            actor,
            action="cost_centers.create_denied",
            target_id=None,
            reason="duplicate_code",
            status_code=status.HTTP_409_CONFLICT,
            detail="Cost center code already exists",
        )

    center = CostCenter(
        code=payload.code,
        name=payload.name,
        status=payload.status,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    db.add(center)
    try:
        db.flush()
        write_audit_log(
            db,
            request,
            action="cost_centers.created",
            target_entity="cost_center",
            target_id=center.id,
            user_id=actor.id,
            details={"status": center.status.value},
        )
        db.commit()
    except IntegrityError:
        _integrity_conflict(
            db,
            request,
            actor,
            action="cost_centers.create_denied",
            target_id=None,
        )
    return center


@router.patch("/{cost_center_id}", response_model=CostCenterResponse)
def update_cost_center(
    cost_center_id: uuid.UUID,
    payload: CostCenterUpdateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_admin)],
) -> CostCenter:
    center = db.scalar(select(CostCenter).where(CostCenter.id == cost_center_id).with_for_update())
    if center is None:
        _audit_denial(
            db,
            request,
            actor,
            action="cost_centers.update_denied",
            target_id=cost_center_id,
            reason="not_found",
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cost center not found",
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        _audit_denial(
            db,
            request,
            actor,
            action="cost_centers.update_denied",
            target_id=cost_center_id,
            reason="no_changes",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one management field is required",
        )
    if any(changes.get(field) is None for field in ("code", "name", "status") if field in changes):
        _audit_denial(
            db,
            request,
            actor,
            action="cost_centers.update_denied",
            target_id=cost_center_id,
            reason="null_required_field",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Code, name, and status cannot be null",
        )

    code = changes.get("code", center.code)
    if _duplicate_code(db, code, excluded_id=center.id):
        _audit_denial(
            db,
            request,
            actor,
            action="cost_centers.update_denied",
            target_id=center.id,
            reason="duplicate_code",
            status_code=status.HTTP_409_CONFLICT,
            detail="Cost center code already exists",
        )

    start_date = changes.get("start_date", center.start_date)
    end_date = changes.get("end_date", center.end_date)
    if start_date is not None and end_date is not None and end_date < start_date:
        _audit_denial(
            db,
            request,
            actor,
            action="cost_centers.update_denied",
            target_id=center.id,
            reason="invalid_date_range",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be on or after start_date",
        )

    if all(getattr(center, field) == value for field, value in changes.items()):
        _audit_denial(
            db,
            request,
            actor,
            action="cost_centers.update_denied",
            target_id=center.id,
            reason="no_changes",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one management field is required",
        )

    for field, value in changes.items():
        setattr(center, field, value)
    try:
        db.flush()
        write_audit_log(
            db,
            request,
            action="cost_centers.updated",
            target_entity="cost_center",
            target_id=center.id,
            user_id=actor.id,
            details={"fields": sorted(changes)},
        )
        db.commit()
    except IntegrityError:
        _integrity_conflict(
            db,
            request,
            actor,
            action="cost_centers.update_denied",
            target_id=cost_center_id,
        )
    return center
