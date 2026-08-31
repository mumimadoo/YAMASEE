from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models.user import User
from schemas.auth_schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    AuthSuccessResponse,
    PasswordChangeRequest,
)
from services.auth_service import (
    get_user_by_email,
    get_user_by_identifier,
    create_user,
    authenticate_user,
    verify_password,
    update_last_login,
    hash_password,
)
from dependencies.auth import get_current_user
from utils.rate_limiter import login_rate_limiter
from utils.origin_checker import verify_same_origin
from utils.audit import record_audit_event

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: UserRegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Registers a new user account."""
    if not verify_same_origin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request forbidden"
        )

    if req.password != req.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )
    
    try:
        user = create_user(
            db=db,
            username=req.username,
            email=req.email,
            password=req.password
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        ) from e

    user_resp = UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_admin=getattr(user, "is_admin", False),
        role=getattr(user, "role", "user"),
        status=getattr(user, "status", "active")
    )
    return {"success": True, "user": user_resp}

@router.post("/login")
async def login(req: UserLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticates a user and starts a session, enforcing account status checks."""
    if not verify_same_origin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request forbidden"
        )

    client_ip = request.client.host if request.client else "127.0.0.1"

    if login_rate_limiter.is_rate_limited(req.email, client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later."
        )

    # 1. Fetch user by identifier
    user = get_user_by_identifier(db, req.email)
    if not user or not verify_password(req.password, user.password_hash):
        login_rate_limiter.record_failure(req.email, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username, email, or password"
        )

    # 2. Status Enforcement after password verification
    user_status = (getattr(user, "status", "active") or "active").lower()
    if user_status != "active" or not user.is_active:
        login_rate_limiter.record_failure(req.email, client_ip)
        if user_status == "banned":
            msg = "บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อผู้ดูแลระบบ"
        elif user_status == "deleted":
            msg = "ไม่สามารถเข้าสู่ระบบด้วยบัญชีนี้ได้"
        else:
            msg = "Invalid username, email, or password"

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg
        )

    # 3. Check for expired temporary password
    if getattr(user, "must_change_password", False):
        expires_at = user.temporary_password_expires_at
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires_at:
                login_rate_limiter.record_failure(req.email, client_ip)
                from services.role_service import record_db_audit_log
                record_db_audit_log(
                    db=db,
                    event_type="password_reset_expired_login",
                    actor=user,
                    target=user,
                    target_role_before=user.role,
                    target_role_after=user.role,
                    target_status_before=user.status,
                    target_status_after=user.status,
                    reason="Temporary password has expired",
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent")
                )
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Temporary password has expired. Please contact an administrator."
                )

    login_rate_limiter.reset_failures(req.email, client_ip)

    user_id = user.id
    user_email = user.email
    request.session["user_id"] = user_id
    request.session["email"] = user_email
    request.session["session_created_at"] = datetime.now(timezone.utc).isoformat()
    update_last_login(db, user)

    record_audit_event("login", user_id=user_id)

    if getattr(user, "must_change_password", False):
        return {"success": True, "redirect_url": "/change-password"}
    return {"success": True, "redirect_url": "/dashboard"}


@router.post("/change-password")
async def change_password(
    req: PasswordChangeRequest,
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Changes a user's password securely."""
    if not verify_same_origin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request forbidden"
        )

    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    client_ip = request.client.host if request.client else "127.0.0.1"
    user_agent = request.headers.get("user-agent")

    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    if req.new_password != req.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirm password do not match"
        )

    current_user.password_hash = hash_password(req.new_password)
    current_user.must_change_password = False
    current_user.temporary_password_expires_at = None

    from services.role_service import record_db_audit_log
    record_db_audit_log(
        db=db,
        event_type="password_changed",
        actor=current_user,
        target=current_user,
        target_role_before=current_user.role,
        target_role_after=current_user.role,
        target_status_before=current_user.status,
        target_status_after=current_user.status,
        reason="Password changed successfully",
        ip_address=client_ip,
        user_agent=user_agent
    )
    db.commit()

    return {"success": True, "message": "Password changed successfully", "redirect_url": "/dashboard"}

@router.post("/logout")
async def logout(request: Request):
    """Clears user session idempotently."""
    if not verify_same_origin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request forbidden"
        )

    user_id = request.session.get("user_id")
    record_audit_event("logout", user_id=user_id)
    request.session.clear()
    return {"success": True, "redirect_url": "/login"}

@router.get("/me")
async def get_me(current_user: User | None = Depends(get_current_user)):
    """Returns information about current authenticated user."""
    if not current_user:
        return {"authenticated": False, "user": None}
    
    user_resp = UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_admin=getattr(current_user, "is_admin", False),
        role=getattr(current_user, "role", "user"),
        status=getattr(current_user, "status", "active")
    )
    return {"authenticated": True, "user": user_resp}
