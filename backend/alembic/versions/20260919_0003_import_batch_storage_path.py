"""Store the immutable local evidence path for accepted imports.

Revision ID: 20260919_0003
Revises: 20260918_0002
Create Date: 2026-09-19 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260919_0003"
down_revision: Union[str, None] = "20260918_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("import_batches", sa.Column("storage_path", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("import_batches", "storage_path")
