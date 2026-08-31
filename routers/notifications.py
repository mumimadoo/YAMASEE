from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from dependencies.auth import get_current_user
from database import get_db
from models.user import User
from services.notification_service import (
    get_notifications,
    get_unread_count,
    mark_as_read,
    mark_all_as_read
)
from schemas.notification_schemas import (
    NotificationResponse,
    UnreadCountResponse
)

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100)
):
    notifications = get_notifications(db, current_user.id, unread_only, page, page_size)
    return notifications

@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_notification_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    count = get_unread_count(db, current_user.id)
    return {"count": count}

@router.post("/{notification_id}/read")
async def mark_notification_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    notification = mark_as_read(db, current_user.id, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "ok"}

@router.post("/mark-all-read")
async def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mark_all_as_read(db, current_user.id)
    return {"status": "ok"}
