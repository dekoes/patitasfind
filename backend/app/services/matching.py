"""Coincidencias entre reportes de perros perdidos/encontrados y perros en adopción.

Dentro de una petición nunca se decodifican fotos: solo se usan las firmas ya calculadas y las que
faltan se encargan a Celery (o a BackgroundTasks). Las tareas sí enriquecen en el momento (enrich=True).
"""
import logging
from collections import OrderedDict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Dog, LostReport, Notification
from app.services import vision
from app.services.geo import bounding_box, haversine_km

logger = logging.getLogger(__name__)

REPORT_RADIUS_KM = 10.0
SEARCH_RADIUS_KM = 50.0
MAX_CANDIDATES = 300
MATCHES_CACHE_PREFIX = "lr-matches:"
ENRICH_DEDUPE_SECONDS = 60 * 60  # no volver a encargar la misma firma durante 1 h


# --------------------------------------------------------------------------- enriquecimiento
def ensure_enrichment(db: Session, obj, with_ai: bool = True, commit: bool = True) -> bool:
    """Calcula photo_signature (y ai_analysis si hay llave) cuando falten o cambien las fotos."""
    changed = False
    photos = [p for p in (obj.photos or []) if isinstance(p, str) and p]
    sig_urls = [p.get("url") for p in ((obj.photo_signature or {}).get("photos") or [])]
    if photos and (not obj.photo_signature or sig_urls != photos[: len(sig_urls)] or not sig_urls):
        sig = vision.signature_for_urls(photos)
        if sig:
            obj.photo_signature = sig
            changed = True
    if with_ai and vision.is_configured() and photos:
        current = obj.ai_analysis or {}
        if current.get("url") != photos[0]:
            try:
                analysis = vision.analyze_url(photos[0])
            except vision.AINotConfigured:
                analysis = None
            if analysis:
                obj.ai_analysis = analysis
                changed = True
    if changed and commit:
        db.commit()
    return changed


def attributes_for(obj) -> dict | None:
    """Atributos comparables: análisis IA si existe; si no, los campos capturados del perro."""
    if obj.ai_analysis and obj.ai_analysis.get("is_dog", True):
        return obj.ai_analysis
    if isinstance(obj, Dog):
        attrs = {"breed_guess": obj.breed or "", "size": obj.size or "", "colors": [obj.color] if obj.color else []}
        if any(attrs.values()):
            return attrs
    return None


def _candidate_dict(obj, score: int, lat=None, lon=None) -> dict:
    from app.services.privacy import public_distance

    # Resultado público: distancia desde las coordenadas aproximadas del candidato (no permite triangular)
    distance = public_distance(obj, lat, lon)
    if isinstance(obj, Dog):
        return {"type": "adoption", "id": obj.id, "name": obj.name, "city": obj.city, "photos": obj.photos or [],
                "score": score, "distance_km": distance}
    return {"type": obj.report_type, "id": obj.id, "name": obj.dog_name, "city": obj.city, "photos": obj.photos or [],
            "score": score, "distance_km": distance}


def _geo_filter(query, model, lat, lon, city, radius_km):
    conditions = []
    if lat is not None and lon is not None:
        min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
        conditions.append(
            (model.latitude.between(min_lat, max_lat)) & (model.longitude.between(min_lon, max_lon))
        )
    if city:
        conditions.append(model.city.ilike(f"%{city.strip()}%"))
    if conditions:
        query = query.filter(or_(*conditions))
    return query


def _within(obj, lat, lon, radius_km) -> bool:
    if lat is None or lon is None or obj.latitude is None or obj.longitude is None:
        return True  # sin coordenadas: ya pasó el filtro por ciudad
    return haversine_km(lat, lon, obj.latitude, obj.longitude) <= radius_km


def candidates_for_report(db: Session, report: LostReport) -> list:
    opposite = "found" if report.report_type == "lost" else "lost"
    lat, lon, city = report.latitude, report.longitude, report.city
    base = db.query(LostReport).filter(
        LostReport.status == "active", LostReport.report_type == opposite, LostReport.id != report.id,
        LostReport.is_hidden == False,  # noqa: E712
    )
    has_geo = (lat is not None and lon is not None) or bool(city)
    reports = (
        _geo_filter(base, LostReport, lat, lon, city, REPORT_RADIUS_KM) if has_geo else base
    ).order_by(LostReport.created_at.desc()).limit(MAX_CANDIDATES).all()
    reports = [r for r in reports if _within(r, lat, lon, REPORT_RADIUS_KM) or (city and r.city and city.lower() in r.city.lower())]
    items = list(reports)
    if report.report_type == "lost":
        # Un perro perdido pudo haber sido rescatado y publicado en adopción
        dogs_q = db.query(Dog).filter(Dog.status == "available", Dog.is_hidden == False)  # noqa: E712
        dogs = (
            _geo_filter(dogs_q, Dog, lat, lon, city, REPORT_RADIUS_KM) if has_geo else dogs_q
        ).order_by(Dog.created_at.desc()).limit(MAX_CANDIDATES).all()
        items += [d for d in dogs if _within(d, lat, lon, REPORT_RADIUS_KM) or (city and d.city and city.lower() in d.city.lower())]
    return items


def _needs_signature(obj) -> bool:
    return not obj.photo_signature and bool(obj.photos)


def enqueue_enrichment(items, background_tasks=None) -> int:
    """Encarga en segundo plano las firmas que faltan (sin IA). Devuelve cuántas faltaban.

    Con Celery va a la cola; sin Celery, a BackgroundTasks si la petición lo da. Nunca corre aquí mismo.
    """
    from app import cache

    missing = [i for i in items if _needs_signature(i)]
    pending: dict[str, list[int]] = {"dog": [], "lost_report": []}
    for item in missing:
        kind = "dog" if isinstance(item, Dog) else "lost_report"
        if cache.add(f"enrich-q:{kind}:{item.id}", ENRICH_DEDUPE_SECONDS):
            pending[kind].append(item.id)
    from app.tasks.matching import enrich_signatures

    for kind, ids in pending.items():
        if not ids:
            continue
        try:
            if settings.celery_enabled:
                enrich_signatures.delay(kind, ids)
            elif background_tasks is not None:
                background_tasks.add_task(enrich_signatures, kind, ids)
        except Exception as exc:  # noqa: BLE001 - broker caído: lo completa el backfill horario
            logger.warning("No se pudieron encargar firmas de %s %s: %s", kind, ids[:5], exc)
    return len(missing)


def _score(db: Session, query_sig, query_attrs, items, lat=None, lon=None, enrich=False, background_tasks=None):
    """(resultados ordenados, cuántos candidatos no tenían firma)."""
    if enrich:
        for item in items:
            if _needs_signature(item):
                ensure_enrichment(db, item, with_ai=False, commit=False)
        db.commit()
        missing = 0
    else:
        missing = enqueue_enrichment(items, background_tasks)
    results = []
    for item in items:
        score = vision.combined_score(query_sig, query_attrs, item.photo_signature, attributes_for(item))
        if score > 0:
            results.append(_candidate_dict(item, score, lat, lon))
    results.sort(key=lambda r: (-r["score"], r["distance_km"] if r["distance_km"] is not None else 1e9))
    return results, missing


def score_against(db: Session, query_sig, query_attrs, items, lat=None, lon=None, enrich=False,
                  background_tasks=None) -> list[dict]:
    return _score(db, query_sig, query_attrs, items, lat, lon, enrich, background_tasks)[0]


def _matches(db: Session, report: LostReport, limit: int, enrich: bool, background_tasks=None):
    missing = 0
    if _needs_signature(report):
        if enrich:
            ensure_enrichment(db, report, with_ai=False)
        else:
            missing += enqueue_enrichment([report], background_tasks)
    items = candidates_for_report(db, report)
    results, missing_items = _score(db, report.photo_signature, attributes_for(report), items,
                                    report.latitude, report.longitude, enrich, background_tasks)
    return results[:limit], missing + missing_items


def matches_for_report(db: Session, report: LostReport, limit: int = 10, enrich: bool = False,
                       background_tasks=None) -> list[dict]:
    return _matches(db, report, limit, enrich, background_tasks)[0]


# --------------------------------------------------------------------------- caché de coincidencias
def matches_cache_key(report_id: int) -> str:
    return f"{MATCHES_CACHE_PREFIX}{report_id}"


def invalidate_report_matches(*report_ids: int):
    """Borra las coincidencias en caché de esos reportes (cambiaron o se recalcularon)."""
    from app import cache

    cache.delete(*[matches_cache_key(i) for i in report_ids if i])


def cached_matches_for_report(db: Session, report: LostReport, limit: int = 10, background_tasks=None) -> list[dict]:
    """Coincidencias para la petición pública, 10 min en Redis.

    Si faltaban firmas (recién publicado) no se guarda: en cuanto Celery las calcula, la siguiente
    consulta ya trae el resultado completo.
    """
    from app import cache

    key = matches_cache_key(report.id)
    hit = cache.get(key)
    if isinstance(hit, list):
        return hit[:limit]
    results, missing = _matches(db, report, limit, enrich=False, background_tasks=background_tasks)
    if not missing:
        cache.set(key, results, ttl=settings.matches_cache_ttl_seconds)
    return results


# --------------------------------------------------------------------------- notificaciones
def _already_notified(db: Session, user_id: int, key: str) -> bool:
    recent = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.type == "possible_match")
        .order_by(Notification.created_at.desc())
        .limit(300)
        .all()
    )
    return any((n.data or {}).get("dedupe") == key for n in recent)


def run_report_matching(db: Session, report_id: int) -> list[dict]:
    """Enriquece el reporte, busca coincidencias y notifica a ambas partes (score >= umbral)."""
    from app.services.notify import notify_report_match

    report = db.query(LostReport).filter(LostReport.id == report_id).first()
    if not report:
        return []
    ensure_enrichment(db, report, with_ai=True)
    matches = matches_for_report(db, report, limit=10, enrich=True)
    # Recién calculado: queda en caché para /lost-reports/{id}/matches y se invalida el de los
    # reportes que ahora coinciden con este (su lista pudo cambiar)
    from app import cache

    cache.set(matches_cache_key(report.id), matches, ttl=settings.matches_cache_ttl_seconds)
    invalidate_report_matches(*[m["id"] for m in matches if m["type"] in ("lost", "found")])
    strong = [m for m in matches if m["score"] >= settings.match_score_threshold]
    for m in strong:
        if m["type"] == "adoption":
            continue
        other = db.query(LostReport).filter(LostReport.id == m["id"]).first()
        if not other:
            continue
        pair = sorted([report.id, other.id])
        key = f"lr:{pair[0]}:{pair[1]}"
        for mine, theirs in ((report, other), (other, report)):
            if mine.reporter_id and not _already_notified(db, mine.reporter_id, key):
                # En la app y, si están configurados, por correo y plantilla de WhatsApp
                notify_report_match(db, mine, theirs, m["score"], key)
        # Reportes previos que llegaron por WhatsApp: avisamos al número de contacto
        if other.source == "whatsapp" and other.contact_phone and not other.reporter_id:
            _notify_whatsapp(other, report, m["score"], key)
    return matches


class _BoundedSet:
    """Conjunto en memoria con tope (descarta lo más viejo); la deduplicación real vive en Redis."""

    def __init__(self, maxlen: int):
        self.maxlen = maxlen
        self._items: OrderedDict[str, None] = OrderedDict()

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def add(self, key: str):
        self._items[key] = None
        self._items.move_to_end(key)
        while len(self._items) > self.maxlen:
            self._items.popitem(last=False)


_wa_sent = _BoundedSet(maxlen=5000)


def is_whatsapp_opted_out(phone: str | None) -> bool:
    """True si ese número escribió BAJA/STOP al bot (se compara por los últimos 10 dígitos)."""
    import re

    from app.database import SessionLocal
    from app.models import BotInteraction

    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 10:
        return False
    db = SessionLocal()
    try:
        return db.query(BotInteraction.id).filter(
            BotInteraction.phone.like(f"%{digits[-10:]}"), BotInteraction.opted_out_at.isnot(None)
        ).first() is not None
    finally:
        db.close()


def has_whatsapp_consent(phone: str | None) -> bool:
    """True si la última constancia de «Avisos por WhatsApp» de ese número es un sí (respondió que sí en el bot,
    escribió ALTA o lo activó en la app). Sin constancia no hay avisos proactivos (privacidad-whatsapp.html §5)."""
    from app.database import SessionLocal
    from app.services import consent

    db = SessionLocal()
    try:
        return consent.latest_phone_consent(db, phone) is True
    finally:
        db.close()


def _notify_whatsapp(target: LostReport, new_report: LostReport, score: int, key: str):
    from app import cache
    from app.services import notify

    if is_whatsapp_opted_out(target.contact_phone):
        logger.info("No se envía alerta por WhatsApp al reporte %s: el número se dio de baja.", target.id)
        return
    if not has_whatsapp_consent(target.contact_phone):
        logger.info("No se envía alerta por WhatsApp al reporte %s: el número no dio permiso de avisos.", target.id)
        return
    dedupe = f"wa-match:{key}"
    if dedupe in _wa_sent or cache.get(dedupe):
        return
    _wa_sent.add(dedupe)
    cache.set(dedupe, 1, ttl=60 * 60 * 24 * 30)
    kind = "encontrado" if new_report.report_type == "found" else "perdido"
    link = settings.public_url(f"/app/?report={new_report.id}")
    # Texto libre solo dentro de la ventana de 24 h; fuera de ella, la plantilla WHATSAPP_TEMPLATE_MATCH
    notify.send_whatsapp(
        target.contact_phone,
        f"🐶 ¡Posible coincidencia! Alguien reportó un perro {kind} que se parece al de tu reporte #{target.id} "
        f"({score}% de similitud).\nMíralo aquí: {link}",
        settings.whatsapp_template_match,
        [f"{target.dog_name} (reporte #{target.id})", link],
    )


def search_by_photo(db: Session, data: bytes, lat=None, lon=None, city=None, report_type=None, use_ai=True):
    sig_one = vision.image_signature(data)
    query_sig = {"v": 1, "photos": [sig_one]} if sig_one else None
    analysis = None
    if use_ai and vision.is_configured():
        try:
            analysis = vision.analyze_image_bytes(data)
        except vision.AINotConfigured:
            analysis = None

    items = []
    want_reports = report_type in (None, "", "lost", "found")
    want_dogs = report_type in (None, "", "adoption")

    def collect(model, base):
        q = _geo_filter(base, model, lat, lon, None if (lat is not None and lon is not None) else city, SEARCH_RADIUS_KM) \
            if ((lat is not None and lon is not None) or city) else base
        found = q.order_by(model.created_at.desc()).limit(MAX_CANDIDATES).all()
        found = [f for f in found if _within(f, lat, lon, SEARCH_RADIUS_KM)]
        if not found:  # sin resultados cerca: buscar en todo
            found = base.order_by(model.created_at.desc()).limit(MAX_CANDIDATES).all()
        return found

    if want_reports:
        base = db.query(LostReport).filter(LostReport.status == "active", LostReport.is_hidden == False)  # noqa: E712
        if report_type in ("lost", "found"):
            base = base.filter(LostReport.report_type == report_type)
        items += collect(LostReport, base)
    if want_dogs:
        items += collect(Dog, db.query(Dog).filter(Dog.status == "available", Dog.is_hidden == False))  # noqa: E712

    query_attrs = analysis if analysis and analysis.get("is_dog", True) else None
    matches = score_against(db, query_sig, query_attrs, items, lat, lon)[:10]
    return analysis, matches
