"""Staydown: impide volver a subir una imagen idéntica a una retirada (derechos-de-autor.html §7).

Al retirar una imagen por un aviso de derechos de autor procedente, por orden de autoridad o por ser material
de abuso sexual infantil se guardan dos huellas perceptuales en BlockedImageHash: el hash promedio (aHash, 8x8)
y el de diferencias (dHash, 9x8). Al subir una foto (images.process_image_bytes) se calculan las mismas huellas
y, si ambas están a distancia de Hamming <= MAX_DISTANCE de una imagen bloqueada, la subida se rechaza.

Las huellas resisten la recompresión y el cambio de tamaño (son la misma imagen), pero no bloquean fotos
distintas del mismo perro. La página no publica estos detalles para que no puedan evadirse.

La lista se lee de la base como máximo cada CACHE_SECONDS por proceso (son pocas filas); al agregar o quitar
filas en este proceso se invalida al momento. Las imágenes en cuarentena (kind="csam") tampoco se mandan nunca a
la IA (vision.analyze_image_bytes y vision.analyze_url).
"""
import hashlib
import logging
import threading
import time

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_DISTANCE = 4  # de 64 bits, en cada una de las dos huellas
CACHE_SECONDS = 60
KINDS = ("derechos_autor", "csam", "autoridad", "moderacion")

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "rows": None}


# --------------------------------------------------------------------------- huellas
def _gray(img: Image.Image) -> Image.Image:
    """Escala de grises; las transparencias se aplanan sobre blanco, como al subir."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        rgba.close()
        return flat.convert("L")
    return img.convert("L")


def hashes_for_image(img: Image.Image) -> tuple[str, str]:
    """(aHash, dHash) en hexadecimal de 16 caracteres. La imagen ya debe venir orientada (exif_transpose)."""
    gray = _gray(img)
    try:
        small = gray.resize((8, 8), Image.LANCZOS)
        px = list(small.getdata())
        mean = sum(px) / len(px)
        a = 0
        for value in px:
            a = (a << 1) | (1 if value >= mean else 0)
        wide = gray.resize((9, 8), Image.LANCZOS)
        px = list(wide.getdata())
        d = 0
        for row in range(8):
            for col in range(8):
                d = (d << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    finally:
        gray.close()
    return f"{a:016x}", f"{d:016x}"


def hashes_for_bytes(data: bytes) -> tuple[str, str] | None:
    from app.services import images

    try:
        with images.open_image(data) as raw:
            img = ImageOps.exif_transpose(raw)
            try:
                return hashes_for_image(img)
            finally:
                if img is not raw:
                    img.close()
    except Exception as exc:  # noqa: BLE001 - imagen ilegible: no hay huella
        logger.warning("No se pudo calcular la huella de una imagen: %s", exc)
        return None


def _distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------- lista de bloqueo
def invalidate_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["rows"] = None


def _load_rows(force: bool = False) -> list[tuple]:
    """[(id, kind, ahash:int, dhash:int, source_url)] de las filas activas."""
    now = time.monotonic()
    with _lock:
        rows = _cache["rows"]
        if rows is not None and not force and now - _cache["at"] < CACHE_SECONDS:
            return rows
    from app.database import SessionLocal
    from app.models import BlockedImageHash

    db = SessionLocal()
    try:
        fresh = [
            (r.id, r.kind, int(r.ahash, 16), int(r.dhash, 16), r.source_url)
            for r in db.query(BlockedImageHash).filter(BlockedImageHash.active == True).all()  # noqa: E712
        ]
    except Exception as exc:  # noqa: BLE001 - sin base: se usa la última lista conocida
        logger.warning("No se pudo leer la lista de staydown: %s", exc)
        return rows or []
    finally:
        db.close()
    with _lock:
        _cache["rows"] = fresh
        _cache["at"] = now
    return fresh


def match_hashes(ahash: str, dhash: str, kinds: tuple[str, ...] | None = None) -> dict | None:
    """Fila bloqueada que coincide con estas huellas ({id, kind}) o None."""
    a, d = int(ahash, 16), int(dhash, 16)
    for row_id, kind, ra, rd, _url in _load_rows():
        if kinds and kind not in kinds:
            continue
        if _distance(a, ra) <= MAX_DISTANCE and _distance(d, rd) <= MAX_DISTANCE:
            return {"id": row_id, "kind": kind}
    return None


def check_image(img: Image.Image) -> None:
    """Hook de la subida: lanza images.StaydownBlocked si la imagen está en la lista de bloqueo."""
    from app.services import images

    if not _load_rows():
        return
    hit = match_hashes(*hashes_for_image(img))
    if hit:
        raise images.StaydownBlocked(block_id=hit["id"], kind=hit["kind"])


def has_quarantine() -> bool:
    return any(kind == "csam" for _id, kind, *_ in _load_rows())


def is_quarantined_bytes(data: bytes) -> bool:
    """True si la imagen coincide con material en cuarentena (nunca se manda a la IA)."""
    if not data or not has_quarantine():
        return False
    hashes = hashes_for_bytes(data)
    return bool(hashes and match_hashes(*hashes, kinds=("csam",)))


def is_quarantined_url(url: str | None) -> bool:
    if not url:
        return False
    path = url.split("?", 1)[0]
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].removesuffix("_thumb")
    for _id, kind, _a, _d, source in _load_rows():
        if kind == "csam" and source and stem and stem in source:
            return True
    return False


def block_bytes(db: Session, data: bytes, kind: str, source_url: str | None = None, *, notice_id: int | None = None,
                evidence_id: int | None = None, actor_id: int | None = None):
    """Agrega una imagen a la lista de bloqueo. Devuelve la fila (sin commit) o None si no es legible."""
    from app.models import BlockedImageHash

    if kind not in KINDS:
        raise ValueError(f"Tipo de bloqueo desconocido: {kind}")
    hashes = hashes_for_bytes(data)
    if not hashes:
        return None
    row = BlockedImageHash(
        kind=kind, ahash=hashes[0], dhash=hashes[1], sha256=hashlib.sha256(data).hexdigest(),
        source_url=(source_url or "")[:500] or None, copyright_notice_id=notice_id, evidence_id=evidence_id,
        created_by_id=actor_id,
    )
    db.add(row)
    invalidate_cache()
    return row


def block_urls(db: Session, urls: list[str], kind: str, **kwargs) -> list:
    """Bloquea las fotos locales (/uploads/...) de una publicación. Las que no existen se omiten."""
    from app.services import images

    rows = []
    for url in urls or []:
        path = images.local_path_for(url)
        if not path:
            continue
        row = block_bytes(db, path.read_bytes(), kind, source_url=url, **kwargs)
        if row is not None:
            rows.append(row)
    return rows


def deactivate(db: Session, *, notice_id: int | None = None, evidence_id: int | None = None) -> int:
    """Quita de la lista lo bloqueado por un aviso (contra-aviso que prosperó) o por una evidencia (cuarentena
    liberada). Devuelve cuántas filas se desactivaron."""
    from app.models import BlockedImageHash

    query = db.query(BlockedImageHash).filter(BlockedImageHash.active == True)  # noqa: E712
    if notice_id is not None:
        query = query.filter(BlockedImageHash.copyright_notice_id == notice_id)
    elif evidence_id is not None:
        query = query.filter(BlockedImageHash.evidence_id == evidence_id)
    else:
        return 0
    rows = query.all()
    for row in rows:
        row.active = False
    invalidate_cache()
    return len(rows)


def record_hit(block_id: int, user_id: int | None = None) -> None:
    """Cuenta un intento de volver a subir una imagen bloqueada (sesión propia: la subida ya cerró la suya).

    Si es material en cuarentena se avisa a los administradores; la imagen nueva no se guarda.
    """
    import datetime

    from app.database import SessionLocal
    from app.models import BlockedImageHash, User

    db = SessionLocal()
    try:
        row = db.query(BlockedImageHash).filter(BlockedImageHash.id == block_id).with_for_update().first()
        if not row:
            return
        row.hits = (row.hits or 0) + 1
        row.last_hit_at = datetime.datetime.utcnow()
        logger.warning("Subida bloqueada por staydown (%s, fila %s, usuario %s).", row.kind, row.id, user_id)
        if row.kind == "csam":
            from app.services import moderation
            from app.services.notify import notify_user

            admins = db.query(User).filter(User.role.in_(moderation.ADMIN_ROLES), User.is_active == True).all()  # noqa: E712
            for admin in admins:
                notify_user(
                    db, admin, "moderation_alert", title="Intento de volver a subir material en cuarentena",
                    body=(f"La cuenta #{user_id or '?'} intentó subir una imagen que coincide con material en cuarentena. "
                          "No se guardó. Revisa la cola de Moderación legal y registra el hecho para la denuncia."),
                    url="/admin/", email=True, data={"blocked_image_id": row.id, "user_id": user_id}, commit=False,
                )
        db.commit()
    except Exception:  # noqa: BLE001 - el rechazo de la subida no depende de este registro
        db.rollback()
        logger.exception("No se pudo registrar el intento bloqueado por staydown")
    finally:
        db.close()
