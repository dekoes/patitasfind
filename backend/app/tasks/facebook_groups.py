"""Tareas de grupos públicos de Facebook (lectura por zona con un proveedor externo; ver services/facebook_groups.py).

- fetch_zone(state): la encarga la creación de un reporte desde la app o WhatsApp. Busca los grupos activos del
  estado (y los que no tienen estado) que no se han leído en FB_GROUPS_FETCH_INTERVAL_HOURS y encarga una
  fetch_group por cada uno (cada lectura puede tardar minutos en el proveedor).
- fetch_group(group_id, manual): lee un grupo si sigue tocando y si cabe en el presupuesto diario.
- expire_imported_posts: diaria; los reportes importados (grupos, Páginas y voluntarios) expiran a los
  FB_GROUPS_POST_TTL_DAYS / FB_VOLUNTEER_POST_TTL_DAYS de la publicación original y se purgan (texto y fotos)
  FB_IMPORTED_PURGE_AFTER_DAYS después; también completa los retiros pedidos por sus autores (72 h).
Sin FB_GROUPS_ENABLED=true (interruptor legal, apagado por defecto) o sin APIFY_TOKEN las lecturas no hacen nada;
la caducidad y la purga del contenido ya importado corren siempre.
"""
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

LOCK_TTL = 600  # igual que task_time_limit: si el worker muere, el candado se libera solo
# Varios reportes seguidos en el mismo estado encargan una sola revisión de grupos en este lapso
ZONE_THROTTLE_SECONDS = 120
NOT_CONFIGURED = "Proveedor no configurado (APIFY_TOKEN)"
DISABLED = "Importación de grupos apagada (FB_GROUPS_ENABLED=false)"
BUDGET_EXHAUSTED = "Presupuesto diario agotado"  # igual que facebook_groups.BUDGET_EXHAUSTED


def _lock_key(group_id: int) -> str:
    return f"fbg:lock:{group_id}"


@celery_app.task
def fetch_zone(state: str | None):
    """Encarga la lectura de los grupos del estado que ya toca leer."""
    from app import cache
    from app.data import estados_mx
    from app.database import SessionLocal
    from app.services import facebook_groups as fbg
    from app.services.background import dispatch

    from app.config import settings

    if not settings.fb_groups_provider_configured:
        fbg.warn_unconfigured_once()
        return {"state": state, "skipped": NOT_CONFIGURED}
    if not settings.fb_groups_enabled:  # interruptor legal (FB_GROUPS_ENABLED)
        return {"state": state, "skipped": DISABLED}
    state = estados_mx.normalize_state(state)
    if not state:
        return {"state": None, "skipped": "Estado desconocido"}
    if fbg.affordable_posts() <= 0:
        fbg.warn_budget_once()
        return {"state": state, "skipped": BUDGET_EXHAUSTED}
    if ZONE_THROTTLE_SECONDS > 0 and not cache.add(f"fbg:zone:{state}", ZONE_THROTTLE_SECONDS):
        return {"state": state, "skipped": "Revisión reciente"}
    db = SessionLocal()
    try:
        group_ids = [g.id for g in fbg.groups_due(db, state)]
    finally:
        db.close()
    for group_id in group_ids:
        dispatch("app.tasks.facebook_groups.fetch_group", group_id)
    return {"state": state, "groups_queued": len(group_ids)}


def run_group_fetch(group_id: int, manual: bool = False, provider=None) -> dict:
    """Lee un grupo (sin Celery: la usan la tarea y las pruebas). Devuelve el resultado de ingest_group o el motivo."""
    from app import cache
    from app.database import SessionLocal
    from app.models import FacebookGroup
    from app.services import facebook_groups as fbg

    from app.config import settings

    if provider is None and not settings.fb_groups_provider_configured:
        fbg.warn_unconfigured_once()
        return {"group_id": group_id, "skipped": NOT_CONFIGURED}
    if not settings.fb_groups_enabled:  # interruptor legal: ni siquiera con un proveedor de pruebas
        return {"group_id": group_id, "skipped": DISABLED}
    provider = provider or fbg.get_provider()
    if provider is None:
        fbg.warn_unconfigured_once()
        return {"group_id": group_id, "skipped": NOT_CONFIGURED}
    limit = fbg.affordable_posts()
    if limit <= 0:
        fbg.warn_budget_once()
        return {"group_id": group_id, "skipped": BUDGET_EXHAUSTED}
    # Un solo lector por grupo: dos reportes seguidos en el mismo estado no pagan dos veces la misma lectura
    if not cache.add(_lock_key(group_id), LOCK_TTL):
        return {"group_id": group_id, "skipped": "Lectura en curso"}
    db = SessionLocal()
    try:
        group = db.query(FacebookGroup).filter(FacebookGroup.id == group_id).first()
        if group is None or group.kind != "group" or not group.group_url:
            return {"group_id": group_id, "skipped": "No es un grupo"}
        if not manual and (not group.is_active or not fbg.is_due(group)):
            return {"group_id": group_id, "skipped": "Aún no toca leerlo"}
        # ingest_group aparta el costo de forma atómica: si otra corrida en paralelo tomó lo que quedaba,
        # devuelve skipped sin llamar al proveedor
        result = fbg.ingest_group(db, group, provider, limit=limit)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        cache.delete(_lock_key(group_id))
    result["since"] = result["since"].isoformat() if result.get("since") else None
    if not result.get("skipped"):
        result.pop("skipped", None)
    return result


@celery_app.task(soft_time_limit=540, time_limit=600)
def fetch_group(group_id: int, manual: bool = False):
    """Lee un grupo y encarga el matching de cada reporte creado (una tarea por reporte)."""
    from app.services.background import dispatch

    result = run_group_fetch(group_id, manual=manual)
    for report_id in result.get("created") or []:
        dispatch("app.tasks.matching.match_lost_report", report_id)
    return result


@celery_app.task
def expire_imported_posts():
    """Caducidad diaria del contenido importado: "expired" a los 30 días de la publicación y purga del texto y las
    fotos (también de los retiros que pidieron sus autores hace más de 72 h y que el admin no descartó)."""
    from app.database import SessionLocal
    from app.services import facebook_groups as fbg

    from app.config import settings

    db = SessionLocal()
    try:
        expired = fbg.expire_imported_reports(db)
        purged = fbg.purge_imported_reports(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    cleaned = 0
    if settings.fb_groups_provider_configured:  # conservación cero en Apify, aunque la importación esté apagada
        try:
            cleaned = fbg.ApifyProvider(settings.apify_token).retry_pending_deletes()
        except Exception:  # noqa: BLE001
            logger.exception("No se pudieron reintentar los borrados pendientes en Apify")
    return {"expired": len(expired), "purged": len(purged), "provider_cleaned": cleaned}


@celery_app.task
def purge_author_removals():
    """Cada hora: borra el texto y las fotos de las publicaciones importadas cuyo autor pidió el retiro con «Soy el
    autor» (sin cuenta) y que el equipo no descartó, a las IMPORTED_REMOVAL_PURGE_HOURS horas. Con solo la tarea
    diaria el borrado podía tardar hasta ~96 h frente a las «menos de 72 horas» de contenido-importado.html."""
    from app.database import SessionLocal
    from app.services import facebook_groups as fbg

    db = SessionLocal()
    try:
        purged = fbg.purge_imported_reports(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {"purged": len(purged)}
