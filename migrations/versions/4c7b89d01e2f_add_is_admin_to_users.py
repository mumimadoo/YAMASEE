"""Add is_admin column to users table

Revision ID: 4c7b89d01e2f
Revises: 3f8a92b1c4e7
Create Date: 2026-07-21 09:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '4c7b89d01e2f'
down_revision: Union[str, None] = '3f8a92b1c4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "users" in tables:
        columns = [c["name"] for c in inspector.get_columns("users")]
        if "is_admin" not in columns:
            is_sqlite = conn.dialect.name == "sqlite"
            default_val = "0" if is_sqlite else "false"
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text(default_val)))

def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "users" in tables:
        columns = [c["name"] for c in inspector.get_columns("users")]
        if "is_admin" in columns:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.drop_column("is_admin")
