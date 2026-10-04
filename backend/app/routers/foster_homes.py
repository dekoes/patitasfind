from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_verified_user
from app.database import get_db
from app.models import FosterHome, User
from app.schemas import FosterHomeCreate, FosterHomeOut

router = APIRouter(tags=["foster_homes"])


@router.post("/foster-homes/register", response_model=FosterHomeOut, status_code=status.HTTP_201_CREATED)
def register_foster_home(
    payload: FosterHomeCreate,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    existing = db.query(FosterHome).filter(FosterHome.user_id == current_user.id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya tienes una casa de paso registrada.",
        )

    foster_home = FosterHome(
        user_id=current_user.id,
        description=payload.description,
        city=payload.city,
        country=payload.country,
        capacity=payload.capacity or 1,
        status="pending",
    )
    db.add(foster_home)

    current_user.role = "foster"
    db.commit()
    db.refresh(foster_home)
    return foster_home


@router.get("/foster-homes", response_model=list[FosterHomeOut])
def list_foster_homes(
    city: str | None = Query(None),
    country: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(FosterHome).filter(FosterHome.status == "approved")
    if city:
        query = query.filter(FosterHome.city.ilike(f"%{city}%"))
    if country:
        query = query.filter(FosterHome.country.ilike(f"%{country}%"))
    return query.order_by(FosterHome.created_at.desc()).all()


@router.get("/foster-homes/me", response_model=FosterHomeOut)
def get_my_foster_home(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    foster_home = db.query(FosterHome).filter(FosterHome.user_id == current_user.id).first()
    if not foster_home:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todavía no tienes una casa de paso registrada.")
    return foster_home
