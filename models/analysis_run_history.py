from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Index, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class AnalysisRunHistory(Base):
    __tablename__ = "analysis_run_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    date_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)  # YouTube / TikTok / Local Upload
    url_or_filename: Mapped[str] = mapped_column(Text, nullable=False)    # URL or file name
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    video_duration: Mapped[float] = mapped_column(Float, nullable=False)  # seconds
    processing_time: Mapped[float] = mapped_column(Float, nullable=False) # seconds
    total_words: Mapped[int] = mapped_column(Integer, nullable=False)
    words_per_minute: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Cost tracking foundation fields
    job_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    api_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    estimated_cost_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1", server_default="v1")
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    user = relationship("User")

    __table_args__ = (
        Index("run_history_user_date_idx", "user_id", "date_time"),
    )
