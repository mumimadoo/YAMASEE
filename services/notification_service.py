from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from models.notification import Notification
from models.analysis_record import utc_now

def create_notification(
    db: Session,
    user_id: int,
    type: str,
    title: str,
    message: str,
    related_job_id: Optional[str] = None,
    target_url: Optional[str] = None,
    deduplication_key: Optional[str] = None,
) -> Notification:
    """
    Creates a new notification. If a deduplication_key is provided and a notification
    with that key exists for the user, it returns the existing notification.
    """
    if deduplication_key:
        existing = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.deduplication_key == deduplication_key
        ).first()
        if existing:
            return existing

    new_notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        related_job_id=related_job_id,
        target_url=target_url,
        deduplication_key=deduplication_key,
        created_at=utc_now()
    )
    try:
        db.add(new_notification)
        db.commit()
        db.refresh(new_notification)
        return new_notification
    except Exception as e:
        db.rollback()
        raise e

def get_notifications(
    db: Session,
    user_id: int,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20
) -> list[Notification]:
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    
    return query.order_by(desc(Notification.created_at)).offset((page - 1) * page_size).limit(page_size).all()

def get_unread_count(db: Session, user_id: int) -> int:
    return db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        Notification.is_read == False
    ).scalar() or 0

def mark_as_read(db: Session, user_id: int, notification_id: int) -> Optional[Notification]:
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id
    ).first()
    if notification and not notification.is_read:
        notification.is_read = True
        notification.read_at = utc_now()
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    return notification

def mark_all_as_read(db: Session, user_id: int):
    try:
        db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False
        ).update({"is_read": True, "read_at": utc_now()}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
