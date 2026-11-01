"""Cifrado en reposo (AES-256-GCM) de los archivos privados y de las columnas sensibles.

Archivos de {UPLOAD_DIR}/private/ (identificaciones, actas, cédulas, constancias fiscales, CFDI, capturas del
cotejo): se cifran al escribirse (write_private) y se descifran solo al servirlos a quien tiene permiso
(read_private / private_file_response). En disco nunca queda el contenido en claro.

Formato de archivo: MAGIC (6 bytes) + id de llave (4) + nonce (12) + texto cifrado con su etiqueta GCM (16).
Formato de columna (EncryptedText): "enc1:" + base64url(id de llave + nonce + texto cifrado).

Llave: PRIVATE_FILES_KEY (base64 de 32 bytes), obligatoria en producción. Para rotarla, pon la nueva en
PRIVATE_FILES_KEY y la anterior en PRIVATE_FILES_OLD_KEYS (separadas por comas): lo ya cifrado se sigue
leyendo y `python -m app.cli encrypt-private-files --rotate` lo vuelve a cifrar con la nueva. Fuera de
producción, sin llave se usa una derivada de SECRET_KEY (solo para desarrollo y pruebas).

Los archivos antiguos que aún están en claro se leen tal cual (transición) hasta correr
`python -m app.cli encrypt-private-files`.
"""
import base64
import binascii
import hashlib
import logging
import os
import secrets
import tempfile
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.types import Text, TypeDecorator

from app.config import settings

logger = logging.getLogger(__name__)

MAGIC = b"PFENC1"
KEY_ID_LEN = 4
NONCE_LEN = 12
HEADER_LEN = len(MAGIC) + KEY_ID_LEN + NONCE_LEN
COLUMN_PREFIX = "enc1:"
KEY_BYTES = 32


class CryptoConfigError(RuntimeError):
    """Falta la llave de cifrado (o no es válida) donde es obligatoria."""


class DecryptionError(RuntimeError):
    """El contenido no se pudo descifrar: llave equivocada o archivo alterado."""


# --------------------------------------------------------------------------- llaves
def decode_key(value: str | None) -> bytes:
    """Base64 (estándar o url-safe, con o sin relleno) de exactamente 32 bytes. ValueError si no."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("vacía")
    padded = raw + "=" * (-len(raw) % 4)
    try:
        key = base64.b64decode(padded.replace("-", "+").replace("_", "/"), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("no es base64 válido")
    if len(key) != KEY_BYTES:
        raise ValueError(f"debe medir {KEY_BYTES} bytes (mide {len(key)})")
    return key


def generate_key() -> str:
    """Llave nueva para PRIVATE_FILES_KEY."""
    return base64.b64encode(secrets.token_bytes(KEY_BYTES)).decode()


def key_id(key: bytes) -> bytes:
    return hashlib.sha256(b"patitasfind-key-id:" + key).digest()[:KEY_ID_LEN]


def _hkdf(key: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=b"patitasfind-private-v1", info=info).derive(key)


@lru_cache(maxsize=8)
def _dev_key(secret_key: str) -> bytes:
    return _hkdf(secret_key.encode(), b"dev-private-files")


@lru_cache(maxsize=16)
def _parse_keys(primary: str | None, old: str | None) -> tuple[bytes | None, tuple[bytes, ...]]:
    main = decode_key(primary) if primary else None
    olds = tuple(decode_key(k) for k in (old or "").split(",") if k.strip())
    return main, olds


def _file_keys() -> tuple[bytes, dict[bytes, bytes]]:
    """(llave para cifrar, {id: llave} para descifrar)."""
    try:
        main, olds = _parse_keys(settings.private_files_key, settings.private_files_old_keys)
    except ValueError as exc:
        raise CryptoConfigError(f"PRIVATE_FILES_KEY o PRIVATE_FILES_OLD_KEYS no es válida: {exc}.")
    candidates = list(olds)
    if not settings.is_production:
        candidates.append(_dev_key(settings.secret_key))  # lo cifrado en desarrollo antes de definir la llave
    if main is None:
        if settings.is_production:
            raise CryptoConfigError("Falta PRIVATE_FILES_KEY: en producción los documentos privados deben cifrarse.")
        main = _dev_key(settings.secret_key)
    keyring = {key_id(k): k for k in [main, *candidates]}
    return main, keyring


def _column_key(file_key: bytes) -> bytes:
    return _hkdf(file_key, b"columns")


def encryption_status() -> dict:
    """Para el panel y el CLI: si hay llave propia y cuál es su id (nunca la llave)."""
    try:
        main, keyring = _file_keys()
    except CryptoConfigError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "own_key": bool(settings.private_files_key), "key_id": key_id(main).hex(),
            "decrypt_keys": len(keyring)}


# --------------------------------------------------------------------------- bytes
def is_encrypted(data: bytes | None) -> bool:
    return bool(data) and data[:len(MAGIC)] == MAGIC


def encrypt_bytes(data: bytes) -> bytes:
    key, _ = _file_keys()
    kid = key_id(key)
    nonce = os.urandom(NONCE_LEN)
    header = MAGIC + kid
    return header + nonce + AESGCM(key).encrypt(nonce, data, header)


def decrypt_bytes(blob: bytes) -> bytes:
    """Descifra; si el contenido no tiene la cabecera (archivo antiguo en claro) lo devuelve igual."""
    if not is_encrypted(blob):
        return blob
    if len(blob) < HEADER_LEN + 16:
        raise DecryptionError("Archivo cifrado incompleto.")
    kid = blob[len(MAGIC):len(MAGIC) + KEY_ID_LEN]
    nonce = blob[len(MAGIC) + KEY_ID_LEN:HEADER_LEN]
    _, keyring = _file_keys()
    key = keyring.get(kid)
    if key is None:
        raise DecryptionError("El archivo se cifró con una llave que no está configurada (PRIVATE_FILES_OLD_KEYS).")
    try:
        return AESGCM(key).decrypt(nonce, blob[HEADER_LEN:], MAGIC + kid)
    except InvalidTag:
        raise DecryptionError("El archivo cifrado está alterado o la llave no corresponde.")


def needs_reencryption(blob: bytes) -> bool:
    """True si está en claro o cifrado con una llave que ya no es la principal."""
    if not is_encrypted(blob):
        return True
    key, _ = _file_keys()
    return blob[len(MAGIC):len(MAGIC) + KEY_ID_LEN] != key_id(key)


# --------------------------------------------------------------------------- archivos
def write_private(path: Path | str, data: bytes) -> None:
    """Escribe el archivo cifrado de forma atómica (temporal + rename) y solo legible por el proceso."""
    path = Path(path)
    blob = encrypt_bytes(data)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_private(path: Path | str) -> bytes:
    """Contenido en claro de un archivo privado (cifrado o antiguo en claro)."""
    blob = Path(path).read_bytes()
    if not is_encrypted(blob) and settings.is_production:
        logger.warning("Archivo privado sin cifrar: %s. Corre python -m app.cli encrypt-private-files.", Path(path).name)
    return decrypt_bytes(blob)


def encrypt_file_in_place(path: Path | str, rotate: bool = False) -> str:
    """Cifra un archivo existente. Devuelve "encrypted", "rotated" o "skipped"."""
    path = Path(path)
    blob = path.read_bytes()
    if is_encrypted(blob):
        if not rotate or not needs_reencryption(blob):
            return "skipped"
        write_private(path, decrypt_bytes(blob))
        return "rotated"
    write_private(path, blob)
    return "encrypted"


def private_file_response(path, media_type: str, filename: str | None = None,
                          content_disposition_type: str = "inline", headers: dict | None = None):
    """Equivale a FileResponse(path, ...) pero descifra el archivo en memoria antes de enviarlo."""
    from urllib.parse import quote

    from fastapi.responses import Response

    data = read_private(path)
    out = {"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff", **(headers or {})}
    if filename:
        ascii_name = filename.encode("ascii", "ignore").decode() or "documento"
        out["Content-Disposition"] = (f'{content_disposition_type}; filename="{ascii_name}"; '
                                      f"filename*=utf-8''{quote(filename)}")
    return Response(content=data, media_type=media_type, headers=out)


# --------------------------------------------------------------------------- columnas
def encrypt_text(value: str | None) -> str | None:
    if value is None or value == "" or (isinstance(value, str) and value.startswith(COLUMN_PREFIX)):
        return value
    main, _ = _file_keys()
    key = _column_key(main)
    kid = key_id(key)
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, str(value).encode("utf-8"), b"col" + kid)
    return COLUMN_PREFIX + base64.urlsafe_b64encode(kid + nonce + ct).decode().rstrip("=")


def decrypt_text(value: str | None) -> str | None:
    """Descifra un valor de columna; los valores antiguos en claro se devuelven igual."""
    if not isinstance(value, str) or not value.startswith(COLUMN_PREFIX):
        return value
    raw = value[len(COLUMN_PREFIX):]
    try:
        blob = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        raise DecryptionError("Valor cifrado dañado.")
    kid, nonce, ct = blob[:KEY_ID_LEN], blob[KEY_ID_LEN:KEY_ID_LEN + NONCE_LEN], blob[KEY_ID_LEN + NONCE_LEN:]
    _, keyring = _file_keys()
    for file_key in keyring.values():
        key = _column_key(file_key)
        if key_id(key) == kid:
            try:
                return AESGCM(key).decrypt(nonce, ct, b"col" + kid).decode("utf-8")
            except InvalidTag:
                break
    raise DecryptionError("No se pudo descifrar un dato fiscal: revisa PRIVATE_FILES_KEY y PRIVATE_FILES_OLD_KEYS.")


def column_needs_reencryption(value: str | None) -> bool:
    if not value:
        return False
    if not value.startswith(COLUMN_PREFIX):
        return True
    raw = value[len(COLUMN_PREFIX):]
    blob = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    main, _ = _file_keys()
    return blob[:KEY_ID_LEN] != key_id(_column_key(main))


class EncryptedText(TypeDecorator):
    """Columna de texto cifrada con AES-GCM: se cifra al escribir y se descifra al leer (transparente).

    En la base es TEXT; no sirve para filtrar ni ordenar por su valor (cada cifrado es distinto).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_text(value)

    def process_result_value(self, value, dialect):
        return decrypt_text(value)


# --------------------------------------------------------------------------- comandos (python -m app.cli ...)
def encrypt_private_files(rotate: bool = False, dry_run: bool = False) -> dict:
    """Cifra los archivos que siguen en claro en {UPLOAD_DIR}/private/ (y subcarpetas). Idempotente.

    rotate=True también vuelve a cifrar con PRIVATE_FILES_KEY lo cifrado con una llave anterior.
    """
    base = Path(settings.upload_dir) / "private"
    stats = {"encrypted": 0, "rotated": 0, "skipped": 0, "errors": 0}
    if not base.is_dir():
        return stats
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name.startswith(".tmp-"):
            continue
        try:
            if dry_run:
                blob = path.read_bytes()
                key = "skipped" if is_encrypted(blob) and not (rotate and needs_reencryption(blob)) else (
                    "rotated" if is_encrypted(blob) else "encrypted")
            else:
                key = encrypt_file_in_place(path, rotate=rotate)
            stats[key] += 1
        except (OSError, DecryptionError) as exc:
            logger.error("No se pudo cifrar %s: %s", path.name, exc)
            stats["errors"] += 1
    return stats


LEGACY_DOC_EXT = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp", "pdf": "pdf"}


def migrate_legacy_documents(db, dry_run: bool = False) -> dict:
    """Documentos antiguos de refugios guardados en la raíz PÚBLICA de /uploads/ (Refuge.documents con
    "/uploads/<nombre>"): se copian cifrados a {UPLOAD_DIR}/private/<uuid>.<ext> y Refuge.documents queda con el id
    nuevo (una copia por refugio). Al final se borra el archivo público y su miniatura, salvo que otra publicación
    lo use como foto (perros, reportes, productos, avatares, clínicas). Idempotente.

    Los nombres que ya no existen en disco se dejan como están (no hay archivo que proteger) y se cuentan en
    "missing" para revisarlos."""
    import uuid

    from sqlalchemy.orm.attributes import flag_modified

    from app.models import Refuge
    from app.routers.documents import legacy_name, private_dir
    from app.services.account_deletion import referenced_uploads

    stats = {"refuges": 0, "migrated": 0, "missing": 0, "public_deleted": 0, "public_kept": 0, "errors": 0}
    base = Path(settings.upload_dir)
    migrated_names: set[str] = set()
    for refuge in db.query(Refuge).order_by(Refuge.id).all():
        docs = list(refuge.documents or [])
        if not any(isinstance(d, str) and legacy_name(d) for d in docs):
            continue
        new_docs, changed = [], False
        for value in docs:
            name = legacy_name(value) if isinstance(value, str) else None
            if not name:
                new_docs.append(value)
                continue
            path = base / name
            ext = LEGACY_DOC_EXT.get(name.rsplit(".", 1)[-1].lower())
            if not path.is_file():
                stats["missing"] += 1
                new_docs.append(value)
                continue
            if not ext:
                logger.error("Documento antiguo del refugio %s con extensión no válida: %s", refuge.id, name)
                stats["errors"] += 1
                new_docs.append(value)
                continue
            try:
                doc_id = f"{uuid.uuid4().hex}.{ext}"
                if not dry_run:
                    write_private(private_dir() / doc_id, path.read_bytes())
                new_docs.append(doc_id)
                migrated_names.add(name)
                stats["migrated"] += 1
                changed = True
            except OSError as exc:
                logger.error("No se pudo migrar el documento %s del refugio %s: %s", name, refuge.id, exc)
                stats["errors"] += 1
                new_docs.append(value)
        if changed:
            stats["refuges"] += 1
            if not dry_run:
                refuge.documents = new_docs
                flag_modified(refuge, "documents")
                db.commit()
    if dry_run or not migrated_names:
        return stats
    still_used = referenced_uploads(db, migrated_names)  # fotos públicas de alguien (y documentos aún sin migrar)
    for name in sorted(migrated_names):
        if name in still_used:
            stats["public_kept"] += 1
            continue
        stem = name.rsplit(".", 1)[0]
        for candidate in (name, f"{stem}_thumb.jpg"):
            path = base / candidate
            try:
                if path.resolve().parent == base.resolve() and path.is_file():
                    path.unlink()
                    if candidate == name:
                        stats["public_deleted"] += 1
            except OSError as exc:
                logger.warning("No se pudo borrar el documento público %s: %s", candidate, exc)
    return stats


def encrypted_columns() -> list:
    """Columnas EncryptedText de los modelos (datos fiscales y secretos de MFA)."""
    from app.database import Base

    return [(table, col) for table in Base.metadata.sorted_tables for col in table.columns
            if isinstance(col.type, EncryptedText)]


def encrypt_existing_columns(db, rotate: bool = False, dry_run: bool = False) -> dict:
    """Cifra los valores que aún están en claro en las columnas EncryptedText (o con una llave anterior)."""
    from sqlalchemy import select, update

    stats: dict[str, int] = {}
    for table, col in encrypted_columns():
        pk = list(table.primary_key.columns)[0]
        raw = select(pk, col.cast(Text)).where(col.isnot(None))
        changed = 0
        for row_id, value in db.execute(raw).all():
            needs = (not str(value).startswith(COLUMN_PREFIX)) or (rotate and column_needs_reencryption(value))
            if not needs:
                continue
            changed += 1
            if not dry_run:
                db.execute(update(table).where(pk == row_id).values({col.name: decrypt_text(value)}))
        stats[f"{table.name}.{col.name}"] = changed
    if not dry_run:
        db.commit()
    return stats
