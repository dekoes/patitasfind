import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdoptionApplication, Dog, Match, PointLog, Refuge, Reminder, User
from app.schemas import AdoptionApplicationCreate, AdoptionApplicationOut, ConversationOut, MatchOut
from app.services.chat import get_or_create_match_conversation
from app.utils.notifications import create_notification

router = APIRouter(tags=["matches"])

POST_ADOPTION_REMINDERS = [
    ("Visita al veterinario", 7, "vet"),
    ("Seguimiento de adaptación", 30, "follow_up"),
    ("Refuerzo de vacunas", 90, "vaccine"),
]


def _get_match(db: Session, match_id: int) -> Match:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos esa solicitud.")
    return match


def _require_owner(match: Match, user: User):
    if match.dog.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo quien publicó al perrito puede hacer esto.")


@router.post("/dogs/{dog_id}/like", response_model=MatchOut)
def like_dog(dog_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dog = db.query(Dog).filter(Dog.id == dog_id).first()
    if not dog:
        raise HTTPException(status_code=404, detail="No encontramos ese perrito.")
    if dog.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes dar like a tu propio perrito.")
    existing = db.query(Match).filter(Match.user_id == current_user.id, Match.dog_id == dog_id).first()
    if existing:
        return existing
    match = Match(user_id=current_user.id, dog_id=dog_id, status="pending_application")
    db.add(match)
    db.commit()
    db.refresh(match)
    create_notification(
        db, user_id=dog.owner_id, type="new_like", title="¡Nuevo like! 💛",
        body=f"A {current_user.full_name} le encantó {dog.name}.", data={"match_id": match.id, "dog_id": dog.id},
    )
    return match


@router.get("/matches", response_model=list[MatchOut])
def list_matches(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned = db.query(Dog.id).filter(Dog.owner_id == current_user.id)
    return (
        db.query(Match)
        .filter((Match.user_id == current_user.id) | (Match.dog_id.in_(owned)))
        .order_by(Match.created_at.desc())
        .all()
    )


@router.get("/matches/{match_id}", response_model=MatchOut)
def get_match(match_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    if match.user_id != current_user.id and match.dog.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta solicitud.")
    return match


@router.post("/matches/{match_id}/apply", response_model=AdoptionApplicationOut)
def submit_application(match_id: int, payload: AdoptionApplicationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    if match.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo quien solicitó la adopción puede enviar el cuestionario.")
    if match.status in ("completed", "rejected"):
        raise HTTPException(status_code=400, detail="Esta solicitud ya está cerrada.")
    application = match.application
    if application:
        application.answers = payload.answers
        application.status = "pending"
    else:
        application = AdoptionApplication(match_id=match.id, answers=payload.answers)
        db.add(application)
    if match.status != "approved":
        match.status = "pending_application"
    db.commit()
    db.refresh(application)
    create_notification(
        db, user_id=match.dog.owner_id, type="new_application", title="Nueva solicitud de adopción",
        body=f"{current_user.full_name} envió el cuestionario para {match.dog.name}.",
        data={"match_id": match.id, "dog_id": match.dog_id},
    )
    return application


@router.get("/matches/{match_id}/application", response_model=AdoptionApplicationOut)
def get_application(match_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    if match.user_id != current_user.id and match.dog.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta solicitud.")
    if not match.application:
        raise HTTPException(status_code=404, detail="Todavía no hay cuestionario para esta solicitud.")
    return match.application


@router.post("/matches/{match_id}/approve", response_model=ConversationOut)
def approve_match(match_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    _require_owner(match, current_user)
    if match.status in ("rejected", "completed"):
        raise HTTPException(status_code=400, detail="Esta solicitud ya está cerrada.")
    first_time = match.status != "approved"
    match.status = "approved"
    if match.application:
        match.application.status = "approved"
    match.dog.status = "in_process"
    conversation = get_or_create_match_conversation(db, match)
    if first_time:
        now = datetime.datetime.utcnow()
        for title, days, rtype in POST_ADOPTION_REMINDERS:
            db.add(Reminder(user_id=match.user_id, match_id=match.id, title=title,
                            due_date=now + datetime.timedelta(days=days), type=rtype))
    db.commit()
    db.refresh(conversation)
    if first_time:
        create_notification(
            db, user_id=match.user_id, type="match_approved", title="¡Solicitud aprobada! 🎉",
            body=f"{current_user.full_name} aprobó tu solicitud para {match.dog.name}. Ya pueden platicar por el chat.",
            data={"match_id": match.id, "conversation_id": conversation.id},
        )
    return conversation


@router.post("/matches/{match_id}/complete", response_model=MatchOut)
def complete_match(match_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    _require_owner(match, current_user)
    if match.status == "completed":
        return match
    if match.status != "approved":
        raise HTTPException(status_code=400, detail="Primero aprueba la solicitud antes de completar la adopción.")
    match.status = "completed"
    match.dog.status = "adopted"
    refuge = db.query(Refuge).filter(Refuge.user_id == current_user.id, Refuge.status == "approved").first()
    if refuge:
        refuge.adopted_count += 1
        refuge.points += 5
        db.add(PointLog(refuge_id=refuge.id, action="adopted_to_home", points=5,
                        description=f"{match.dog.name} fue adoptado por {match.user.full_name}"))
    db.commit()
    db.refresh(match)
    create_notification(
        db, user_id=match.user_id, type="adoption_completed", title="¡Felicidades! 🐶🎉",
        body=f"¡{match.dog.name} ya es oficialmente parte de tu familia! Gracias por adoptar. Te recordaremos sus citas importantes.",
        data={"match_id": match.id, "dog_id": match.dog_id},
    )
    return match


@router.post("/matches/{match_id}/reject", response_model=MatchOut)
def reject_match(match_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    _require_owner(match, current_user)
    match.status = "rejected"
    if match.application:
        match.application.status = "rejected"
    if match.dog.status == "in_process":
        match.dog.status = "available"
    db.commit()
    db.refresh(match)
    create_notification(
        db, user_id=match.user_id, type="match_rejected", title="Solicitud no aprobada",
        body=f"{current_user.full_name} no aprobó tu solicitud para {match.dog.name}. ¡Hay muchos perritos esperándote!",
        data={"match_id": match.id},
    )
    return match
