"""Add derived reconciliation cases for immutable physical-audit evidence.

Revision ID: 20260920_0004
Revises: 20260919_0003
Create Date: 2026-09-20 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260920_0004"
down_revision: Union[str, None] = "20260919_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

audit_match_strategy = sa.Enum("exact_original_code", "normalized_code", name="audit_match_strategy", create_constraint=True)
audit_match_reason = sa.Enum(
    "missing_identifier", "no_normalized_candidate", "ambiguous_normalized_candidate",
    name="audit_match_reason", create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "reconciliation_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("audit_observation_id", sa.Uuid(), nullable=False),
        sa.Column("cost_center_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_asset_id", sa.Uuid(), nullable=True),
        sa.Column("match_strategy", audit_match_strategy, nullable=True),
        sa.Column("match_reason", audit_match_reason, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "(candidate_asset_id IS NOT NULL AND match_strategy IS NOT NULL AND match_reason IS NULL) "
            "OR (candidate_asset_id IS NULL AND match_strategy IS NULL AND match_reason IS NOT NULL)",
            name="ck_reconciliation_cases_reconciliation_case_valid_outcome",
        ),
        sa.ForeignKeyConstraint(["audit_observation_id"], ["asset_observations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_reconciliation_cases"),
        sa.UniqueConstraint("audit_observation_id", name="reconciliation_case_per_audit_observation"),
    )
    op.create_index("ix_reconciliation_cases_candidate_asset_id", "reconciliation_cases", ["candidate_asset_id"], unique=False)
    op.create_index("ix_reconciliation_cases_cost_center_id", "reconciliation_cases", ["cost_center_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reconciliation_cases_cost_center_id", table_name="reconciliation_cases")
    op.drop_index("ix_reconciliation_cases_candidate_asset_id", table_name="reconciliation_cases")
    op.drop_table("reconciliation_cases")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        audit_match_reason.drop(bind, checkfirst=True)
        audit_match_strategy.drop(bind, checkfirst=True)
