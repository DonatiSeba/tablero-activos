"""Create the core asset-reconciliation persistence schema.

Revision ID: 20260917_0001
Revises:
Create Date: 2026-09-17 00:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260917_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

json_document = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")
ip_address = postgresql.INET().with_variant(sa.String(length=45), "sqlite")
user_role = sa.Enum("viewer", "editor", "admin", name="user_role", create_constraint=True)
cost_center_status = sa.Enum("active", "inactive", name="cost_center_status", create_constraint=True)
import_source = sa.Enum("system", "audit", "return", name="import_source", create_constraint=True)
observation_source = sa.Enum("system", "audit", "return", name="observation_source", create_constraint=True)
observation_event = sa.Enum("snapshot", "found", "returned", name="observation_event", create_constraint=True)
import_batch_status = sa.Enum("completed", "rejected", name="import_batch_status", create_constraint=True)
reconciliation_state = sa.Enum(
    "pending", "matched", "mismatched", "returned", "review_required",
    name="reconciliation_state",
    create_constraint=True,
)


def _create_immutable_evidence_triggers() -> None:
    """Reject every direct mutation of import evidence in supported databases."""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION immutable_evidence_row() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'immutable evidence: % rows cannot be updated or deleted', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table_name in ("import_batches", "asset_observations"):
            op.execute(
                f"CREATE TRIGGER {table_name}_immutable BEFORE UPDATE OR DELETE ON {table_name} "
                "FOR EACH ROW EXECUTE FUNCTION immutable_evidence_row();"
            )
    elif dialect == "sqlite":
        for table_name in ("import_batches", "asset_observations"):
            op.execute(
                f"CREATE TRIGGER {table_name}_immutable_update BEFORE UPDATE ON {table_name} "
                f"BEGIN SELECT RAISE(ABORT, '{table_name} rows are immutable'); END;"
            )
            op.execute(
                f"CREATE TRIGGER {table_name}_immutable_delete BEFORE DELETE ON {table_name} "
                f"BEGIN SELECT RAISE(ABORT, '{table_name} rows are immutable'); END;"
            )


def _drop_immutable_evidence_triggers() -> None:
    """Remove database-level immutability protection before dropping evidence tables."""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table_name in ("asset_observations", "import_batches"):
            op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
        op.execute("DROP FUNCTION immutable_evidence_row()")
    elif dialect == "sqlite":
        for table_name in ("asset_observations", "import_batches"):
            op.execute(f"DROP TRIGGER {table_name}_immutable_update")
            op.execute(f"DROP TRIGGER {table_name}_immutable_delete")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "cost_centers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", cost_center_status, nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(code) > 0", name="ck_cost_centers_cost_center_code_not_empty"),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_cost_centers_cost_center_date_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cost_centers"),
        sa.UniqueConstraint("code", name="uq_cost_centers_code"),
    )
    op.create_index("ix_cost_centers_status", "cost_centers", ["status"], unique=False)
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_code", sa.String(length=255), nullable=False),
        sa.Column("normalized_code", sa.String(length=255), nullable=False),
        sa.Column("serial_number", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(original_code) > 0", name="ck_assets_asset_original_code_not_empty"),
        sa.CheckConstraint("length(normalized_code) > 0", name="ck_assets_asset_normalized_code_not_empty"),
        sa.CheckConstraint("serial_number IS NULL OR length(serial_number) > 0", name="ck_assets_asset_serial_number_not_empty"),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
        sa.UniqueConstraint("original_code", name="uq_assets_original_code"),
    )
    op.create_index("ix_assets_normalized_code", "assets", ["normalized_code"], unique=False)
    op.create_index("ix_assets_serial_number", "assets", ["serial_number"], unique=False)
    op.create_index("ix_assets_category", "assets", ["category"], unique=False)
    op.create_table(
        "asset_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("source", import_source, nullable=False),
        sa.Column("original_alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(original_alias) > 0", name="ck_asset_aliases_asset_alias_original_not_empty"),
        sa.CheckConstraint("length(normalized_alias) > 0", name="ck_asset_aliases_asset_alias_normalized_not_empty"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name="fk_asset_aliases_asset_id_assets", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], name="fk_asset_aliases_confirmed_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_asset_aliases"),
        sa.UniqueConstraint("asset_id", "original_alias", name="asset_alias_original_per_asset"),
    )
    op.create_index("ix_asset_aliases_normalized_alias", "asset_aliases", ["normalized_alias"], unique=False)
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", import_source, nullable=False),
        sa.Column("cost_center_id", sa.Uuid(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("status", import_batch_status, nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", json_document, nullable=True),
        sa.Column("imported_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(sha256) = 64", name="ck_import_batches_import_batch_sha256_length"),
        sa.CheckConstraint("row_count >= 0", name="ck_import_batches_import_batch_row_count_nonnegative"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], name="fk_import_batches_cost_center_id_cost_centers", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["imported_by_user_id"], ["users.id"], name="fk_import_batches_imported_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
        sa.UniqueConstraint("sha256", name="uq_import_batches_sha256"),
    )
    op.create_index("ix_import_batches_cost_center_id", "import_batches", ["cost_center_id"], unique=False)
    op.create_index("ix_import_batches_report_date", "import_batches", ["report_date"], unique=False)
    op.create_table(
        "asset_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("source", observation_source, nullable=False),
        sa.Column("event", observation_event, nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("cost_center_id", sa.Uuid(), nullable=True),
        sa.Column("original_data", json_document, nullable=False),
        sa.Column("reported_status", sa.String(length=128), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_asset_observations_asset_observation_quantity_positive"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name="fk_asset_observations_asset_id_assets", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], name="fk_asset_observations_cost_center_id_cost_centers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"], name="fk_asset_observations_import_batch_id_import_batches", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_asset_observations"),
    )
    op.create_index("ix_asset_observations_source_observed_on", "asset_observations", ["source", "observed_on"], unique=False)
    op.create_index("ix_asset_observations_asset_id", "asset_observations", ["asset_id"], unique=False)
    op.create_index("ix_asset_observations_cost_center_id", "asset_observations", ["cost_center_id"], unique=False)
    op.create_index("ix_asset_observations_reported_status", "asset_observations", ["reported_status"], unique=False)
    _create_immutable_evidence_triggers()
    op.create_table(
        "reconciliation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("cost_center_id", sa.Uuid(), nullable=False),
        sa.Column("system_observation_id", sa.Uuid(), nullable=True),
        sa.Column("audit_observation_id", sa.Uuid(), nullable=True),
        sa.Column("return_observation_id", sa.Uuid(), nullable=True),
        sa.Column("state", reconciliation_state, nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_reconciliation_results_reconciliation_confidence_range"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name="fk_reconciliation_results_asset_id_assets", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["audit_observation_id"], ["asset_observations.id"], name="fk_recon_results_audit_observation", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cost_center_id"], ["cost_centers.id"], name="fk_reconciliation_results_cost_center_id_cost_centers", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["return_observation_id"], ["asset_observations.id"], name="fk_recon_results_return_observation", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], name="fk_reconciliation_results_reviewed_by_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["system_observation_id"], ["asset_observations.id"], name="fk_recon_results_system_observation", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_reconciliation_results"),
        sa.UniqueConstraint("asset_id", "cost_center_id", name="reconciliation_result_coverage"),
        sa.UniqueConstraint("system_observation_id", name="uq_reconciliation_results_system_observation_id"),
        sa.UniqueConstraint("audit_observation_id", name="uq_reconciliation_results_audit_observation_id"),
        sa.UniqueConstraint("return_observation_id", name="uq_reconciliation_results_return_observation_id"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_entity", sa.String(length=128), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("details", json_document, nullable=True),
        sa.Column("ip_address", ip_address, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_audit_logs_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_entity", "target_id"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    _drop_immutable_evidence_triggers()
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_target", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("reconciliation_results")
    op.drop_index("ix_asset_observations_reported_status", table_name="asset_observations")
    op.drop_index("ix_asset_observations_cost_center_id", table_name="asset_observations")
    op.drop_index("ix_asset_observations_asset_id", table_name="asset_observations")
    op.drop_index("ix_asset_observations_source_observed_on", table_name="asset_observations")
    op.drop_table("asset_observations")
    op.drop_index("ix_import_batches_report_date", table_name="import_batches")
    op.drop_index("ix_import_batches_cost_center_id", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_index("ix_asset_aliases_normalized_alias", table_name="asset_aliases")
    op.drop_table("asset_aliases")
    op.drop_index("ix_assets_category", table_name="assets")
    op.drop_index("ix_assets_serial_number", table_name="assets")
    op.drop_index("ix_assets_normalized_code", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_cost_centers_status", table_name="cost_centers")
    op.drop_table("cost_centers")
    op.drop_table("users")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        reconciliation_state.drop(bind, checkfirst=True)
        observation_event.drop(bind, checkfirst=True)
        observation_source.drop(bind, checkfirst=True)
        import_batch_status.drop(bind, checkfirst=True)
        import_source.drop(bind, checkfirst=True)
        cost_center_status.drop(bind, checkfirst=True)
        user_role.drop(bind, checkfirst=True)
