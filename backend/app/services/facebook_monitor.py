"""Ingesta de publicaciones de Facebook.

Nota honesta: la API de Grupos de Facebook fue retirada por Meta en 2024 y hacer scraping de
grupos viola sus términos. Por eso aquí solo se soporta:
  1. Páginas de Facebook vía Graph API (/{page_id}/posts) con un Page Access Token.
  2. Importación manual: voluntarios pegan el texto, la URL y las fotos de una publicación.
"""
import datetime
import logging
import re
import unicodedata

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models import FacebookGroup, LostReport
from app.services import images, vision

logger = logging.getLogger(__name__)

DOG_WORDS = ("perr", "lomit", "cachorr", "mascota", "canino", "perrit", "firulais")
LOST_WORDS = ("perdid", "extraviad", "se busca", "se perdio", "ayudanos a encontrar", "desaparecid", "se escapo", "recompensa")
FOUND_WORDS = ("encontrad", "rescatad", "se encontro", "aparecio", "deambulando", "busca a su familia",
               "busca a sus duenos", "busca dueno", "anda solito", "anda perdido")


class FacebookNotConfigured(RuntimeError):
    pass


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


def create_report_from_post(
    db: Session, *, text: str, image_urls: list[str], report_type: str | None, city: str | None,
    post_url: str | None, require_dog: bool = True,
) -> LostReport | None:
    if post_url:
        existing = db.query(LostReport).filter(LostReport.external_url == post_url).first()
        if existing:
            return None
    report_type = report_type if report_type in ("lost", "found") else (classify_post(text) or "found")

    stored = []
    for url in (image_urls or [])[:3]:
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
        reporter_id=None,
        dog_name="Perrito encontrado" if report_type == "found" else _guess_name(text),
        report_type=report_type,
        description=description,
        city=city,
        country="México",
        photos=stored,
        status="active",
        source="facebook",
        external_url=post_url,
        ai_analysis=analysis,
        photo_signature=vision.signature_for_urls(stored) if stored else None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def ingest_page(db: Session, source: FacebookGroup) -> list[int]:
    """Lee las publicaciones nuevas de una Página y crea reportes. Devuelve los IDs creados."""
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
            text = post.get("message") or ""
            kind = classify_post(text)
            if not kind:
                continue
            report = create_report_from_post(
                db, text=text, image_urls=[post["full_picture"]] if post.get("full_picture") else [],
                report_type=kind, city=source.city, post_url=post.get("permalink_url"),
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
