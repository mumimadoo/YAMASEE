from typing import Any, Optional
from datetime import datetime, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from models.user import User
from models.audit_log import AuditLog
from utils.audit import record_audit_event

VALID_ROLES = {"owner", "admin", "user"}
VALID_STATUSES = {"active", "disabled", "banned", "deleted"}

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def normalize_role(role: str) -> str:
    """Normalizes and validates role string."""
    if not role or not isinstance(role, str):
        return "user"
    clean_role = role.strip().lower()
    if clean_role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {', '.join(sorted(VALID_ROLES))}")
    return clean_role

def normalize_status(status_str: str) -> str:
    """Normalizes and validates status string."""
    if not status_str or not isinstance(status_str, str):
        return "active"
    clean_status = status_str.strip().lower()
    if clean_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status_str}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
    return clean_status

def count_active_owners(db: Session) -> int:
    """Counts active, non-deleted Owner accounts in database."""
    return db.query(func.count(User.id)).filter(
        func.lower(User.role) == "owner",
        func.lower(User.status) == "active"
    ).scalar() or 0

def ensure_not_last_owner(db: Session, target_user: User) -> None:
    """
    Prevents modifying, disabling, banning, or deleting the last active Owner account.
    Raises ValueError if target_user is the last remaining active Owner.
    """
    if getattr(target_user, "role", "user") == "owner":
        active_owners_count = count_active_owners(db)
        if active_owners_count <= 1:
            raise ValueError("Action denied: Cannot modify, disable, ban, or delete the last remaining Owner account.")

def can_manage_user(actor: User, target: User) -> bool:
    """
    Role-based authority rule check:
    - User cannot manage anyone.
    - Admin can manage regular Users, but CANNOT manage Admins, Owners, or themselves.
    - Owner can manage Users and Admins.
    """
    if not actor or not target:
        return False
    
    actor_role = (getattr(actor, "role", "user") or "user").lower()
    target_role = (getattr(target, "role", "user") or "user").lower()
    
    if actor_role == "user":
        return False
    
    if actor.id == target.id:
        return False  # Cannot alter own role/status directly via user management
        
    if actor_role == "admin":
        # Admin can only manage regular Users
        return target_role == "user"
        
    if actor_role == "owner":
        # Owner can manage Users and Admins
        return target_role in ("user", "admin")
        
    return False

def record_db_audit_log(
    db: Session,
    event_type: str,
    actor: User,
    target: User,
    target_role_before: str,
    target_role_after: str,
    target_status_before: str,
    target_status_after: str,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> AuditLog:
    """Records an audit log entry in the database within the current transaction."""
    log_entry = AuditLog(
        event_type=event_type,
        actor_user_id=actor.id,
        target_user_id=target.id,
        actor_role=actor.role,
        target_role_before=target_role_before,
        target_role_after=target_role_after,
        target_status_before=target_status_before,
        target_status_after=target_status_after,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(log_entry)
    
    # Also record to in-memory logger for dual tracking
    record_audit_event(
        event_type=event_type,
        user_id=actor.id,
        details={
            "target_user_id": target.id,
            "target_role_before": target_role_before,
            "target_role_after": target_role_after,
            "target_status_before": target_status_before,
            "target_status_after": target_status_after,
            "reason": reason
        }
    )
    return log_entry

# --- 🛠️ ACTIONS ---

def disable_user_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> User:
    if actor.id == target.id:
        raise ValueError("Cannot disable your own account.")
    if not can_manage_user(actor, target):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to disable this user.")
    ensure_not_last_owner(db, target)

    if target.status == "disabled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account is already disabled.")
    if target.status == "banned":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot disable a banned account.")
    if target.status == "deleted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot disable a deleted account.")

    role_before = target.role
    status_before = target.status

    target.status = "disabled"
    target.disabled_at = utc_now()
    target.disabled_by = actor.id

    record_db_audit_log(
        db=db,
        event_type="user_disabled",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def enable_user_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> User:
    if not can_manage_user(actor, target):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to enable this user.")

    if target.status == "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account is already active.")
    if target.status == "banned":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot enable a banned account. Must unban first.")
    if target.status == "deleted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot enable a deleted account. Must restore first.")

    role_before = target.role
    status_before = target.status

    target.status = "active"
    target.disabled_at = None
    target.disabled_by = None

    record_db_audit_log(
        db=db,
        event_type="user_enabled",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def ban_user_action(db: Session, actor: User, target: User, reason: str, ip_address: str = None, user_agent: str = None) -> User:
    if actor.id == target.id:
        raise ValueError("Cannot ban your own account.")
    if not can_manage_user(actor, target):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to ban this user.")
    ensure_not_last_owner(db, target)

    clean_reason = (reason or "").strip()
    if not clean_reason or len(clean_reason) < 3 or len(clean_reason) > 500:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ban reason is required (between 3 and 500 characters).")

    if target.status == "banned":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account is already banned.")

    role_before = target.role
    status_before = target.status

    target.status = "banned"
    target.banned_at = utc_now()
    target.banned_by = actor.id
    target.ban_reason = clean_reason

    record_db_audit_log(
        db=db,
        event_type="user_banned",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        reason=clean_reason,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def unban_user_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> User:
    if not can_manage_user(actor, target):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to unban this user.")

    if target.status != "banned":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account is not currently banned.")

    role_before = target.role
    status_before = target.status

    target.status = "active"
    target.banned_at = None
    target.banned_by = None
    target.ban_reason = None

    record_db_audit_log(
        db=db,
        event_type="user_unbanned",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def soft_delete_user_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> User:
    if actor.id == target.id:
        raise ValueError("Cannot delete your own account.")
    if not can_manage_user(actor, target):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to soft delete this user.")
    ensure_not_last_owner(db, target)

    if target.status == "deleted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account is already deleted.")

    role_before = target.role
    status_before = target.status

    target.status = "deleted"
    target.deleted_at = utc_now()
    target.deleted_by = actor.id

    record_db_audit_log(
        db=db,
        event_type="user_soft_deleted",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def restore_user_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> User:
    if not can_manage_user(actor, target):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to restore this user.")

    if target.status != "deleted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account is not currently deleted.")

    role_before = target.role
    status_before = target.status

    target.status = "active"
    target.deleted_at = None
    target.deleted_by = None

    record_db_audit_log(
        db=db,
        event_type="user_restored",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def promote_user_to_admin_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> User:
    if actor.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner can promote users to Admin.")
    if actor.id == target.id:
        raise ValueError("Cannot promote yourself.")
    if target.role in ("admin", "owner"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already an Admin or Owner.")
    if target.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot promote an inactive, banned, or deleted user.")

    role_before = target.role
    status_before = target.status

    target.role = "admin"

    record_db_audit_log(
        db=db,
        event_type="user_promoted_to_admin",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def demote_admin_to_user_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> User:
    if actor.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner can demote Admins.")
    if actor.id == target.id:
        raise ValueError("Cannot demote yourself.")
    if target.role == "owner":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot demote an Owner account.")
    if target.role != "admin":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Target is not an Admin.")

    role_before = target.role
    status_before = target.status

    target.role = "user"

    record_db_audit_log(
        db=db,
        event_type="admin_demoted_to_user",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=target.role,
        target_status_before=status_before,
        target_status_after=target.status,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    db.refresh(target)
    return target

def reset_password_action(db: Session, actor: User, target: User, ip_address: str = None, user_agent: str = None) -> str:
    """
    Resets user password to a temporary password, forcing change on next login.
    Enforces that actor can manage target user based on roles.
    """
    from services.auth_service import generate_temporary_password, hash_password
    from datetime import timedelta

    if not can_manage_user(actor, target):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to reset this user's password.")

    temp_password = generate_temporary_password()
    new_hash = hash_password(temp_password)

    target.password_hash = new_hash
    target.must_change_password = True

    now_utc = datetime.now(timezone.utc)
    target.password_reset_at = now_utc
    target.password_reset_by = actor.id
    target.temporary_password_expires_at = now_utc + timedelta(hours=24)

    record_db_audit_log(
        db=db,
        event_type="password_reset",
        actor=actor,
        target=target,
        target_role_before=target.role,
        target_role_after=target.role,
        target_status_before=target.status,
        target_status_after=target.status,
        reason="Temporary password generated",
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.commit()
    return temp_password

def can_edit_user_profile(actor: User, target: User) -> bool:
    """
    Checks if the actor is permitted to edit the target's username and email.
    - Owner can edit normal users, admins, and themselves.
    - Admin can only edit normal users.
    - Normal user cannot edit anyone.
    """
    if not actor or not target:
        return False
    actor_role = (getattr(actor, "role", "user") or "user").lower()
    target_role = (getattr(target, "role", "user") or "user").lower()

    if actor_role == "owner":
        return target_role in ("user", "admin") or actor.id == target.id
    elif actor_role == "admin":
        return target_role == "user"
    return False

def edit_user_profile_action(
    db: Session,
    actor: User,
    target: User,
    new_username: str,
    new_email: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> User:
    """
    Edits a target user's username and email, checking permissions and performing validations.
    """
    import re
    import json

    # 1. Permission checks
    if not can_edit_user_profile(actor, target):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied to edit this user's profile."
        )

    # 2. Input validation
    if new_username is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must not be empty"
        )
    if new_email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email must not be empty"
        )

    clean_username = new_username.strip()
    clean_email = new_email.strip().lower()

    if not clean_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must not be empty"
        )
    if not clean_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email must not be empty"
        )

    email_pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(email_pattern, clean_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format"
        )

    # 3. Conflict validation (email uniqueness)
    existing = db.query(User).filter(
        func.lower(User.email) == clean_email,
        User.id != target.id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already used"
        )

    # 4. Detect changed fields
    changed_fields = []
    old_values = {}
    new_values = {}

    if target.username != clean_username:
        changed_fields.append("username")
        old_values["username"] = target.username
        new_values["username"] = clean_username

    if target.email != clean_email:
        changed_fields.append("email")
        old_values["email"] = target.email
        new_values["email"] = clean_email

    # If no changes, just return target
    if not changed_fields:
        return target

    # 5. Perform update (explicitly preserve role, status, is_active, is_admin, password_hash)
    role_before = target.role
    status_before = target.status

    target.username = clean_username
    target.email = clean_email

    # 6. Audit log entry
    reason_str = json.dumps({
        "changed_fields": changed_fields,
        "old_values": old_values,
        "new_values": new_values
    }, ensure_ascii=False)

    record_db_audit_log(
        db=db,
        event_type="user_profile_edited",
        actor=actor,
        target=target,
        target_role_before=role_before,
        target_role_after=role_before,
        target_status_before=status_before,
        target_status_after=status_before,
        reason=reason_str,
        ip_address=ip_address,
        user_agent=user_agent
    )

    db.commit()
    db.refresh(target)

    # 7. Create notification for target user if changed by administrator (i.e. actor.id != target.id)
    if actor.id != target.id:
        from services.notification_service import create_notification
        from utils.logger import get_logger
        logger = get_logger()
        title = "ข้อมูลบัญชีของคุณถูกแก้ไขโดยผู้ดูแลระบบ"
        changes_desc = []
        if "username" in changed_fields:
            changes_desc.append(f"ชื่อผู้ใช้งาน (เดิม: {old_values['username']} -> ใหม่: {new_values['username']})")
        if "email" in changed_fields:
            changes_desc.append(f"อีเมล (เดิม: {old_values['email']} -> ใหม่: {new_values['email']})")
        message = "ข้อมูลบัญชีของคุณได้รับการแก้ไขโดยผู้ดูแลระบบ: " + ", ".join(changes_desc)
        try:
            create_notification(
                db=db,
                user_id=target.id,
                type="system",
                title=title,
                message=message
            )
        except Exception as e:
            logger.error(f"Failed to create notification for edited user {target.id}: {e}", exc_info=True)

    return target

