from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdoptionApplication, Dog, Donation, Match, PointLog, Product, Refuge, User
from app.schemas import (
    DogOut, DonationCheckoutOut, PointLogOut, ProductOut, RefugeAction, RefugeCreate, RefugeOut, RefugeStats,
)
from app.services.payment_flow import create_donation_checkout

router = APIRouter(tags=["refuges"])


class DonationPayload(BaseModel):
    amount: Decimal


def _my_refuge(db: Session, user: User) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == user.id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="Todavía no tienes un refugio registrado.")
    return refuge


@router.post("/refuges/register", response_model=RefugeOut, status_code=status.HTTP_201_CREATED)
def register_refuge(payload: RefugeCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.query(Refuge).filter(Refuge.user_id == current_user.id).first():
        raise HTTPException(status_code=400, detail="Ya tienes un refugio registrado.")
    refuge = Refuge(
        user_id=current_user.id, name=payload.name, description=payload.description, city=payload.city,
        country=payload.country, documents=payload.documents or [], status="pending",
    )
    db.add(refuge)
    if current_user.role not in ("admin", "superadmin"):
        current_user.role = "refuge"
    db.commit()
    db.refresh(refuge)
    return refuge


@router.get("/refuges", response_model=list[RefugeOut])
def list_refuges(city: str | None = Query(None), country: str | None = Query(None), db: Session = Depends(get_db)):
    query = db.query(Refuge).filter(Refuge.status == "approved")
    if city:
        query = query.filter(Refuge.city.ilike(f"%{city}%"))
    if country:
        query = query.filter(Refuge.country.ilike(f"%{country}%"))
    return query.order_by(Refuge.points.desc(), Refuge.adopted_count.desc()).all()


@router.get("/refuges/me", response_model=RefugeOut)
def get_my_refuge(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _my_refuge(db, current_user)


@router.get("/refuges/me/products", response_model=list[ProductOut])
def my_refuge_products(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = _my_refuge(db, current_user)
    return db.query(Product).filter(Product.refuge_id == refuge.id).order_by(Product.created_at.desc()).all()


@router.get("/refuges/me/stats", response_model=RefugeStats)
def my_refuge_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = _my_refuge(db, current_user)
    rows = db.query(Dog.status, func.count(Dog.id)).filter(Dog.owner_id == refuge.user_id).group_by(Dog.status).all()
    by_status = {s: 0 for s in ("available", "in_process", "adopted", "in_foster", "unavailable")}
    by_status.update({s: n for s, n in rows})
    owned = db.query(Dog.id).filter(Dog.owner_id == refuge.user_id)
    pending = (
        db.query(func.count(AdoptionApplication.id))
        .join(Match, Match.id == AdoptionApplication.match_id)
        .filter(Match.dog_id.in_(owned), AdoptionApplication.status == "pending", Match.status == "pending_application")
        .scalar()
    )
    total, count = (
        db.query(func.coalesce(func.sum(Donation.amount), 0), func.count(Donation.id))
        .filter(Donation.refuge_id == refuge.id, Donation.status == "approved")
        .one()
    )
    return {
        "refuge": refuge,
        "dogs_by_status": by_status,
        "total_dogs": sum(by_status.values()),
        "pending_applications": pending or 0,
        "donations_total": Decimal(total or 0),
        "donations_count": count or 0,
    }


@router.get("/refuges/ranking", response_model=list[RefugeOut])
def ranking(city: str | None = Query(None), country: str | None = Query(None), db: Session = Depends(get_db)):
    return list_refuges(city, country, db)


def _require_approved_refuge(refuge_id: int, current_user: User, db: Session) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.id == refuge_id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    if refuge.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el responsable del refugio puede hacer esto.")
    if refuge.status != "approved":
        raise HTTPException(status_code=403, detail="Tu refugio todavía no está aprobado.")
    return refuge


def _log_points(db: Session, refuge: Refuge, action: str, points: int, description: str | None):
    db.add(PointLog(refuge_id=refuge.id, action=action, points=points, description=description))


@router.post("/refuges/{id}/rescue", response_model=RefugeOut)
def rescue_dog(id: int, payload: RefugeAction | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = _require_approved_refuge(id, current_user, db)
    refuge.rescued_count += 1
    refuge.points += 5
    _log_points(db, refuge, "rescue", 5, payload.description if payload else None)
    db.commit()
    db.refresh(refuge)
    return refuge


@router.post("/refuges/{id}/adopt", response_model=RefugeOut)
def adopt_dog(id: int, payload: RefugeAction | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = _require_approved_refuge(id, current_user, db)
    refuge.adopted_count += 1
    refuge.points += 5
    _log_points(db, refuge, "adopted_to_home", 5, payload.description if payload else None)
    db.commit()
    db.refresh(refuge)
    return refuge


@router.post("/refuges/{id}/foster", response_model=RefugeOut)
def foster_dog(id: int, payload: RefugeAction | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = _require_approved_refuge(id, current_user, db)
    refuge.foster_count += 1
    refuge.points += 3
    _log_points(db, refuge, "foster_home", 3, payload.description if payload else None)
    db.commit()
    db.refresh(refuge)
    return refuge


@router.get("/refuges/{id}/points", response_model=list[PointLogOut])
def list_point_logs(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = db.query(Refuge).filter(Refuge.id == id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    if refuge.user_id != current_user.id and current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="No tienes acceso a este historial.")
    return db.query(PointLog).filter(PointLog.refuge_id == id).order_by(PointLog.created_at.desc()).all()


@router.get("/refuges/{id}/dogs", response_model=list[DogOut])
def refuge_dogs(id: int, status_filter: str | None = Query("available", alias="status"), db: Session = Depends(get_db)):
    refuge = db.query(Refuge).filter(Refuge.id == id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    q = db.query(Dog).options(joinedload(Dog.owner)).filter(Dog.owner_id == refuge.user_id)
    if status_filter and status_filter != "all":
        q = q.filter(Dog.status == status_filter)
    return q.order_by(Dog.created_at.desc()).all()


@router.get("/refuges/{id}", response_model=RefugeOut)
def get_refuge(id: int, db: Session = Depends(get_db)):
    refuge = db.query(Refuge).filter(Refuge.id == id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    return refuge


@router.post("/refuges/{id}/donate", response_model=DonationCheckoutOut)
def donate_to_refuge(id: int, payload: DonationPayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Compatibilidad: usa el mismo flujo de Mercado Pago que POST /payments/donations."""
    return create_donation_checkout(db, current_user, id, payload.amount)
