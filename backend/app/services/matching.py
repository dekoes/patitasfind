"""Coincidencias entre reportes de perros perdidos/encontrados y perros en adopción."""
import logging

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
    distance = None
    if lat is not None and lon is not None and obj.latitude is not None and obj.longitude is not None:
        distance = round(haversine_km(lat, lon, obj.latitude, obj.longitude), 2)
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
        LostReport.status == "active", LostReport.report_type == opposite, LostReport.id != report.id
    )
    has_geo = (lat is not None and lon is not None) or bool(city)
    reports = (
        _geo_filter(base, LostReport, lat, lon, city, REPORT_RADIUS_KM) if has_geo else base
    ).order_by(LostReport.created_at.desc()).limit(MAX_CANDIDATES).all()
    reports = [r for r in reports if _within(r, lat, lon, REPORT_RADIUS_KM) or (city and r.city and city.lower() in r.city.lower())]
    items = list(reports)
    if report.report_type == "lost":
        # Un perro perdido pudo haber sido rescatado y publicado en adopción
        dogs_q = db.query(Dog).filter(Dog.status == "available")
        dogs = (
            _geo_filter(dogs_q, Dog, lat, lon, city, REPORT_RADIUS_KM) if has_geo else dogs_q
        ).order_by(Dog.created_at.desc()).limit(MAX_CANDIDATES).all()
        items += [d for d in dogs if _within(d, lat, lon, REPORT_RADIUS_KM) or (city and d.city and city.lower() in d.city.lower())]
    return items


def score_against(db: Session, query_sig, query_attrs, items, lat=None, lon=None) -> list[dict]:
    results = []
    for item in items:
        if not item.photo_signature and item.photos:
            ensure_enrichment(db, item, with_ai=False, commit=False)
        score = vision.combined_score(query_sig, query_attrs, item.photo_signature, attributes_for(item))
        if score > 0:
            results.append(_candidate_dict(item, score, lat, lon))
    db.commit()
    results.sort(key=lambda r: (-r["score"], r["distance_km"] if r["distance_km"] is not None else 1e9))
    return results


def matches_for_report(db: Session, report: LostReport, limit: int = 10) -> list[dict]:
    if not report.photo_signature and report.photos:
        ensure_enrichment(db, report, with_ai=False)
    items = candidates_for_report(db, report)
    return score_against(db, report.photo_signature, attributes_for(report), items, report.latitude, report.longitude)[:limit]


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
    from app.utils.notifications import create_notification

    report = db.query(LostReport).filter(LostReport.id == report_id).first()
    if not report:
        return []
    ensure_enrichment(db, report, with_ai=True)
    matches = matches_for_report(db, report, limit=10)
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
                create_notification(
                    db,
                    user_id=mine.reporter_id,
                    type="possible_match",
                    title="¡Posible coincidencia!",
                    body=(
                        f"Encontramos un reporte de perro {'encontrado' if theirs.report_type == 'found' else 'perdido'} "
                        f"que se parece a {mine.dog_name} ({m['score']}% de similitud). Revísalo."
                    ),
                    data={"dedupe": key, "report_id": mine.id, "match_report_id": theirs.id, "score": m["score"]},
                )
        # Reportes previos que llegaron por WhatsApp: avisamos al número de contacto
        if other.source == "whatsapp" and other.contact_phone and not other.reporter_id:
            _notify_whatsapp(other, report, m["score"], key)
    return matches


_wa_sent: set[str] = set()


def _notify_whatsapp(target: LostReport, new_report: LostReport, score: int, key: str):
    from app import cache
    from app.services import whatsapp_api

    dedupe = f"wa-match:{key}"
    if dedupe in _wa_sent or cache.get(dedupe):
        return
    _wa_sent.add(dedupe)
    cache.set(dedupe, 1, ttl=60 * 60 * 24 * 30)
    kind = "encontrado" if new_report.report_type == "found" else "perdido"
    whatsapp_api.send_text(
        target.contact_phone,
        f"🐶 ¡Posible coincidencia! Alguien reportó un perro {kind} que se parece al de tu reporte #{target.id} "
        f"({score}% de similitud).\nMíralo aquí: {settings.public_url(f'/app/?report={new_report.id}')}",
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
        base = db.query(LostReport).filter(LostReport.status == "active")
        if report_type in ("lost", "found"):
            base = base.filter(LostReport.report_type == report_type)
        items += collect(LostReport, base)
    if want_dogs:
        items += collect(Dog, db.query(Dog).filter(Dog.status == "available"))

    query_attrs = analysis if analysis and analysis.get("is_dog", True) else None
    matches = score_against(db, query_sig, query_attrs, items, lat, lon)[:10]
    return analysis, matches
