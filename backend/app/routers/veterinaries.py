"""Directorio de clínicas veterinarias: registro con cédula, verificación por admins, reseñas propias y bloque
"Reseñas en Google Maps" consultado en tiempo real (services/google_places.py).

Reglas que vienen de la investigación legal (docs/legal/secciones/gap-veterinarias-y-resenas.json):
- Ningún perfil se publica sin que un admin coteje la cédula del médico veterinario responsable en el Registro
  Nacional de Profesionistas (hallazgos 01-03); la verificación caduca a los 12 meses (17, tarea diaria).
- GuauWoow es directorio, no proveedor: deslinde y aviso de urgencias en cada perfil (09); insignia "Cédula
  verificada" con texto fijo y sin rankings editoriales (17); sin superlativos, avales ni "sin receta" en el
  perfil y con lista cerrada de servicios (05, 08).
- Reseñas propias: teléfono verificado, una por cuenta y clínica, nunca la propia clínica, orden cronológico por
  defecto, promedio simple, la clínica no las edita ni oculta, etiqueta "Reseña incentivada" (12); filtro de
  datos personales y retención para revisión humana de imputaciones o insultos (13, 15); nombre abreviado del
  autor (15); respuesta pública de la clínica, una por reseña (14).
- Google: solo el place_id vive en la base; reseñas y calificación se piden en tiempo real, sin caché (10, 11), con
  límite por cuenta e IP además del tope diario.
- Verificación con evidencia: carrera del RNP y captura fechada privada que sube el admin (03, 16); la cédula y la
  captura se borran 12 meses después de dejar de publicarse (tasks/veterinaries.purge_documents).
- Solo documentos privados subidos por la misma cuenta (nunca una foto pública de /uploads/).
- Respuestas públicas sin ids de cuenta (is_owner / mine en su lugar) y nombres de terceros retenidos (15).
- Aclaraciones y quejas, también sin cuenta (POST /veterinaries/{id}/requests): 5 días hábiles / 72 horas hábiles;
  la aclaración aprobada se publica junto a la reseña sin comentarios (13, 14, 16).
"""
import datetime
import json
import logging
import re
import unicodedata
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import String, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.data.estados_mx import STATE_NAMES, normalize_state
from app.database import get_db
from app.dependencies import client_ip, get_current_user, get_optional_user, get_verified_user, require_admin
from app.models import User, Veterinary, VeterinaryRequest, VeterinaryReview
from app.routers.documents import MEDIA_TYPES, delete_private_document, own_private_document, private_document_path
from app.schemas import (
    HOURS_DAYS,
    VETERINARY_REQUEST_KINDS,
    VETERINARY_REQUEST_STATUSES,
    VETERINARY_STATUSES,
    GooglePlaceCandidate,
    GooglePlaceLinkRequest,
    GooglePlaceSearchRequest,
    VeterinaryAdminOut,
    VeterinaryCreate,
    VeterinaryDetailOut,
    VeterinaryOut,
    VeterinaryPrivateOut,
    VeterinaryRejectPayload,
    VeterinaryRequestAdminOut,
    VeterinaryRequestCreate,
    VeterinaryRequestOut,
    VeterinaryRequestResolve,
    VeterinaryReviewAdminOut,
    VeterinaryReviewCreate,
    VeterinaryReviewOut,
    VeterinaryReviewReply,
    VeterinaryUpdate,
    VeterinaryVerifyPayload,
)
from app.services import crypto_storage, geo, google_places, legal_acceptance, ratelimit
from app.services.audit import record_admin_action
from app.services.moderation import ADMIN_ROLES, is_staff
from app.services.notify import notify_user

router = APIRouter(tags=["veterinaries"])
logger = logging.getLogger(__name__)

DEFAULT_RADIUS_KM = 25.0
MAX_RADIUS_KM = 300.0
DETAIL_REVIEWS = 10
VERIFICATION_DAYS = 365  # reverificación anual de la cédula (hallazgo 17)
REVIEWS_PER_DAY = 10
GOOGLE_SEARCHES_PER_HOUR = 20  # Text Search se cobra por consulta
# Consultas en tiempo real del bloque de Google por hora (además del tope diario GOOGLE_PLACES_DAILY_LIMIT): sin
# esto, una sola persona o un script podría agotar en segundos el tope del día para todas las clínicas.
GOOGLE_DETAIL_PER_USER_HOUR = 30
GOOGLE_DETAIL_PER_IP_HOUR = 120  # varias cuentas detrás de la misma IP (redes móviles con NAT)
GOOGLE_DETAIL_ANON_PER_IP_HOUR = 10  # sin sesión (la app pide iniciar sesión: casi siempre son scripts)
# Solicitudes de aclaración y quejas (gap-veterinarias-y-resenas 13, 14 y 16)
REQUEST_DUE_BUSINESS_DAYS = {"aclaracion": 5, "queja": 3}  # 5 días hábiles / 72 horas hábiles
REQUESTS_PER_DAY_IP = 5
REQUESTS_PER_DAY_USER = 10
DEFAULT_TZ = "America/Mexico_City"

# Lista cerrada de servicios (hallazgos 05 y 08): la misma que muestra el formulario de la app
SERVICES_CATALOG = (
    "Consulta general", "Vacunas", "Desparasitación", "Esterilización", "Cirugía", "Hospitalización", "Laboratorio",
    "Rayos X", "Ultrasonido", "Odontología", "Estética y baño", "Nutrición", "Atención a domicilio",
    "Animales exóticos", "Guardería o pensión",
)

# Zona horaria por estado para "Abierto ahora" (sin horario de verano desde 2022 salvo la frontera norte).
# Los estados que no aparecen usan la hora del centro (America/Mexico_City).
STATE_TIMEZONES = {
    "Baja California": "America/Tijuana",
    "Baja California Sur": "America/Mazatlan",
    "Sinaloa": "America/Mazatlan",
    "Nayarit": "America/Mazatlan",
    "Sonora": "America/Hermosillo",
    "Chihuahua": "America/Chihuahua",
    "Quintana Roo": "America/Cancun",
}

# Textos fijos (hallazgos 09, 11, 12 y 17). La insignia se completa con la fecha y la cédula.
NOTICES = {
    "disclaimer": (
        "GuauWoow es un directorio. No presta servicios veterinarios, no emplea a los veterinarios, no participa en "
        "el diagnóstico ni en el tratamiento, no cobra consultas ni garantiza resultados médicos. La relación es entre "
        "tú y la clínica; la clínica y su médico responsable responden por la atención. Lo que verificamos es la cédula "
        "del médico veterinario responsable en una fecha; no verificamos la calidad de la atención."
    ),
    "emergency": (
        "Si tu perro está en peligro, llama directamente a la clínica o acude a urgencias; GuauWoow no es un "
        "servicio de emergencias."
    ),
    "reviews": (
        "Opiniones de personas usuarias de GuauWoow con teléfono verificado, una por cuenta. Se muestran de la más "
        "reciente a la más antigua y el promedio es simple. No ocultamos las opiniones negativas y la clínica no puede "
        "editarlas ni borrarlas. No se mezclan con las reseñas de Google. Opina sobre tu experiencia, no acuses: "
        "no incluyas teléfonos, correos ni nombres de otras personas."
    ),
    "google": google_places.ORDER_NOTICE,
    "complaints": (
        "Si tienes una queja como consumidor contra la clínica, comunícate primero con ella; también puedes acudir a "
        "la PROFECO (https://www.gob.mx/profeco)."
    ),
}
BADGE_TEMPLATE = (
    "GuauWoow consultó el {date} que la cédula profesional {cedula} del médico veterinario responsable existe en "
    "el Registro Nacional de Profesionistas de la SEP y coincide con el nombre registrado. No verificamos la calidad "
    "de la atención, las instalaciones, los precios ni los permisos locales; no somos autoridad ni colegio de "
    "profesionistas."
)
VERIFIED_LABEL = "Cédula consultada en el Registro Nacional de Profesionistas el {date}"
_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre")

# Publicidad que no se puede comprobar o que está prohibida para servicios veterinarios (hallazgos 05, 08 y 17)
_AD_TERMS = re.compile(
    r"\b(sin receta|garantizad[oa]s?|certificad[oa]s?|avalad[oa]s?|recomendad[oa]s? por|"
    r"(el|la|los|las) mejor(es)?|numero ?1|no\. ?1)\b|#1\b"
)
AD_TERMS_MESSAGE = (
    "Evita afirmaciones que no podamos comprobar o que la ley no permite anunciar (por ejemplo «garantizado», "
    "«certificada», «avalada», «la mejor», «número 1» o «sin receta»). Describe tus servicios de forma objetiva."
)
# Datos personales en reseñas y respuestas (hallazgos 13 y 15)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?:\+?\d[\s().-]*){8,}")
PII_MESSAGE = "No incluyas teléfonos ni correos en tu texto: opina sobre tu experiencia sin datos personales."
# Imputaciones de delitos e insultos: la reseña se guarda oculta hasta que un admin la revise (hallazgo 13)
_HOLD_TERMS = re.compile(
    r"\b(estafa\w*|fraude\w*|ladron\w*|rateros?|asesin\w*|criminal\w*|delincuent\w*|mato a|mataron a|"
    r"maltrata\w*|pendej\w*|idiotas?|imbecil\w*|culer[oa]s?|hijos? de (su )?puta|pinches?|mierda)\b"
)
# Nombres completos de terceros (empleados, otros clientes) en reseñas y respuestas: con tratamiento o puesto
# seguido de nombre y apellido ("la Dra. Ana López", "el recepcionista Juan Pérez") la reseña se retiene para
# revisión humana (hallazgos 13 y 15). No se retiene si es el médico responsable, cuyo nombre ya es público.
_NAME_WORD = r"[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+"
_THIRD_PARTY_NAME_RE = re.compile(
    # El tratamiento sin distinguir mayúsculas; el nombre y el apellido, con mayúscula inicial
    r"\b(?i:dr|dra|doctor|doctora|mvz|lic|sr|sra|srta|señor|señora|señorita|recepcionista|enfermer[oa]|"
    r"asistente|auxiliar|estilista|encargad[oa]|veterinari[oa])\.?\s+"
    rf"({_NAME_WORD})\s+({_NAME_WORD})"
)
PROFILE_LOCK_FIELDS = ("name", "responsible_vet_name", "cedula_profesional", "cedula_institution", "cedula_document_id")
NOT_NULL_FIELDS = {"name", "responsible_vet_name", "cedula_profesional", "hours", "services", "photos", "emergency_24h"}
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,255}$")


# --------------------------------------------------------------------------- utilidades
def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _fold(text: str | None) -> str:
    """Minúsculas y sin acentos (para los filtros de texto)."""
    raw = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(raw.split())


def _date_es(value: datetime.datetime | None) -> str:
    if value is None:
        return ""
    local = value.replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo(DEFAULT_TZ))
    return f"{local.day} de {_MONTHS[local.month - 1]} de {local.year}"


def short_name(full_name: str | None) -> str:
    """Nombre público del autor de una reseña: nombre y primera inicial ("Ana G.")."""
    parts = (full_name or "").split()
    if not parts:
        return "Usuario"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[1][0].upper()}."


def _tz(state: str | None) -> ZoneInfo:
    return ZoneInfo(STATE_TIMEZONES.get(normalize_state(state) or "", DEFAULT_TZ))


def _minutes(value) -> int | None:
    try:
        hh, mm = str(value).split(":")
        return int(hh) * 60 + int(mm)
    except (TypeError, ValueError):
        return None


def is_open_now(hours: dict | None, state: str | None, emergency_24h: bool = False,
                now: datetime.datetime | None = None) -> bool | None:
    """¿Abierta en este momento (hora local del estado)? None si la clínica no registró horario.

    Un rango con cierre menor que la apertura termina pasada la medianoche; apertura == cierre es todo el día.
    Las clínicas con urgencias 24 h siempre cuentan como abiertas.
    """
    if emergency_24h:
        return True
    if not hours or not isinstance(hours, dict):
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    local = now.astimezone(_tz(state))
    minute = local.hour * 60 + local.minute
    today, yesterday = HOURS_DAYS[local.weekday()], HOURS_DAYS[(local.weekday() - 1) % 7]
    for r in hours.get(today) or []:
        o, c = _minutes((r or {}).get("open")), _minutes((r or {}).get("close"))
        if o is None or c is None:
            continue
        if o == c or (o < c and o <= minute < c) or (c < o and minute >= o):
            return True
    for r in hours.get(yesterday) or []:
        o, c = _minutes((r or {}).get("open")), _minutes((r or {}).get("close"))
        if o is not None and c is not None and c < o and minute < c:
            return True
    return False


def _rating_stats(db: Session, ids: list[int]) -> dict[int, tuple[float, int]]:
    """Promedio simple y conteo de reseñas visibles de cuentas activas (sin mezclar con Google)."""
    if not ids:
        return {}
    rows = (
        db.query(VeterinaryReview.veterinary_id, func.avg(VeterinaryReview.rating), func.count(VeterinaryReview.id))
        .join(User, User.id == VeterinaryReview.user_id)
        .filter(VeterinaryReview.veterinary_id.in_(ids), VeterinaryReview.is_hidden == False,  # noqa: E712
                User.is_active == True)  # noqa: E712
        .group_by(VeterinaryReview.veterinary_id).all()
    )
    return {vid: (round(float(avg), 1), int(n)) for vid, avg, n in rows}


def _decorate(db: Session, vets: list[Veterinary], lat: float | None = None, lon: float | None = None) -> list[Veterinary]:
    """Llena los atributos calculados: calificación propia, abierto ahora, distancia e insignia."""
    stats = _rating_stats(db, [v.id for v in vets])
    for v in vets:
        avg, count = stats.get(v.id, (None, 0))
        v.rating_avg, v.rating_count = avg, count
        v.open_now = is_open_now(v.hours, v.state, v.emergency_24h)
        if v.distance_km is None and lat is not None and lon is not None:
            v.distance_km = geo.distance_to(v, lat, lon, exact=True)  # la dirección del negocio es pública
        if v.status == "verified" and v.verified_at:
            date = _date_es(v.verified_at)
            v.badge_text = BADGE_TEMPLATE.format(date=date, cedula=v.cedula_profesional)
            v.verified_label = VERIFIED_LABEL.format(date=date)
    return vets


def _public_filter(query):
    """Solo clínicas verificadas, visibles y de cuentas activas."""
    return query.join(User, User.id == Veterinary.owner_user_id).filter(
        Veterinary.status == "verified", Veterinary.is_hidden == False,  # noqa: E712
        User.is_active == True,  # noqa: E712
    )


def _is_public(vet: Veterinary) -> bool:
    return vet.status == "verified" and not vet.is_hidden and bool(vet.owner and vet.owner.is_active)


def _can_view(vet: Veterinary, user: User | None) -> bool:
    return _is_public(vet) or bool(user and (user.id == vet.owner_user_id or is_staff(user)))


def _load(db: Session, id: int) -> Veterinary | None:
    return db.query(Veterinary).options(joinedload(Veterinary.owner)).filter(Veterinary.id == id).first()


def _visible_or_404(db: Session, id: int, user: User | None) -> Veterinary:
    vet = _load(db, id)
    if not vet or not _can_view(vet, user):
        raise HTTPException(status_code=404, detail="No encontramos esa veterinaria.")
    return vet


def _own_or_404(db: Session, id: int, user: User) -> Veterinary:
    vet = _load(db, id)
    if not vet:
        raise HTTPException(status_code=404, detail="No encontramos esa veterinaria.")
    if vet.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Solo quien registró la veterinaria puede hacer esto.")
    return vet


def _review_out(r: VeterinaryReview, viewer: User | None = None) -> dict:
    """Reseña pública: nombre abreviado y `mine` en lugar del id de la cuenta (no se pueden ligar las reseñas
    de una misma persona entre clínicas ni con su cuenta)."""
    name = short_name(r.user.full_name if r.user else None)
    return {
        "id": r.id, "veterinary_id": r.veterinary_id, "mine": bool(viewer and viewer.id == r.user_id),
        "user": {"full_name": name, "avatar_url": r.user.avatar_url if r.user else None},
        "author_name": name, "rating": r.rating, "text": r.text, "visited_month": r.visited_month,
        "incentivized": bool(r.incentivized), "owner_reply": r.owner_reply, "owner_reply_at": r.owner_reply_at,
        "clarification": r.clarification, "clarification_at": r.clarification_at,
        "is_hidden": bool(r.is_hidden), "created_at": r.created_at, "updated_at": r.updated_at,
    }


def _visible_reviews(db: Session, vet_id: int):
    return (
        db.query(VeterinaryReview).join(User, User.id == VeterinaryReview.user_id)
        .options(joinedload(VeterinaryReview.user))
        .filter(VeterinaryReview.veterinary_id == vet_id, VeterinaryReview.is_hidden == False,  # noqa: E712
                User.is_active == True)  # noqa: E712
    )


def _check_ad_terms(*texts: str | None) -> None:
    for text in texts:
        if text and _AD_TERMS.search(_fold(text)):
            raise HTTPException(status_code=400, detail=AD_TERMS_MESSAGE)


def _has_pii(text: str | None) -> bool:
    return bool(text and (_EMAIL_RE.search(text) or _PHONE_RE.search(text)))


def _names_third_party(text: str | None, vet: Veterinary | None = None) -> bool:
    """¿Menciona con nombre y apellido a alguien que no es el médico responsable (cuyo nombre ya es público)?"""
    if not text:
        return False
    public = set(_fold(vet.responsible_vet_name).split()) if vet and vet.responsible_vet_name else set()
    for match in _THIRD_PARTY_NAME_RE.finditer(text):
        if not {_fold(w) for w in match.groups()} <= public:
            return True
    return False


def _needs_hold(text: str | None, vet: Veterinary | None = None) -> bool:
    """Insultos, imputaciones de delitos o nombres completos de terceros: se retiene para revisión humana."""
    return bool(text and (_HOLD_TERMS.search(_fold(text)) or _names_third_party(text, vet)))


def _validate_profile(data: dict, user: User, current: Veterinary | None = None) -> dict:
    """Reglas de contenido del perfil (además de las del esquema). Devuelve los datos normalizados."""
    if "state" in data and data["state"] is not None:
        state = normalize_state(data["state"])
        if not state:
            raise HTTPException(status_code=400, detail="Elige un estado de la República Mexicana.")
        data["state"] = state
    if data.get("services") is not None:
        catalog = {s.lower(): s for s in SERVICES_CATALOG}
        unknown = [s for s in data["services"] if s.lower() not in catalog]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Servicio no válido: {unknown[0]}. Elige de la lista: {', '.join(SERVICES_CATALOG)}.",
            )
        data["services"] = [catalog[s.lower()] for s in data["services"]]
    if data.get("email") and not re.match(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$", data["email"]):
        raise HTTPException(status_code=400, detail="Revisa el correo de la clínica.")
    for field in ("phone", "whatsapp"):
        if data.get(field) and len(re.sub(r"\D", "", data[field])) < 10:
            raise HTTPException(status_code=400, detail="Los teléfonos deben tener al menos 10 dígitos.")
    doc = data.get("cedula_document_id")
    if doc and doc != getattr(current, "cedula_document_id", None) and not own_private_document(doc, user.id):
        # Solo documentos privados subidos por esta cuenta (POST /upload/document): nunca el nombre de una foto
        # pública, que al cancelar la cuenta se borraría como si fuera la cédula
        raise HTTPException(status_code=400, detail="No encontramos el documento de la cédula. Súbelo de nuevo.")
    _check_ad_terms(data.get("name"), data.get("description"))

    merged = {f: data.get(f, getattr(current, f, None) if current else None)
              for f in ("address", "city", "state", "phone", "whatsapp", "cedula_document_id")}
    if not (merged["address"] or "").strip() or not (merged["city"] or "").strip() or not merged["state"]:
        raise HTTPException(status_code=400, detail="Escribe la dirección, la ciudad y el estado de la clínica.")
    if not merged["phone"] and not merged["whatsapp"]:
        raise HTTPException(status_code=400, detail="Indica al menos un teléfono o WhatsApp de la clínica.")
    if not merged["cedula_document_id"]:
        # La imagen de una cédula ya verificada se borra a los 30 días (services/retention.py): la clínica puede
        # seguir editando su ficha sin volver a subirla, salvo que cambie los datos de la cédula
        purged = current is not None and getattr(current, "cedula_document_purged_at", None) is not None
        cedula_changed = any(f in data and data[f] != getattr(current, f, None)
                             for f in ("responsible_vet_name", "cedula_profesional", "cedula_institution"))
        if not purged or cedula_changed:
            raise HTTPException(status_code=400, detail="Sube la foto o el PDF de la cédula profesional del responsable.")
    return data


def _notify_admins(db: Session, kind: str, title: str, body: str, data: dict) -> None:
    admins = db.query(User).filter(User.role.in_(ADMIN_ROLES), User.is_active == True).all()  # noqa: E712
    for admin in admins:
        notify_user(db, admin, kind, title=title, body=body, url="/admin/", email=True, data=data, commit=False)


def _private_out(db: Session, vet: Veterinary) -> VeterinaryPrivateOut:
    """Respuesta para la dueña de la clínica (endpoints propios)."""
    _decorate(db, [vet])
    return VeterinaryPrivateOut.model_validate(vet).model_copy(update={"is_owner": True})


# --------------------------------------------------------------------------- público
@router.get("/veterinaries", response_model=list[VeterinaryOut])
def list_veterinaries(
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(DEFAULT_RADIUS_KM, gt=0, le=MAX_RADIUS_KM),
    city: str | None = Query(None, max_length=100),
    state: str | None = Query(None, max_length=100),
    emergency: bool | None = Query(None),
    q: str | None = Query(None, max_length=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Clínicas verificadas. Con lat/lon: solo las del radio, de la más cercana a la más lejana; sin ubicación,
    en orden alfabético (no hay rankings editoriales ni por calificación de Google)."""
    query = _public_filter(db.query(Veterinary))
    if city and city.strip():
        query = query.filter(Veterinary.city.icontains(city.strip(), autoescape=True))
    if state and state.strip():
        query = query.filter(Veterinary.state == (normalize_state(state) or state.strip()))
    if emergency:
        query = query.filter(Veterinary.emergency_24h == True)  # noqa: E712
    if q and q.strip():
        term = q.strip()
        # Los servicios se guardan como JSON con los acentos escapados ("\u00f3"): se buscan por su forma escapada
        services = [json.dumps(s)[1:-1] for s in SERVICES_CATALOG if _fold(term) in _fold(s)]
        query = query.filter(or_(
            Veterinary.name.icontains(term, autoescape=True),
            Veterinary.description.icontains(term, autoescape=True),
            Veterinary.city.icontains(term, autoescape=True),
            *(cast(Veterinary.services, String).contains(s, autoescape=True) for s in services),
        ))
    if lat is not None and lon is not None:
        items = geo.nearest(query, Veterinary, lat, lon, radius_km, skip, limit, exact=True)
    else:
        items = query.order_by(Veterinary.name.asc(), Veterinary.id.asc()).offset(skip).limit(limit).all()
    return _decorate(db, items, lat, lon)


@router.get("/veterinaries/meta")
def veterinaries_meta():
    """Catálogos y textos fijos de la sección (servicios, estados, avisos y reglas de reseñas)."""
    return {
        "services": list(SERVICES_CATALOG),
        "states": list(STATE_NAMES),
        "notices": NOTICES,
        "badge_title": "Cédula verificada",
        "review_min_account_days": max(0, int(settings.veterinary_review_min_account_days or 0)),
        "google_enabled": google_places.enabled(),
    }


@router.get("/veterinaries/me", response_model=VeterinaryPrivateOut)
def my_veterinary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    vet = db.query(Veterinary).options(joinedload(Veterinary.owner)).filter(
        Veterinary.owner_user_id == current_user.id).first()
    if not vet:
        raise HTTPException(status_code=404, detail="Todavía no registras una veterinaria.")
    return _private_out(db, vet)


def _google_allowed(request: Request, user: User | None) -> bool:
    """Límite por cuenta e IP de las consultas en tiempo real a Google (no guarda contenido de Google)."""
    ip = client_ip(request)
    if not user:
        return ratelimit.hit(f"gplaces:anon:{ip}", GOOGLE_DETAIL_ANON_PER_IP_HOUR, 3600)
    return (ratelimit.hit(f"gplaces:user:{user.id}", GOOGLE_DETAIL_PER_USER_HOUR, 3600)
            and ratelimit.hit(f"gplaces:ip:{ip}", GOOGLE_DETAIL_PER_IP_HOUR, 3600))


@router.get("/veterinaries/{id}", response_model=VeterinaryDetailOut)
def get_veterinary(
    id: int,
    request: Request,
    response: Response,
    include_google: bool = Query(True, alias="google", description="false: sin el bloque de Google (no consulta ni gasta cuota)"),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    vet = _visible_or_404(db, id, current_user)
    _decorate(db, [vet])
    reviews = (
        _visible_reviews(db, vet.id)
        .order_by(VeterinaryReview.created_at.desc(), VeterinaryReview.id.desc()).limit(DETAIL_REVIEWS).all()
    )
    mine = None
    if current_user:
        own = db.query(VeterinaryReview).options(joinedload(VeterinaryReview.user)).filter(
            VeterinaryReview.veterinary_id == vet.id, VeterinaryReview.user_id == current_user.id).first()
        mine = _review_out(own, current_user) if own else None
    google = None
    if include_google and vet.google_place_id and _is_public(vet) and google_places.enabled():
        # Contenido de Google: en tiempo real, nunca en la base ni en caché (tampoco en el navegador o proxies).
        # Con el límite por cuenta o IP agotado se manda el bloque sin reseñas (solo el enlace a Google Maps).
        if _google_allowed(request, current_user):
            google = google_places.fetch_place_block(vet.google_place_id, vet.google_maps_url)
        else:
            google = google_places.unavailable_block(vet.google_place_id, vet.google_maps_url)
        response.headers["Cache-Control"] = "no-store"
    data = VeterinaryOut.model_validate(vet).model_dump()
    data["is_owner"] = bool(current_user and current_user.id == vet.owner_user_id)
    return VeterinaryDetailOut(
        **data, reviews=[_review_out(r, current_user) for r in reviews], my_review=mine, google=google,
        notices=NOTICES,
    )


@router.get("/veterinaries/{id}/reviews", response_model=list[VeterinaryReviewOut])
def list_reviews(
    id: int,
    order: str = Query("recent", pattern="^(recent|oldest|highest|lowest)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Reseñas visibles; por defecto de la más reciente a la más antigua (selector: oldest, highest, lowest)."""
    vet = _visible_or_404(db, id, current_user)
    orders = {
        "recent": (VeterinaryReview.created_at.desc(), VeterinaryReview.id.desc()),
        "oldest": (VeterinaryReview.created_at.asc(), VeterinaryReview.id.asc()),
        "highest": (VeterinaryReview.rating.desc(), VeterinaryReview.created_at.desc()),
        "lowest": (VeterinaryReview.rating.asc(), VeterinaryReview.created_at.desc()),
    }
    rows = _visible_reviews(db, vet.id).order_by(*orders[order]).offset(skip).limit(limit).all()
    return [_review_out(r, current_user) for r in rows]


# --------------------------------------------------------------------------- registro y edición
@router.post("/veterinaries", response_model=VeterinaryPrivateOut, status_code=status.HTTP_201_CREATED)
def create_veterinary(
    payload: VeterinaryCreate,
    request: Request,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Registra la clínica de la cuenta (una por cuenta). Queda "pending" hasta que un admin coteje la cédula."""
    if db.query(Veterinary.id).filter(Veterinary.owner_user_id == current_user.id).first():
        raise HTTPException(status_code=409, detail="Ya registraste una veterinaria con esta cuenta.")
    data = payload.model_dump()
    accepted_annex = data.pop("accepted_annex", False)
    if data.pop("consent", False) is not True:
        raise HTTPException(status_code=400, detail=(
            "Marca la casilla de consentimiento: confirma que los datos son verdaderos, que cuentas con la "
            "autorización del médico responsable y que aceptas publicar su nombre, cédula e institución."))
    data = _validate_profile(data, current_user)
    # Evidencia del consentimiento: fecha y versión de los Términos vigentes (gap-veterinarias-y-resenas 15)
    vet = Veterinary(owner_user_id=current_user.id, status="pending", consent_at=_utcnow(),
                     consent_terms_version=settings.legal_terms_version, **data)
    db.add(vet)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya registraste una veterinaria con esta cuenta.")
    # Anexo de clínicas (casilla separada): bitácora de aceptaciones; obligatorio con LEGAL_ANNEX_REQUIRED
    legal_acceptance.accept_annex(db, current_user, "clinica", accepted_annex, request, context={"veterinary_id": vet.id})
    _notify_admins(db, "veterinary_pending", "Nueva veterinaria por verificar 🩺",
                   f"«{vet.name}» espera el cotejo de la cédula {vet.cedula_profesional} en el Registro Nacional "
                   "de Profesionistas.", {"veterinary_id": vet.id})
    db.commit()
    db.refresh(vet)
    return _private_out(db, vet)


@router.patch("/veterinaries/{id}", response_model=VeterinaryPrivateOut)
def update_veterinary(
    id: int,
    payload: VeterinaryUpdate,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Edita la clínica propia. Cambiar el nombre o los datos de la cédula (o corregir una rechazada) la regresa
    a revisión: deja de mostrarse hasta que un admin la vuelva a verificar."""
    vet = _own_or_404(db, id, current_user)
    data = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
            if not (k in NOT_NULL_FIELDS and v is None)}
    data = _validate_profile(data, current_user, current=vet)
    relock = any(f in data and data[f] != getattr(vet, f) for f in PROFILE_LOCK_FIELDS)
    old_doc = vet.cedula_document_id if "cedula_document_id" in data and data["cedula_document_id"] != vet.cedula_document_id else None
    for field, value in data.items():
        setattr(vet, field, value)
    if data.get("cedula_document_id"):
        vet.cedula_document_purged_at = None  # cédula nueva: su imagen se borra 30 días después de la nueva decisión
    if relock or vet.status == "rejected":
        was = vet.status
        if was != "pending":
            # Deja de publicarse (o reabre una rechazada): el plazo de retención corre desde hoy
            vet.unpublished_at = _utcnow()
        vet.status = "pending"
        vet.rejection_note = None
        vet.verified_at = None
        vet.verified_by_id = None
        vet.verification_expires_at = None
        if was != "pending":
            _notify_admins(db, "veterinary_pending", "Veterinaria por volver a verificar 🩺",
                           f"«{vet.name}» cambió sus datos y espera revisión.", {"veterinary_id": vet.id})
    db.commit()
    if old_doc:
        delete_private_document(old_doc)  # la cédula reemplazada ya no se conserva (minimización)
    db.refresh(vet)
    return _private_out(db, vet)


# --------------------------------------------------------------------------- reseñas
@router.post("/veterinaries/{id}/reviews", response_model=VeterinaryReviewOut)
def upsert_review(
    id: int,
    payload: VeterinaryReviewCreate,
    response: Response,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Crea o actualiza la reseña propia (una por cuenta y clínica). 201 al crearla, 200 al editarla.

    Con teléfonos o correos se rechaza; con insultos o imputaciones de delitos se guarda oculta (is_hidden=True)
    hasta que un admin la revise. Una reseña oculta por moderación sigue oculta aunque se edite.
    """
    vet = _visible_or_404(db, id, current_user)
    if not _is_public(vet):
        raise HTTPException(status_code=400, detail="Esta veterinaria todavía no recibe reseñas.")
    if vet.owner_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes reseñar tu propia veterinaria.")
    min_days = max(0, int(settings.veterinary_review_min_account_days or 0))
    if min_days and current_user.created_at and (_utcnow() - current_user.created_at).days < min_days:
        raise HTTPException(status_code=403, detail=f"Tu cuenta debe tener al menos {min_days} días para reseñar clínicas.")
    text = (payload.text or "").strip() or None
    if _has_pii(text):
        raise HTTPException(status_code=400, detail=PII_MESSAGE)
    ratelimit.check(f"vetrev:{current_user.id}", limit=REVIEWS_PER_DAY, window_seconds=86_400,
                    detail="Llegaste al límite de reseñas por hoy. Inténtalo mañana.")
    hold = _needs_hold(text, vet)
    review = db.query(VeterinaryReview).filter(
        VeterinaryReview.veterinary_id == vet.id, VeterinaryReview.user_id == current_user.id).first()
    created = review is None
    if created:
        review = VeterinaryReview(veterinary_id=vet.id, user_id=current_user.id)
        db.add(review)
    review.rating = payload.rating
    review.text = text
    review.visited_month = payload.visited_month
    review.incentivized = payload.incentivized
    review.updated_at = _utcnow()
    if hold:
        review.is_hidden = True
    try:
        db.flush()
    except IntegrityError:  # dos envíos simultáneos de la misma cuenta
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya enviaste una reseña de esta veterinaria. Recarga la página.")
    if hold:
        _notify_admins(db, "veterinary_review_held", "Reseña de veterinaria en revisión 🚩",
                       f"Una reseña de «{vet.name}» quedó retenida por posibles insultos o acusaciones. Revísala.",
                       {"veterinary_id": vet.id, "veterinary_review_id": review.id})
    elif created and vet.owner and vet.owner.is_active:
        notify_user(db, vet.owner, "veterinary_review", title="Nueva opinión de tu veterinaria ⭐",
                    body=f"Alguien calificó «{vet.name}» con {review.rating} de 5.", url=f"/app/?vet={vet.id}",
                    data={"veterinary_id": vet.id, "veterinary_review_id": review.id}, commit=False)
    db.commit()
    db.refresh(review)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _review_out(review, current_user)


@router.delete("/veterinaries/{id}/reviews/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_review(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    review = db.query(VeterinaryReview).filter(
        VeterinaryReview.veterinary_id == id, VeterinaryReview.user_id == current_user.id).first()
    if not review:
        raise HTTPException(status_code=404, detail="No tienes una reseña de esta veterinaria.")
    db.delete(review)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _own_review_target(db: Session, id: int, review_id: int, user: User) -> tuple[Veterinary, VeterinaryReview]:
    vet = _own_or_404(db, id, user)
    if vet.status != "verified":
        raise HTTPException(status_code=400, detail="Podrás responder cuando tu veterinaria esté verificada.")
    review = db.query(VeterinaryReview).options(joinedload(VeterinaryReview.user)).filter(
        VeterinaryReview.id == review_id, VeterinaryReview.veterinary_id == vet.id).first()
    if not review or review.is_hidden:
        raise HTTPException(status_code=404, detail="No encontramos esa reseña.")
    return vet, review


@router.post("/veterinaries/{id}/reviews/{review_id}/reply", response_model=VeterinaryReviewOut)
def reply_review(
    id: int,
    review_id: int,
    payload: VeterinaryReviewReply,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Respuesta pública de la clínica (una por reseña; se puede corregir). La clínica no edita la reseña."""
    vet, review = _own_review_target(db, id, review_id, current_user)
    text = payload.text.strip()
    if _has_pii(text):
        raise HTTPException(status_code=400, detail=PII_MESSAGE)
    if _needs_hold(text, vet):
        raise HTTPException(status_code=400, detail=(
            "Responde con respeto, sin acusaciones ni nombres completos de otras personas: revisa tu texto."))
    review.owner_reply = text
    review.owner_reply_at = _utcnow()
    if review.user and review.user.is_active:
        notify_user(db, review.user, "veterinary_review", title="La clínica respondió tu opinión",
                    body=f"«{vet.name}» respondió a tu reseña.", url=f"/app/?vet={vet.id}",
                    data={"veterinary_id": vet.id, "veterinary_review_id": review.id}, commit=False)
    db.commit()
    db.refresh(review)
    return _review_out(review, current_user)


@router.delete("/veterinaries/{id}/reviews/{review_id}/reply", response_model=VeterinaryReviewOut)
def delete_reply(id: int, review_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _vet, review = _own_review_target(db, id, review_id, current_user)
    review.owner_reply = None
    review.owner_reply_at = None
    db.commit()
    db.refresh(review)
    return _review_out(review, current_user)


# --------------------------------------------------------------------------- Google Maps (ficha de la clínica)
@router.post("/veterinaries/{id}/google-search", response_model=list[GooglePlaceCandidate])
def google_search(
    id: int,
    payload: GooglePlaceSearchRequest,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Busca la ficha de la clínica en Google Maps cerca de su ubicación (Text Search New)."""
    vet = _own_or_404(db, id, current_user)
    if not google_places.enabled():
        raise HTTPException(status_code=503, detail=google_places.NOT_CONFIGURED)
    ratelimit.check(f"gsearch:{current_user.id}", limit=GOOGLE_SEARCHES_PER_HOUR, window_seconds=3600,
                    detail="Hiciste muchas búsquedas en Google Maps. Espera un rato e inténtalo de nuevo.")
    try:
        return google_places.search_text(payload.query.strip(), vet.latitude, vet.longitude)
    except google_places.PlacesError:
        raise HTTPException(status_code=502, detail="Google Maps no respondió. Inténtalo de nuevo en unos minutos.")


@router.post("/veterinaries/{id}/google-link", response_model=VeterinaryPrivateOut)
def google_link(
    id: int,
    payload: GooglePlaceLinkRequest,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Vincula (place_id) o desvincula (null) la ficha de Google Maps. Solo se guarda el place_id."""
    vet = _own_or_404(db, id, current_user)
    if not payload.place_id:
        vet.google_place_id = None
        vet.google_maps_url = None
        vet.google_place_checked_at = None
        vet.google_place_error_at = None
        vet.google_fetched_at = None
        db.commit()
        db.refresh(vet)
        return _private_out(db, vet)
    place_id = payload.place_id.strip()
    if not _PLACE_ID_RE.match(place_id):
        raise HTTPException(status_code=400, detail="Ese identificador de Google Maps no es válido.")
    if not google_places.enabled():
        raise HTTPException(status_code=503, detail=google_places.NOT_CONFIGURED)
    try:
        current = google_places.refresh_place_id(place_id)  # IDs Only: sin costo
    except google_places.PlacesError:
        raise HTTPException(status_code=502, detail="Google Maps no respondió. Inténtalo de nuevo en unos minutos.")
    if not current:
        raise HTTPException(status_code=400, detail="Google Maps ya no tiene ese lugar. Búscalo de nuevo.")
    taken = db.query(Veterinary.id).filter(Veterinary.google_place_id == current, Veterinary.id != vet.id).first()
    if taken:
        raise HTTPException(status_code=409, detail="Esa ficha de Google Maps ya está vinculada a otra veterinaria.")
    now = _utcnow()
    vet.google_place_id = current
    vet.google_maps_url = google_places.maps_url(current, vet.name)
    vet.google_place_checked_at = now
    vet.google_place_error_at = None
    vet.google_fetched_at = now
    db.commit()
    db.refresh(vet)
    return _private_out(db, vet)


# --------------------------------------------------------------------------- administración
@router.get("/admin/veterinaries", response_model=list[VeterinaryAdminOut])
def admin_list_veterinaries(
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = Query(None, max_length=100, description="Nombre, ciudad, estado, cédula, responsable o correo"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Cola de verificación (status=pending, la más antigua primero) y consulta de las demás."""
    query = db.query(Veterinary).options(joinedload(Veterinary.owner))
    if q and q.strip():
        term = q.strip()
        owners = db.query(User.id).filter(User.email.icontains(term, autoescape=True))
        query = query.filter(or_(
            Veterinary.name.icontains(term, autoescape=True), Veterinary.city.icontains(term, autoescape=True),
            Veterinary.state.icontains(term, autoescape=True),
            Veterinary.cedula_profesional.icontains(term, autoescape=True),
            Veterinary.responsible_vet_name.icontains(term, autoescape=True),
            Veterinary.owner_user_id.in_(owners),
        ))
    if status_filter and status_filter != "all":
        if status_filter not in VETERINARY_STATUSES:
            raise HTTPException(status_code=400, detail="Estado inválido. Usa: pending, verified o rejected.")
        query = query.filter(Veterinary.status == status_filter)
    order = (Veterinary.created_at.asc(),) if status_filter == "pending" else (Veterinary.created_at.desc(),)
    vets = _decorate(db, query.order_by(*order, Veterinary.id.asc()).offset(skip).limit(limit).all())
    return [
        VeterinaryAdminOut.model_validate(v).model_copy(update={"owner_email": v.owner.email if v.owner else None})
        for v in vets
    ]


def _admin_target(db: Session, id: int) -> Veterinary:
    vet = _load(db, id)
    if not vet:
        raise HTTPException(status_code=404, detail="No encontramos esa veterinaria.")
    return vet


def _admin_out(db: Session, vet: Veterinary) -> VeterinaryAdminOut:
    _decorate(db, [vet])
    return VeterinaryAdminOut.model_validate(vet).model_copy(
        update={"owner_email": vet.owner.email if vet.owner else None})


@router.post("/admin/veterinaries/{id}/verify", response_model=VeterinaryAdminOut)
def admin_verify(
    id: int,
    payload: VeterinaryVerifyPayload,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Marca la cédula como cotejada en el Registro Nacional de Profesionistas (vigencia de 12 meses).

    Exige la evidencia del cotejo (gap-veterinarias-y-resenas 03 y 16, retención 0): la carrera que muestra el RNP
    y la captura fechada de la consulta (documento privado que el admin sube con POST /upload/document). Quién
    verificó queda en verified_by_id y en la bitácora.
    """
    vet = _admin_target(db, id)
    # Reverificación anual: la imagen de la cédula ya verificada se borró a los 30 días (queda la constancia y se
    # coteja de nuevo el número en el RNP)
    if not private_document_path(vet.cedula_document_id) and not vet.cedula_document_purged_at:
        raise HTTPException(status_code=400, detail="La veterinaria no tiene documento de cédula: no se puede verificar.")
    evidence = payload.evidence_document_id
    if evidence == vet.cedula_document_id or not own_private_document(evidence, admin_user.id):
        raise HTTPException(status_code=400, detail=(
            "Sube la captura fechada de la consulta en el Registro Nacional de Profesionistas (no la cédula que "
            "envió la clínica)."))
    carrera = " ".join(payload.carrera.split())
    # Verificación y reverificación anual: requieren los Términos para clínicas vigentes (terminos-clinicas 1.2)
    legal_acceptance.require_ally_annexes(
        db, vet.owner, ("clinica",), status_code=400,
        detail="La clínica aún no acepta la versión vigente de los Términos para clínicas veterinarias. Le pedimos "
               "aceptarlos en la app; verifícala después.",
        notify_title="Acepta los Términos para clínicas para tu verificación")
    now = _utcnow()
    previous = vet.status
    old_evidence = vet.verification_evidence_document_id
    vet.status = "verified"
    vet.rejection_note = None
    vet.verified_at = now
    vet.verified_by_id = admin_user.id
    vet.verification_expires_at = now + datetime.timedelta(days=VERIFICATION_DAYS)
    vet.cedula_carrera = carrera
    vet.verification_evidence_document_id = evidence
    vet.unpublished_at = None
    record_admin_action(db, admin_user, "veterinary.verify", "veterinary", vet.id,
                        {"status_from": previous, "cedula": vet.cedula_profesional, "carrera": carrera,
                         "evidence": evidence, "previous_evidence": old_evidence}, request)
    if vet.owner and vet.owner.is_active:
        notify_user(db, vet.owner, "veterinary_verified", title="¡Tu veterinaria ya está publicada! 🩺",
                    body=f"Verificamos la cédula de «{vet.name}». Ya aparece en el directorio de GuauWoow.",
                    url=f"/app/?vet={vet.id}", email=True, data={"veterinary_id": vet.id}, commit=False)
    db.commit()
    if old_evidence and old_evidence != evidence:
        delete_private_document(old_evidence)  # la nueva captura sustituye a la de la verificación anterior
    db.refresh(vet)
    return _admin_out(db, vet)


@router.post("/admin/veterinaries/{id}/reject", response_model=VeterinaryAdminOut)
def admin_reject(
    id: int,
    payload: VeterinaryRejectPayload,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    vet = _admin_target(db, id)
    previous = vet.status
    note = payload.note.strip()
    vet.status = "rejected"
    vet.rejection_note = note
    vet.verified_at = None
    vet.verified_by_id = None
    vet.verification_expires_at = None
    # Rechazo o revocación: la cédula y la evidencia se conservan 12 meses desde hoy (tarea purge_documents)
    vet.unpublished_at = _utcnow()
    record_admin_action(db, admin_user, "veterinary.reject", "veterinary", vet.id,
                        {"status_from": previous, "note": note}, request)
    if vet.owner and vet.owner.is_active:
        notify_user(db, vet.owner, "veterinary_rejected", title="Revisa el registro de tu veterinaria",
                    body=f"No pudimos verificar «{vet.name}»: {note} Corrige los datos y se revisará de nuevo.",
                    url="/app/", email=True, data={"veterinary_id": vet.id}, commit=False)
    db.commit()
    db.refresh(vet)
    return _admin_out(db, vet)


@router.get("/admin/veterinaries/{id}/cedula")
def admin_cedula(id: int, request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Descarga el documento privado de la cédula (solo admins; queda en la bitácora)."""
    vet = _admin_target(db, id)
    path = private_document_path(vet.cedula_document_id)  # solo la carpeta privada, nunca /uploads/ público
    if not path:
        raise HTTPException(status_code=404, detail="Esta veterinaria no tiene documento de cédula.")
    record_admin_action(db, admin_user, "veterinary_cedula.view", "veterinary", vet.id,
                        {"document": path.name}, request)
    db.commit()
    return _private_file(path)


@router.get("/admin/veterinaries/{id}/evidence")
def admin_evidence(id: int, request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Descarga la captura privada del cotejo en el RNP (solo admins; queda en la bitácora)."""
    vet = _admin_target(db, id)
    path = private_document_path(vet.verification_evidence_document_id)
    if not path:
        raise HTTPException(status_code=404, detail="Esta veterinaria no tiene captura del cotejo.")
    record_admin_action(db, admin_user, "veterinary_evidence.view", "veterinary", vet.id,
                        {"document": path.name}, request)
    db.commit()
    return _private_file(path)


def _private_file(path):
    """El documento se descifra en memoria (crypto_storage): en disco solo está cifrado."""
    ext = path.suffix.lstrip(".").lower()
    return crypto_storage.private_file_response(
        path, media_type=MEDIA_TYPES.get(ext, "application/octet-stream"), filename=path.name,
        content_disposition_type="inline",
    )


@router.get("/admin/veterinary-reviews", response_model=list[VeterinaryReviewAdminOut])
def admin_list_reviews(
    hidden: bool | None = Query(None, description="true: retenidas u ocultas (cola de revisión)"),
    veterinary_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reseñas de clínicas para moderar. Para publicar una retenida: PATCH /admin/content/veterinary_review/{id}."""
    query = db.query(VeterinaryReview).options(joinedload(VeterinaryReview.user), joinedload(VeterinaryReview.veterinary))
    if hidden is not None:
        query = query.filter(VeterinaryReview.is_hidden == hidden)
    if veterinary_id:
        query = query.filter(VeterinaryReview.veterinary_id == veterinary_id)
    rows = query.order_by(VeterinaryReview.updated_at.desc(), VeterinaryReview.id.desc()).offset(skip).limit(limit).all()
    out = []
    for r in rows:
        item = _review_out(r)
        item["user_id"] = r.user_id
        item["user"]["full_name"] = r.user.full_name if r.user else item["author_name"]  # el admin ve el nombre completo
        item["veterinary_name"] = r.veterinary.name if r.veterinary else None
        item["user_email"] = r.user.email if r.user else None
        out.append(item)
    return out


# --------------------------------------------------------------------------- aclaraciones y quejas (con o sin cuenta)
REQUEST_KIND_LABELS = {"aclaracion": "Solicitud de aclaración", "queja": "Queja"}
_REQUEST_EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")


def add_business_days(start: datetime.datetime, days: int) -> datetime.datetime:
    """Suma días hábiles (lunes a viernes, hora del centro). No descuenta días festivos: el plazo real es igual o
    más holgado que el publicado."""
    local = start.replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo(DEFAULT_TZ))
    added = 0
    while added < days:
        local += datetime.timedelta(days=1)
        if local.weekday() < 5:
            added += 1
    return local.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _send_request_email(to: str | None, title: str, body: str) -> None:
    """Correo a quien presentó la solicitud sin cuenta (no hay notificación en la app que mandarle)."""
    if not to:
        return
    from app.services.background import dispatch

    try:
        dispatch("app.tasks.notifications.send_notification_email", to, title, body, None)
    except Exception:  # noqa: BLE001 - un correo caído no debe tumbar la solicitud
        logger.exception("No se pudo despachar el correo de la solicitud de veterinaria")


def _request_admin_out(r: VeterinaryRequest, now: datetime.datetime | None = None) -> VeterinaryRequestAdminOut:
    now = now or _utcnow()
    return VeterinaryRequestAdminOut(
        id=r.id, kind=r.kind, status=r.status, due_at=r.due_at, created_at=r.created_at,
        veterinary_id=r.veterinary_id, veterinary_name=r.veterinary.name if r.veterinary else None,
        review_id=r.review_id, review_text=r.review.text if r.review else None,
        review_clarification=r.review.clarification if r.review else None,
        user_id=r.user_id, name=r.name, email=r.email, relation=r.relation, reason=r.reason, text=r.text,
        overdue=r.status == "pending" and r.due_at < now, resolution_note=r.resolution_note,
        resolved_by_id=r.resolved_by_id, resolved_at=r.resolved_at,
    )


@router.post("/veterinaries/{id}/requests", response_model=VeterinaryRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    id: int,
    payload: VeterinaryRequestCreate,
    request: Request,
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Solicitar aclaración sobre una reseña (la clínica o una persona aludida) o presentar una queja sobre una
    clínica o una reseña, también sin cuenta (gap-veterinarias-y-resenas 13, 14 y 16).

    Sin cuenta se piden nombre, correo y la aceptación del aviso de privacidad. El equipo responde en 5 días
    hábiles (aclaración: si procede, se publica junto a la reseña sin comentarios) o en 72 horas hábiles (queja).
    """
    vet = _load(db, id)
    if not vet or not _can_view(vet, current_user):
        raise HTTPException(status_code=404, detail="No encontramos esa veterinaria.")
    review = None
    if payload.review_id is not None:
        review = db.query(VeterinaryReview).filter(
            VeterinaryReview.id == payload.review_id, VeterinaryReview.veterinary_id == vet.id).first()
        if not review or review.is_hidden:
            raise HTTPException(status_code=404, detail="No encontramos esa reseña.")
    if payload.kind == "aclaracion" and not review:
        raise HTTPException(status_code=400, detail="Elige la reseña sobre la que quieres publicar una aclaración.")
    if payload.kind == "queja" and not payload.reason:
        raise HTTPException(status_code=400, detail="Elige el motivo de tu queja.")
    text = (payload.text or "").strip()
    if len(text) < 10:
        raise HTTPException(status_code=400, detail="Cuéntanos con más detalle (mínimo 10 caracteres).")
    if payload.kind == "aclaracion" and _has_pii(text):
        raise HTTPException(status_code=400, detail=(
            "La aclaración se publica: no incluyas teléfonos ni correos. Te responderemos al correo de tu solicitud."))

    relation = payload.relation
    if current_user:
        if current_user.id == vet.owner_user_id:
            relation = "clinica"
        name = (payload.name or "").strip() or current_user.full_name
        email = current_user.email if current_user.email and "@" in current_user.email else (payload.email or "").strip()
        ratelimit.check(f"vetreq:user:{current_user.id}", limit=REQUESTS_PER_DAY_USER, window_seconds=86_400,
                        detail="Enviaste muchas solicitudes hoy. Inténtalo mañana.")
    else:
        name = (payload.name or "").strip()
        email = (payload.email or "").strip().lower()
        if len(name) < 3:
            raise HTTPException(status_code=400, detail="Escribe tu nombre para poder responderte.")
        if not _REQUEST_EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail="Escribe un correo válido para poder responderte.")
        if payload.accept_privacy is not True:
            raise HTTPException(status_code=400, detail="Acepta el aviso de privacidad para enviar tu solicitud.")
        ratelimit.check(f"vetreq:ip:{client_ip(request)}", limit=REQUESTS_PER_DAY_IP, window_seconds=86_400,
                        detail="Enviaste muchas solicitudes hoy. Inténtalo mañana.")

    dup = db.query(VeterinaryRequest.id).filter(
        VeterinaryRequest.veterinary_id == vet.id, VeterinaryRequest.kind == payload.kind,
        VeterinaryRequest.status == "pending",
        VeterinaryRequest.review_id == review.id if review else VeterinaryRequest.review_id.is_(None),
        VeterinaryRequest.user_id == current_user.id if current_user else VeterinaryRequest.email == email,
    ).first()
    if dup:
        raise HTTPException(status_code=409, detail="Ya tienes una solicitud igual en revisión. Te responderemos pronto.")

    now = _utcnow()
    days = REQUEST_DUE_BUSINESS_DAYS[payload.kind]
    req = VeterinaryRequest(
        kind=payload.kind, veterinary_id=vet.id, review_id=review.id if review else None,
        user_id=current_user.id if current_user else None, name=name[:255] or None, email=email[:255] or None,
        relation=relation, reason=payload.reason, text=text, status="pending",
        due_at=add_business_days(now, days), created_at=now,
    )
    db.add(req)
    db.flush()
    label = REQUEST_KIND_LABELS[payload.kind]
    _notify_admins(db, "veterinary_request", f"{label} sobre una veterinaria 📨",
                   f"«{vet.name}»: {label.lower()} #{req.id}. Plazo: {days} días hábiles.",
                   {"veterinary_id": vet.id, "veterinary_request_id": req.id})
    db.commit()
    db.refresh(req)
    if not current_user:
        _send_request_email(
            email, f"Recibimos tu {label.lower()} (folio {req.id})",
            f"Recibimos tu {label.lower()} sobre «{vet.name}». La revisaremos y te responderemos a este correo a más "
            f"tardar el {_date_es(req.due_at)} ({days} días hábiles). Folio: {req.id}.",
        )
    return VeterinaryRequestOut(id=req.id, kind=req.kind, status=req.status, due_at=req.due_at,
                                created_at=req.created_at)


@router.get("/admin/veterinary-requests", response_model=list[VeterinaryRequestAdminOut])
def admin_list_requests(
    status_filter: str | None = Query("pending", alias="status"),
    kind: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Aclaraciones y quejas. Pendientes primero las de plazo más próximo."""
    query = db.query(VeterinaryRequest).options(
        joinedload(VeterinaryRequest.veterinary), joinedload(VeterinaryRequest.review))
    if status_filter and status_filter != "all":
        if status_filter not in VETERINARY_REQUEST_STATUSES:
            raise HTTPException(status_code=400, detail="Estado inválido. Usa: pending, published, resolved o rejected.")
        query = query.filter(VeterinaryRequest.status == status_filter)
    if kind:
        if kind not in VETERINARY_REQUEST_KINDS:
            raise HTTPException(status_code=400, detail="Tipo inválido. Usa: aclaracion o queja.")
        query = query.filter(VeterinaryRequest.kind == kind)
    order = (VeterinaryRequest.due_at.asc(),) if status_filter == "pending" else (VeterinaryRequest.created_at.desc(),)
    now = _utcnow()
    return [_request_admin_out(r, now) for r in query.order_by(*order, VeterinaryRequest.id.asc()).offset(skip).limit(limit)]


@router.post("/admin/veterinary-requests/{id}/resolve", response_model=VeterinaryRequestAdminOut)
def admin_resolve_request(
    id: int,
    payload: VeterinaryRequestResolve,
    request: Request,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """publish: publica la aclaración junto a la reseña, sin comentarios; resolve: atendida; reject: no procede.
    Se avisa a quien la presentó (en la app o por correo) y, si se publica, a quien escribió la reseña."""
    req = db.query(VeterinaryRequest).options(
        joinedload(VeterinaryRequest.veterinary), joinedload(VeterinaryRequest.review),
        joinedload(VeterinaryRequest.user)).filter(VeterinaryRequest.id == id).first()
    if not req:
        raise HTTPException(status_code=404, detail="No encontramos esa solicitud.")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="Esta solicitud ya se resolvió.")
    note = payload.note.strip()
    now = _utcnow()
    review = req.review
    if payload.action == "publish":
        if req.kind != "aclaracion" or not review:
            raise HTTPException(status_code=400, detail="Solo se publica una aclaración ligada a una reseña existente.")
        review.clarification = req.text
        review.clarification_at = now
        req.status = "published"
    else:
        req.status = "resolved" if payload.action == "resolve" else "rejected"
    req.resolution_note = note
    req.resolved_by_id = admin_user.id
    req.resolved_at = now
    record_admin_action(db, admin_user, f"veterinary_request.{payload.action}", "veterinary_request", req.id,
                        {"veterinary_id": req.veterinary_id, "review_id": req.review_id, "kind": req.kind,
                         "late": req.due_at < now}, request)
    vet_name = req.veterinary.name if req.veterinary else "la veterinaria"
    label = REQUEST_KIND_LABELS.get(req.kind, "Solicitud")
    outcome = {"published": "Publicamos tu aclaración junto a la reseña", "resolved": "Atendimos tu solicitud",
               "rejected": "Revisamos tu solicitud y no procede"}[req.status]
    body = f"{outcome} sobre «{vet_name}» (folio {req.id}). {note}"
    if req.user and req.user.is_active:
        notify_user(db, req.user, "veterinary_request_resolved", title=f"{label}: respuesta del equipo",
                    body=body, url=f"/app/?vet={req.veterinary_id}", email=True,
                    data={"veterinary_id": req.veterinary_id, "veterinary_request_id": req.id}, commit=False)
    if req.status == "published" and review and review.user and review.user.is_active:
        notify_user(db, review.user, "veterinary_review", title="Se publicó una aclaración en tu reseña",
                    body=f"Junto a tu reseña de «{vet_name}» se publicó una aclaración.",
                    url=f"/app/?vet={req.veterinary_id}",
                    data={"veterinary_id": req.veterinary_id, "veterinary_review_id": review.id}, commit=False)
    db.commit()
    db.refresh(req)
    if not req.user_id:
        _send_request_email(req.email, f"{label}: respuesta del equipo (folio {req.id})", body)
    return _request_admin_out(req, now)
