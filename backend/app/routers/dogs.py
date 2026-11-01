from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import cache
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, get_optional_user, get_verified_user
from app.models import Dog, DogPass, FosterHome, Match, User
from app.schemas import DogCreate, DogOut, DogPrivateOut, DogUpdate, DogUpdateStatus
from app.services import privacy, reglas
from app.services.background import dispatch
from app.services.geo import apply_distance, distance_to, nearest

router = APIRouter(tags=["dogs"])
CACHE_NS = "dogs"  # listados públicos en caché; se invalidan solos al cambiar un perro (app/cache.py)

VALID_STATUSES = {"available", "adopted", "in_foster", "unavailable", "in_process"}
# Textos que se revisan contra cobros, venta y rifas (contrato L-adopcion; services/reglas.py)
TEXT_FIELDS = ("name", "breed", "color", "description")


def _apply_adoption_rules(db: Session, dog: Dog, user: User, data: dict, creating: bool) -> None:
    """Perro encontrado: lista de revisión y resguardo; textos con cobros o rifas: retención para revisión."""
    reglas.apply_found_fields(db, dog, data, user, creating)
    if reglas.found_hold_active(dog, db) and dog.status == "available":
        dog.status = "unavailable"  # en resguardo: no aparece en adopción hasta cumplir el plazo y la lista
    if creating or any(f in data for f in TEXT_FIELDS):
        reason, terms = reglas.adoption_terms(*reglas.dog_texts(dog))
        reglas.check_hold(db, "dog", dog, reason, terms, force=creating)


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


@router.post("/dogs", response_model=DogPrivateOut, status_code=status.HTTP_201_CREATED)
def create_dog(payload: DogCreate, background_tasks: BackgroundTasks, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Escribe el nombre del perrito.")
    data = payload.model_dump()
    data["photos"] = data.get("photos") or []
    found = {k: data.pop(k) for k in ("found_report_id", "was_found", "microchip_checked", "microchip_result",
                                      "authority_notified", "authority_notice")}
    dog = Dog(owner_id=current_user.id, **data)
    db.add(dog)
    db.flush()
    _apply_adoption_rules(db, dog, current_user, {**found, **data}, creating=True)
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
        .filter(Dog.status == "available", Dog.owner_id != current_user.id, ~Dog.id.in_(liked), ~Dog.id.in_(passed),
                Dog.is_hidden == False)  # noqa: E712
    )
    if size:
        query = query.filter(Dog.size.ilike(f"%{size}%"))
    if breed:
        query = query.filter(Dog.breed.ilike(f"%{breed}%"))
    if city and (lat is None or lon is None):
        query = query.filter(Dog.city.ilike(f"%{city}%"))
    return privacy.coarsen_distances(apply_distance(query, Dog, None, lat, lon, radius_km, skip, limit), lat, lon)


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


@router.get("/dogs/me", response_model=list[DogPrivateOut])
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
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    key = None
    if viewer is None:
        # Sin sesión la respuesta es igual para toda la zona (~1 km): se calcula desde el punto
        # aproximado y se guarda 60 s en Redis (la portada es lo más visitado en los picos)
        lat, lon = privacy.coarse(lat), privacy.coarse(lon)
        key = cache.make_key(CACHE_NS, view="featured", lat=lat, lon=lon, radius_km=radius_km, limit=limit,
                             city=(city or "").strip().lower() if lat is None or lon is None else None)
        hit = cache.get(key)
        if isinstance(hit, list):
            return JSONResponse(hit)
    query = db.query(Dog).options(joinedload(Dog.owner)).filter(Dog.status == "available", Dog.is_hidden == False)  # noqa: E712
    if viewer is not None:
        # Con sesión no se muestran los que ya le gustaron o descartó (no se guarda en caché)
        liked = db.query(Match.dog_id).filter(Match.user_id == viewer.id)
        passed = db.query(DogPass.dog_id).filter(DogPass.user_id == viewer.id)
        query = query.filter(~Dog.id.in_(liked), ~Dog.id.in_(passed))
    if city and (lat is None or lon is None):
        query = query.filter(Dog.city.ilike(f"%{city}%"))
    items = privacy.coarsen_distances(apply_distance(query, Dog, None, lat, lon, radius_km, 0, limit), lat, lon)
    if key:
        cache.set(key, [DogOut.model_validate(d).model_dump(mode="json") for d in items], ttl=settings.list_cache_ttl_seconds)
    return items


@router.get("/dogs/nearby", response_model=list[DogOut])
def nearby_dogs(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(30, gt=0, le=500),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Dog).options(joinedload(Dog.owner)).filter(Dog.status == "available", Dog.is_hidden == False)  # noqa: E712
    # Radio, orden por cercanía y paginación en Postgres
    return privacy.coarsen_distances(nearest(query, Dog, lat, lon, radius_km, skip, limit), lat, lon)


@router.get("/dogs/{id}", response_model=DogOut)
def get_dog(
    id: int,
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    dog = _get_dog(db, id)
    if privacy.is_owner_or_admin(viewer, dog.owner_id):
        # El dueño y los admins ven las coordenadas exactas
        dog.distance_km = distance_to(dog, lat, lon)
        return JSONResponse(jsonable_encoder(DogPrivateOut.model_validate(dog)))
    if (dog.owner and dog.owner.deleted_at) or dog.is_hidden:  # oculto por moderación: solo dueño y admins
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese perrito.")
    if reglas.found_hold_active(dog, db):  # perro encontrado en resguardo: todavía no se ofrece en adopción
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ese perrito.")
    dog.distance_km = privacy.public_distance(dog, lat, lon)
    return dog


@router.patch("/dogs/{id}", response_model=DogPrivateOut)
def update_dog(id: int, payload: DogUpdate, background_tasks: BackgroundTasks, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    dog = _owned_dog(db, id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and not (data["name"] or "").strip():
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío.")
    photos_changed = "photos" in data and data["photos"] != dog.photos
    found = {k: data.pop(k) for k in ("found_report_id", "was_found", "microchip_checked", "microchip_result",
                                      "authority_notified", "authority_notice") if k in data}
    for field, value in data.items():
        if field == "photos":
            value = value or []
        setattr(dog, field, value)
    _apply_adoption_rules(db, dog, current_user, {**found, **data}, creating=False)
    db.commit()
    db.refresh(dog)
    if photos_changed and dog.photos:
        dispatch("app.tasks.images.enrich_dog", dog.id, background_tasks=background_tasks)
    return dog


@router.patch("/dogs/{id}/status", response_model=DogPrivateOut)
def update_dog_status(id: int, payload: DogUpdateStatus, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Usa: {', '.join(sorted(VALID_STATUSES))}.")
    dog = _owned_dog(db, id, current_user)
    if payload.status == "available" and reglas.found_hold_active(dog, db):
        # Perro encontrado: no se ofrece en adopción antes del plazo, sin microchip revisado ni aviso a la autoridad
        raise HTTPException(status_code=409, detail=reglas.found_hold_info(db, dog)["message"])
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


@router.post("/dogs/{id}/assign-foster/{foster_home_id}", response_model=DogPrivateOut)
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
