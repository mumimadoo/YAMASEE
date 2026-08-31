from datetime import datetime, timezone
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from services.auth_service import get_user_by_id

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """
    Dependency that extracts current authenticated user from session.
    Returns User object if logged in and status is active, otherwise None.
    Clears invalid session if user_id is missing, disabled, banned, or deleted.
    NEVER accepts user_id from frontend form or JSON parameter.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = get_user_by_id(db, user_id)
    if not user or getattr(user, "status", "active") != "active" or not user.is_active:
        request.session.clear()
        return None

    # Enforce server-side session revocation
    if user.password_reset_at:
        session_created_str = request.session.get("session_created_at")
        if not session_created_str:
            request.session.clear()
            return None
        try:
            session_created = datetime.fromisoformat(session_created_str)
            if session_created.tzinfo is None:
                session_created = session_created.replace(tzinfo=timezone.utc)
            
            pwd_reset_at = user.password_reset_at
            if pwd_reset_at.tzinfo is None:
                pwd_reset_at = pwd_reset_at.replace(tzinfo=timezone.utc)
                
            if session_created < pwd_reset_at:
                request.session.clear()
                return None
        except Exception:
            request.session.clear()
            return None

    return user

def require_current_user_api(current_user: User | None = Depends(get_current_user)) -> User:
    """
    Dependency for API endpoints requiring authentication.
    Raises HTTP 401 Unauthorized with JSON detail if user is not authenticated.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    if getattr(current_user, "must_change_password", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required"
        )
    return current_user

def require_admin(current_user: User | None = Depends(get_current_user)) -> User:
    """
    Dependency for Admin endpoints.
    - Not logged in -> HTTP 401 Unauthorized
    - Logged in but not admin/owner -> HTTP 403 Forbidden
    - Admin or Owner -> returns User
    """
    user = require_current_user_api(current_user)
    user_role = getattr(user, "role", "user")
    is_admin_flag = getattr(user, "is_admin", False)
    if not (is_admin_flag or user_role in ("admin", "owner")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required"
        )
    return user

def require_owner(current_user: User | None = Depends(get_current_user)) -> User:
    """
    Dependency for Owner endpoints.
    - Not logged in -> HTTP 401 Unauthorized
    - Logged in but not owner -> HTTP 403 Forbidden
    - Owner -> returns User
    """
    user = require_current_user_api(current_user)
    if getattr(user, "role", "user") != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner privilege required"
        )
    return user

def require_admin_or_owner(current_user: User | None = Depends(get_current_user)) -> User:
    """Alias for require_admin to explicitly clarify Admin/Owner access."""
    return require_admin(current_user)

# Alias for backwards compatibility
require_current_user = require_current_user_api
