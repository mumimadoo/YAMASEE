import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import String, Text, Integer, Float, DateTime, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def generate_public_id() -> str:
    return str(uuid.uuid4())

class VideoComparison(Base):
    """
    Persistence and cache model for video comparison results.
    Stores metadata, canonical pair key for symmetric caching (A+B and B+A),
    user display order, input fingerprint for invalidation, structured result JSON,
    and telemetry fields ready for Phase 2.
    """
    __tablename__ = "video_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=generate_public_id, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    canonical_pair_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    analysis_id_a: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    analysis_id_b: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    display_order_a: Mapped[str] = mapped_column(String(36), nullable=False)
    display_order_b: Mapped[str] = mapped_column(String(36), nullable=False)

    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.1")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Telemetry readiness for Phase 2
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processing_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    api_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    user = relationship("User")

    __table_args__ = (
        Index("comp_user_canonical_idx", "user_id", "canonical_pair_key", "schema_version"),
        Index("comp_user_created_idx", "user_id", "created_at"),
    )
