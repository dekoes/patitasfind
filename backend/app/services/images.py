"""Pipeline de imágenes: validación, auto-orientación, borrado de EXIF, redimensión y miniatura.

También concentra las reglas de seguridad de las fotos:
- Las URLs que manda el usuario solo pueden apuntar a nuestros /uploads (validate_upload_url).
- Tope de 40 megapíxeles contra "bombas de descompresión" (se revisa la cabecera antes de decodificar).
- Solo el servidor descarga medios remotos (WhatsApp/Facebook) y únicamente de hosts permitidos,
  a IPs públicas, con tiempo y tamaño acotados (fetch_remote_media).
"""
import io
import ipaddress
import logging
import re
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image, ImageOps, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError

from app.config import settings

logger = logging.getLogger(__name__)

MAX_DIMENSION = 1600
THUMB_DIMENSION = 480
MAX_PIXELS = 40_000_000  # 40 megapíxeles
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
PUBLIC_PREFIX = "/uploads"
REMOTE_TIMEOUT = 10  # segundos en total por descarga remota
MAX_REDIRECTS = 3

# Pillow avisa por encima de este valor y falla por encima del doble; nosotros rechazamos antes (ver probe_image)
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# Nombres que generamos al subir: <uuid hex>.<ext> y su miniatura <uuid hex>_thumb.jpg
GENERATED_NAME = re.compile(r"^([0-9a-f]{32})(_thumb)?\.(jpg|jpeg|png|webp)$")
# Nombres aceptados en URLs de fotos que manda el usuario (incluye archivos antiguos con otro nombre)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
# Solo en development: fotos de perros de dog.ceo para seed_data.py
DEV_REMOTE_HOSTS = ("images.dog.ceo",)
# Fotos de publicaciones de grupos públicos de Facebook (las devuelve el proveedor: scontent-*.fbcdn.net,
# *.fbsbx.com). Siempre permitidas, además de REMOTE_MEDIA_HOSTS.
FACEBOOK_MEDIA_HOSTS = ("*.fbcdn.net", "*.fbsbx.com")

TOO_MANY_PIXELS = "La imagen es demasiado grande en dimensiones. Máximo 40 megapíxeles (p. ej. 6000 × 6000 px)."
INVALID_IMAGE = "El archivo no es una imagen válida. Usa JPG, PNG o WebP."
EXTERNAL_URL = "Solo se aceptan fotos subidas a GuauWoow (no enlaces externos)."


class ImageError(ValueError):
    pass


class StaydownBlocked(ImageError):
    """La imagen coincide con una retirada (staydown, services/staydown.py). El mensaje no revela el motivo."""

    def __init__(self, block_id: int | None = None, kind: str | None = None):
        super().__init__("No se puede subir esta imagen porque se retiró de GuauWoow. Si crees que es un error, "
                         "escríbenos.")
        self.block_id = block_id
        self.kind = kind


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


def _swap(old: Image.Image, new: Image.Image) -> Image.Image:
    """Libera la imagen anterior en cuanto ya no se usa (las grandes ocupan cientos de MB)."""
    if new is not old:
        old.close()
    return new


# --------------------------------------------------------------------------- validación y decodificación
def probe_image(data: bytes) -> tuple[str, tuple[int, int]]:
    """Valida tamaño, formato y dimensiones leyendo solo la cabecera (sin decodificar los píxeles)."""
    if not data:
        raise ImageError("El archivo está vacío.")
    if len(data) > max_bytes():
        raise ImageError(f"La imagen es demasiado grande. Máximo {settings.max_upload_mb} MB.")
    try:
        probe = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError:
        raise ImageError(TOO_MANY_PIXELS)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageError(INVALID_IMAGE)
    with probe:
        fmt, size = probe.format, probe.size
        if fmt not in ALLOWED_FORMATS:
            raise ImageError(f"Formato no permitido ({fmt}). Usa JPG, PNG o WebP.")
        if size[0] * size[1] > MAX_PIXELS:
            raise ImageError(TOO_MANY_PIXELS)
        try:
            probe.verify()
        except Exception:  # noqa: BLE001 - verify() puede lanzar casi cualquier cosa con archivos dañados
            raise ImageError(INVALID_IMAGE)
    return fmt, size


def open_image(data: bytes, draft_size: tuple[int, int] | None = (MAX_DIMENSION, MAX_DIMENSION)) -> Image.Image:
    """Valida y decodifica. Los JPEG se decodifican directo a escala (1/2, 1/4 u 1/8) si sobran píxeles."""
    probe_image(data)
    img = Image.open(io.BytesIO(data))
    try:
        if draft_size and img.format in ("JPEG", "MPO"):
            # draft() reduce según el lado más justo: se le pide el tamaño final con la misma proporción
            ratio = min(draft_size[0] / img.width, draft_size[1] / img.height)
            if ratio < 1:
                img.draft("RGB", (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
        img.load()
    except Exception as exc:  # noqa: BLE001
        img.close()
        raise ImageError("No pudimos leer la imagen; puede estar dañada. Intenta con otra.") from exc
    return img


def process_image_bytes(data: bytes) -> str:
    """Guarda la imagen procesada y su miniatura. Devuelve la URL pública (/uploads/...)."""
    img = open_image(data)
    try:
        if img.mode not in ("RGB", "RGBA", "L", "LA"):
            # Paletas, CMYK, 16 bits...: a RGB(A) antes de reducir (la paleta se reescalaría sin suavizado)
            img = _swap(img, img.convert("RGBA" if _has_alpha(img) else "RGB"))
        # Primero se reduce (en su lugar) para no copiar la imagen grande en cada paso
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
        img = _swap(img, ImageOps.exif_transpose(img))  # aplica la orientación y descarta la rotación EXIF
        from app.services import staydown  # import diferido: staydown usa open_image

        staydown.check_image(img)  # imágenes retiradas (derechos de autor, autoridad, cuarentena): StaydownBlocked
        keep_alpha = _has_alpha(img)
        img = _swap(img, img.convert("RGBA" if keep_alpha else "RGB"))

        name = uuid.uuid4().hex
        folder = upload_dir()
        # Imagen nueva sin metadatos: no se copia EXIF (privacidad de GPS)
        clean = Image.new(img.mode, img.size)
        clean.paste(img)
        if keep_alpha:
            filename = f"{name}.webp"
            clean.save(folder / filename, "WEBP", quality=85, method=4)
            thumb = Image.new("RGB", img.size, (255, 255, 255))
            thumb.paste(img, mask=img.getchannel("A"))
            clean.close()
        else:
            filename = f"{name}.jpg"
            clean.save(folder / filename, "JPEG", quality=85, optimize=True, progressive=True)
            thumb = clean
        _save_thumbnail(thumb, folder / f"{name}_thumb.jpg")
        thumb.close()
        return f"{PUBLIC_PREFIX}/{filename}"
    finally:
        img.close()


def _save_thumbnail(img: Image.Image, path: Path) -> None:
    thumb = img.copy()
    thumb.thumbnail((THUMB_DIMENSION, THUMB_DIMENSION), Image.LANCZOS)
    thumb.save(path, "JPEG", quality=80, optimize=True)
    thumb.close()


def ensure_thumbnail(path: Path) -> bool:
    """Crea <stem>_thumb.jpg para una foto ya guardada que no la tenga (archivos antiguos). True si la creó."""
    target = path.with_name(f"{path.stem}_thumb.jpg")
    if path.stem.endswith("_thumb") or target.exists():
        return False
    try:
        with open_image(path.read_bytes(), draft_size=(THUMB_DIMENSION, THUMB_DIMENSION)) as img:
            rgba = img.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, (255, 255, 255))
        rgb.paste(rgba, mask=rgba.getchannel("A"))  # transparencias sobre fondo blanco, como al subir
        rgba.close()
        _save_thumbnail(rgb, target)
        rgb.close()
        return True
    except (ImageError, OSError) as exc:
        logger.warning("No se pudo crear la miniatura de %s: %s", path.name, exc)
        return False


def thumb_url(url: str) -> str:
    if not url.startswith(PUBLIC_PREFIX + "/"):
        return url
    stem = url.rsplit(".", 1)[0]
    return f"{stem}_thumb.jpg"


# --------------------------------------------------------------------------- URLs que manda el usuario
def _own_upload_path(raw: str) -> str:
    """Ruta /uploads/... de una URL relativa o absoluta a nuestro dominio. ValueError si es externa."""
    if raw.lower().startswith(("http://", "https://")) or raw.startswith("//"):
        parsed = urlparse(raw)
        own = urlparse(settings.public_url())
        if ((parsed.scheme.lower(), parsed.netloc.lower()) != (own.scheme.lower(), own.netloc.lower())
                or parsed.params or parsed.query or parsed.fragment):
            raise ValueError(EXTERNAL_URL)
        raw = parsed.path
    prefix = PUBLIC_PREFIX + "/"
    if not raw.startswith(prefix):
        raise ValueError(EXTERNAL_URL)
    return raw


def validate_upload_url(value: str) -> str:
    """Validador para fotos/avatares: solo /uploads/<archivo> o <PUBLIC_BASE_URL>/uploads/<archivo>.

    Rechaza enlaces externos (SSRF, rastreo de IP de otros usuarios), subcarpetas y "..".
    Devuelve siempre la ruta relativa /uploads/<archivo>.
    """
    if not isinstance(value, str):
        raise ValueError(EXTERNAL_URL)
    path = _own_upload_path(value.strip())
    name = path[len(PUBLIC_PREFIX) + 1:]
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError("El nombre del archivo de la foto no es válido.")
    return f"{PUBLIC_PREFIX}/{name}"


def local_path_for(url: str) -> Path | None:
    """Archivo local de una URL /uploads/<archivo> (o absoluta a nuestro dominio). None si no existe."""
    if not url or not isinstance(url, str):
        return None
    try:
        path = _own_upload_path(url.strip())
    except ValueError:
        return None
    folder = upload_dir().resolve()
    candidate = folder / path[len(PUBLIC_PREFIX) + 1:]
    try:
        if candidate.resolve().parent == folder and candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


# --------------------------------------------------------------------------- descargas remotas (solo del servidor)
def _ip_is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class _PublicOnlyHTTPSConnection(HTTPSConnection):
    """Resuelve el DNS y solo conecta a IPs públicas (nada de localhost, red privada, link-local ni metadata).

    La validación ocurre al abrir el socket, así que cubre también redirecciones y DNS rebinding.
    El certificado TLS se sigue verificando contra el nombre del host.
    """

    def _new_conn(self):
        host = self._dns_host
        try:
            infos = socket.getaddrinfo(host, self.port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise NewConnectionError(self, f"No se pudo resolver {host}: {exc}") from exc
        addresses = [info[4][0] for info in infos]
        blocked = [a for a in addresses if not _ip_is_public(a)]
        if not addresses or blocked:
            raise NewConnectionError(self, f"Destino no permitido: {host} resuelve a {', '.join(blocked) or 'nada'}")
        self._dns_host = addresses[0]
        try:
            return super()._new_conn()
        finally:
            self._dns_host = host


class _PublicOnlyHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicOnlyHTTPSConnection


class _PublicOnlyAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {**self.poolmanager.pool_classes_by_scheme, "https": _PublicOnlyHTTPSPool}


def _remote_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # sin proxies del entorno: la validación de IP aplica al destino real
    session.mount("https://", _PublicOnlyAdapter(max_retries=0))
    return session


def remote_hosts() -> list[str]:
    hosts = [h.strip().lower() for h in (settings.remote_media_hosts or "").split(",") if h.strip()]
    hosts += [h for h in FACEBOOK_MEDIA_HOSTS if h not in hosts]
    if settings.is_development:
        hosts += DEV_REMOTE_HOSTS
    return hosts


def _host_allowed(host: str, extra_hosts=()) -> bool:
    host = host.lower().rstrip(".")
    for pattern in [*remote_hosts(), *(h.lower() for h in extra_hosts)]:
        if pattern.startswith("*."):
            if host == pattern[2:] or host.endswith(pattern[1:]):
                return True
        elif host == pattern:
            return True
    return False


def _remote_url_problem(url: str, extra_hosts=()) -> str | None:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return "URL inválida"
    if parsed.scheme != "https":
        return "solo se permite https"
    if parsed.username or parsed.password:
        return "la URL trae credenciales"
    if port not in (None, 443):
        return f"puerto no permitido ({port})"
    if not parsed.hostname or not _host_allowed(parsed.hostname, extra_hosts):
        return f"host no permitido ({parsed.hostname})"
    return None


def _display(url: str) -> str:
    """URL sin query (las de WhatsApp/Facebook traen firmas temporales) para los logs."""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname}{parsed.path[:80]}"
    except ValueError:
        return "<URL inválida>"


def fetch_remote_media(url: str, headers: dict | None = None, timeout: float = REMOTE_TIMEOUT,
                       extra_hosts: tuple[str, ...] = ()) -> bytes | None:
    """Descarga medios de servidores permitidos (REMOTE_MEDIA_HOSTS: WhatsApp/Facebook). None si no se puede.

    Solo https, sin credenciales en la URL, a IPs públicas, máximo MAX_REDIRECTS redirecciones (cada una
    validada), `timeout` segundos en total y MAX_UPLOAD_MB leídos en streaming. Los `headers` (p. ej. el
    token de WhatsApp) solo se envían al host original.
    """
    limit = max_bytes()
    deadline = time.monotonic() + timeout
    origin = (urlparse(url).hostname or "").lower() if isinstance(url, str) else ""
    current = url
    with _remote_session() as session:
        for _ in range(MAX_REDIRECTS + 1):
            problem = _remote_url_problem(current, extra_hosts)
            if problem:
                logger.warning("Descarga remota rechazada (%s): %s", problem, _display(current))
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("Descarga remota cancelada por tiempo: %s", _display(current))
                return None
            same_host = (urlparse(current).hostname or "").lower() == origin
            send = {"User-Agent": "GuauWoow/1.0", **((headers or {}) if same_host else {})}
            try:
                resp = session.get(current, headers=send, timeout=(min(5, remaining), remaining),
                                   stream=True, allow_redirects=False)
            except requests.RequestException as exc:
                logger.warning("No se pudo descargar %s: %s", _display(current), exc)
                return None
            with resp:
                if resp.is_redirect:
                    current = urljoin(current, resp.headers.get("location", ""))
                    continue
                if resp.status_code != 200:
                    logger.warning("Descarga remota con HTTP %s: %s", resp.status_code, _display(current))
                    return None
                length = resp.headers.get("content-length", "")
                if length.isdigit() and int(length) > limit:
                    logger.warning("Archivo remoto demasiado grande (%s bytes): %s", length, _display(current))
                    return None
                buf = bytearray()
                try:
                    for chunk in resp.iter_content(64 * 1024):
                        buf.extend(chunk)
                        if len(buf) > limit:
                            logger.warning("Archivo remoto demasiado grande: %s", _display(current))
                            return None
                        if time.monotonic() > deadline:
                            logger.warning("Descarga remota cancelada por tiempo: %s", _display(current))
                            return None
                except requests.RequestException as exc:
                    logger.warning("Descarga remota interrumpida %s: %s", _display(current), exc)
                    return None
                return bytes(buf)
    logger.warning("Demasiadas redirecciones: %s", _display(url))
    return None


def load_image_bytes(url: str, headers: dict | None = None, timeout: int = REMOTE_TIMEOUT,
                     allow_remote: bool = False) -> bytes | None:
    """Bytes de una imagen local (/uploads/... o absoluta a nuestro dominio).

    Las URLs remotas solo se descargan con allow_remote=True (medios que origina el servidor:
    WhatsApp/Facebook) y pasan por fetch_remote_media. Las fotos guardadas en la BD siempre son locales.
    """
    if not url or not isinstance(url, str):
        return None
    local = local_path_for(url)
    if local:
        if local.stat().st_size > max_bytes():
            logger.warning("Imagen local demasiado grande: %s", local.name)
            return None
        return local.read_bytes()
    if url.startswith(("http://", "https://")):
        if allow_remote:
            return fetch_remote_media(url, headers=headers, timeout=timeout)
        logger.info("Se ignora la imagen remota %s: solo se leen archivos locales.", _display(url))
    return None


def download_and_store(url: str, headers: dict | None = None) -> str | None:
    """Descarga (local o de un host permitido) y guarda la imagen procesada. Para medios de WhatsApp/Facebook."""
    data = load_image_bytes(url, headers=headers, allow_remote=True)
    if not data:
        return None
    try:
        return process_image_bytes(data)
    except ImageError as exc:
        logger.warning("Imagen descartada %s: %s", _display(url), exc)
        return None
