"""Documentos privados de refugios (comprobantes, actas, identificaciones).

Se guardan en {UPLOAD_DIR}/private/, que NUNCA se sirve como archivo estático (ver PublicUploads
y la regla de Nginx para /uploads/private/). Solo los admins los descargan con GET /admin/documents/{id}.
"""
import io
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from app import cache
from app.config import settings
from app.database import get_db
from app.dependencies import get_verified_user, require_admin
from app.models import Refuge, User
from app.services import crypto_storage, ratelimit
from app.services.audit import record_admin_action

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

PRIVATE_DIRNAME = "private"
MAX_DOCUMENT_MB = 10
MAX_DOCUMENTS_PER_HOUR = 30
# Id público de un documento: <uuid hex>.<ext>
DOCUMENT_ID_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp|pdf)$")
# Nombres de archivo aceptados para documentos antiguos guardados en /uploads/
LEGACY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.[A-Za-z0-9]{2,5}$")
IMAGE_EXT = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "WEBP": "webp"}
MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}
MAX_IMAGE_SIDE = 4000  # suficiente para leer un documento escaneado


class PublicUploads(StaticFiles):
    """Sirve /uploads/ excepto la carpeta privada (responde 404 a /uploads/private/...)."""

    def lookup_path(self, path: str):
        full_path, stat_result = super().lookup_path(path)
        if full_path and _inside_private(full_path):
            return "", None
        return full_path, stat_result


def _inside_private(full_path: str) -> bool:
    # Se compara la ruta real (sin "..", "%2e%2e" ni enlaces) y sin mayúsculas: el disco puede no distinguirlas.
    real = os.path.realpath(full_path).lower()
    private = os.path.realpath(os.path.join(settings.upload_dir, PRIVATE_DIRNAME)).lower()
    return real == private or real.startswith(private + os.sep)


def private_dir() -> Path:
    path = Path(settings.upload_dir) / PRIVATE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_document_id(value: str) -> bool:
    return bool(DOCUMENT_ID_RE.match(value or ""))


def legacy_name(value: str) -> str | None:
    """Nombre de archivo de un documento antiguo ("/uploads/abc.jpg" -> "abc.jpg"), o None si no es válido."""
    if not isinstance(value, str) or not value.startswith("/uploads/"):
        return None
    name = value[len("/uploads/"):]
    return name if LEGACY_NAME_RE.match(name) else None


def document_path(doc_id: str) -> Path | None:
    """Ruta en disco de un documento (id nuevo o nombre de un documento antiguo). None si no existe."""
    if not doc_id or not (is_document_id(doc_id) or LEGACY_NAME_RE.match(doc_id)):
        return None
    base = Path(settings.upload_dir)
    for folder in (base / PRIVATE_DIRNAME, base):
        candidate = folder / doc_id
        try:
            if candidate.resolve().parent == folder.resolve() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def private_document_path(doc_id: str | None) -> Path | None:
    """Ruta de un documento de la carpeta privada (solo ids nuevos <uuid>.<ext>). None si no existe.

    Nunca busca en la raíz pública de /uploads/: las fotos públicas también se llaman <uuid>.jpg y no deben
    aceptarse (ni borrarse) como si fueran documentos privados.
    """
    if not isinstance(doc_id, str) or not is_document_id(doc_id):
        return None
    folder = Path(settings.upload_dir) / PRIVATE_DIRNAME
    candidate = folder / doc_id
    try:
        if candidate.resolve().parent == folder.resolve() and candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def delete_private_document(doc_id: str | None) -> bool:
    """Borra un documento de la carpeta privada. Ignora cualquier otra cosa (fotos públicas, rutas antiguas)."""
    path = private_document_path(doc_id)
    if not path:
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.warning("No se pudo borrar el documento %s: %s", path, exc)
        return False


# Quién subió cada documento (Redis, 7 días): POST /upload/document lo anota y los formularios que reciben un
# id (veterinarias, refugios) comprueban que lo subió la misma cuenta.
DOC_OWNER_TTL_SECONDS = 7 * 86_400


def _owner_key(doc_id: str) -> str:
    return f"doc_owner:{doc_id}"


def remember_document_owner(doc_id: str, user_id: int) -> None:
    cache.set(_owner_key(doc_id), int(user_id), ttl=DOC_OWNER_TTL_SECONDS)


def document_uploaded_by(doc_id: str) -> int | None:
    """Id de la cuenta que subió el documento, o None si no se sabe (Redis caído o anotación vencida)."""
    value = cache.get(_owner_key(doc_id))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def own_private_document(doc_id: str | None, user_id: int) -> bool:
    """¿Es un documento privado existente que no subió otra cuenta?

    Si no hay anotación (Redis caído o más de 7 días) basta con que exista en la carpeta privada: los ids son
    aleatorios de 128 bits y solo los conocen quien subió el documento y los admins.
    """
    if not private_document_path(doc_id):
        return False
    owner = document_uploaded_by(doc_id)
    return owner is None or owner == int(user_id)


def delete_document(value: str) -> bool:
    """Borra un documento privado (por id o ruta antigua /uploads/...). Devuelve True si borró algo.

    Ojo: con una ruta antigua puede borrar un archivo PÚBLICO de /uploads/. Para borrar lo de una cuenta que se
    cancela usa delete_private_document (ids nuevos) y account_deletion.delete_upload_files (rutas antiguas, que
    revisa si otra persona usa el archivo).
    """
    name = value if is_document_id(value) else legacy_name(value)
    path = document_path(name) if name else None
    if not path:
        return False
    try:
        path.unlink()
        if path.parent.name != PRIVATE_DIRNAME:
            # documento antiguo subido con el flujo de fotos: también tiene miniatura pública
            thumb = path.with_name(f"{path.stem}_thumb.jpg")
            if thumb.is_file():
                thumb.unlink()
        return True
    except OSError as exc:
        logger.warning("No se pudo borrar el documento %s: %s", path, exc)
        return False


def _store_document(data: bytes, owner_id: int | None = None) -> str:
    """Valida el archivo por su contenido (no por el nombre), lo guarda en la carpeta privada y anota quién lo subió."""
    doc_id = _write_document(data)
    if owner_id is not None:
        remember_document_owner(doc_id, owner_id)
    return doc_id


def _write_document(data: bytes) -> str:
    if not data:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(data) > MAX_DOCUMENT_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El documento es demasiado grande. Máximo {MAX_DOCUMENT_MB} MB.")
    name = uuid.uuid4().hex
    folder = private_dir()
    if data[:5] == b"%PDF-":
        doc_id = f"{name}.pdf"
        crypto_storage.write_private(folder / doc_id, data)  # cifrado en reposo (AES-GCM)
        return doc_id
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        probe.verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="Formato no permitido. Sube un PDF o una imagen JPG, PNG o WebP.")
    ext = IMAGE_EXT.get(fmt)
    if not ext:
        raise HTTPException(status_code=400, detail="Formato no permitido. Sube un PDF o una imagen JPG, PNG o WebP.")
    # Se vuelve a codificar sin metadatos (EXIF/GPS) y con la orientación correcta
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
    doc_id = f"{name}.{ext}"
    out = io.BytesIO()
    if ext == "jpg":
        img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    elif ext == "png":
        img.save(out, "PNG", optimize=True)
    else:
        img.convert("RGBA" if "A" in img.getbands() else "RGB").save(out, "WEBP", quality=90)
    # En disco solo queda la versión cifrada (services/crypto_storage.py); se descifra al descargarla
    crypto_storage.write_private(folder / doc_id, out.getvalue())
    return doc_id


@router.post("/upload/document")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Sube un documento privado (JPG, PNG, WebP o PDF, máx. 10 MB). Devuelve {"id": "<uuid>.<ext>"}."""
    user_id = current_user.id
    # La sesión solo sirvió para autenticar: se libera la conexión antes de leer y procesar el archivo.
    # Redis (límite por hora) también se consulta fuera del event loop.
    await run_in_threadpool(db.close)
    await run_in_threadpool(
        ratelimit.check, f"docs:{user_id}", limit=MAX_DOCUMENTS_PER_HOUR, window_seconds=3600,
        detail="Subiste demasiados documentos. Espera un rato e inténtalo de nuevo.",
    )
    try:
        data = await file.read(MAX_DOCUMENT_MB * 1024 * 1024 + 1)
    finally:
        await file.close()
    doc_id = await run_in_threadpool(_store_document, data, user_id)
    return {"id": doc_id}


@router.get("/admin/documents/{doc_id}")
def download_document(doc_id: str, request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Descarga un documento de refugio (solo admins). Acepta ids nuevos y nombres de documentos antiguos."""
    path = document_path(doc_id)
    if not path:
        raise HTTPException(status_code=404, detail="No encontramos ese documento.")
    refuge = db.query(Refuge.id).filter(cast(Refuge.documents, String).like(f"%{path.name}%")).first()
    record_admin_action(db, admin_user, "refuge_document.view", "refuge", refuge.id if refuge else None,
                        details={"document": path.name}, request=request)
    db.commit()
    ext = path.suffix.lstrip(".").lower()
    # Se descifra en memoria (crypto_storage); los documentos antiguos aún en claro se sirven igual
    return crypto_storage.private_file_response(
        path,
        media_type=MEDIA_TYPES.get(ext, "application/octet-stream"),
        filename=path.name,
        content_disposition_type="inline",
    )
