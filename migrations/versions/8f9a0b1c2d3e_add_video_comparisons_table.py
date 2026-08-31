"""add_video_comparisons_table

Revision ID: 8f9a0b1c2d3e
Revises: 7a8b9c0d1e2f
Create Date: 2026-08-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f9a0b1c2d3e'
down_revision: Union[str, Sequence[str], None] = '7a8b9c0d1e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "video_comparisons" not in tables:
        op.create_table(
            "video_comparisons",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("public_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("canonical_pair_key", sa.String(length=100), nullable=False),
            sa.Column("analysis_id_a", sa.String(length=36), nullable=False),
            sa.Column("analysis_id_b", sa.String(length=36), nullable=False),
            sa.Column("display_order_a", sa.String(length=36), nullable=False),
            sa.Column("display_order_b", sa.String(length=36), nullable=False),
            sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("schema_version", sa.String(length=20), nullable=False, server_default="1.0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("model_used", sa.String(length=100), nullable=True),
            sa.Column("processing_seconds", sa.Float(), nullable=True),
            sa.Column("api_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("token_usage", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_video_comparisons_public_id", "video_comparisons", ["public_id"], unique=True)
        op.create_index("ix_video_comparisons_user_id", "video_comparisons", ["user_id"], unique=False)
        op.create_index("ix_video_comparisons_canonical_pair_key", "video_comparisons", ["canonical_pair_key"], unique=False)
        op.create_index("ix_video_comparisons_analysis_id_a", "video_comparisons", ["analysis_id_a"], unique=False)
        op.create_index("ix_video_comparisons_analysis_id_b", "video_comparisons", ["analysis_id_b"], unique=False)
        op.create_index(
            "comp_user_canonical_idx",
            "video_comparisons",
            ["user_id", "canonical_pair_key", "schema_version"],
            unique=False
        )
        op.create_index(
            "comp_user_created_idx",
            "video_comparisons",
            ["user_id", "created_at"],
            unique=False
        )
    else:
        columns = [c["name"] for c in inspector.get_columns("video_comparisons")]
        if "model_used" not in columns:
            op.add_column("video_comparisons", sa.Column("model_used", sa.String(length=100), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "video_comparisons" in tables:
        op.drop_index("comp_user_created_idx", table_name="video_comparisons")
        op.drop_index("comp_user_canonical_idx", table_name="video_comparisons")
        op.drop_index("ix_video_comparisons_analysis_id_b", table_name="video_comparisons")
        op.drop_index("ix_video_comparisons_analysis_id_a", table_name="video_comparisons")
        op.drop_index("ix_video_comparisons_canonical_pair_key", table_name="video_comparisons")
        op.drop_index("ix_video_comparisons_user_id", table_name="video_comparisons")
        op.drop_index("ix_video_comparisons_public_id", table_name="video_comparisons")
        op.drop_table("video_comparisons")
