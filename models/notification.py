from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Index, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_notifications_user_id", ondelete="SET NULL"), nullable=True, index=True)
    
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    
    related_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    target_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"), index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    deduplication_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Unique index to prevent duplicate notifications for the same event per user
    __table_args__ = (
        Index("ix_notifications_user_dedup", "user_id", "deduplication_key", unique=True),
    )

    user = relationship("User", back_populates="notifications")
