"""Persist reproducible current state derived from audit column L.

Revision ID: 20260921_0005
Revises: 20260920_0004
Create Date: 2026-09-21 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260921_0005"
down_revision: Union[str, None] = "20260920_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

audit_current_state = sa.Enum("found", "returned", "review_required", name="audit_current_state", create_constraint=True)
audit_return_marker_category = sa.Enum(
    "recognized_return", "ambiguous_return", "unmarked_unknown",
    name="audit_return_marker_category",
    create_constraint=True,
)
json_document = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "audit_current_state_projections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("cost_center_id", sa.Uuid(), nullable=False),
        sa.Column("audit_observation_id", sa.Uuid(), nullable=False),
        sa.Column("state", audit_current_state, nullable=False),
        sa.Column("marker_category", audit_return_marker_category, nullable=False),
        sa.Column("marker_raw_value", json_document, nullable=True),
        sa.Column("marker_column", sa.Integer(), server_default=sa.text("12"), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("projection_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("marker_column = 12", name="audit_current_state_marker_column_l"),
        sa.CheckConstraint(
            "(state = 'returned' AND marker_category = 'recognized_return') "
            "OR (state = 'review_required' AND marker_category = 'ambiguous_return') "
            "OR (state = 'found' AND marker_category = 'unmarked_unknown')",
            name="audit_current_state_matches_marker_category",
        ),
        sa.CheckConstraint("length(projection_version) > 0", name="audit_current_state_projection_version_not_empty"),
        sa.CheckConstraint("length(reason) > 0", name="audit_current_state_reason_not_empty"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["audit_observation_id"], ["asset_observations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_current_state_projections"),
        sa.UniqueConstraint("asset_id", "cost_center_id", name="audit_current_state_per_asset_cost_center"),
    )
    op.create_index(
        "ix_audit_current_state_projections_cost_center_id",
        "audit_current_state_projections",
        ["cost_center_id"],
        unique=False,
    )
    op.create_index("ix_audit_current_state_projections_state", "audit_current_state_projections", ["state"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_current_state_projections_state", table_name="audit_current_state_projections")
    op.drop_index("ix_audit_current_state_projections_cost_center_id", table_name="audit_current_state_projections")
    op.drop_table("audit_current_state_projections")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        audit_return_marker_category.drop(bind, checkfirst=True)
        audit_current_state.drop(bind, checkfirst=True)
