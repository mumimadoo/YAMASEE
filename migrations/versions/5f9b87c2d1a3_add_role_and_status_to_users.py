"""add_role_and_status_to_users

Revision ID: 5f9b87c2d1a3
Revises: 4c7b89d01e2f
Create Date: 2026-07-21 16:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '5f9b87c2d1a3'
down_revision: Union[str, None] = '4c7b89d01e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    
    if "users" in tables:
        columns = [c["name"] for c in inspector.get_columns("users")]
        with op.batch_alter_table("users", schema=None) as batch_op:
            if "role" not in columns:
                batch_op.add_column(sa.Column("role", sa.String(20), nullable=False, server_default=sa.text("'user'")))
                batch_op.create_index("ix_users_role", ["role"], unique=False)
            if "status" not in columns:
                batch_op.add_column(sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")))
                batch_op.create_index("ix_users_status", ["status"], unique=False)
            if "banned_at" not in columns:
                batch_op.add_column(sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True))
            if "banned_by" not in columns:
                batch_op.add_column(sa.Column("banned_by", sa.Integer(), sa.ForeignKey("users.id", name="fk_users_banned_by", ondelete="SET NULL"), nullable=True))
            if "ban_reason" not in columns:
                batch_op.add_column(sa.Column("ban_reason", sa.String(500), nullable=True))
            if "disabled_at" not in columns:
                batch_op.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
            if "disabled_by" not in columns:
                batch_op.add_column(sa.Column("disabled_by", sa.Integer(), sa.ForeignKey("users.id", name="fk_users_disabled_by", ondelete="SET NULL"), nullable=True))
            if "deleted_at" not in columns:
                batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
            if "deleted_by" not in columns:
                batch_op.add_column(sa.Column("deleted_by", sa.Integer(), sa.ForeignKey("users.id", name="fk_users_deleted_by", ondelete="SET NULL"), nullable=True))

        # Data Migration
        is_sqlite = conn.dialect.name == "sqlite"
        admin_true = "1" if is_sqlite else "TRUE"
        admin_false = "0" if is_sqlite else "FALSE"
        active_true = "1" if is_sqlite else "TRUE"
        active_false = "0" if is_sqlite else "FALSE"

        conn.execute(
            sa.text(
                "UPDATE users SET role = 'owner' WHERE LOWER(username) = 'goat'"
            )
        )
        conn.execute(
            sa.text(
                f"UPDATE users SET role = 'admin' WHERE is_admin = {admin_true} AND LOWER(username) != 'goat'"
            )
        )
        conn.execute(
            sa.text(
                f"UPDATE users SET role = 'user' WHERE (is_admin = {admin_false} OR is_admin IS NULL) AND LOWER(username) != 'goat'"
            )
        )
        conn.execute(
            sa.text(
                f"UPDATE users SET status = 'active' WHERE is_active = {active_true} OR is_active IS NULL"
            )
        )
        conn.execute(
            sa.text(
                f"UPDATE users SET status = 'disabled' WHERE is_active = {active_false}"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    
    if "users" in tables:
        columns = [c["name"] for c in inspector.get_columns("users")]
        with op.batch_alter_table("users", schema=None) as batch_op:
            if "role" in columns:
                batch_op.drop_index("ix_users_role")
                batch_op.drop_column("role")
            if "status" in columns:
                batch_op.drop_index("ix_users_status")
                batch_op.drop_column("status")
            if "banned_at" in columns:
                batch_op.drop_column("banned_at")
            if "banned_by" in columns:
                batch_op.drop_column("banned_by")
            if "ban_reason" in columns:
                batch_op.drop_column("ban_reason")
            if "disabled_at" in columns:
                batch_op.drop_column("disabled_at")
            if "disabled_by" in columns:
                batch_op.drop_column("disabled_by")
            if "deleted_at" in columns:
                batch_op.drop_column("deleted_at")
            if "deleted_by" in columns:
                batch_op.drop_column("deleted_by")
