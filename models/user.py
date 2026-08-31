import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Index, text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from database import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    
    # Phase 13.1 Role & User Status Foundation
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default=text("'user'"), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default=text("'active'"), index=True)
    
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    banned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_users_banned_by", ondelete="SET NULL"), nullable=True)
    ban_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_users_disabled_by", ondelete="SET NULL"), nullable=True)
    
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_users_deleted_by", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Phase 13.3 Temporary Password Reset
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    password_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_reset_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_users_password_reset_by", ondelete="SET NULL"), nullable=True)
    temporary_password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    analysis_records = relationship("AnalysisRecord", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    @validates('role')
    def _validate_role(self, key, value):
        val = (value or 'user').lower().strip()
        if val not in ('owner', 'admin', 'user'):
            raise ValueError(f"Invalid role '{value}'. Must be one of: owner, admin, user")
        target_admin = (val in ('admin', 'owner'))
        if self.is_admin != target_admin:
            self.__dict__['is_admin'] = target_admin
        return val

    @validates('status')
    def _validate_status(self, key, value):
        val = (value or 'active').lower().strip()
        if val not in ('active', 'disabled', 'banned', 'deleted'):
            raise ValueError(f"Invalid status '{value}'. Must be one of: active, disabled, banned, deleted")
        target_active = (val == 'active')
        if self.is_active != target_active:
            self.__dict__['is_active'] = target_active
        return val

    @validates('is_admin')
    def _validate_is_admin(self, key, value):
        target_admin = bool(value)
        current_role = (getattr(self, 'role', 'user') or 'user').lower()
        if target_admin and current_role not in ('admin', 'owner'):
            self.__dict__['role'] = 'admin'
        elif not target_admin and current_role in ('admin', 'owner'):
            self.__dict__['role'] = 'user'
        return target_admin

    @validates('is_active')
    def _validate_is_active(self, key, value):
        target_active = bool(value)
        current_status = (getattr(self, 'status', 'active') or 'active').lower()
        if target_active and current_status != 'active':
            self.__dict__['status'] = 'active'
        elif not target_active and current_status == 'active':
            self.__dict__['status'] = 'disabled'
        return target_active
