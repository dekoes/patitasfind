"""Pipeline de imágenes: validación, auto-orientación, borrado de EXIF, redimensión y miniatura."""
import io
import logging
import uuid
from pathlib import Path

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings

logger = logging.getLogger(__name__)

MAX_DIMENSION = 1600
THUMB_DIMENSION = 480
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
PUBLIC_PREFIX = "/uploads"


class ImageError(ValueError):
    pass


def upload_dir() -> Path:
    path = Path(settings.upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def max_bytes() -> int:
    return settings.max_upload_mb * 1024 * 1024


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        return img.getchannel("A").getextrema()[0] < 255
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def open_image(data: bytes) -> Image.Image:
    if not data:
        raise ImageError("El archivo está vacío.")
    if len(data) > max_bytes():
        raise ImageError(f"La imagen es demasiado grande. Máximo {settings.max_upload_mb} MB.")
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ImageError("El archivo no es una imagen válida. Usa JPG, PNG o WebP.")
    if fmt not in ALLOWED_FORMATS:
        raise ImageError(f"Formato no permitido ({fmt}). Usa JPG, PNG o WebP.")
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def process_image_bytes(data: bytes) -> str:
    """Guarda la imagen procesada y su miniatura. Devuelve la URL pública (/uploads/...)."""
    img = open_image(data)
    img = ImageOps.exif_transpose(img)  # aplica la orientación y descarta la rotación EXIF
    keep_alpha = _has_alpha(img)
    img = img.convert("RGBA" if keep_alpha else "RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    name = uuid.uuid4().hex
    folder = upload_dir()
    if keep_alpha:
        filename = f"{name}.webp"
        # Imagen nueva sin metadatos: no se copia EXIF (privacidad de GPS)
        clean = Image.new("RGBA", img.size)
        clean.paste(img)
        clean.save(folder / filename, "WEBP", quality=85, method=4)
        base_rgb = Image.new("RGB", img.size, (255, 255, 255))
        base_rgb.paste(img, mask=img.getchannel("A"))
        thumb_src = base_rgb
    else:
        filename = f"{name}.jpg"
        clean = Image.new("RGB", img.size)
        clean.paste(img)
        clean.save(folder / filename, "JPEG", quality=85, optimize=True, progressive=True)
        thumb_src = clean

    thumb = thumb_src.copy()
    thumb.thumbnail((THUMB_DIMENSION, THUMB_DIMENSION), Image.LANCZOS)
    thumb.save(folder / f"{name}_thumb.jpg", "JPEG", quality=80, optimize=True)
    return f"{PUBLIC_PREFIX}/{filename}"


def thumb_url(url: str) -> str:
    if not url.startswith(PUBLIC_PREFIX + "/"):
        return url
    stem = url.rsplit(".", 1)[0]
    return f"{stem}_thumb.jpg"


def local_path_for(url: str) -> Path | None:
    if url and url.startswith(PUBLIC_PREFIX + "/"):
        candidate = upload_dir() / url[len(PUBLIC_PREFIX) + 1:]
        if candidate.resolve().parent == upload_dir().resolve() and candidate.exists():
            return candidate
    return None


def load_image_bytes(url: str, headers: dict | None = None, timeout: int = 15) -> bytes | None:
    """Obtiene los bytes de una imagen local (/uploads/...) o remota (http/https)."""
    if not url:
        return None
    local = local_path_for(url)
    if not local and url.startswith(("http://", "https://")):
        # URL absoluta a nuestros propios /uploads (p. ej. https://patitasfind.mx/uploads/x.jpg)
        from urllib.parse import urlparse

        local = local_path_for(urlparse(url).path)
    if local:
        return local.read_bytes()
    if url.startswith("http://") or url.startswith("https://"):
        try:
            resp = requests.get(url, headers={"User-Agent": "PatitasFind/1.0", **(headers or {})}, timeout=timeout, stream=True)
            resp.raise_for_status()
            content = resp.raw.read(max_bytes() + 1, decode_content=True)
            if len(content) > max_bytes():
                logger.warning("Imagen remota demasiado grande: %s", url)
                return None
            return content
        except requests.RequestException as exc:
            logger.warning("No se pudo descargar la imagen %s: %s", url, exc)
            return None
    return None


def download_and_store(url: str, headers: dict | None = None) -> str | None:
    data = load_image_bytes(url, headers=headers)
    if not data:
        return None
    try:
        return process_image_bytes(data)
    except ImageError as exc:
        logger.warning("Imagen descartada %s: %s", url, exc)
        return None
