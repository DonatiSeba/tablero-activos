"""Add BG direct-fill audit marker provenance and pending state.

Revision ID: 20261029_0007
Revises: 20260922_0006
Create Date: 2026-10-29 00:07:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261029_0007"
down_revision: Union[str, None] = "20260922_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

old_audit_current_state = sa.Enum("found", "returned", "review_required", name="audit_current_state", create_constraint=True)
audit_current_state = sa.Enum("found", "returned", "pending", "review_required", name="audit_current_state", create_constraint=True)
old_audit_return_marker_category = sa.Enum(
    "recognized_return", "ambiguous_return", "unmarked_unknown",
    name="audit_return_marker_category",
    create_constraint=True,
)
audit_return_marker_category = sa.Enum(
    "recognized_return", "ambiguous_return", "unmarked_unknown", "bg_direct_fill_return", "bg_direct_fill_pending",
    name="audit_return_marker_category",
    create_constraint=True,
)
audit_marker_source = sa.Enum(
    "column_l_value", "bg_row_direct_fill", name="audit_marker_source", create_constraint=True,
)


def _replace_projection_constraints() -> None:
    op.create_check_constraint(
        "audit_current_state_marker_source_location",
        "audit_current_state_projections",
        "(marker_source = 'column_l_value' AND marker_column = 12) "
        "OR (marker_source = 'bg_row_direct_fill' AND marker_column IS NULL)",
    )
    op.create_check_constraint(
        "audit_current_state_matches_marker_category",
        "audit_current_state_projections",
        "(state = 'returned' AND marker_category IN ('recognized_return', 'bg_direct_fill_return')) "
        "OR (state = 'review_required' AND marker_category = 'ambiguous_return') "
        "OR (state = 'found' AND marker_category = 'unmarked_unknown') "
        "OR (state = 'pending' AND marker_category = 'bg_direct_fill_pending')",
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL does not permit enum labels added in a transaction to be
        # referenced by constraints until that transaction commits.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE audit_current_state ADD VALUE IF NOT EXISTS 'pending'")
            op.execute("ALTER TYPE audit_return_marker_category ADD VALUE IF NOT EXISTS 'bg_direct_fill_return'")
            op.execute("ALTER TYPE audit_return_marker_category ADD VALUE IF NOT EXISTS 'bg_direct_fill_pending'")
        audit_marker_source.create(bind, checkfirst=True)
        op.add_column(
            "audit_current_state_projections",
            sa.Column("marker_source", audit_marker_source, server_default=sa.text("'column_l_value'"), nullable=False),
        )
        op.drop_constraint("audit_current_state_marker_column_l", "audit_current_state_projections", type_="check")
        op.drop_constraint("audit_current_state_matches_marker_category", "audit_current_state_projections", type_="check")
        op.alter_column("audit_current_state_projections", "marker_column", existing_type=sa.Integer(), nullable=True)
        _replace_projection_constraints()
        return

    with op.batch_alter_table("audit_current_state_projections") as batch:
        batch.drop_constraint("audit_current_state_marker_column_l", type_="check")
        batch.drop_constraint("audit_current_state_matches_marker_category", type_="check")
        batch.drop_constraint("audit_current_state", type_="check")
        batch.drop_constraint("audit_return_marker_category", type_="check")
        batch.alter_column("state", existing_type=old_audit_current_state, type_=audit_current_state)
        batch.alter_column(
            "marker_category",
            existing_type=old_audit_return_marker_category,
            type_=audit_return_marker_category,
        )
        batch.alter_column("marker_column", existing_type=sa.Integer(), nullable=True)
        batch.add_column(
            sa.Column("marker_source", audit_marker_source, server_default=sa.text("'column_l_value'"), nullable=False)
        )
        batch.create_check_constraint(
            "audit_current_state_marker_source_location",
            "(marker_source = 'column_l_value' AND marker_column = 12) "
            "OR (marker_source = 'bg_row_direct_fill' AND marker_column IS NULL)",
        )
        batch.create_check_constraint(
            "audit_current_state_matches_marker_category",
            "(state = 'returned' AND marker_category IN ('recognized_return', 'bg_direct_fill_return')) "
            "OR (state = 'review_required' AND marker_category = 'ambiguous_return') "
            "OR (state = 'found' AND marker_category = 'unmarked_unknown') "
            "OR (state = 'pending' AND marker_category = 'bg_direct_fill_pending')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        raise NotImplementedError("PostgreSQL enum values cannot be removed safely after BG evidence exists")

    with op.batch_alter_table("audit_current_state_projections") as batch:
        batch.drop_constraint("audit_current_state_marker_source_location", type_="check")
        batch.drop_constraint("audit_current_state_matches_marker_category", type_="check")
        batch.drop_constraint("audit_current_state", type_="check")
        batch.drop_constraint("audit_return_marker_category", type_="check")
        batch.drop_constraint("audit_marker_source", type_="check")
        batch.drop_column("marker_source", existing_type=audit_marker_source)
        batch.alter_column("state", existing_type=audit_current_state, type_=old_audit_current_state)
        batch.alter_column(
            "marker_category",
            existing_type=audit_return_marker_category,
            type_=old_audit_return_marker_category,
        )
        batch.alter_column("marker_column", existing_type=sa.Integer(), nullable=False, server_default=sa.text("12"))
        batch.create_check_constraint("audit_current_state_marker_column_l", "marker_column = 12")
        batch.create_check_constraint(
            "audit_current_state_matches_marker_category",
            "(state = 'returned' AND marker_category = 'recognized_return') "
            "OR (state = 'review_required' AND marker_category = 'ambiguous_return') "
            "OR (state = 'found' AND marker_category = 'unmarked_unknown')",
        )
