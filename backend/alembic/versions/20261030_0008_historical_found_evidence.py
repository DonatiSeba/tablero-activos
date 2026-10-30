"""Add durable manual-to-BG historical-found relationship projections.

Revision ID: 20261030_0008
Revises: 20261029_0007
Create Date: 2026-10-30 00:08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261030_0008"
down_revision: Union[str, None] = "20261029_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

historical_found_link_strategy = sa.Enum(
    "exact_bg_code",
    "whitespace_normalized_bg_code",
    "embedded_identifier_or_serial",
    name="historical_found_link_strategy",
    create_constraint=True,
)
historical_found_link_reason = sa.Enum(
    "no_bg_candidate",
    "ambiguous_bg_candidate",
    name="historical_found_link_reason",
    create_constraint=True,
)


def upgrade() -> None:
    # These are new enum types. Unlike ALTER TYPE ... ADD VALUE, CREATE TYPE is
    # usable by this table in the same PostgreSQL migration transaction; 0007's
    # autocommit boundary remains necessary for its added enum values.
    op.create_table(
        "historical_found_evidence_projections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("manual_observation_id", sa.Uuid(), nullable=False),
        sa.Column("bg_observation_id", sa.Uuid(), nullable=True),
        sa.Column("link_strategy", historical_found_link_strategy, nullable=True),
        sa.Column("link_reason", historical_found_link_reason, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "(bg_observation_id IS NOT NULL AND link_strategy IS NOT NULL AND link_reason IS NULL) "
            "OR (bg_observation_id IS NULL AND link_strategy IS NULL AND link_reason IS NOT NULL)",
            name="historical_found_link_valid_outcome",
        ),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manual_observation_id"], ["asset_observations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bg_observation_id"], ["asset_observations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manual_observation_id", name="historical_found_manual_observation_once"),
    )
    op.create_index(
        "ix_historical_found_evidence_projections_import_batch_id",
        "historical_found_evidence_projections",
        ["import_batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_historical_found_evidence_projections_bg_observation_id",
        "historical_found_evidence_projections",
        ["bg_observation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_historical_found_evidence_projections_bg_observation_id", table_name="historical_found_evidence_projections")
    op.drop_index("ix_historical_found_evidence_projections_import_batch_id", table_name="historical_found_evidence_projections")
    op.drop_table("historical_found_evidence_projections")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        historical_found_link_reason.drop(bind, checkfirst=True)
        historical_found_link_strategy.drop(bind, checkfirst=True)
