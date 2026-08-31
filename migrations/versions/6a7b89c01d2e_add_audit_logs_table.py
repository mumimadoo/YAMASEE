"""add_audit_logs_table

Revision ID: 6a7b89c01d2e
Revises: 5f9b87c2d1a3
Create Date: 2026-07-21 16:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '6a7b89c01d2e'
down_revision: Union[str, None] = '5f9b87c2d1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    
    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_audit_actor", ondelete="SET NULL"), nullable=True),
            sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_audit_target", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_role", sa.String(20), nullable=True),
            sa.Column("target_role_before", sa.String(20), nullable=True),
            sa.Column("target_role_after", sa.String(20), nullable=True),
            sa.Column("target_status_before", sa.String(20), nullable=True),
            sa.Column("target_status_after", sa.String(20), nullable=True),
            sa.Column("reason", sa.String(500), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"], unique=False)
        op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"], unique=False)
        op.create_index("ix_audit_logs_target_user_id", "audit_logs", ["target_user_id"], unique=False)
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)

def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    
    if "audit_logs" in tables:
        op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
        op.drop_index("ix_audit_logs_target_user_id", table_name="audit_logs")
        op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
        op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
        op.drop_table("audit_logs")
