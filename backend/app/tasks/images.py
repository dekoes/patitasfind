import logging
import os
import time
from pathlib import Path

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

MAX_AI_ATTEMPTS = 5
AI_BACKOFF_SECONDS = 60 * 60  # 1 h, 2 h, 4 h, 8 h entre intentos
BACKFILL_TIME_BUDGET = 240  # segundos (antes del task_soft_time_limit de 300)
ORPHAN_MIN_AGE_HOURS = 48
ORPHAN_MAX_DELETE = 2000
THUMBNAILS_PER_RUN = 300
# Stem de los archivos que generamos (<uuid hex>[_thumb].<ext>) dentro de cualquier texto o JSON de la BD
_STEM_SQL = r"([0-9a-f]{32})(?:_thumb)?\.(?:jpg|jpeg|png|webp)"


@celery_app.task
def enrich_dog(dog_id: int):
    """Calcula firma visual y análisis IA de un perro recién publicado."""
    from app.database import SessionLocal
    from app.models import Dog
    from app.services.matching import ensure_enrichment

    db = SessionLocal()
    try:
        dog = db.query(Dog).filter(Dog.id == dog_id).first()
        if dog:
            ensure_enrichment(db, dog, with_ai=True)
    finally:
        db.close()


# --------------------------------------------------------------------------- firmas e IA pendientes
def _json_null(column):
    """SQL NULL o JSON null (lo que guarda SQLAlchemy al asignar None)."""
    from sqlalchemy import Text, cast, or_

    return or_(column.is_(None), cast(column, Text) == "null")


def _backfill_query(db, model, with_ai: bool, now: float | None = None):
    """Filas sin firma visual o (con IA) sin análisis cuyo siguiente intento ya toca. Solo PostgreSQL."""
    from sqlalchemy import and_, not_, or_

    now = time.time() if now is None else now
    needs = _json_null(model.photo_signature)
    if with_ai:
        done = model.photo_signature[("backfill", "done")].as_boolean()
        next_at = model.photo_signature[("backfill", "ai_next_at")].as_float()
        needs = or_(needs, and_(
            _json_null(model.ai_analysis), not_(_json_null(model.photo_signature)),
            or_(done.is_(None), done.is_(False)), or_(next_at.is_(None), next_at <= now),
        ))
    return db.query(model).filter(needs).order_by(model.created_at.desc())


def _backfill_one(obj, with_ai: bool, now: float | None = None) -> str:
    """Procesa una fila. Devuelve "processed", "skipped" (sin fotos locales) o "ai_failed"."""
    from app.services import images, vision

    now = time.time() if now is None else now
    photos = [p for p in (obj.photos or []) if isinstance(p, str) and images.local_path_for(p)]
    if not photos:
        # Sin fotos locales legibles: se marca como procesada para que no bloquee la cola. Si luego
        # cambian las fotos, ensure_enrichment recalcula la firma (y el análisis) desde cero.
        obj.photo_signature = {"v": 1, "photos": [], "backfill": {"done": True, "reason": "sin_fotos"}}
        return "skipped"
    if not isinstance(obj.photo_signature, dict):
        sig = vision.signature_for_urls(photos)
        if not sig:
            obj.photo_signature = {"v": 1, "photos": [], "backfill": {"done": True, "reason": "ilegibles"}}
            return "skipped"
        obj.photo_signature = sig
    if not with_ai or obj.ai_analysis:
        return "processed"

    meta = dict(obj.photo_signature.get("backfill") or {})
    try:
        analysis = vision.analyze_url(photos[0])
    except vision.AINotConfigured:
        return "processed"
    if analysis:
        obj.ai_analysis = analysis
        if meta:
            obj.photo_signature = {k: v for k, v in obj.photo_signature.items() if k != "backfill"}
        return "processed"
    attempts = int(meta.get("ai_attempts") or 0) + 1
    meta.update(ai_attempts=attempts, ai_next_at=now + AI_BACKOFF_SECONDS * 2 ** (attempts - 1))
    if attempts >= MAX_AI_ATTEMPTS:
        meta.update(done=True, reason="ia_fallida")
        logger.warning("Se abandona el análisis IA de %s %s tras %s intentos.", obj.__tablename__, obj.id, attempts)
    obj.photo_signature = {**obj.photo_signature, "backfill": meta}  # dict nuevo: SQLAlchemy detecta el cambio
    return "ai_failed"


@celery_app.task
def backfill_photo_signatures(batch: int = 50):
    """Completa firmas visuales (y análisis IA si hay llave) faltantes. Solo lee archivos locales.

    Las filas sin fotos se marcan como procesadas; si la IA falla se reintenta con espera exponencial
    y se abandona tras MAX_AI_ATTEMPTS intentos (el contador vive en photo_signature["backfill"]).
    """
    from app.database import SessionLocal
    from app.models import Dog, LostReport
    from app.services import vision

    db = SessionLocal()
    stats = {"processed": 0, "skipped": 0, "ai_failed": 0}
    started = time.monotonic()
    try:
        with_ai = vision.is_configured()
        for model in (Dog, LostReport):
            for obj in _backfill_query(db, model, with_ai).limit(batch).all():
                if time.monotonic() - started > BACKFILL_TIME_BUDGET:
                    return stats
                stats[_backfill_one(obj, with_ai)] += 1
                db.commit()  # una por una: un fallo o el límite de tiempo no pierde lo avanzado
        return stats
    finally:
        db.close()


@celery_app.task
def process_uploaded_image(file_path: str, purpose: str = "general"):
    """Compatibilidad: el procesamiento ahora es síncrono en la subida (Pillow)."""
    return {"file_path": file_path, "purpose": purpose, "status": "processed"}


# --------------------------------------------------------------------------- archivos huérfanos
def referenced_upload_stems(db) -> set[str] | None:
    """Stems de archivos subidos que aparecen en CUALQUIER columna de texto o JSON de la BD.

    Se revisan todas las tablas de los modelos (fotos de perros, reportes, productos, avatares, documentos
    antiguos, mensajes, datos del bot de WhatsApp, notificaciones...), así que una columna nueva queda
    cubierta sin tocar esto. None si no se puede revisar (no es PostgreSQL o falló una consulta).
    """
    from sqlalchemy import JSON, String, text

    from app.database import Base

    if db.bind.dialect.name != "postgresql":
        logger.warning("La limpieza de archivos huérfanos solo funciona con PostgreSQL.")
        return None
    quote = db.bind.dialect.identifier_preparer
    stems: set[str] = set()
    try:
        for table in Base.metadata.sorted_tables:
            columns = [c for c in table.columns if isinstance(c.type, (String, JSON))]  # Text hereda de String
            if not columns:
                continue
            joined = "concat_ws(' ', " + ", ".join(f"CAST({quote.quote(c.name)} AS TEXT)" for c in columns) + ")"
            sql = text(
                f"SELECT DISTINCT lower((regexp_matches({joined}, :pattern, 'gi'))[1]) "
                f"FROM {quote.format_table(table)} WHERE {joined} ~* :pattern"
            )
            stems.update(row[0] for row in db.execute(sql, {"pattern": _STEM_SQL}))
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("No se pudieron revisar las referencias a archivos; no se borra nada.")
        return None
    return stems


def remove_orphan_uploads(db, folder: Path | None = None, min_age_hours: int = ORPHAN_MIN_AGE_HOURS,
                          max_delete: int = ORPHAN_MAX_DELETE, dry_run: bool = False) -> dict:
    """Borra fotos generadas (<uuid>.<ext> y su _thumb) con más de `min_age_hours` que nada referencia.

    Solo mira archivos sueltos en la raíz de UPLOAD_DIR: nunca entra a carpetas (private/, .pre-restore-*)
    ni sigue enlaces. Si una foto está referenciada se conserva también su miniatura.
    """
    from app.services import images

    folder = Path(folder or images.upload_dir())
    cutoff = time.time() - min_age_hours * 3600
    groups: dict[str, list[Path]] = {}
    recent: set[str] = set()
    with os.scandir(folder) as entries:
        for entry in entries:
            match = images.GENERATED_NAME.match(entry.name)
            if not match or not entry.is_file(follow_symlinks=False):
                continue
            stem = match.group(1)
            groups.setdefault(stem, []).append(Path(entry.path))
            if entry.stat(follow_symlinks=False).st_mtime > cutoff:
                recent.add(stem)
    candidates = {stem: paths for stem, paths in groups.items() if stem not in recent}
    result = {"scanned": len(groups), "deleted": [], "kept_referenced": 0, "thumbnails": 0}
    if not candidates:
        return result

    referenced = referenced_upload_stems(db)
    if referenced is None:
        result["error"] = "no se pudieron revisar las referencias"
        return result
    if not referenced:
        # Una BD sin ninguna foto pero con archivos viejos suele ser una BD equivocada o recién restaurada
        logger.warning("Ninguna fila referencia archivos subidos; por seguridad no se borra nada en %s.", folder)
        result["error"] = "sin referencias en la BD"
        return result

    for stem, paths in sorted(candidates.items()):
        if stem in referenced:
            result["kept_referenced"] += 1
            continue
        if len(result["deleted"]) >= max_delete:
            logger.warning("Se alcanzó el máximo de %s archivos huérfanos por corrida; el resto queda para mañana.", max_delete)
            break
        for path in paths:
            if not dry_run:
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
            logger.info("Archivo huérfano %s: %s", "detectado" if dry_run else "eliminado", path.name)
            result["deleted"].append(path.name)

    # Fotos antiguas sin miniatura (C10: cada /uploads/<stem>.<ext> tiene <stem>_thumb.jpg)
    if not dry_run:
        for stem, paths in groups.items():
            if result["thumbnails"] >= THUMBNAILS_PER_RUN:
                break
            if stem not in referenced or any(p.stem.endswith("_thumb") for p in paths):
                continue
            main = next((p for p in paths if p.exists()), None)
            if main and images.ensure_thumbnail(main):
                result["thumbnails"] += 1
    logger.info("Limpieza de uploads: %s archivos borrados, %s fotos referenciadas conservadas, %s miniaturas creadas.",
                len(result["deleted"]), result["kept_referenced"], result["thumbnails"])
    return result


@celery_app.task
def cleanup_orphan_uploads(min_age_hours: int = ORPHAN_MIN_AGE_HOURS, dry_run: bool = False):
    """Tarea diaria: borra fotos subidas que nadie usa (formularios abandonados, fotos reemplazadas)."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = remove_orphan_uploads(db, min_age_hours=min_age_hours, dry_run=dry_run)
        return {**result, "deleted": len(result["deleted"])}
    finally:
        db.close()
