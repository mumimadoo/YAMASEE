"""add_cost_tracking_fields

Revision ID: 6594106a9a4f
Revises: 8e489b9aca1b
Create Date: 2026-08-04 14:36:37.071506

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6594106a9a4f'
down_revision: Union[str, Sequence[str], None] = '8e489b9aca1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('analysis_run_history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('job_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('api_calls', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('estimated_cost', sa.Numeric(precision=10, scale=4), nullable=True))
        batch_op.add_column(sa.Column('estimated_cost_version', sa.String(length=20), server_default='v1', nullable=False))
        batch_op.create_index('ix_analysis_run_history_job_id', ['job_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    with op.batch_alter_table('analysis_run_history', schema=None) as batch_op:
        if dialect_name == 'postgresql':
            try:
                op.execute("ALTER TABLE analysis_run_history DROP CONSTRAINT IF EXISTS analysis_run_history_job_id_key")
            except Exception:
                pass
        else:
            try:
                batch_op.drop_index('ix_analysis_run_history_job_id')
            except Exception:
                pass

        batch_op.drop_column('estimated_cost_version')
        batch_op.drop_column('estimated_cost')
        batch_op.drop_column('api_calls')
        batch_op.drop_column('job_id')
