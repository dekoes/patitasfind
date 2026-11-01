"""Ingesta de publicaciones de Facebook.

La API de Grupos de Facebook fue retirada por Meta en 2024 y GuauWoow no entra a Facebook. Fuentes:
  1. Páginas de Facebook vía Graph API (/{page_id}/posts) con un Page Access Token (este módulo).
  2. Grupos públicos por estado, leídos con un proveedor externo (Apify): app/services/facebook_groups.py.
  3. Importación manual: admins o voluntarios pegan el texto, la URL y las fotos de una publicación.
Todas terminan en create_report_from_post (deduplicado por la URL de la publicación).
"""
import datetime
import logging
import re
import time
import unicodedata

import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.data import estados_mx
from app.models import FacebookGroup, LostReport
from app.services import images, vision

logger = logging.getLogger(__name__)

DOG_WORDS = ("perr", "lomit", "cachorr", "mascota", "canino", "perrit", "firulais")
LOST_WORDS = ("perdid", "extraviad", "se busca", "se perdio", "ayudanos a encontrar", "desaparecid", "se escapo", "recompensa")
FOUND_WORDS = ("encontrad", "rescatad", "se encontro", "aparecio", "deambulando", "busca a su familia",
               "busca a sus duenos", "busca dueno", "anda solito", "anda perdido")
# Las tareas de Celery tienen soft_time_limit=300 s: se deja margen para el resto del trabajo
INGEST_TIME_BUDGET = 240.0
MAX_PHOTOS = 3  # fotos remotas que se descargan por publicación
MAX_LOCAL_PHOTOS = 5  # fotos propias que adjunta un voluntario


class FacebookNotConfigured(RuntimeError):
    pass


class FacebookImportDisabled(RuntimeError):
    """Interruptor legal FB_GROUPS_ENABLED apagado: ninguna importación automática, tampoco de Páginas."""


def _norm(text: str | None) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def classify_post(text: str | None) -> str | None:
    """Devuelve "lost", "found" o None si no parece un reporte de perro."""
    t = _norm(text)
    if not any(w in t for w in DOG_WORDS):
        return None
    if any(w in t for w in FOUND_WORDS):
        return "found"
    if any(w in t for w in LOST_WORDS):
        return "lost"
    return None


def _guess_name(text: str) -> str:
    m = re.search(r"(?:se llama|responde al nombre de|nombre:?)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)", text or "", re.IGNORECASE)
    return m.group(1).capitalize() if m else "Sin nombre"


def canonical_post_url(post_url: str | None) -> str | None:
    """Enlace con el que se deduplica: el canónico de Facebook (sin ?__cft__, m., barra final...) o, si no es de
    Facebook, el enlace tal cual (sin espacios). Todas las fuentes (Páginas, grupos, admins, voluntarios) lo usan."""
    from app.services.facebook_groups import normalize_post_url  # importación diferida: facebook_groups usa este módulo

    raw = (post_url or "").strip()[:500]
    if not raw:
        return None
    return normalize_post_url(raw) or raw


def find_by_post_url(db: Session, post_url: str | None) -> LostReport | None:
    """Reporte que ya se importó de esa publicación (deduplicación por LostReport.external_url)."""
    post_url = canonical_post_url(post_url)
    if not post_url:
        return None
    return db.query(LostReport).filter(LostReport.external_url == post_url).first()


def create_report_from_post(
    db: Session, *, text: str, image_urls: list[str], report_type: str | None, city: str | None,
    post_url: str | None, require_dog: bool = True, state: str | None = None,
    local_photos: list[str] | None = None, source: str = "facebook", reporter_id: int | None = None,
    posted_at: datetime.datetime | None = None, consent_version: str | None = None,
) -> LostReport | None:
    """Crea un reporte a partir de una publicación. None si la publicación ya se importó o la foto no es de un perro.

    image_urls son fotos remotas (se descargan solo de hosts permitidos); local_photos son subidas propias
    (/uploads/...) ya validadas, p. ej. las que adjunta un voluntario. El estado se normaliza o se deduce
    de la ciudad. source: "facebook" (Páginas, grupos, importación de admins) o "volunteer".
    posted_at es la fecha de la publicación original (la caducidad cuenta desde ahí); consent_version, la
    versión de los términos que aceptó el voluntario (se guarda con la fecha). La deduplicación es por el enlace
    canónico, con un índice único en la base: si dos envíos llegan a la vez, el segundo devuelve None.
    """
    from app.services.facebook_groups import strip_pii  # importación diferida: facebook_groups usa este módulo

    post_url = canonical_post_url(post_url)
    if find_by_post_url(db, post_url):
        return None
    # Todas las fuentes (Páginas, grupos, admins, voluntarios): sin teléfonos, correos, enlaces, datos de pago ni
    # nombres de contacto antes de guardar (idempotente si ya venía limpio)
    text = strip_pii(text)
    report_type = report_type if report_type in ("lost", "found") else (classify_post(text) or "found")

    stored = list(local_photos or [])[:MAX_LOCAL_PHOTOS]
    for url in (image_urls or [])[:MAX_PHOTOS]:
        if len(stored) >= MAX_LOCAL_PHOTOS:
            break
        local = images.download_and_store(url)
        if local:
            stored.append(local)

    analysis = None
    if stored and vision.is_configured():
        try:
            analysis = vision.analyze_url(stored[0])
        except vision.AINotConfigured:
            analysis = None
        if require_dog and analysis is not None and analysis.get("is_dog") is False:
            logger.info("Publicación descartada: la foto no parece de un perro (%s)", post_url)
            return None

    description = (text or "").strip()[:3000]
    if analysis and analysis.get("description_es"):
        description = f"{analysis['description_es']}\n\n{description}" if description else analysis["description_es"]
    if post_url:
        description += f"\n\nPublicación original: {post_url}"

    report = LostReport(
        reporter_id=reporter_id,
        dog_name="Perrito encontrado" if report_type == "found" else _guess_name(text),
        report_type=report_type,
        description=description,
        city=(city or "").strip()[:100] or None,
        state=estados_mx.derive_state(state, city),
        country="México",
        photos=stored,
        status="active",
        source=source if source in ("facebook", "volunteer") else "facebook",
        external_url=post_url,
        external_posted_at=posted_at if posted_at and posted_at <= datetime.datetime.utcnow() else None,
        consent_at=datetime.datetime.utcnow() if consent_version else None,
        consent_version=(consent_version or None) and consent_version[:20],
        ai_analysis=analysis,
        photo_signature=vision.signature_for_urls(stored) if stored else None,
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        # Otro envío de la misma publicación ganó la carrera (índice único uq_lost_reports_external_url)
        db.rollback()
        logger.info("Publicación ya importada por otro envío simultáneo: %s", post_url)
        return None
    db.refresh(report)
    return report


def ingest_page(db: Session, source: FacebookGroup, time_budget_seconds: float = INGEST_TIME_BUDGET) -> list[int]:
    """Lee las publicaciones nuevas de una Página y crea reportes. Devuelve los IDs creados.

    Si se acaba `time_budget_seconds` se detiene sin mover last_scraped: la siguiente corrida retoma
    (las publicaciones ya importadas se saltan por su URL sin descargar nada).
    """
    # Un solo punto para todos los que llaman (tarea horaria y botones del panel): sin el interruptor legal no se
    # importa nada automáticamente aunque haya token de Páginas (contrato L-fb)
    if not settings.fb_groups_enabled:
        raise FacebookImportDisabled("Importación de Facebook apagada (FB_GROUPS_ENABLED=false)")
    if not settings.facebook_enabled:
        raise FacebookNotConfigured("Falta FACEBOOK_PAGE_ACCESS_TOKEN")
    if source.kind != "page" or not source.page_id:
        raise ValueError("Esta fuente es manual: importa sus publicaciones desde el formulario.")

    params = {
        "fields": "message,full_picture,created_time,permalink_url",
        "limit": 50,
        "access_token": settings.facebook_page_access_token,
    }
    if source.last_scraped:
        params["since"] = int(source.last_scraped.replace(tzinfo=datetime.timezone.utc).timestamp())
    url = f"https://graph.facebook.com/{settings.graph_api_version}/{source.page_id}/posts"
    created: list[int] = []
    pages = 0
    deadline = time.monotonic() + time_budget_seconds
    while url and pages < 5:
        try:
            resp = requests.get(url, params=params, timeout=20)
        except requests.RequestException as exc:
            raise RuntimeError(f"No se pudo conectar con Facebook: {exc}") from exc
        if resp.status_code >= 400:
            logger.error("Graph API %s: %s", resp.status_code, resp.text[:400])
            raise RuntimeError("Facebook rechazó la solicitud. Revisa el token y el ID de la página.")
        payload = resp.json()
        for post in payload.get("data") or []:
            if time.monotonic() > deadline:
                logger.warning("Ingesta de la página %s cortada por tiempo; se retoma en la siguiente corrida.",
                               source.page_id)
                return created
            text = post.get("message") or ""
            kind = classify_post(text)
            if not kind:
                continue
            from app.services.facebook_groups import parse_datetime

            report = create_report_from_post(
                db, text=text, image_urls=[post["full_picture"]] if post.get("full_picture") else [],
                report_type=kind, city=source.city, state=source.state, post_url=post.get("permalink_url"),
                posted_at=parse_datetime(post.get("created_time")),
            )
            if report:
                created.append(report.id)
        url = (payload.get("paging") or {}).get("next")
        params = None  # la URL "next" ya trae los parámetros
        pages += 1

    source.last_scraped = datetime.datetime.utcnow()
    db.commit()
    return created


def scrape_group(db: Session, group_id: int) -> int:
    """Compatibilidad: procesa una fuente y devuelve cuántos reportes se crearon."""
    source = db.query(FacebookGroup).filter(FacebookGroup.id == group_id).first()
    if source is None:
        raise LookupError("No encontramos esa fuente de Facebook.")
    return len(ingest_page(db, source))
