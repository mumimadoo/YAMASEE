import os
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dependencies.auth import get_current_user
from models.user import User
from sqlalchemy import func
from database import SessionLocal
from models.analysis_run_history import AnalysisRunHistory

CURRENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(CURRENT_DIR, "templates")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

def get_footer_stats():
    db = SessionLocal()
    try:
        total_runs = db.query(func.count(AnalysisRunHistory.id)).scalar() or 0
        total_words = db.query(func.sum(AnalysisRunHistory.total_words)).scalar() or 0
        return {
            "total_analysis_runs": f"{total_runs:,}",
            "total_words_processed": f"{total_words:,}"
        }
    except Exception:
        return {
            "total_analysis_runs": "0",
            "total_words_processed": "0"
        }
    finally:
        db.close()

templates.env.globals["get_footer_stats"] = get_footer_stats


router = APIRouter(tags=["Page Routes"])

@router.get("/", response_class=HTMLResponse)
async def serve_root_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """
    Root Entry Point:
    - Guest: Renders Landing Page (landing.html)
    - Logged-in User: Redirects to /dashboard (303) (or /change-password if forced)
    """
    if current_user:
        if getattr(current_user, "must_change_password", False):
            return RedirectResponse(url="/change-password", status_code=303)
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="landing.html")

@router.get("/landing", response_class=HTMLResponse)
async def serve_landing_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """Serves Landing Page for both guests and logged-in users."""
    if current_user and getattr(current_user, "must_change_password", False):
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request=request, name="landing.html", context={"user": current_user})

@router.get("/login", response_class=HTMLResponse)
async def serve_login_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """Serves Login Page. Redirects logged-in users to /dashboard."""
    if current_user:
        if getattr(current_user, "must_change_password", False):
            return RedirectResponse(url="/change-password", status_code=303)
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html")

@router.get("/register", response_class=HTMLResponse)
async def serve_register_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """Serves Register Page. Redirects logged-in users to /dashboard."""
    if current_user:
        if getattr(current_user, "must_change_password", False):
            return RedirectResponse(url="/change-password", status_code=303)
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="register.html")

@router.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """
    Serves Protected Dashboard Page (index.html).
    - Guest: Redirects to /login (303)
    - Logged-in User: Renders index.html
    """
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    if getattr(current_user, "must_change_password", False):
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request=request, name="index.html", context={"user": current_user})

@router.get("/history", response_class=HTMLResponse)
async def serve_history_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """
    Serves Protected History Page (history.html).
    - Guest: Redirects to /login (303)
    - Logged-in User: Renders history.html
    """
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    if getattr(current_user, "must_change_password", False):
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request=request, name="history.html", context={"user": current_user})

@router.get("/change-password", response_class=HTMLResponse)
async def serve_change_password_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """
    Serves Protected Change Password Page.
    - Guest: Redirects to /login (303)
    - Logged-in User: Renders change_password.html
    """
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="change_password.html", context={"user": current_user})

@router.get("/comparison", response_class=HTMLResponse)
async def serve_comparison_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """
    Serves Protected Video Comparison Workspace Page (comparison.html).
    - Guest: Redirects to /login (303)
    - Logged-in User: Renders comparison.html
    """
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    if getattr(current_user, "must_change_password", False):
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request=request, name="comparison.html", context={"user": current_user, "comparison_public_id": None})

@router.get("/comparison/history", response_class=HTMLResponse)
async def serve_comparison_history_page(request: Request, current_user: User | None = Depends(get_current_user)):
    """
    Serves Protected Video Comparison History Page (comparison_history.html).
    - Guest: Redirects to /login (303)
    - Logged-in User: Renders comparison_history.html
    """
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    if getattr(current_user, "must_change_password", False):
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request=request, name="comparison_history.html", context={"user": current_user})

@router.get("/comparison/{public_id}", response_class=HTMLResponse)
async def serve_comparison_detail_page(public_id: str, request: Request, current_user: User | None = Depends(get_current_user)):
    """
    Serves Protected Video Comparison Workspace Page with pre-loaded comparison public_id.
    - Guest: Redirects to /login (303)
    - Logged-in User: Renders comparison.html with comparison_public_id context
    """
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    if getattr(current_user, "must_change_password", False):
        return RedirectResponse(url="/change-password", status_code=303)
    return templates.TemplateResponse(request=request, name="comparison.html", context={"user": current_user, "comparison_public_id": public_id})

