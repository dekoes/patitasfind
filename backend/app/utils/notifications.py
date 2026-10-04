from sqlalchemy.orm import Session

from app.models import Notification


def create_notification(
    db: Session,
    user_id: int,
    type: str,
    title: str,
    body: str,
    data: dict | None = None,
    commit: bool = True,
) -> Notification:
    notification = Notification(user_id=user_id, type=type, title=title, body=body, data=data)
    db.add(notification)
    if commit:
        db.commit()
        db.refresh(notification)
    return notification
