"""Bóveda de evidencia (Decreto NNA art. 5 fr. II; moderacion.html §9; autoridades.html §4; proteccion-nna.html §11).

Qué entra: cada vez que se oculta o retira contenido o se suspende una cuenta (por reporte, filtro, aviso de
derechos de autor, orden de autoridad o decisión del equipo) se guarda una copia del contenido, sus datos
asociados (autor, fechas, datos técnicos), el reporte que lo originó y la decisión.

Cómo: un paquete JSON (con las fotos en base64) cifrado con AES-256-GCM (services/crypto_storage.write_private)
en EVIDENCE_DIR, por defecto <UPLOAD_DIR>/private/evidencia, que ni Nginx ni el backend sirven nunca.

Integridad: SHA-256 del paquete sin cifrar y un índice de solo inserción (evidence_records) en el que cada fila
guarda el hash de la anterior (prev_hash) y el suyo (row_hash) sobre sus campos inmutables. Un trigger de
PostgreSQL impide borrar filas o cambiar esos campos (lo crea la migración; ver APPEND_ONLY_SQL).

Plazo: retained_until = fin del día hábil EVIDENCE_RETENTION_BUSINESS_DAYS (90) después del retiro, con el
calendario de días hábiles de la tienda (order_flow: lunes a viernes sin días de descanso obligatorio). La
retención legal (legal_hold) lo prorroga hasta que se libere; el material de abuso sexual infantil nace con
retención legal: se conserva solo para entregarlo al Ministerio Público. Eliminar la cuenta no borra la copia.

Purga: purge_expired() (tarea diaria app.tasks.moderacion_legal.purge_expired_evidence) borra el archivo de lo
vencido sin retención legal ni apelación o disputa abierta; la fila se queda con purged_at para que la cadena
siga verificable.
"""
import base64
import datetime
import hashlib
import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EvidenceRecord

logger = logging.getLogger(__name__)

BUNDLE_VERSION = 1
CHAIN_LOCK_KEY = 0x50464556  # "PFEV": candado de transacción para encadenar filas sin carreras
CSAM_HOLD_REASON = "Material de abuso sexual infantil: se conserva solo para entregarlo al Ministerio Público."
# Columnas que nunca entran al paquete
_SKIP_COLUMNS = {"hashed_password", "phone_otp_hash", "phone_otp_expires_at", "phone_otp_attempts", "token_version"}
# Campos que entran al row_hash (los demás, como legal_hold o purged_at, cambian con el tiempo)
_HASHED_FIELDS = ("kind", "target_type", "target_id", "owner_user_id", "content_report_id", "copyright_notice_id",
                  "authority_request_id", "reason", "is_csam", "content_sha256", "size_bytes")

# Trigger de solo inserción para la migración (Alembic 0004): sin DELETE y sin cambiar los campos inmutables.
APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION evidence_records_append_only() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'evidence_records es de solo inserción';
  END IF;
  IF NEW.kind IS DISTINCT FROM OLD.kind OR NEW.target_type IS DISTINCT FROM OLD.target_type
     OR NEW.target_id IS DISTINCT FROM OLD.target_id OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
     OR NEW.content_report_id IS DISTINCT FROM OLD.content_report_id
     OR NEW.copyright_notice_id IS DISTINCT FROM OLD.copyright_notice_id
     OR NEW.authority_request_id IS DISTINCT FROM OLD.authority_request_id OR NEW.reason IS DISTINCT FROM OLD.reason
     OR NEW.is_csam IS DISTINCT FROM OLD.is_csam OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
     OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR NEW.prev_hash IS DISTINCT FROM OLD.prev_hash
     OR NEW.row_hash IS DISTINCT FROM OLD.row_hash OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.retained_until < OLD.retained_until
     OR (OLD.storage_path IS NOT NULL AND NEW.storage_path IS NOT NULL AND NEW.storage_path <> OLD.storage_path)
     OR (OLD.purged_at IS NOT NULL AND NEW.purged_at IS DISTINCT FROM OLD.purged_at) THEN
    RAISE EXCEPTION 'evidence_records: solo pueden cambiar la retención legal, la prórroga y la purga';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS evidence_records_append_only ON evidence_records;
CREATE TRIGGER evidence_records_append_only BEFORE UPDATE OR DELETE ON evidence_records
  FOR EACH ROW EXECUTE FUNCTION evidence_records_append_only();
"""


class EvidenceError(RuntimeError):
    pass


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def evidence_dir() -> Path:
    if settings.evidence_dir:
        path = Path(settings.evidence_dir)
    else:
        from app.routers.documents import PRIVATE_DIRNAME

        path = Path(settings.upload_dir) / PRIVATE_DIRNAME / "evidencia"
    path.mkdir(parents=True, exist_ok=True)
    return path


def retention_deadline(start: datetime.datetime | None = None) -> datetime.datetime:
    """Fin (UTC, sin zona) del día hábil EVIDENCE_RETENTION_BUSINESS_DAYS después de `start`."""
    from app.services import order_flow

    start = start or _now()
    day = order_flow.add_business_days(order_flow._local_date(start), max(1, settings.evidence_retention_business_days))
    return order_flow._end_of_local_day_utc(day)


# --------------------------------------------------------------------------- paquete
def _jsonable(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    if hasattr(value, "__float__") and not isinstance(value, (int, float, bool)):
        return str(value)  # Decimal
    return value


def row_data(obj) -> dict | None:
    """Columnas de una fila (sin secretos) listas para JSON."""
    if obj is None:
        return None
    mapper = sa_inspect(obj).mapper
    return {c.key: _jsonable(getattr(obj, c.key)) for c in mapper.column_attrs if c.key not in _SKIP_COLUMNS}


def target_photo_urls(target_type: str, obj) -> list[str]:
    if obj is None:
        return []
    if target_type == "user":
        return [obj.avatar_url] if getattr(obj, "avatar_url", None) else []
    photos = getattr(obj, "photos", None)
    return [p for p in (photos or []) if isinstance(p, str)]


def local_files(urls: list[str]) -> list[tuple[str, bytes]]:
    """(nombre, bytes) de las fotos locales /uploads/... que existen."""
    from app.services import images

    out = []
    for url in urls or []:
        path = images.local_path_for(url)
        if path:
            try:
                out.append((url, path.read_bytes()))
            except OSError as exc:
                logger.warning("No se pudo leer %s para la evidencia: %s", path.name, exc)
    return out


def owner_data(db: Session, user_id: int | None) -> dict | None:
    from app.models import User

    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"id": user_id}
    return {k: _jsonable(getattr(user, k, None)) for k in (
        "id", "email", "full_name", "phone", "phone_verified", "role", "city", "created_at", "is_active",
        "suspended_at", "deleted_at", "terms_accepted_at", "terms_version",
    )}


def report_data(report) -> dict | None:
    return row_data(report) if report is not None else None


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def _row_hash(prev_hash: str | None, record: EvidenceRecord) -> str:
    fields = {f: getattr(record, f) for f in _HASHED_FIELDS}
    fields["retained_until"] = record.retained_until.isoformat()
    fields["created_at"] = record.created_at.isoformat()
    return hashlib.sha256((prev_hash or "").encode() + b"|" + _canonical(fields)).hexdigest()


def _lock_chain(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CHAIN_LOCK_KEY})


def capture(
    db: Session,
    *,
    kind: str,
    target_type: str,
    target_id: int | None = None,
    obj=None,
    owner_user_id: int | None = None,
    reason: str | None = None,
    report=None,
    decision: dict | None = None,
    extra: dict | None = None,
    files: list[tuple[str, bytes]] | None = None,
    include_photos: bool = True,
    is_csam: bool = False,
    legal_hold_reason: str | None = None,
    copyright_notice_id: int | None = None,
    authority_request_id: int | None = None,
    actor_id: int | None = None,
) -> EvidenceRecord:
    """Guarda una copia cifrada y agrega su fila encadenada (flush, sin commit: va en la transacción de quien llama).

    `files` reemplaza a las fotos del contenido; con include_photos=False no se copia ninguna foto.
    """
    from app.services import crypto_storage

    now = _now()
    if files is None:
        files = local_files(target_photo_urls(target_type, obj)) if include_photos else []
    file_meta = [{"name": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in files]
    bundle = {
        "version": BUNDLE_VERSION,
        "captured_at": now.isoformat(),
        "kind": kind,
        "target": {"type": target_type, "id": target_id, "data": row_data(obj)},
        "owner": owner_data(db, owner_user_id),
        "report": report_data(report),
        "decision": decision,
        "extra": extra,
        "files": [{**meta, "data_b64": base64.b64encode(data).decode()} for meta, (_n, data) in zip(file_meta, files)],
    }
    plaintext = _canonical(bundle)
    name = f"{uuid.uuid4().hex}.bin"
    crypto_storage.write_private(evidence_dir() / name, plaintext)

    hold = legal_hold_reason or (CSAM_HOLD_REASON if is_csam else None)
    record = EvidenceRecord(
        kind=kind, target_type=target_type, target_id=target_id, owner_user_id=owner_user_id,
        content_report_id=getattr(report, "id", None), copyright_notice_id=copyright_notice_id,
        authority_request_id=authority_request_id, reason=(reason or "")[:60] or None, is_csam=is_csam,
        storage_path=name, size_bytes=len(plaintext), content_sha256=hashlib.sha256(plaintext).hexdigest(),
        files=file_meta or None, retained_until=retention_deadline(now), legal_hold=bool(hold),
        legal_hold_reason=hold, legal_hold_by_id=actor_id if hold else None, legal_hold_at=now if hold else None,
        created_by_id=actor_id, created_at=now,
    )
    _lock_chain(db)
    last = db.query(EvidenceRecord.row_hash).order_by(EvidenceRecord.id.desc()).first()
    record.prev_hash = last[0] if last else None
    record.row_hash = _row_hash(record.prev_hash, record)
    db.add(record)
    db.flush()
    return record


def read_bundle(record: EvidenceRecord) -> dict:
    """Paquete descifrado. EvidenceError si ya se purgó o no cuadra su SHA-256."""
    from app.services import crypto_storage

    if not record.storage_path or record.purged_at:
        raise EvidenceError("Esta evidencia ya se eliminó al vencer su plazo de conservación.")
    path = evidence_dir() / Path(record.storage_path).name
    try:
        plaintext = crypto_storage.read_private(path)
    except FileNotFoundError:
        raise EvidenceError("No encontramos el archivo de esta evidencia.")
    if hashlib.sha256(plaintext).hexdigest() != record.content_sha256:
        raise EvidenceError("La evidencia no coincide con su huella SHA-256: pudo alterarse.")
    return json.loads(plaintext)


def bundle_files(bundle: dict) -> list[tuple[str, bytes]]:
    return [(f["name"], base64.b64decode(f["data_b64"])) for f in bundle.get("files") or []]


def metadata(record: EvidenceRecord) -> dict:
    """Lo único que muestra el panel (nunca el contenido)."""
    return {f: getattr(record, f) for f in (
        "id", "kind", "target_type", "target_id", "owner_user_id", "content_report_id", "copyright_notice_id",
        "authority_request_id", "reason", "is_csam", "size_bytes", "content_sha256", "files", "prev_hash", "row_hash",
        "retained_until", "legal_hold", "legal_hold_reason", "legal_hold_at", "purged_at", "created_by_id", "created_at",
    )}


# --------------------------------------------------------------------------- integridad, retención y purga
def verify_chain(db: Session) -> dict:
    """Recalcula la cadena completa. {ok, rows, broken_at}."""
    prev = None
    count = 0
    for record in db.query(EvidenceRecord).order_by(EvidenceRecord.id).yield_per(500):
        count += 1
        if record.prev_hash != prev or _row_hash(prev, record) != record.row_hash:
            return {"ok": False, "rows": count, "broken_at": record.id}
        prev = record.row_hash
    return {"ok": True, "rows": count, "broken_at": None}


def set_legal_hold(db: Session, record: EvidenceRecord, hold: bool, reason: str | None, actor_id: int | None) -> None:
    if record.purged_at and hold:
        raise EvidenceError("Esta evidencia ya se eliminó; no se puede retener.")
    if not hold and record.is_csam and not reason:
        raise EvidenceError("Para liberar material en cuarentena indica las instrucciones de la autoridad.")
    record.legal_hold = hold
    record.legal_hold_reason = (reason or "")[:300] or (None if not hold else "Retención legal")
    record.legal_hold_by_id = actor_id
    record.legal_hold_at = _now()


def hold_for_targets(db: Session, targets: list[dict], reason: str, actor_id: int | None,
                     authority_request_id: int | None = None) -> list[int]:
    """Retención legal de toda la evidencia de esas cuentas o contenidos (orden de conservación)."""
    from sqlalchemy import and_, or_

    conditions = []
    for t in targets or []:
        ttype, tid = t.get("type"), t.get("id")
        if not ttype or tid is None:
            continue
        conditions.append(and_(EvidenceRecord.target_type == ttype, EvidenceRecord.target_id == tid))
        if ttype == "user":
            conditions.append(EvidenceRecord.owner_user_id == tid)
    if not conditions:
        return []
    rows = db.query(EvidenceRecord).filter(or_(*conditions), EvidenceRecord.purged_at.is_(None)).all()
    for row in rows:
        if not row.legal_hold:
            set_legal_hold(db, row, True, reason + (f" (requerimiento #{authority_request_id})" if authority_request_id else ""),
                           actor_id)
    return [r.id for r in rows]


def _blocked_by_open_case(db: Session, record: EvidenceRecord) -> bool:
    """Apelación pendiente o disputa de derechos de autor abierta: no se purga todavía."""
    from app.models import CopyrightNotice, ModerationAction, ModerationAppeal

    pending = (
        db.query(ModerationAppeal.id).join(ModerationAction, ModerationAction.id == ModerationAppeal.action_id)
        .filter(ModerationAction.evidence_id == record.id, ModerationAppeal.status == "pending").first()
    )
    if pending:
        return True
    if record.copyright_notice_id:
        notice = db.query(CopyrightNotice.status).filter(CopyrightNotice.id == record.copyright_notice_id).first()
        if notice and notice[0] in ("counter_notice", "litigation"):
            return True
    return False


def purge_expired(db: Session, now: datetime.datetime | None = None, limit: int = 500,
                  only_ids: list[int] | None = None) -> int:
    """Borra el archivo cifrado de la evidencia vencida sin retención legal. Devuelve cuántas purgó (con commit).

    La llama la purga diaria de conservación (services/retention.purge_evidence, fila R30).
    """
    now = now or _now()
    query = db.query(EvidenceRecord).filter(
        EvidenceRecord.retained_until < now, EvidenceRecord.legal_hold == False,  # noqa: E712
        EvidenceRecord.purged_at.is_(None))
    if only_ids is not None:
        query = query.filter(EvidenceRecord.id.in_(only_ids))
    rows = query.order_by(EvidenceRecord.id).limit(limit).all()
    purged = 0
    for record in rows:
        if _blocked_by_open_case(db, record):
            continue
        if record.storage_path:
            try:
                (evidence_dir() / Path(record.storage_path).name).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("No se pudo borrar la evidencia %s: %s", record.id, exc)
                continue
        record.storage_path = None
        record.purged_at = now
        purged += 1
    db.commit()
    return purged
