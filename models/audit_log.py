from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from database import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_audit_actor", ondelete="SET NULL"), nullable=True, index=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_audit_target", ondelete="SET NULL"), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_role_before: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_role_after: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_status_before: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_status_after: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
