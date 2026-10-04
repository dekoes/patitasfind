import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import (
    PHONE_VERIFICATION_CODE, PHONE_VERIFICATION_MESSAGE, _user_from_token, get_current_user, get_verified_user,
)
from app.models import Conversation, Message, User
from app.schemas import ConversationSummary, MessageCreate, MessageOut
from app.services import chat
from app.services.realtime import hub

router = APIRouter(tags=["messages"])
logger = logging.getLogger(__name__)
MAX_MESSAGE = 4000


def _get_conversation(db: Session, conversation_id: int, user: User) -> Conversation:
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos esa conversación.")
    if not conv.has_participant(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No participas en esta conversación.")
    return conv


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convs = (
        db.query(Conversation)
        .filter((Conversation.user_a_id == current_user.id) | (Conversation.user_b_id == current_user.id))
        .order_by(func.coalesce(Conversation.last_message_at, Conversation.created_at).desc())
        .all()
    )
    summaries = [chat.summarize(db, c, current_user) for c in convs]
    summaries.sort(key=lambda s: (s["last_message"]["created_at"] if s["last_message"] else s["created_at"]), reverse=True)
    return summaries


@router.get("/conversations/{conversation_id}", response_model=ConversationSummary)
def get_conversation(conversation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return chat.summarize(db, _get_conversation(db, conversation_id, current_user), current_user)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(
    conversation_id: int,
    before_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_conversation(db, conversation_id, current_user)
    q = db.query(Message).filter(Message.conversation_id == conversation_id)
    if before_id:
        q = q.filter(Message.id < before_id)
    return q.order_by(Message.id.desc()).offset(skip).limit(limit).all()


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def post_message(conversation_id: int, payload: MessageCreate, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    conv = _get_conversation(db, conversation_id, current_user)
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="El mensaje está vacío.")
    if len(content) > MAX_MESSAGE:
        raise HTTPException(status_code=400, detail=f"El mensaje es demasiado largo (máximo {MAX_MESSAGE} caracteres).")
    msg = chat.create_message(db, conv, current_user, content)
    hub.publish_sync(conv.id, chat.message_event(msg))
    return msg


@router.patch("/conversations/{conversation_id}/read")
def mark_conversation_read(conversation_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = _get_conversation(db, conversation_id, current_user)
    return {"updated": chat.mark_read(db, conv, current_user)}


# --------------------------------------------------------------------------- WebSocket
def _ws_authorize(token: str, conversation_id: int) -> tuple[int, bool] | None:
    db = SessionLocal()
    try:
        user = _user_from_token(token, db)
        if not user:
            return None
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv or not conv.has_participant(user.id):
            return None
        return user.id, not user.phone_verification_required
    finally:
        db.close()


def _ws_save_message(conversation_id: int, user_id: int, content: str) -> dict | None:
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if not conv or not user or not conv.has_participant(user_id):
            return None
        msg = chat.create_message(db, conv, user, content)
        return chat.message_event(msg)
    finally:
        db.close()


@router.websocket("/ws/chat/{conversation_id}")
async def chat_websocket(websocket: WebSocket, conversation_id: int):
    token = websocket.query_params.get("token")
    auth = await run_in_threadpool(_ws_authorize, token, conversation_id) if token else None
    if not auth:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id, can_send = auth
    await hub.prepare()
    await websocket.accept()
    await hub.connect(conversation_id, websocket)
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except (ValueError, KeyError):
                continue  # JSON inválido: se ignora
            if not isinstance(data, dict):
                continue
            kind = data.get("type", "message")
            if kind == "typing":
                await hub.publish(conversation_id, {"type": "typing", "sender_id": user_id, "conversation_id": conversation_id},
                                  exclude=websocket)
                continue
            if kind != "message":
                continue
            content = str(data.get("content") or "").strip()
            if not content:
                continue
            if not can_send:
                await websocket.send_json({"type": "error", "code": PHONE_VERIFICATION_CODE,
                                           "detail": PHONE_VERIFICATION_MESSAGE})
                continue
            if len(content) > MAX_MESSAGE:
                await websocket.send_json({"type": "error", "detail": "El mensaje es demasiado largo."})
                continue
            event = await run_in_threadpool(_ws_save_message, conversation_id, user_id, content)
            if event:
                await hub.publish(conversation_id, event)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Error en el WebSocket de la conversación %s", conversation_id)
    finally:
        hub.disconnect(conversation_id, websocket)
