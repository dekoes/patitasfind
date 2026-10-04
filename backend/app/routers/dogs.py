from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user, get_verified_user
from app.models import Dog, DogPass, FosterHome, Match, User
from app.schemas import DogCreate, DogOut, DogUpdate, DogUpdateStatus
from app.services.background import dispatch
from app.services.geo import apply_distance, distance_to

router = APIRouter(tags=["dogs"])

VALID_STATUSES = {"available", "adopted", "in_foster", "unavailable", "in_process"}


def _get_dog(db: Session, dog_id: int) -> Dog:
    dog = db.query(Dog).options(joinedload(Dog.owner)).filter(Dog.id == dog_id).first()
    if not dog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese perrito.")
    return dog


def _owned_dog(db: Session, dog_id: int, user: User) -> Dog:
    dog = _get_dog(db, dog_id)
    if dog.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo quien publicó a este perrito puede modificarlo.")
    return dog


@router.post("/dogs", response_model=DogOut, status_code=status.HTTP_201_CREATED)
def create_dog(payload: DogCreate, background_tasks: BackgroundTasks, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Escribe el nombre del perrito.")
    data = payload.model_dump()
    data["photos"] = data.get("photos") or []
    dog = Dog(owner_id=current_user.id, **data)
    db.add(dog)
    db.commit()
    db.refresh(dog)
    if dog.photos:
        dispatch("app.tasks.images.enrich_dog", dog.id, background_tasks=background_tasks)
    return dog


@router.get("/dogs/discover", response_model=list[DogOut])
def discover_dogs(
    city: str | None = Query(None),
    size: str | None = Query(None),
    breed: str | None = Query(None),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(50, gt=0, le=2000),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    liked = db.query(Match.dog_id).filter(Match.user_id == current_user.id)
    passed = db.query(DogPass.dog_id).filter(DogPass.user_id == current_user.id)
    query = (
        db.query(Dog)
        .options(joinedload(Dog.owner))
        .filter(Dog.status == "available", Dog.owner_id != current_user.id, ~Dog.id.in_(liked), ~Dog.id.in_(passed))
    )
    if size:
        query = query.filter(Dog.size.ilike(f"%{size}%"))
    if breed:
        query = query.filter(Dog.breed.ilike(f"%{breed}%"))
    if city and (lat is None or lon is None):
        query = query.filter(Dog.city.ilike(f"%{city}%"))
    return apply_distance(query, Dog, None, lat, lon, radius_km, skip, limit)


@router.post("/dogs/{dog_id}/pass", status_code=status.HTTP_204_NO_CONTENT)
def pass_dog(dog_id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    _get_dog(db, dog_id)
    exists = db.query(DogPass).filter(DogPass.user_id == current_user.id, DogPass.dog_id == dog_id).first()
    if not exists:
        db.add(DogPass(user_id=current_user.id, dog_id=dog_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dogs/me", response_model=list[DogOut])
def list_my_dogs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Dog).options(joinedload(Dog.owner)).filter(Dog.owner_id == current_user.id)
        .order_by(Dog.created_at.desc()).all()
    )


@router.get("/dogs/featured", response_model=list[DogOut])
def featured_dogs(
    city: str | None = Query(None),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(50, gt=0, le=2000),
    limit: int = Query(6, ge=1, le=20),
    db: Session = Depends(get_db),
):
    query = db.query(Dog).options(joinedload(Dog.owner)).filter(Dog.status == "available")
    if city and (lat is None or lon is None):
        query = query.filter(Dog.city.ilike(f"%{city}%"))
    return apply_distance(query, Dog, None, lat, lon, radius_km, 0, limit)


@router.get("/dogs/nearby", response_model=list[DogOut])
def nearby_dogs(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(30, gt=0, le=500),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    from app.services.geo import bounding_box, haversine_km

    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
    dogs = (
        db.query(Dog).options(joinedload(Dog.owner))
        .filter(
            Dog.status == "available", Dog.latitude.between(min_lat, max_lat), Dog.longitude.between(min_lon, max_lon)
        )
        .limit(2000).all()
    )
    result = []
    for d in dogs:
        dist = haversine_km(lat, lon, d.latitude, d.longitude)
        if dist <= radius_km:
            d.distance_km = round(dist, 2)
            result.append(d)
    result.sort(key=lambda d: d.distance_km)
    return result[:limit]


@router.get("/dogs/{id}", response_model=DogOut)
def get_dog(
    id: int,
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    db: Session = Depends(get_db),
):
    dog = _get_dog(db, id)
    dog.distance_km = distance_to(dog, lat, lon)
    return dog


@router.patch("/dogs/{id}", response_model=DogOut)
def update_dog(id: int, payload: DogUpdate, background_tasks: BackgroundTasks, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    dog = _owned_dog(db, id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and not (data["name"] or "").strip():
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")
    photos_changed = "photos" in data and data["photos"] != dog.photos
    for field, value in data.items():
        if field == "photos":
            value = value or []
        setattr(dog, field, value)
    db.commit()
    db.refresh(dog)
    if photos_changed and dog.photos:
        dispatch("app.tasks.images.enrich_dog", dog.id, background_tasks=background_tasks)
    return dog


@router.patch("/dogs/{id}/status", response_model=DogOut)
def update_dog_status(id: int, payload: DogUpdateStatus, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Usa: {', '.join(sorted(VALID_STATUSES))}.")
    dog = _owned_dog(db, id, current_user)
    dog.status = payload.status
    db.commit()
    db.refresh(dog)
    return dog


@router.delete("/dogs/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dog(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dog = _owned_dog(db, id, current_user)
    dog.status = "unavailable"
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/dogs/{id}/assign-foster/{foster_home_id}", response_model=DogOut)
def assign_foster_home(id: int, foster_home_id: int, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    dog = _owned_dog(db, id, current_user)
    foster_home = db.query(FosterHome).filter(FosterHome.id == foster_home_id).first()
    if not foster_home:
        raise HTTPException(status_code=404, detail="No encontramos esa casa de paso.")
    if foster_home.status != "approved":
        raise HTTPException(status_code=400, detail="Esa casa de paso todavía no está aprobada.")
    dog.status = "in_foster"
    db.commit()
    db.refresh(dog)
    return dog
