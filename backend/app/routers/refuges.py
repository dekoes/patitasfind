import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, get_optional_user, get_verified_user, require_admin
from app.models import AdoptionApplication, Dog, Donation, Match, PointLog, Product, Refuge, RefugeFiscalProfile, User
from app.routers.documents import is_document_id, legacy_name, own_private_document
from app.schemas import (
    REGIMENES_FISICA, REGIMENES_MORAL, DogOut, DonationCheckoutOut, PaymentConnectOut, PointLogOut, ProductOut,
    RefugeAction, RefugeCreate, RefugeFiscalOut, RefugeFiscalUpdate, RefugeOut, RefugePrivateOut, RefugeStats,
    SellerPaymentsStatusOut, rfc_person_type,
)
from app.services import legal_acceptance, mercadopago_oauth
from app.services.audit import record_admin_action
from app.services.payment_flow import create_donation_checkout
from app.services.privacy import is_owner_or_admin

router = APIRouter(tags=["refuges"])

MAX_DOCUMENTS = 10
PAGE_MAX = 100


class DonationPayload(BaseModel):
    amount: Decimal
    share_name: bool = False


def _my_refuge(db: Session, user: User) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == user.id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="Todavía no tienes un refugio registrado.")
    return refuge


def _clean_documents(raw: list[str] | None, user_id: int) -> list[str]:
    """Acepta ids de POST /upload/document (o rutas antiguas /uploads/...). Nada más.

    Un id nuevo debe estar en la carpeta privada y haberlo subido la misma cuenta: las fotos públicas también se
    llaman <uuid>.jpg y, si se aceptaran, cancelar la cuenta borraría la foto de otra persona.
    """
    docs = []
    for value in raw or []:
        value = (value or "").strip()
        if not value:
            continue
        if is_document_id(value):
            if not own_private_document(value, user_id):
                raise HTTPException(status_code=400, detail="No encontramos uno de tus documentos. Vuelve a subirlo.")
        elif not legacy_name(value):
            raise HTTPException(status_code=400, detail="Uno de los documentos no es válido. Vuelve a subirlo.")
        if value not in docs:
            docs.append(value)
    if len(docs) > MAX_DOCUMENTS:
        raise HTTPException(status_code=400, detail=f"Puedes enviar máximo {MAX_DOCUMENTS} documentos.")
    return docs


@router.post("/refuges/register", response_model=RefugePrivateOut, status_code=status.HTTP_201_CREATED)
def register_refuge(payload: RefugeCreate, request: Request, current_user: User = Depends(get_verified_user),
                    db: Session = Depends(get_db)):
    if db.query(Refuge).filter(Refuge.user_id == current_user.id).first():
        raise HTTPException(status_code=400, detail="Ya tienes un refugio registrado.")
    refuge = Refuge(
        user_id=current_user.id, name=payload.name, description=payload.description, city=payload.city,
        country=payload.country, documents=_clean_documents(payload.documents, current_user.id), status="pending",
    )
    db.add(refuge)
    db.flush()
    # Términos para Refugios + Acuerdo de datos (casilla separada): bitácora; obligatoria con LEGAL_ANNEX_REQUIRED
    legal_acceptance.accept_annex(db, current_user, "refugio", payload.accepted_annex, request,
                                  context={"refuge_id": refuge.id})
    if current_user.role not in ("admin", "superadmin"):
        current_user.role = "refuge"
    db.commit()
    db.refresh(refuge)
    return refuge


def _approved_refuges(db: Session, city: str | None, country: str | None, skip: int, limit: int):
    query = db.query(Refuge).filter(Refuge.status == "approved")
    if city:
        query = query.filter(Refuge.city.ilike(f"%{city}%"))
    if country:
        query = query.filter(Refuge.country.ilike(f"%{country}%"))
    return (
        query.order_by(Refuge.points.desc(), Refuge.adopted_count.desc(), Refuge.id)
        .offset(skip).limit(limit).all()
    )


@router.get("/refuges", response_model=list[RefugeOut])
def list_refuges(
    city: str | None = Query(None),
    country: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=PAGE_MAX),
    db: Session = Depends(get_db),
):
    return _approved_refuges(db, city, country, skip, limit)


@router.get("/refuges/me", response_model=RefugePrivateOut)
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


# --------------------------------------------------------------------------- tienda: Mercado Pago y datos fiscales
@router.get("/refuges/me/payments/connect", response_model=PaymentConnectOut)
def connect_payments(current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    """URL de autorización de Mercado Pago (OAuth) para que el refugio cobre con su propia cuenta (split)."""
    refuge = _my_refuge(db, current_user)
    if refuge.status != "approved":
        raise HTTPException(status_code=403, detail="Tu refugio todavía no está aprobado.")
    try:
        return {"url": mercadopago_oauth.authorization_url(refuge, current_user.id)}
    except mercadopago_oauth.OAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/refuges/me/payments/status", response_model=SellerPaymentsStatusOut)
def payments_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return mercadopago_oauth.status_out(_my_refuge(db, current_user))


@router.post("/refuges/me/payments/disconnect", response_model=SellerPaymentsStatusOut)
def disconnect_payments(current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    """Desvincula la cuenta de Mercado Pago: tus productos se siguen viendo pero ya no se pueden comprar."""
    refuge = _my_refuge(db, current_user)
    if refuge.payment_account:
        mercadopago_oauth.disconnect(refuge.payment_account, "Desvinculada por el refugio.")
        db.commit()
        db.refresh(refuge)
    return mercadopago_oauth.status_out(refuge)


@router.get("/refuges/me/fiscal", response_model=RefugeFiscalOut | None)
def get_fiscal_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Datos fiscales del refugio vendedor (null si aún no los registra)."""
    return _my_refuge(db, current_user).fiscal_profile


@router.patch("/refuges/me/fiscal", response_model=RefugeFiscalOut)
def update_fiscal_profile(payload: RefugeFiscalUpdate, current_user: User = Depends(get_verified_user),
                          db: Session = Depends(get_db)):
    """Alta o cambio de datos fiscales (fiscal-tienda-21). Son los del receptor de los CFDI de comisión y retenciones."""
    refuge = _my_refuge(db, current_user)
    profile = refuge.fiscal_profile
    data = {k: getattr(profile, k) for k in ("person_type", "rfc", "legal_name", "regimen_fiscal", "postal_code",
                                             "is_donataria", "csf_document_id")} if profile else {}
    data.update(payload.model_dump(exclude_unset=True))
    data["rfc"] = (data.get("rfc") or "").strip().upper().replace(" ", "").replace("-", "")
    data["legal_name"] = " ".join((data.get("legal_name") or "").upper().split())
    missing = [label for key, label in (("person_type", "tipo de persona"), ("rfc", "RFC"),
                                        ("legal_name", "nombre o razón social"), ("regimen_fiscal", "régimen fiscal"),
                                        ("postal_code", "código postal fiscal")) if not data.get(key)]
    if missing:
        raise HTTPException(status_code=400, detail="Completa tus datos fiscales: " + ", ".join(missing) + ".")
    kind = rfc_person_type(data["rfc"])
    if kind is None:
        raise HTTPException(status_code=400, detail="El RFC no es válido: 13 caracteres para persona física o 12 para "
                                                    "persona moral.")
    if kind != data["person_type"]:
        raise HTTPException(status_code=400, detail="El RFC no corresponde al tipo de persona (física: 13 caracteres; "
                                                    "moral: 12).")
    if data["regimen_fiscal"] not in (REGIMENES_FISICA if kind == "fisica" else REGIMENES_MORAL):
        raise HTTPException(status_code=400, detail="Ese régimen fiscal no aplica a tu tipo de persona. Revísalo en tu "
                                                    "Constancia de Situación Fiscal.")
    if data.get("is_donataria") and kind != "moral":
        raise HTTPException(status_code=400, detail="Solo una persona moral puede ser donataria autorizada.")
    csf = (data.get("csf_document_id") or "").strip() or None
    if csf and not own_private_document(csf, current_user.id):  # solo la carpeta privada, nunca una foto pública
        raise HTTPException(status_code=400, detail="No encontramos tu Constancia de Situación Fiscal. Vuelve a subirla.")
    data["csf_document_id"] = csf
    data["is_donataria"] = bool(data.get("is_donataria"))
    if not profile:
        profile = RefugeFiscalProfile(refuge_id=refuge.id)
        db.add(profile)
    for key, value in data.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/refuges/ranking", response_model=list[RefugeOut])
def ranking(
    city: str | None = Query(None),
    country: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=PAGE_MAX),
    db: Session = Depends(get_db),
):
    return _approved_refuges(db, city, country, skip, limit)


def _visible_refuge(db: Session, refuge_id: int, viewer: User | None) -> Refuge:
    """El público solo ve refugios aprobados; el responsable y los admins ven el suyo en cualquier estado."""
    refuge = db.query(Refuge).filter(Refuge.id == refuge_id).first()
    if not refuge or (refuge.status != "approved" and not is_owner_or_admin(viewer, refuge.user_id)):
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    return refuge


def _log_points(db: Session, refuge: Refuge, action: str, points: int, description: str | None):
    db.add(PointLog(refuge_id=refuge.id, action=action, points=points, description=description))


# Rescates, adopciones y casas de paso registrados a mano: solo los asigna un admin después de verificarlos
# (un refugio no puede sumarse puntos a sí mismo). Las adopciones completadas en la app suman solas.
MANUAL_ACTIONS = {
    "rescue": ("rescued_count", 5, "rescue"),
    "adopt": ("adopted_count", 5, "adopted_to_home"),
    "foster": ("foster_count", 3, "foster_home"),
}


def _admin_refuge_action(kind: str, refuge_id: int, payload: RefugeAction | None, admin_user: User, request: Request,
                         db: Session) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.id == refuge_id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    if refuge.status != "approved":
        raise HTTPException(status_code=400, detail="El refugio todavía no está aprobado.")
    counter, points, action = MANUAL_ACTIONS[kind]
    setattr(refuge, counter, getattr(refuge, counter) + 1)
    refuge.points += points
    description = payload.description if payload else None
    _log_points(db, refuge, action, points, description)
    record_admin_action(db, admin_user, f"refuge.{kind}", "refuge", refuge.id,
                        details={"points": points, "description": description}, request=request)
    db.commit()
    db.refresh(refuge)
    return refuge


@router.post("/refuges/{id}/rescue", response_model=RefugeOut)
def rescue_dog(id: int, request: Request, payload: RefugeAction | None = None, admin_user: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    return _admin_refuge_action("rescue", id, payload, admin_user, request, db)


@router.post("/refuges/{id}/adopt", response_model=RefugeOut)
def adopt_dog(id: int, request: Request, payload: RefugeAction | None = None, admin_user: User = Depends(require_admin),
              db: Session = Depends(get_db)):
    return _admin_refuge_action("adopt", id, payload, admin_user, request, db)


@router.post("/refuges/{id}/foster", response_model=RefugeOut)
def foster_dog(id: int, request: Request, payload: RefugeAction | None = None, admin_user: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    return _admin_refuge_action("foster", id, payload, admin_user, request, db)


@router.get("/refuges/{id}/points", response_model=list[PointLogOut])
def list_point_logs(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = db.query(Refuge).filter(Refuge.id == id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="No encontramos ese refugio.")
    if refuge.user_id != current_user.id and current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="No tienes acceso a este historial.")
    return db.query(PointLog).filter(PointLog.refuge_id == id).order_by(PointLog.created_at.desc()).all()


@router.get("/refuges/{id}/dogs", response_model=list[DogOut])
def refuge_dogs(
    id: int,
    status_filter: str | None = Query("available", alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=PAGE_MAX),
    viewer: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    refuge = _visible_refuge(db, id, viewer)
    q = db.query(Dog).options(joinedload(Dog.owner)).filter(Dog.owner_id == refuge.user_id)
    owner_view = is_owner_or_admin(viewer, refuge.user_id)
    if not owner_view:
        q = q.filter(Dog.is_hidden.is_(False))
        # Perro encontrado en resguardo: no se muestra a otras personas (igual que GET /dogs/{id}). Se descarta en SQL
        # lo que seguro sigue en resguardo y abajo se revisa el reporte ligado de los demás
        from app.services import reglas

        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=settings.found_dog_hold_days)
        q = q.filter(or_(
            and_(Dog.found_at.is_(None), Dog.found_report_id.is_(None)),
            and_(Dog.found_report_id.isnot(None), Dog.found_at <= cutoff, Dog.microchip_checked_at.isnot(None),
                 Dog.authority_notified_at.isnot(None)),
        ))
    if status_filter and status_filter != "all":
        q = q.filter(Dog.status == status_filter)
    rows = q.order_by(Dog.created_at.desc(), Dog.id.desc()).offset(skip).limit(limit).all()
    if not owner_view:
        rows = [d for d in rows if not reglas.found_hold_active(d, db)]
    return rows


@router.get("/refuges/{id}", response_model=RefugeOut)
def get_refuge(id: int, viewer: User | None = Depends(get_optional_user), db: Session = Depends(get_db)):
    return _visible_refuge(db, id, viewer)


@router.post("/refuges/{id}/donate", response_model=DonationCheckoutOut)
def donate_to_refuge(id: int, payload: DonationPayload, current_user: User = Depends(get_verified_user), db: Session = Depends(get_db)):
    """Compatibilidad: usa el mismo flujo de Mercado Pago que POST /payments/donations."""
    return create_donation_checkout(db, current_user, id, payload.amount, share_name=payload.share_name)
