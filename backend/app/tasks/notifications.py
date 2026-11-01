"""Tareas de avisos: correo, WhatsApp y alertas de perritos perdidos/encontrados cerca."""
import datetime
import logging
import re

from sqlalchemy import func, or_

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

MAX_PARTNERS = 50  # refugios y casas de paso por alerta


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def send_notification_email(self, to: str, title: str, body: str, url: str | None = None):
    from app.services.notify import send_email_now

    return send_email_now(to, title, body, url)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def send_whatsapp_notification(self, phone: str, text: str, template_name: str | None = None, params: list | None = None):
    from app.services.notify import send_whatsapp

    return send_whatsapp(phone, text, template_name, params or [])


# --------------------------------------------------------------------------- alertas cercanas
def _distance_km_sql(lat_col, lon_col, lat: float, lon: float):
    """Haversine en SQL (km), para filtrar y ordenar en la base de datos."""
    from app.services.geo import EARTH_RADIUS_KM

    dlat = func.radians(lat_col - lat)
    dlon = func.radians(lon_col - lon)
    a = (
        func.power(func.sin(dlat / 2), 2)
        + func.cos(func.radians(lat)) * func.cos(func.radians(lat_col)) * func.power(func.sin(dlon / 2), 2)
    )
    return 2 * EARTH_RADIUS_KM * func.asin(func.sqrt(func.least(1.0, a)))


def _within(query, model_lat, model_lon, lat: float, lon: float, radius_km: float):
    """Caja (usa el índice de latitud/longitud) + distancia exacta en SQL. Devuelve (query, distancia)."""
    from app.services.geo import bounding_box

    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
    dist = _distance_km_sql(model_lat, model_lon, lat, lon)
    query = query.filter(
        model_lat.isnot(None), model_lon.isnot(None),
        model_lat.between(min_lat, max_lat), model_lon.between(min_lon, max_lon),
        dist <= radius_km,
    )
    return query, dist


def nearby_recipients(db, report) -> list[tuple]:
    """[(user, distance_km | None)] a quienes avisar de `report`, sin repetir y sin quien lo publicó.

    - Usuarios con notify_nearby a <= NEARBY_ALERT_RADIUS_KM (máx. NEARBY_ALERT_MAX_RECIPIENTS).
    - Responsables de refugios y casas de paso aprobados a <= NEARBY_ALERT_PARTNER_RADIUS_KM (según la
      ubicación de su cuenta) o, si no hay coordenadas, de la misma ciudad.
    """
    from app.config import settings
    from app.models import FosterHome, Refuge, User
    from app.services.consent import nearby_consent_clause

    # K-PREF: interruptor encendido Y constancia de consentimiento vigente (la más reciente es un «sí»)
    base = db.query(User).filter(User.notify_nearby == True, User.is_active == True,  # noqa: E712
                                 nearby_consent_clause(User))
    if report.reporter_id:
        base = base.filter(User.id != report.reporter_id)
    digits = re.sub(r"\D", "", report.contact_phone or "")
    if len(digits) >= 10:  # reportes de WhatsApp: no avisar a la cuenta con ese mismo número
        base = base.filter(or_(User.phone.is_(None), ~User.phone.like(f"%{digits[-10:]}")))

    lat, lon = report.latitude, report.longitude
    found: dict[int, tuple] = {}
    if lat is not None and lon is not None:
        q, dist = _within(base, User.latitude, User.longitude, lat, lon, settings.nearby_alert_radius_km)
        for user, d in q.add_columns(dist).order_by(dist).limit(settings.nearby_alert_max_recipients).all():
            found[user.id] = (user, round(float(d), 1))

    partners = or_(
        User.id.in_(db.query(Refuge.user_id).filter(Refuge.status == "approved")),
        User.id.in_(db.query(FosterHome.user_id).filter(FosterHome.status == "approved")),
    )
    partner_q = base.filter(partners)
    if lat is not None and lon is not None:
        q, dist = _within(partner_q, User.latitude, User.longitude, lat, lon, settings.nearby_alert_partner_radius_km)
        for user, d in q.add_columns(dist).order_by(dist).limit(MAX_PARTNERS).all():
            found.setdefault(user.id, (user, round(float(d), 1)))
    city = (report.city or "").strip().lower()
    if city:
        same_city = or_(
            User.id.in_(db.query(Refuge.user_id).filter(
                Refuge.status == "approved", func.lower(func.trim(Refuge.city)) == city)),
            User.id.in_(db.query(FosterHome.user_id).filter(
                FosterHome.status == "approved", func.lower(func.trim(FosterHome.city)) == city)),
        )
        q = partner_q.filter(same_city)
        if lat is not None and lon is not None:
            q = q.filter(or_(User.latitude.is_(None), User.longitude.is_(None)))  # los que tienen coordenadas ya se evaluaron
        for user in q.limit(MAX_PARTNERS).all():
            found.setdefault(user.id, (user, None))
    return list(found.values())


def _daily_counts(db, user_ids: list[int]) -> dict[int, int]:
    """Alertas cercanas ya recibidas hoy (respaldo en la base de datos cuando no hay Redis)."""
    from app.models import Notification

    if not user_ids:
        return {}
    today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(Notification.user_id, func.count(Notification.id))
        .filter(Notification.type == "nearby_alert", Notification.created_at >= today, Notification.user_id.in_(user_ids))
        .group_by(Notification.user_id)
        .all()
    )
    return {uid: n for uid, n in rows}


def _cap_key(user_id: int) -> str:
    return f"nearby:cap:{user_id}:{datetime.datetime.utcnow():%Y%m%d}"


def _under_daily_cap(r, user_id: int, cap: int, fallback: dict[int, int], charged: list[str]) -> bool:
    """Cuenta un aviso para `user_id` y dice si todavía cabe en el tope diario.

    Las llaves de Redis que incrementa se anotan en `charged` para devolverlas si la tarea falla.
    """
    if r is not None:
        key = _cap_key(user_id)
        try:
            count = r.incr(key)
            charged.append(key)
            if count == 1:
                r.expire(key, 2 * 24 * 60 * 60)
            return count <= cap
        except Exception:  # noqa: BLE001
            pass
    if fallback.get(user_id, 0) >= cap:
        return False
    fallback[user_id] = fallback.get(user_id, 0) + 1
    return True


def _release(r, lock_key: str | None, charged: list[str]):
    """Deshace lo anotado en Redis por una tarea que falló: libera el candado y regresa los conteos del tope."""
    if r is None:
        return
    try:
        pipe = r.pipeline()
        if lock_key:
            pipe.delete(lock_key)
        for key in charged:
            pipe.decr(key)
        pipe.execute()
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo liberar en Redis el candado %s de la alerta cercana.", lock_key)


def _alert_texts(report, distance_km: float | None) -> tuple[str, str, str]:
    """(título, cuerpo, resumen para la plantilla de WhatsApp)."""
    where = f"a {distance_km:.1f} km de ti" if distance_km is not None else f"en {report.city}"
    place = f" ({report.city})" if report.city and distance_km is not None else ""
    if report.report_type == "found":
        title = "🐾 Encontraron un perrito cerca de ti"
        summary = f"encontraron un perrito {where}{place}"
        body = f"Alguien encontró un perrito {where}{place}. ¿Es tuyo o conoces a su familia? Revisa las fotos."
    else:
        name = (report.dog_name or "").strip()
        dog = "un perrito" if not name or name.lower() in ("sin nombre", "perrito encontrado") else name
        title = "🐶 Perrito perdido cerca de ti"
        summary = f"se perdió {dog} {where}{place}"
        body = f"Se perdió {dog} {where}{place}. Si lo ves, avisa en GuauWoow: cada minuto cuenta."
    return title, body, summary


NEARBY_LOCK_TTL = 15 * 60  # candado "en curso" por reporte: cubre task_time_limit con margen
NEARBY_DONE_TTL = 7 * 24 * 60 * 60  # marca "listo": la misma alerta no se repite aunque se vuelva a encolar


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def notify_nearby_report(self, report_id: int) -> int:
    """Avisa de un reporte nuevo de perro perdido/encontrado a quienes están cerca. Devuelve cuántos avisos creó.

    Si falla algo pasajero (base de datos, correo) se libera el candado, se regresan los conteos del tope
    diario y la tarea se reintenta, para que la alerta no se pierda.
    """
    from app import cache
    from app.config import settings
    from app.database import SessionLocal
    from app.models import LostReport
    from app.services.notify import absolute_url, notify_user

    r = cache._get_redis()
    lock_key = f"nearby:report:{report_id}"
    locked = False
    charged: list[str] = []  # llaves del tope diario incrementadas en esta corrida
    db = SessionLocal()
    try:
        report = db.query(LostReport).filter(LostReport.id == report_id).first()
        if (
            not report or report.status != "active" or report.is_hidden
            or report.report_type not in ("lost", "found") or report.source == "facebook"
        ):
            return 0
        if r is not None:
            try:
                # Una sola vez por reporte aunque la tarea se encole dos veces. El candado se marca como
                # "listo" solo cuando los avisos ya quedaron guardados; si falla antes, se libera.
                locked = bool(r.set(lock_key, "en_curso", nx=True, ex=NEARBY_LOCK_TTL))
                if not locked:
                    return 0
            except Exception:  # noqa: BLE001
                r = None
        recipients = nearby_recipients(db, report)
        fallback = _daily_counts(db, [u.id for u, _ in recipients]) if r is None else {}
        url = f"/app/?report={report.id}"
        created = 0
        for user, distance_km in recipients:
            if not _under_daily_cap(r, user.id, settings.nearby_alert_daily_cap, fallback, charged):
                continue
            title, body, summary = _alert_texts(report, distance_km)
            notify_user(
                db, user, "nearby_alert", title, body, url=url, email=True,
                whatsapp_template=settings.whatsapp_template_nearby,
                template_params=[summary, absolute_url(url)],
                data={"report_id": report.id, "report_type": report.report_type, "distance_km": distance_km},
                commit=False,
            )
            created += 1
        db.commit()
        if r is not None:
            try:
                r.set(lock_key, "listo", ex=NEARBY_DONE_TTL)
            except Exception:  # noqa: BLE001
                pass
        if created:
            logger.info("Alerta cercana del reporte %s enviada a %s personas.", report.id, created)
        return created
    except Exception as exc:
        db.rollback()
        _release(r, lock_key if locked else None, charged)
        logger.warning("Falló la alerta cercana del reporte %s (intento %s): %s", report_id, self.request.retries + 1, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
