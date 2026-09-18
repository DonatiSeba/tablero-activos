"""Core persistence entities for the asset-reconciliation domain.

Original source values are stored beside their normalized counterparts so that
matching never destroys the evidence supplied by an import.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from .db import Base

JSON_DOCUMENT = JSONB().with_variant(JSON(), "sqlite")
IP_ADDRESS = INET().with_variant(String(45), "sqlite")


def persisted_enum(enum_class: type[enum.Enum], name: str) -> Enum:
    """Persist Python enum values, matching the lowercase PostgreSQL enum labels."""
    return Enum(
        enum_class,
        name=name,
        create_constraint=True,
        values_callable=lambda enum_type: [member.value for member in enum_type],
    )


class UserRole(str, enum.Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


class CostCenterStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ImportSource(str, enum.Enum):
    SYSTEM = "system"
    AUDIT = "audit"
    RETURN = "return"


class ObservationEvent(str, enum.Enum):
    SNAPSHOT = "snapshot"
    FOUND = "found"
    RETURNED = "returned"


class ImportBatchStatus(str, enum.Enum):
    COMPLETED = "completed"
    REJECTED = "rejected"


class ReconciliationState(str, enum.Enum):
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    RETURNED = "returned"
    REVIEW_REQUIRED = "review_required"


class AuditMatchStrategy(str, enum.Enum):
    EXACT_ORIGINAL_CODE = "exact_original_code"
    NORMALIZED_CODE = "normalized_code"


class AuditMatchReason(str, enum.Enum):
    MISSING_IDENTIFIER = "missing_identifier"
    NO_NORMALIZED_CANDIDATE = "no_normalized_candidate"
    AMBIGUOUS_NORMALIZED_CANDIDATE = "ambiguous_normalized_candidate"


class AuditReturnMarkerCategory(str, enum.Enum):
    """Interpretation of the immutable blank-header audit column L value."""

    RECOGNIZED_RETURN = "recognized_return"
    AMBIGUOUS_RETURN = "ambiguous_return"
    UNMARKED_UNKNOWN = "unmarked_unknown"


class AuditCurrentState(str, enum.Enum):
    FOUND = "found"
    RETURNED = "returned"
    REVIEW_REQUIRED = "review_required"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        persisted_enum(UserRole, name="user_role"), nullable=False, default=UserRole.VIEWER
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserSession(Base):
    """A server-side session record; cookies contain only a signed session identifier."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"), Index("ix_user_sessions_expires_at", "expires_at"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CostCenter(Base):
    __tablename__ = "cost_centers"
    __table_args__ = (
        CheckConstraint("length(code) > 0", name="cost_center_code_not_empty"),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="cost_center_date_range",
        ),
        Index("ix_cost_centers_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CostCenterStatus] = mapped_column(
        persisted_enum(CostCenterStatus, name="cost_center_status"),
        nullable=False,
        default=CostCenterStatus.ACTIVE,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("length(original_code) > 0", name="asset_original_code_not_empty"),
        CheckConstraint("length(normalized_code) > 0", name="asset_normalized_code_not_empty"),
        CheckConstraint("serial_number IS NULL OR length(serial_number) > 0", name="asset_serial_number_not_empty"),
        Index("ix_assets_normalized_code", "normalized_code"),
        Index("ix_assets_serial_number", "serial_number"),
        Index("ix_assets_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    original_code: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    normalized_code: Mapped[str] = mapped_column(String(255), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AssetAlias(Base):
    __tablename__ = "asset_aliases"
    __table_args__ = (
        UniqueConstraint("asset_id", "original_alias", name="asset_alias_original_per_asset"),
        CheckConstraint("length(original_alias) > 0", name="asset_alias_original_not_empty"),
        CheckConstraint("length(normalized_alias) > 0", name="asset_alias_normalized_not_empty"),
        Index("ix_asset_aliases_normalized_alias", "normalized_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[ImportSource] = mapped_column(
        persisted_enum(ImportSource, name="import_source"), nullable=False
    )
    original_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("length(sha256) = 64", name="import_batch_sha256_length"),
        CheckConstraint("row_count >= 0", name="import_batch_row_count_nonnegative"),
        Index("ix_import_batches_cost_center_id", "cost_center_id"),
        Index("ix_import_batches_report_date", "report_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[ImportSource] = mapped_column(
        persisted_enum(ImportSource, name="import_source"), nullable=False
    )
    cost_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cost_centers.id", ondelete="RESTRICT"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ImportBatchStatus] = mapped_column(
        persisted_enum(ImportBatchStatus, name="import_batch_status"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    row_count: Mapped[int] = mapped_column(nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    imported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AssetObservation(Base):
    __tablename__ = "asset_observations"
    __table_args__ = (
        Index("ix_asset_observations_source_observed_on", "source", "observed_on"),
        Index("ix_asset_observations_asset_id", "asset_id"),
        Index("ix_asset_observations_cost_center_id", "cost_center_id"),
        Index("ix_asset_observations_reported_status", "reported_status"),
        CheckConstraint("quantity > 0", name="asset_observation_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[ImportSource] = mapped_column(
        persisted_enum(ImportSource, name="observation_source"), nullable=False
    )
    event: Mapped[ObservationEvent] = mapped_column(
        persisted_enum(ObservationEvent, name="observation_event"), nullable=False
    )
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    cost_center_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True
    )
    original_data: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    reported_status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, default=Decimal("1"), server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReconciliationCase(Base):
    """One derived, deterministic match outcome for one audit observation.

    This deliberately does not reuse ``ReconciliationResult``: unmatched audit
    evidence has no asset identity and therefore cannot satisfy that table's
    non-null asset coverage invariant.
    """

    __tablename__ = "reconciliation_cases"
    __table_args__ = (
        UniqueConstraint("audit_observation_id", name="reconciliation_case_per_audit_observation"),
        CheckConstraint(
            "(candidate_asset_id IS NOT NULL AND match_strategy IS NOT NULL AND match_reason IS NULL) "
            "OR (candidate_asset_id IS NULL AND match_strategy IS NULL AND match_reason IS NOT NULL)",
            name="reconciliation_case_valid_outcome",
        ),
        Index("ix_reconciliation_cases_candidate_asset_id", "candidate_asset_id"),
        Index("ix_reconciliation_cases_cost_center_id", "cost_center_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audit_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset_observations.id", ondelete="RESTRICT"), nullable=False
    )
    cost_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cost_centers.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True
    )
    match_strategy: Mapped[AuditMatchStrategy | None] = mapped_column(
        persisted_enum(AuditMatchStrategy, name="audit_match_strategy"), nullable=True
    )
    match_reason: Mapped[AuditMatchReason | None] = mapped_column(
        persisted_enum(AuditMatchReason, name="audit_match_reason"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditCurrentStateProjection(Base):
    """Reproducible current audit state; it never changes the source evidence.

    Version ``audit_l_return_v1`` implements the user's authorized assumption
    that a recognized column-L return marker occurred after its audit snapshot.
    """

    __tablename__ = "audit_current_state_projections"
    __table_args__ = (
        UniqueConstraint("asset_id", "cost_center_id", name="audit_current_state_per_asset_cost_center"),
        CheckConstraint("marker_column = 12", name="audit_current_state_marker_column_l"),
        CheckConstraint(
            "(state = 'returned' AND marker_category = 'recognized_return') "
            "OR (state = 'review_required' AND marker_category = 'ambiguous_return') "
            "OR (state = 'found' AND marker_category = 'unmarked_unknown')",
            name="audit_current_state_matches_marker_category",
        ),
        CheckConstraint("length(projection_version) > 0", name="audit_current_state_projection_version_not_empty"),
        CheckConstraint("length(reason) > 0", name="audit_current_state_reason_not_empty"),
        Index("ix_audit_current_state_projections_cost_center_id", "cost_center_id"),
        Index("ix_audit_current_state_projections_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    cost_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cost_centers.id", ondelete="RESTRICT"), nullable=False
    )
    audit_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset_observations.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[AuditCurrentState] = mapped_column(
        persisted_enum(AuditCurrentState, name="audit_current_state"), nullable=False
    )
    marker_category: Mapped[AuditReturnMarkerCategory] = mapped_column(
        persisted_enum(AuditReturnMarkerCategory, name="audit_return_marker_category"), nullable=False
    )
    # A scalar copy supports a minimal read API; the authoritative typed raw
    # cell and its sheet/row provenance remain in AssetObservation.original_data.
    marker_raw_value: Mapped[Any | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    marker_column: Mapped[int] = mapped_column(nullable=False, default=12, server_default=text("12"))
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (
        UniqueConstraint("asset_id", "cost_center_id", name="reconciliation_result_coverage"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="reconciliation_confidence_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    cost_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cost_centers.id", ondelete="RESTRICT"), nullable=False
    )
    system_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_observations.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    audit_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_observations.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    return_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_observations.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    state: Mapped[ReconciliationState] = mapped_column(
        persisted_enum(ReconciliationState, name="reconciliation_state"), nullable=False
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_target", "target_entity", "target_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_entity: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(IP_ADDRESS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
