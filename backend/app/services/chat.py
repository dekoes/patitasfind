"""Lógica compartida del chat (REST y WebSocket)."""
import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Conversation, LostReport, Match, Message, Notification, User
from app.utils.notifications import create_notification


def get_or_create_match_conversation(db: Session, match: Match) -> Conversation:
    conv = match.conversation
    if not conv:
        conv = Conversation(match_id=match.id, user_a_id=match.user_id, user_b_id=match.dog.owner_id)
        db.add(conv)
        db.flush()
    elif not conv.user_a_id:
        conv.user_a_id, conv.user_b_id = match.user_id, match.dog.owner_id
    return conv


def get_or_create_report_conversation(db: Session, report: LostReport, user: User) -> Conversation:
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.lost_report_id == report.id,
            ((Conversation.user_a_id == user.id) & (Conversation.user_b_id == report.reporter_id))
            | ((Conversation.user_a_id == report.reporter_id) & (Conversation.user_b_id == user.id)),
        )
        .first()
    )
    created = False
    if not conv:
        conv = Conversation(lost_report_id=report.id, user_a_id=user.id, user_b_id=report.reporter_id)
        db.add(conv)
        db.flush()
        created = True
    return conv, created


def conversation_title_photo(conv: Conversation) -> tuple[str, str | None]:
    if conv.match and conv.match.dog:
        dog = conv.match.dog
        return dog.name, (dog.photos or [None])[0]
    if conv.lost_report:
        lr = conv.lost_report
        return f"Reporte: {lr.dog_name}", (lr.photos or [None])[0]
    return "Conversación", None


def summarize(db: Session, conv: Conversation, user: User) -> dict:
    title, photo = conversation_title_photo(conv)
    other_id = conv.other_user_id(user.id)
    other = db.query(User).filter(User.id == other_id).first() if other_id else None
    last = (
        db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.id.desc()).first()
    )
    unread = (
        db.query(func.count(Message.id))
        .filter(Message.conversation_id == conv.id, Message.sender_id != user.id, Message.is_read == False)  # noqa: E712
        .scalar()
    )
    return {
        "id": conv.id,
        "match_id": conv.match_id,
        "lost_report_id": conv.lost_report_id,
        "title": title,
        "photo": photo,
        "other_user": {"id": other.id, "full_name": other.full_name, "avatar_url": other.avatar_url} if other else None,
        "last_message": {"content": last.content, "created_at": last.created_at, "sender_id": last.sender_id} if last else None,
        "unread_count": unread or 0,
        "created_at": conv.created_at,
    }


def message_event(msg: Message) -> dict:
    return {
        "type": "message",
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender_id": msg.sender_id,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
        "is_read": msg.is_read,
    }


def create_message(db: Session, conv: Conversation, sender: User, content: str) -> Message:
    msg = Message(conversation_id=conv.id, sender_id=sender.id, content=content)
    db.add(msg)
    conv.last_message_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(msg)
    _notify_other(db, conv, sender, content)
    return msg


def _notify_other(db: Session, conv: Conversation, sender: User, content: str):
    other_id = conv.other_user_id(sender.id)
    if not other_id:
        return
    pending = (
        db.query(Notification)
        .filter(Notification.user_id == other_id, Notification.type == "new_message", Notification.is_read == False)  # noqa: E712
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )
    if any((n.data or {}).get("conversation_id") == conv.id for n in pending):
        return  # ya tiene un aviso sin leer de esta conversación: no hacemos spam
    title, _ = conversation_title_photo(conv)
    preview = content if len(content) <= 80 else content[:77] + "..."
    create_notification(
        db, user_id=other_id, type="new_message", title=f"Nuevo mensaje de {sender.full_name}",
        body=f"{title}: {preview}", data={"conversation_id": conv.id},
    )


def mark_read(db: Session, conv: Conversation, user: User) -> int:
    updated = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id, Message.sender_id != user.id, Message.is_read == False)  # noqa: E712
        .update({Message.is_read: True}, synchronize_session=False)
    )
    # También se marcan como leídos los avisos de mensajes de esta conversación
    for n in db.query(Notification).filter(
        Notification.user_id == user.id, Notification.type == "new_message", Notification.is_read == False  # noqa: E712
    ).all():
        if (n.data or {}).get("conversation_id") == conv.id:
            n.is_read = True
    db.commit()
    return updated
