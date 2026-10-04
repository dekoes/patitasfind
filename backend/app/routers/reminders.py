from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user
from app.database import get_db
from app.models import Match, Reminder, User
from app.schemas import ReminderCreate, ReminderOut

router = APIRouter(tags=["reminders"])


@router.post("/reminders", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
def create_reminder(
    payload: ReminderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match = db.query(Match).filter(Match.id == payload.match_id).first()
    if not match:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos esa solicitud de adopción.")
    if match.user_id != current_user.id and match.dog.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes crear recordatorios para esta adopción.",
        )

    reminder = Reminder(
        user_id=current_user.id,
        match_id=payload.match_id,
        title=payload.title,
        due_date=payload.due_date,
        type=payload.type,
        is_completed=False,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


@router.get("/reminders", response_model=list[ReminderOut])
def list_my_reminders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Reminder)
        .filter(Reminder.user_id == current_user.id)
        .order_by(Reminder.due_date.asc())
        .all()
    )


@router.patch("/reminders/{id}/complete", response_model=ReminderOut)
def complete_reminder(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reminder = db.query(Reminder).filter(Reminder.id == id).first()
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese recordatorio.")
    if reminder.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este recordatorio.")

    reminder.is_completed = True
    db.commit()
    db.refresh(reminder)
    return reminder
