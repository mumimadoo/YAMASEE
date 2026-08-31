"""add_unique_job_id_constraint

Revision ID: 14d21f673c87
Revises: 9e9fe471c738
Create Date: 2026-07-20 11:28:00.262946

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14d21f673c87'
down_revision: Union[str, Sequence[str], None] = '9e9fe471c738'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "analysis_records" in inspector.get_table_names():
        dups = conn.execute(
            sa.text(
                "SELECT job_id, COUNT(*) as cnt FROM analysis_records "
                "WHERE job_id IS NOT NULL GROUP BY job_id HAVING COUNT(*) > 1"
            )
        ).fetchall()
        if dups:
            dup_details = conn.execute(
                sa.text(
                    "SELECT public_id, user_id, job_id FROM analysis_records "
                    "WHERE job_id IN (SELECT job_id FROM analysis_records WHERE job_id IS NOT NULL GROUP BY job_id HAVING COUNT(*) > 1)"
                )
            ).fetchall()
            rows = [f"public_id={r[0]}, user_id={r[1]}, job_id={r[2]}" for r in dup_details]
            raise RuntimeError(f"Duplicate job_ids found in database before migration: {rows}")

    with op.batch_alter_table("analysis_records", schema=None) as batch_op:
        batch_op.create_index("ix_analysis_records_job_id", ["job_id"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("analysis_records", schema=None) as batch_op:
        batch_op.drop_index("ix_analysis_records_job_id")
