"""add_token_usage_to_analysis_run_history

Revision ID: 7a8b9c0d1e2f
Revises: 6594106a9a4f
Create Date: 2026-08-17 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, Sequence[str], None] = '6594106a9a4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('analysis_run_history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('token_usage', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('analysis_run_history', schema=None) as batch_op:
        batch_op.drop_column('token_usage')
