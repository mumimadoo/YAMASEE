"""Add is_pinned column and index to analysis_records

Revision ID: 3f8a92b1c4e7
Revises: 14d21f673c87
Create Date: 2026-07-20 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '3f8a92b1c4e7'
down_revision: Union[str, None] = '14d21f673c87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "analysis_records" in tables:
        columns = [c["name"] for c in inspector.get_columns("analysis_records")]
        if "is_pinned" not in columns:
            is_sqlite = conn.dialect.name == "sqlite"
            default_val = "0" if is_sqlite else "false"
            with op.batch_alter_table("analysis_records", schema=None) as batch_op:
                batch_op.add_column(sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text(default_val)))
                batch_op.create_index("records_user_pinned_created_idx", ["user_id", "is_pinned", "created_at"], unique=False)

def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "analysis_records" in tables:
        columns = [c["name"] for c in inspector.get_columns("analysis_records")]
        if "is_pinned" in columns:
            with op.batch_alter_table("analysis_records", schema=None) as batch_op:
                batch_op.drop_index("records_user_pinned_created_idx")
                batch_op.drop_column("is_pinned")
