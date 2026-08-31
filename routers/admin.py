import os
import math
import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, Depends, HTTPException, Query, status, Body
from fastapi.responses import JSONResponse, Response, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc, asc, text

from database import get_db
from models.user import User
from models.analysis_record import AnalysisRecord
from models.audit_log import AuditLog
from dependencies.auth import require_admin, get_current_user
from utils.audit import record_audit_event
from utils.origin_checker import verify_same_origin
from utils.metrics import metrics
from utils.error_classification import classify_error
from services.role_service import (
    can_manage_user,
    disable_user_action,
    enable_user_action,
    ban_user_action,
    unban_user_action,
    soft_delete_user_action,
    restore_user_action,
    promote_user_to_admin_action,
    demote_admin_to_user_action,
    reset_password_action,
    can_edit_user_profile,
    edit_user_profile_action,
)
from services.cost_engine import calculate_run_cost
from utils.rate_limiter import password_reset_rate_limiter

CURRENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(CURRENT_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

from routers.pages import get_footer_stats
templates.env.globals["get_footer_stats"] = get_footer_stats

router = APIRouter(tags=["Admin Center"])

def _format_size_human(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    digit_group = int(math.floor(math.log(size_bytes, 1024)))
    digit_group = min(digit_group, len(units) - 1)
    size_val = round(size_bytes / (1024 ** digit_group), 2)
    return f"{size_val} {units[digit_group]}"

def _add_no_cache_headers(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

@router.get("/admin", response_class=HTMLResponse)
async def serve_admin_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user)
):
    """
    Serves Admin Center HTML Page.
    - Guest: Redirects to /login (303)
    - Authenticated Non-Admin/Non-Owner: HTTP 403 Forbidden
    - Authenticated Admin/Owner: Renders admin.html
    """
    if not current_user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=303)

    if getattr(current_user, "must_change_password", False):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/change-password", status_code=303)

    user_role = getattr(current_user, "role", "user")
    is_admin_flag = getattr(current_user, "is_admin", False)
    if not (is_admin_flag or user_role in ("admin", "owner")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required"
        )

    record_audit_event("admin_center_viewed", user_id=current_user.id)
    response = templates.TemplateResponse(request=request, name="admin.html", context={"user": current_user})
    _add_no_cache_headers(response)
    return response

@router.get("/api/admin/overview")
async def get_admin_overview(
    response: Response,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Returns high-level system metrics and diagnostics for Admin Center.
    Preserves top-level keys for backward compatibility.
    """
    _add_no_cache_headers(response)
    record_audit_event("admin_center_viewed", user_id=current_admin.id)

    # 1. User metrics
    active_users = db.query(func.count(User.id)).filter(func.lower(User.status) == "active").scalar() or 0
    disabled_users = db.query(func.count(User.id)).filter(func.lower(User.status) == "disabled").scalar() or 0
    banned_users = db.query(func.count(User.id)).filter(func.lower(User.status) == "banned").scalar() or 0
    deleted_users = db.query(func.count(User.id)).filter(func.lower(User.status) == "deleted").scalar() or 0
    total_users_in_db = db.query(func.count(User.id)).scalar() or 0

    admin_users_count = db.query(func.count(User.id)).filter(
        func.lower(User.status) != "deleted",
        or_(User.is_admin == True, func.lower(User.role).in_(["admin", "owner"]))
    ).scalar() or 0

    # 2. Record metrics
    total_records = db.query(func.count(AnalysisRecord.id)).scalar() or 0

    # 3. Active Jobs in memory
    from main import JOBS_DATA
    active_jobs_count = sum(1 for j in JOBS_DATA.values() if j.get("status") in ("queued", "processing"))
    completed_jobs_count = sum(1 for j in JOBS_DATA.values() if j.get("status") == "completed")
    failed_jobs_count = sum(1 for j in JOBS_DATA.values() if j.get("status") == "failed")

    # 4. Database & WAL Diagnostics
    db_ok = False
    wal_enabled = False
    alembic_rev = "unknown"
    dialect_name = "sqlite"
    db_version = None
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        dialect_name = db.bind.dialect.name
        
        if dialect_name == "sqlite":
            try:
                wal_res = db.execute(text("PRAGMA journal_mode")).scalar()
                if wal_res and str(wal_res).lower() == "wal":
                    wal_enabled = True
            except Exception:
                wal_enabled = False
        elif dialect_name == "postgresql":
            try:
                db_version_raw = db.execute(text("SELECT version()")).scalar()
                if db_version_raw:
                    parts = db_version_raw.split()
                    if len(parts) >= 2 and parts[0] == "PostgreSQL":
                        major = parts[1].split('.')[0]
                        db_version = f"PostgreSQL {major}"
                    else:
                        db_version = "PostgreSQL"
            except Exception:
                db_version = "PostgreSQL"

        try:
            mig_res = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if mig_res:
                alembic_rev = str(mig_res)
        except Exception:
            alembic_rev = "unknown"
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "unhealthy",
        "timestamp": time.time(),
        "total_users": active_users,
        "admin_users_count": admin_users_count,
        "total_analysis_records": total_records,
        "active_jobs_count": active_jobs_count,
        "completed_jobs_count": completed_jobs_count,
        "failed_jobs_count": failed_jobs_count,
        "database_status": "ok" if db_ok else "unavailable",
        "sqlite_wal": wal_enabled,
        "alembic_revision": alembic_rev,
        "database_dialect": dialect_name,
        "database_version": db_version,
        "metrics": {
            "total_users": active_users,
            "admin_users": admin_users_count,
            "total_records": total_records,
            "active_jobs": active_jobs_count,
            "completed_jobs": completed_jobs_count,
            "failed_jobs": failed_jobs_count,
            "active_users": active_users,
            "disabled_users": disabled_users,
            "banned_users": banned_users,
            "deleted_users": deleted_users,
            "total_users_in_db": total_users_in_db
        },
        "system": {
            "database_connected": db_ok,
            "wal_mode": wal_enabled,
            "alembic_revision": alembic_rev,
        }
    }

@router.get("/api/admin/users")
async def get_admin_users(
    response: Response,
    search: Optional[str] = Query(None, max_length=100),
    role_filter: Optional[str] = Query(None, alias="role", max_length=20),
    status_filter: Optional[str] = Query(None, alias="status", max_length=20),
    include_deleted: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Paginated User Listing for Admin / Owner with Search, Role, and Status filters.
    NEVER includes password_hash or sensitive secrets.
    """
    _add_no_cache_headers(response)
    record_audit_event("admin_users_list_viewed", user_id=current_admin.id)

    query = db.query(
        User,
        func.count(AnalysisRecord.id).label("analysis_count")
    ).outerjoin(AnalysisRecord, User.id == AnalysisRecord.user_id).group_by(User.id)

    if not include_deleted and (not status_filter or status_filter.lower() != "deleted"):
        query = query.filter(func.lower(User.status) != "deleted")

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )

    if role_filter:
        query = query.filter(func.lower(User.role) == role_filter.strip().lower())

    if status_filter:
        query = query.filter(func.lower(User.status) == status_filter.strip().lower())

    # Count query
    total_count_query = db.query(func.count(User.id))
    if not include_deleted and (not status_filter or status_filter.lower() != "deleted"):
        total_count_query = total_count_query.filter(func.lower(User.status) != "deleted")
    if search:
        search_pattern = f"%{search.strip()}%"
        total_count_query = total_count_query.filter(
            or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern)
            )
        )
    if role_filter:
        total_count_query = total_count_query.filter(func.lower(User.role) == role_filter.strip().lower())
    if status_filter:
        total_count_query = total_count_query.filter(func.lower(User.status) == status_filter.strip().lower())

    total_count = total_count_query.scalar() or 0

    # Sorting
    allowed_sort_fields = {
        "created_at": User.created_at,
        "username": User.username,
        "email": User.email,
        "id": User.id,
        "role": User.role,
        "status": User.status,
    }
    sort_column = allowed_sort_fields.get(sort.lower(), User.created_at)
    if order.lower() == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    total_pages = max(1, math.ceil(total_count / page_size))
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()

    items = []
    actor_role = getattr(current_admin, "role", "admin")
    for user_obj, record_count in results:
        items.append({
            "id": user_obj.id,
            "username": user_obj.username,
            "email": user_obj.email,
            "role": user_obj.role,
            "status": user_obj.status,
            "is_admin": getattr(user_obj, "is_admin", False),
            "is_active": user_obj.is_active,
            "created_at": user_obj.created_at.isoformat() if user_obj.created_at else None,
            "updated_at": user_obj.updated_at.isoformat() if user_obj.updated_at else None,
            "last_login_at": user_obj.last_login_at.isoformat() if user_obj.last_login_at else None,
            "banned_at": user_obj.banned_at.isoformat() if user_obj.banned_at else None,
            "ban_reason": user_obj.ban_reason if user_obj.ban_reason else None,
            "disabled_at": user_obj.disabled_at.isoformat() if user_obj.disabled_at else None,
            "deleted_at": user_obj.deleted_at.isoformat() if user_obj.deleted_at else None,
            "analysis_count": record_count,
            "can_manage": can_manage_user(current_admin, user_obj),
            "can_edit_profile": can_edit_user_profile(current_admin, user_obj)
        })

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }

@router.get("/api/admin/users/{user_id}")
async def get_user_detail(
    user_id: int,
    response: Response,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Returns detailed user profile for Admin / Owner.
    """
    _add_no_cache_headers(response)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    actor_role = getattr(current_admin, "role", "admin")
    target_role = getattr(target, "role", "user")

    if actor_role == "admin" and target_role in ("admin", "owner") and current_admin.id != target.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to view management details for this account.")

    def resolve_username(uid: Optional[int]) -> Optional[str]:
        if not uid:
            return None
        u = db.get(User, uid)
        return u.username if u else f"User #{uid}"

    analysis_count = db.query(func.count(AnalysisRecord.id)).filter(AnalysisRecord.user_id == target.id).scalar() or 0

    return {
        "id": target.id,
        "username": target.username,
        "email": target.email,
        "role": target.role,
        "status": target.status,
        "is_admin": getattr(target, "is_admin", False),
        "is_active": target.is_active,
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "updated_at": target.updated_at.isoformat() if target.updated_at else None,
        "last_login_at": target.last_login_at.isoformat() if target.last_login_at else None,
        "banned_at": target.banned_at.isoformat() if target.banned_at else None,
        "banned_by": target.banned_by,
        "banned_by_username": resolve_username(target.banned_by),
        "ban_reason": target.ban_reason,
        "disabled_at": target.disabled_at.isoformat() if target.disabled_at else None,
        "disabled_by": target.disabled_by,
        "disabled_by_username": resolve_username(target.disabled_by),
        "deleted_at": target.deleted_at.isoformat() if target.deleted_at else None,
        "deleted_by": target.deleted_by,
        "deleted_by_username": resolve_username(target.deleted_by),
        "analysis_count": analysis_count,
        "can_manage": can_manage_user(current_admin, target),
        "can_edit_profile": can_edit_user_profile(current_admin, target)
    }

# --- 🔐 USER MANAGEMENT ACTIONS ---

@router.post("/api/admin/users/{user_id}/disable")
async def disable_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = disable_user_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Disabled account for {updated_target.username}",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status,
                "disabled_at": updated_target.disabled_at.isoformat() if updated_target.disabled_at else None
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/enable")
async def enable_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = enable_user_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Enabled account for {updated_target.username}",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/ban")
async def ban_user(
    user_id: int,
    request: Request,
    payload: Dict[str, Any] = Body(...),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    reason = payload.get("reason", "")
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = ban_user_action(db, current_admin, target, reason=reason, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Banned account for {updated_target.username}",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status,
                "banned_at": updated_target.banned_at.isoformat() if updated_target.banned_at else None,
                "ban_reason": updated_target.ban_reason
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/unban")
async def unban_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = unban_user_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Unbanned account for {updated_target.username}",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/delete")
async def soft_delete_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = soft_delete_user_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Soft-deleted account for {updated_target.username}",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status,
                "deleted_at": updated_target.deleted_at.isoformat() if updated_target.deleted_at else None
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/restore")
async def restore_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = restore_user_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Restored account for {updated_target.username}",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/promote-admin")
async def promote_user_to_admin(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = promote_user_to_admin_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Promoted {updated_target.username} to Admin",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/demote-user")
async def demote_admin_to_user(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_target = demote_admin_to_user_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        return {
            "success": True,
            "message": f"Demoted {updated_target.username} to User",
            "user": {
                "id": updated_target.id,
                "username": updated_target.username,
                "role": updated_target.role,
                "status": updated_target.status
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Generates a temporary password for the target user and forces password change on next login."""
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    actor_id = current_admin.id
    if password_reset_rate_limiter.is_rate_limited(actor_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password resets. Please try again later."
        )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        temp_password = reset_password_action(db, current_admin, target, ip_address=client_ip, user_agent=user_agent)
        password_reset_rate_limiter.record_reset(actor_id)
        return {
            "success": True,
            "message": f"Successfully generated temporary password for {target.username}.",
            "temporary_password": temp_password
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
@router.post("/api/admin/users/{user_id}/edit")
async def edit_user(
    user_id: int,
    request: Request,
    payload: Dict[str, Any] = Body(...),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    username = payload.get("username")
    email = payload.get("email")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    updated_target = edit_user_profile_action(
        db=db,
        actor=current_admin,
        target=target,
        new_username=username,
        new_email=email,
        ip_address=client_ip,
        user_agent=user_agent
    )

    return {
        "success": True,
        "message": f"Successfully updated profile for {updated_target.username}",
        "user": {
            "id": updated_target.id,
            "username": updated_target.username,
            "email": updated_target.email,
            "role": updated_target.role,
            "status": updated_target.status,
            "is_admin": getattr(updated_target, "is_admin", False),
            "is_active": updated_target.is_active,
        }
    }

@router.get("/api/admin/jobs")
async def get_admin_jobs(
    response: Response,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Returns list of in-memory active and recent jobs for Admin.
    Safe output: NO file paths, API keys, tracebacks, or raw transcripts.
    """
    _add_no_cache_headers(response)
    record_audit_event("admin_jobs_viewed", user_id=current_admin.id)

    from main import JOBS_DATA, derive_media_type_display

    user_ids = {j.get("user_id") for j in JOBS_DATA.values() if j.get("user_id")}
    users_map: Dict[int, str] = {}
    if user_ids:
        users = db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u.username for u in users}

    jobs_list = []
    for job_id, job_info in list(JOBS_DATA.items()):
        owner_id = job_info.get("user_id")
        owner_name = users_map.get(owner_id, "System / Unknown") if owner_id else "System / Guest"

        raw_error = job_info.get("error")
        sanitized_error_category = None
        if raw_error:
            if isinstance(raw_error, Exception):
                sanitized_error_category = classify_error(raw_error)
            elif isinstance(raw_error, str):
                sanitized_error_category = "General Error"

        source_type = job_info.get("source_type")
        if not source_type or source_type in ["unknown", "upload"]:
            source_type = derive_media_type_display(
                job_info.get("mode"),
                job_info.get("url"),
                job_info.get("filename") or job_info.get("file_path")
            )

        jobs_list.append({
            "job_id": job_id,
            "owner_id": owner_id,
            "owner_username": owner_name,
            "status": job_info.get("status", "unknown"),
            "progress": job_info.get("progress", 0),
            "source_type": source_type,
            "created_at": job_info.get("created_at"),
            "started_at": job_info.get("started_at"),
            "completed_at": job_info.get("completed_at"),
            "terminal_at": job_info.get("terminal_at"),
            "error_category": sanitized_error_category
        })

    jobs_list.sort(key=lambda x: x.get("created_at") or 0, reverse=True)

    return {
        "items": jobs_list,
        "total": len(jobs_list),
        "is_in_memory": True,
        "note": "งานที่กำลังประมวลผลของ Process ปัจจุบัน (In-memory jobs)"
    }

# --- AUDIT LOGS ENDPOINTS (PHASE 13.4) ---

@router.get("/api/admin/audit-logs")
async def list_audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25),
    event_type: Optional[str] = Query(None),
    actor_username: Optional[str] = Query(None),
    target_username: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    if page_size not in (10, 25, 50, 100):
        raise HTTPException(status_code=400, detail="Invalid page_size. Must be 10, 25, 50, or 100.")

    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid sort_order. Must be asc or desc.")

    import sqlalchemy as sa
    from sqlalchemy.orm import aliased
    from datetime import datetime, timezone

    ActorUser = aliased(User, name="actor_user")
    TargetUser = aliased(User, name="target_user")

    query = db.query(
        AuditLog,
        ActorUser.username.label("actor_username"),
        TargetUser.username.label("target_username")
    ).outerjoin(
        ActorUser, AuditLog.actor_user_id == ActorUser.id
    ).outerjoin(
        TargetUser, AuditLog.target_user_id == TargetUser.id
    )

    # Apply Admin visibility scope: Admin can only see User-related events or events they performed
    if current_admin.role == "admin":
        query = query.filter(
            sa.or_(
                AuditLog.actor_user_id == current_admin.id,
                AuditLog.target_role_before == "user",
                AuditLog.target_role_after == "user"
            )
        )

    # Filter: event_type
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)

    # Filter: actor_username
    if actor_username:
        query = query.filter(ActorUser.username == actor_username)

    # Filter: target_username
    if target_username:
        query = query.filter(TargetUser.username == target_username)

    # Filter: date range
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            if dt_from.tzinfo is None:
                dt_from = dt_from.replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format.")

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if dt_to.tzinfo is None:
                dt_to = dt_to.replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format.")

    # Filter: free text search
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            sa.or_(
                ActorUser.username.like(search_pattern),
                TargetUser.username.like(search_pattern),
                AuditLog.event_type.like(search_pattern),
                AuditLog.reason.like(search_pattern)
            )
        )

    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * page_size
    items_query = query.order_by(
        AuditLog.created_at.desc() if sort_order == "desc" else AuditLog.created_at.asc()
    ).offset(offset).limit(page_size)

    items = items_query.all()

    response_items = []
    for log, actor_uname, target_uname in items:
        response_items.append({
            "id": log.id,
            "event_type": log.event_type,
            "actor_user_id": log.actor_user_id,
            "actor_username": actor_uname or ("Deleted account" if log.actor_user_id else "-"),
            "actor_role": log.actor_role or "-",
            "target_user_id": log.target_user_id,
            "target_username": target_uname or ("Deleted account" if log.target_user_id else "-"),
            "target_role_before": log.target_role_before or "-",
            "target_role_after": log.target_role_after or "-",
            "target_status_before": log.target_status_before or "-",
            "target_status_after": log.target_status_after or "-",
            "reason": log.reason or "-",
            "ip_address": log.ip_address or "-",
            "user_agent": log.user_agent or "-",
            "created_at": log.created_at.isoformat() if log.created_at else None
        })

    return {
        "items": response_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    }

@router.get("/api/admin/audit-logs/export.csv")
async def export_audit_logs_csv(
    request: Request,
    event_type: Optional[str] = Query(None),
    actor_username: Optional[str] = Query(None),
    target_username: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid sort_order. Must be asc or desc.")

    import sqlalchemy as sa
    from sqlalchemy.orm import aliased
    from datetime import datetime, timezone
    import csv
    import io
    from fastapi.responses import StreamingResponse

    ActorUser = aliased(User, name="actor_user")
    TargetUser = aliased(User, name="target_user")

    query = db.query(
        AuditLog,
        ActorUser.username.label("actor_username"),
        TargetUser.username.label("target_username")
    ).outerjoin(
        ActorUser, AuditLog.actor_user_id == ActorUser.id
    ).outerjoin(
        TargetUser, AuditLog.target_user_id == TargetUser.id
    )

    # Apply Admin visibility scope: Admin can only export User-related events or events they performed
    if current_admin.role == "admin":
        query = query.filter(
            sa.or_(
                AuditLog.actor_user_id == current_admin.id,
                AuditLog.target_role_before == "user",
                AuditLog.target_role_after == "user"
            )
        )

    # Filter: event_type
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)

    # Filter: actor_username
    if actor_username:
        query = query.filter(ActorUser.username == actor_username)

    # Filter: target_username
    if target_username:
        query = query.filter(TargetUser.username == target_username)

    # Filter: date range
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            if dt_from.tzinfo is None:
                dt_from = dt_from.replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format.")

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if dt_to.tzinfo is None:
                dt_to = dt_to.replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format.")

    # Filter: free text search
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            sa.or_(
                ActorUser.username.like(search_pattern),
                TargetUser.username.like(search_pattern),
                AuditLog.event_type.like(search_pattern),
                AuditLog.reason.like(search_pattern)
            )
        )

    records = query.order_by(
        AuditLog.created_at.desc() if sort_order == "desc" else AuditLog.created_at.asc()
    ).all()

    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Excel support
    writer = csv.writer(output)

    writer.writerow([
        "Audit ID", "Event Type", "Actor ID", "Actor Username", "Actor Role",
        "Target ID", "Target Username", "Target Role Before", "Target Role After",
        "Target Status Before", "Target Status After", "Reason", "IP Address",
        "User Agent", "Created At UTC"
    ])

    def escape_formula(val):
        if val is None:
            return ""
        val_str = str(val)
        if val_str and val_str[0] in ('=', '+', '-', '@'):
            return f"'{val_str}"
        return val_str

    for log, actor_uname, target_uname in records:
        writer.writerow([
            log.id,
            escape_formula(log.event_type),
            log.actor_user_id or "",
            escape_formula(actor_uname or ("Deleted account" if log.actor_user_id else "-")),
            escape_formula(log.actor_role or "-"),
            log.target_user_id or "",
            escape_formula(target_uname or ("Deleted account" if log.target_user_id else "-")),
            escape_formula(log.target_role_before or "-"),
            escape_formula(log.target_role_after or "-"),
            escape_formula(log.target_status_before or "-"),
            escape_formula(log.target_status_after or "-"),
            escape_formula(log.reason or "-"),
            escape_formula(log.ip_address or "-"),
            escape_formula(log.user_agent or "-"),
            log.created_at.isoformat() if log.created_at else ""
        ])

    output.seek(0)
    filename = f"audit_logs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_UTC.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Content-Type-Options": "nosniff"
        }
    )

@router.get("/api/admin/audit-logs/{audit_id}")
async def get_audit_log_detail(
    request: Request,
    audit_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    import sqlalchemy as sa
    from sqlalchemy.orm import aliased

    ActorUser = aliased(User, name="actor_user")
    TargetUser = aliased(User, name="target_user")

    query = db.query(
        AuditLog,
        ActorUser.username.label("actor_username"),
        TargetUser.username.label("target_username")
    ).outerjoin(
        ActorUser, AuditLog.actor_user_id == ActorUser.id
    ).outerjoin(
        TargetUser, AuditLog.target_user_id == TargetUser.id
    ).filter(
        AuditLog.id == audit_id
    )

    if current_admin.role == "admin":
        query = query.filter(
            sa.or_(
                AuditLog.actor_user_id == current_admin.id,
                AuditLog.target_role_before == "user",
                AuditLog.target_role_after == "user"
            )
        )

    result = query.first()
    if not result:
        raise HTTPException(status_code=404, detail="Audit log not found")

    log, actor_uname, target_uname = result

    return {
        "id": log.id,
        "event_type": log.event_type,
        "actor_user_id": log.actor_user_id,
        "actor_username": actor_uname or ("Deleted account" if log.actor_user_id else "-"),
        "actor_role": log.actor_role or "-",
        "target_user_id": log.target_user_id,
        "target_username": target_uname or ("Deleted account" if log.target_user_id else "-"),
        "target_role_before": log.target_role_before or "-",
        "target_role_after": log.target_role_after or "-",
        "target_status_before": log.target_status_before or "-",
        "target_status_after": log.target_status_after or "-",
        "reason": log.reason or "-",
        "ip_address": log.ip_address or "-",
        "user_agent": log.user_agent or "-",
        "created_at": log.created_at.isoformat() if log.created_at else None
    }


# -------------------------------------------------------------
# ANALYSIS RUN HISTORY ENDPOINTS
# -------------------------------------------------------------
from models.analysis_run_history import AnalysisRunHistory

@router.get("/api/admin/analysis-run-history")
async def list_run_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25),
    search: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    if page_size not in (10, 25, 50, 100):
        raise HTTPException(status_code=400, detail="Invalid page_size. Must be 10, 25, 50, or 100.")

    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid sort_order. Must be asc or desc.")

    import sqlalchemy as sa
    from datetime import datetime, timezone

    query = db.query(
        AnalysisRunHistory,
        User.username.label("user_username")
    ).join(
        User, AnalysisRunHistory.user_id == User.id
    )

    # Filter: search query
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            sa.or_(
                User.username.like(search_pattern),
                AnalysisRunHistory.url_or_filename.like(search_pattern),
                AnalysisRunHistory.model_used.like(search_pattern),
                AnalysisRunHistory.source_type.like(search_pattern),
                AnalysisRunHistory.job_id.like(search_pattern)
            )
        )

    # Filter: source_type
    if source_type:
        query = query.filter(func.lower(AnalysisRunHistory.source_type) == source_type.lower())

    # Filter: date range
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            if dt_from.tzinfo is None:
                dt_from = dt_from.replace(tzinfo=timezone.utc)
            query = query.filter(AnalysisRunHistory.date_time >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format.")

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if dt_to.tzinfo is None:
                dt_to = dt_to.replace(tzinfo=timezone.utc)
            query = query.filter(AnalysisRunHistory.date_time <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format.")

    # Count total records matching filters
    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * page_size
    items_query = query.order_by(
        AnalysisRunHistory.date_time.desc() if sort_order == "desc" else AnalysisRunHistory.date_time.asc()
    ).offset(offset).limit(page_size)

    items = items_query.all()

    response_items = []
    for run, username in items:
        proc_t = run.processing_time
        if (proc_t is None or proc_t <= 0.0) and run.job_id:
            try:
                rec = db.query(AnalysisRecord).filter_by(job_id=run.job_id).first()
                if rec and rec.completed_at and rec.created_at:
                    proc_t = float((rec.completed_at - rec.created_at).total_seconds())
            except Exception:
                pass

        cost_data = calculate_run_cost(
            token_usage=run.token_usage,
            model_used=run.model_used,
            video_duration=run.video_duration,
        )

        response_items.append({
            "id": run.id,
            "user_id": run.user_id,
            "user_username": username or "Unknown",
            "date_time": run.date_time.isoformat() if run.date_time else None,
            "source_type": run.source_type,
            "url_or_filename": run.url_or_filename,
            "model_used": run.model_used,
            "video_duration": run.video_duration,
            "processing_time": proc_t,
            "total_words": run.total_words,
            "words_per_minute": run.words_per_minute,
            "job_id": run.job_id,
            "api_calls": cost_data["api_calls"] or run.api_calls,
            "estimated_cost": float(cost_data["estimated_cost_thb"]) if cost_data["estimated_cost_thb"] is not None else (float(run.estimated_cost) if run.estimated_cost is not None else None),
            "estimated_cost_usd": cost_data["estimated_cost_usd"],
            "estimated_cost_thb": cost_data["estimated_cost_thb"],
            "display_thb": cost_data["display_thb"],
            "display_usd": cost_data["display_usd"],
            "estimation_quality": cost_data["estimation_quality"],
            "quality_label_th": cost_data["quality_label_th"],
            "disclaimer_th": cost_data["disclaimer_th"],
            "cost_per_video_minute_thb": cost_data["cost_per_video_minute_thb"],
            "tokens_per_video_minute": cost_data["tokens_per_video_minute"],
            "cost_breakdown": {
                "input_usd": cost_data["cost_input_usd"],
                "cached_usd": cost_data["cost_cached_usd"],
                "output_usd": cost_data["cost_output_usd"],
                "grounding_usd": cost_data["cost_grounding_usd"],
                "models": cost_data["models_breakdown"],
                "stages": cost_data["stages_breakdown"],
            },
            "estimated_cost_version": cost_data["pricing_version"],
            "token_usage": run.token_usage
        })

    return {
        "items": response_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    }

def format_seconds_to_hhmmss(val):
    if val is None:
        return "-"
    try:
        import math
        f_val = float(val)
        if math.isnan(f_val) or math.isinf(f_val):
            return "-"
        if f_val < 0:
            return "-"
        total_seconds = int(round(f_val))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "-"

@router.get("/api/admin/analysis-run-history/export.csv")
async def export_run_history_csv(
    request: Request,
    search: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid sort_order. Must be asc or desc.")

    import sqlalchemy as sa
    from datetime import datetime, timezone
    import csv
    import io
    from fastapi.responses import StreamingResponse

    query = db.query(
        AnalysisRunHistory,
        User.username.label("user_username")
    ).join(
        User, AnalysisRunHistory.user_id == User.id
    )

    # Filter: search query
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            sa.or_(
                User.username.like(search_pattern),
                AnalysisRunHistory.url_or_filename.like(search_pattern),
                AnalysisRunHistory.model_used.like(search_pattern),
                AnalysisRunHistory.source_type.like(search_pattern),
                AnalysisRunHistory.job_id.like(search_pattern)
            )
        )

    # Filter: source_type
    if source_type:
        query = query.filter(func.lower(AnalysisRunHistory.source_type) == source_type.lower())

    # Filter: date range
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            if dt_from.tzinfo is None:
                dt_from = dt_from.replace(tzinfo=timezone.utc)
            query = query.filter(AnalysisRunHistory.date_time >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format.")

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if dt_to.tzinfo is None:
                dt_to = dt_to.replace(tzinfo=timezone.utc)
            query = query.filter(AnalysisRunHistory.date_time <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format.")

    records = query.order_by(
        AnalysisRunHistory.date_time.desc() if sort_order == "desc" else AnalysisRunHistory.date_time.asc()
    ).all()

    output = io.StringIO()
    output.write('\ufeff')  # UTF-8 BOM for Excel support
    writer = csv.writer(output)

    writer.writerow([
        "Run ID", "Date/Time UTC", "User ID", "Username", "Source Type",
        "URL or File Name", "Model Used", "Video Duration (sec)",
        "เวลาประมวลผล (HH:MM:SS)", "Total Words", "Words Per Minute",
        "Job ID", "API Calls",
        "Estimated Cost USD", "Estimated Cost THB", "Estimation Quality",
        "Pricing Version", "FX Rate", "Cost Input USD", "Cost Output USD",
        "Cost Cache USD", "Cost Grounding USD", "Cost per Video Minute THB",
        "Total Tokens", "Prompt Tokens", "Candidates Tokens", "Cached Tokens", "Thinking Tokens"
    ])

    def escape_formula(val):
        if val is None:
            return ""
        val_str = str(val)
        if val_str and val_str[0] in ('=', '+', '-', '@'):
            return f"'{val_str}"
        return val_str

    for run, username in records:
        cost_res = calculate_run_cost(
            token_usage=run.token_usage,
            model_used=run.model_used,
            video_duration=run.video_duration,
        )
        writer.writerow([
            run.id,
            run.date_time.isoformat() if run.date_time else "",
            run.user_id,
            escape_formula(username or "Unknown"),
            escape_formula(run.source_type),
            escape_formula(run.url_or_filename),
            escape_formula(run.model_used),
            run.video_duration,
            format_seconds_to_hhmmss(run.processing_time),
            run.total_words,
            run.words_per_minute,
            escape_formula(run.job_id),
            cost_res["api_calls"] or run.api_calls,
            cost_res["estimated_cost_usd"] if cost_res["estimated_cost_usd"] is not None else "",
            cost_res["estimated_cost_thb"] if cost_res["estimated_cost_thb"] is not None else "",
            cost_res["estimation_quality"],
            cost_res["pricing_version"],
            cost_res["fx_rate"],
            cost_res["cost_input_usd"],
            cost_res["cost_output_usd"],
            cost_res["cost_cached_usd"],
            cost_res["cost_grounding_usd"],
            cost_res["cost_per_video_minute_thb"] if cost_res["cost_per_video_minute_thb"] is not None else "",
            cost_res["total_tokens"],
            cost_res["prompt_tokens"],
            cost_res["candidates_tokens"],
            cost_res["cached_tokens"],
            cost_res["thoughts_tokens"],
        ])

    response = StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv"
    )
    response.headers["Content-Disposition"] = "attachment; filename=analysis_run_history.csv"
    return response


# -------------------------------------------------------------
# ADMIN ANALYSIS HISTORY ENDPOINTS (Analysis & Comparison Viewer)
# -------------------------------------------------------------

@router.get("/api/admin/all-analyses")
async def list_all_analyses_admin(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25),
    search: Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None, alias="user"),
    source_type: Optional[str] = Query(None),
    model_used: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort: str = Query("newest"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    if page_size not in (10, 25, 50, 100):
        raise HTTPException(status_code=400, detail="Invalid page_size. Must be 10, 25, 50, or 100.")

    if sort not in ("newest", "oldest"):
        raise HTTPException(status_code=400, detail="Invalid sort. Must be newest or oldest.")

    from datetime import datetime, timezone
    import sqlalchemy as sa

    query = db.query(
        AnalysisRecord,
        User.username.label("user_username")
    ).outerjoin(
        User, AnalysisRecord.user_id == User.id
    )

    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            sa.or_(
                User.username.ilike(search_pattern),
                AnalysisRecord.display_title.ilike(search_pattern),
                AnalysisRecord.original_filename.ilike(search_pattern),
                AnalysisRecord.source_url.ilike(search_pattern)
            )
        )

    if user_filter and user_filter.strip():
        uf = user_filter.strip()
        if uf.isdigit():
            query = query.filter(sa.or_(User.id == int(uf), User.username.ilike(uf)))
        else:
            query = query.filter(User.username.ilike(f"%{uf}%"))

    if source_type and source_type.strip():
        st = source_type.strip().lower()
        if st == "youtube":
            query = query.filter(AnalysisRecord.source_type == "youtube")
        elif st == "tiktok":
            query = query.filter(AnalysisRecord.source_type.in_(["tiktok", "tiktok_url", "external_tiktok"]))
        elif st == "upload":
            query = query.filter(AnalysisRecord.source_type.in_(["upload", "mp4", "file"]))
        else:
            query = query.filter(func.lower(AnalysisRecord.source_type) == st)

    if model_used and model_used.strip():
        query = query.filter(AnalysisRecord.model_used.ilike(f"%{model_used.strip()}%"))

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            if dt_from.tzinfo is None:
                dt_from = dt_from.replace(tzinfo=timezone.utc)
            query = query.filter(AnalysisRecord.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format.")

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if dt_to.tzinfo is None:
                dt_to = dt_to.replace(tzinfo=timezone.utc)
            query = query.filter(AnalysisRecord.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format.")

    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * page_size
    items_query = query.order_by(
        AnalysisRecord.created_at.desc() if sort == "newest" else AnalysisRecord.created_at.asc(),
        AnalysisRecord.id.desc() if sort == "newest" else AnalysisRecord.id.asc()
    ).offset(offset).limit(page_size)

    items = items_query.all()

    response_items = []
    for rec, username in items:
        dur = rec.duration_seconds
        if (dur is None or dur <= 0) and rec.cache:
            dur = rec.cache.duration_seconds
            if (dur is None or dur <= 0) and rec.cache.result_json:
                rj = rec.cache.result_json
                if isinstance(rj, dict):
                    dur = rj.get("duration_seconds") or rj.get("duration") or rj.get("video_metadata", {}).get("duration")

        response_items.append({
            "public_id": rec.public_id,
            "user_id": rec.user_id,
            "username": username or "Unknown",
            "display_title": rec.display_title,
            "source_type": rec.source_type,
            "source_url": rec.source_url,
            "original_filename": rec.original_filename,
            "duration_seconds": float(dur) if dur is not None and str(dur).replace('.', '', 1).isdigit() else dur,
            "status": rec.status,
            "progress": rec.progress,
            "model_used": rec.model_used or "gemini-2.5-flash",
            "has_cache": rec.cache_id is not None,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
            "processing_seconds": rec.processing_seconds
        })

    return {
        "items": response_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    }

@router.get("/api/admin/all-comparisons")
async def list_all_comparisons_admin(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25),
    search: Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None, alias="user"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort: str = Query("newest"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    if page_size not in (10, 25, 50, 100):
        raise HTTPException(status_code=400, detail="Invalid page_size. Must be 10, 25, 50, or 100.")

    if sort not in ("newest", "oldest"):
        raise HTTPException(status_code=400, detail="Invalid sort. Must be newest or oldest.")

    from datetime import datetime, timezone
    import sqlalchemy as sa
    from models.video_comparison import VideoComparison

    query = db.query(
        VideoComparison,
        User.username.label("user_username")
    ).outerjoin(
        User, VideoComparison.user_id == User.id
    )

    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            sa.or_(
                User.username.ilike(search_pattern),
                VideoComparison.canonical_pair_key.ilike(search_pattern),
                VideoComparison.display_order_a.ilike(search_pattern),
                VideoComparison.display_order_b.ilike(search_pattern)
            )
        )

    if user_filter and user_filter.strip():
        uf = user_filter.strip()
        if uf.isdigit():
            query = query.filter(sa.or_(User.id == int(uf), User.username.ilike(uf)))
        else:
            query = query.filter(User.username.ilike(f"%{uf}%"))

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            if dt_from.tzinfo is None:
                dt_from = dt_from.replace(tzinfo=timezone.utc)
            query = query.filter(VideoComparison.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO format.")

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if dt_to.tzinfo is None:
                dt_to = dt_to.replace(tzinfo=timezone.utc)
            query = query.filter(VideoComparison.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO format.")

    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * page_size
    items_query = query.order_by(
        VideoComparison.created_at.desc() if sort == "newest" else VideoComparison.created_at.asc(),
        VideoComparison.id.desc() if sort == "newest" else VideoComparison.id.asc()
    ).offset(offset).limit(page_size)

    items = items_query.all()

    response_items = []
    for comp, username in items:
        disp_a = comp.display_order_a or comp.analysis_id_a or ""
        disp_b = comp.display_order_b or comp.analysis_id_b or ""

        rec_a = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == disp_a).first() if disp_a else None
        rec_b = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == disp_b).first() if disp_b else None

        video_a_meta = {
            "analysis_id": disp_a,
            "title": rec_a.display_title if rec_a else f"Video A ({disp_a[:8] if disp_a else 'A'})",
            "thumbnail_url": rec_a.thumbnail_url if rec_a else "/static/Logo_boy.png",
            "source_type": rec_a.source_type if rec_a else "unknown"
        }

        video_b_meta = {
            "analysis_id": disp_b,
            "title": rec_b.display_title if rec_b else f"Video B ({disp_b[:8] if disp_b else 'B'})",
            "thumbnail_url": rec_b.thumbnail_url if rec_b else "/static/Logo_boy.png",
            "source_type": rec_b.source_type if rec_b else "unknown"
        }

        response_items.append({
            "public_id": comp.public_id,
            "user_id": comp.user_id,
            "username": username or "Unknown",
            "canonical_pair_key": comp.canonical_pair_key,
            "display_order_a": disp_a,
            "display_order_b": disp_b,
            "status": comp.status,
            "model_used": comp.model_used or "gemini-2.5-flash",
            "processing_seconds": comp.processing_seconds or 0.0,
            "created_at": comp.created_at.isoformat() if comp.created_at else None,
            "updated_at": comp.updated_at.isoformat() if comp.updated_at else None,
            "video_a": video_a_meta,
            "video_b": video_b_meta
        })

    return {
        "items": response_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1
    }

@router.get("/api/admin/analyses/{public_id}")
async def get_admin_analysis_detail(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    from services.history_query_service import build_analysis_detail
    record = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == public_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis record not found")

    detail = build_analysis_detail(db, record)
    if record.user_id:
        u = db.query(User).filter(User.id == record.user_id).first()
        detail["username"] = u.username if u else "Unknown"
    else:
        detail["username"] = "Guest"

    return detail

@router.get("/api/admin/comparisons/{public_id}")
async def get_admin_comparison_detail(
    public_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin)
):
    if not verify_same_origin(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin request forbidden")

    from models.video_comparison import VideoComparison
    from routers.comparison import summarize_evidence_counts

    comp = db.query(VideoComparison).filter(VideoComparison.public_id == public_id).first()
    if not comp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison record not found")

    u = db.query(User).filter(User.id == comp.user_id).first() if comp.user_id else None
    owner_username = u.username if u else "Unknown"

    disp_a = comp.display_order_a or comp.analysis_id_a or ""
    disp_b = comp.display_order_b or comp.analysis_id_b or ""

    rec_a = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == disp_a).first() if disp_a else None
    rec_b = db.query(AnalysisRecord).filter(AnalysisRecord.public_id == disp_b).first() if disp_b else None

    video_a_meta = {
        "analysis_id": disp_a,
        "title": rec_a.display_title if rec_a else f"Video A ({disp_a[:8] if disp_a else 'A'})",
        "thumbnail_url": rec_a.thumbnail_url if rec_a else "/static/Logo_boy.png",
        "source_type": rec_a.source_type if rec_a else "unknown"
    }

    video_b_meta = {
        "analysis_id": disp_b,
        "title": rec_b.display_title if rec_b else f"Video B ({disp_b[:8] if disp_b else 'B'})",
        "thumbnail_url": rec_b.thumbnail_url if rec_b else "/static/Logo_boy.png",
        "source_type": rec_b.source_type if rec_b else "unknown"
    }

    res_json = comp.result_json or {}
    ev_summary = summarize_evidence_counts(res_json)

    return {
        "public_id": comp.public_id,
        "comparison_public_id": comp.public_id,
        "username": owner_username,
        "canonical_pair_key": comp.canonical_pair_key,
        "display_order_a": disp_a,
        "display_order_b": disp_b,
        "video_a": video_a_meta,
        "video_b": video_b_meta,
        "status": comp.status,
        "result": res_json,
        "result_json": res_json,
        "evidence_summary": ev_summary,
        "model_used": comp.model_used or "gemini-2.5-flash",
        "processing_seconds": comp.processing_seconds or 0.0,
        "created_at": comp.created_at.isoformat() if comp.created_at else None,
        "updated_at": comp.updated_at.isoformat() if comp.updated_at else None
    }
