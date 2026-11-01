"""Grupos públicos de Facebook por estado: lectura con un proveedor externo, limpieza e ingesta.

GuauWoow no entra a Facebook: un proveedor (Apify, actor "apify/facebook-groups-scraper") devuelve las
publicaciones públicas de cada grupo y aquí se convierten en reportes con fuente "facebook":
  - Se quitan teléfonos, correos, @usuarios, enlaces, datos de pago (tarjetas, CLABE), números de casa y
    nombres de contacto del texto antes de guardarlo (strip_pii).
  - Solo se importan publicaciones que parecen de perros perdidos/encontrados (classify_post) y, con IA
    configurada, cuya foto sea de un perro (create_report_from_post con require_dog=True).
  - Cada grupo se intenta leer como máximo cada FB_GROUPS_FETCH_INTERVAL_HOURS (last_attempt_at, también tras
    un error) y se piden las publicaciones desde la última lectura correcta (last_fetched_at, con tope
    FB_GROUPS_LOOKBACK_DAYS): un error no hace perder publicaciones.
  - El gasto diario en el proveedor se aparta en Redis antes de cada corrida, de forma atómica
    (FB_GROUPS_DAILY_BUDGET_USD); al rebasarlo se detiene. Al terminar se ajusta con el costo real que
    informa Apify (usageTotalUsd) o, si no lo da, con la estimación.
  - Tras leer cada corrida se borra su dataset en Apify (no se quedan copias de las publicaciones allá).
  - Las publicaciones se deduplican por su URL canónica (LostReport.external_url, índice único).
  - Los reportes importados (y los envíos de voluntarios) caducan a los 30 días de la publicación y luego se
    borran su texto y fotos (expire_imported_reports / purge_imported_reports).
También viven aquí la importación de voluntarios (POST /facebook/volunteer-import) y el retiro sin cuenta.
"""
import datetime
import logging
import re
import threading
import time
import unicodedata
from decimal import Decimal
from urllib.parse import urlparse

import requests
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import cache
from app.config import settings
from app.data import estados_mx
from app.models import ContentReport, FacebookGroup, LostReport, User
from app.services import facebook_monitor
from app.services.background import dispatch

logger = logging.getLogger(__name__)

APIFY_API = "https://api.apify.com/v2"
# La corrida del actor dura como máximo APIFY_RUN_TIMEOUT (Apify la corta: estado TIMED-OUT). Se consulta cada
# APIFY_WAIT_SECONDS con waitForFinish (máximo 60 s según la API) hasta ese tiempo más un margen.
APIFY_RUN_TIMEOUT = 240  # segundos que puede durar la corrida del actor
APIFY_WAIT_SECONDS = 60
APIFY_POLL_MARGIN = 60  # segundos de espera extra tras APIFY_RUN_TIMEOUT antes de abortar la corrida
APIFY_HTTP_TIMEOUT = (10, APIFY_WAIT_SECONDS + 15)  # (conexión, lectura) de cada petición HTTP
APIFY_TERMINAL = ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED")
# Tiempo total por grupo (lectura en el proveedor + descarga de fotos e IA). La tarea fetch_group tiene
# soft_time_limit=540 s; si se acaba, lo pendiente se lee en la siguiente corrida.
GROUP_INGEST_TIME_BUDGET = 500.0
SPEND_KEY_TTL = 31 * 86400  # los contadores del día se conservan 31 días (historial del panel)
KEY_PREFIX = "fbg"  # prefijo de las claves de Redis (las pruebas usan uno propio)
MAX_IMAGES_PER_POST = 3
BUDGET_EXHAUSTED = "Presupuesto diario agotado"
PARTIAL_RUN_ERROR = "Lectura incompleta: Apify agotó el tiempo; lo que falta se lee en la siguiente corrida."

IMPORTED_SOURCES = ("facebook", "volunteer")
AUTHOR_REMOVAL_REASON = "retiro_autor"  # motivo de ContentReport para «Soy el autor: retirar»
AUTHOR_REMOVAL_PURGE_HOURS = 72  # el retiro se completa (texto y fotos borrados) a más tardar en 72 h
PURGED_DESCRIPTION = ("Contenido retirado: esta publicación importada de Facebook caducó o su autor pidió "
                      "retirarla. Ya no guardamos su texto ni sus fotos.")
PURGED_NAME = "Contenido retirado"

GROUP_URL_RE = re.compile(r"^https?://(?:www\.|m\.|web\.|mobile\.|touch\.)?facebook\.com/groups/([A-Za-z0-9._-]+)/?(?:[?#].*)?$",
                          re.IGNORECASE)
FACEBOOK_HOSTS = ("facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "mobile.facebook.com",
                  "touch.facebook.com", "fb.com", "www.fb.com", "fb.watch", "l.facebook.com", "business.facebook.com")
# Rutas cuyo identificador de publicación va en la query
QUERY_ID_PATHS = ("/permalink.php", "/photo.php", "/story.php", "/photo", "/watch")
# Subpáginas de un grupo que no son una publicación
GROUP_SUBPAGES = {"about", "members", "media", "files", "events", "buy_sell_discussion", "search", "photos",
                  "videos", "announcements", "featured"}
GROUP_LINK_PROBLEM = ("Ese enlace es del grupo, no de la publicación. Abre la publicación (toca su fecha) y copia "
                      "ese enlace.")
PROFILE_LINK_PROBLEM = ("Ese enlace es de un perfil o una página, no de la publicación. Abre la publicación (toca su "
                        "fecha) y copia ese enlace.")
NOT_FACEBOOK_PROBLEM = "El enlace debe ser de una publicación de Facebook (facebook.com/...)."


class ProviderError(RuntimeError):
    """El proveedor falló (token, saldo, tiempo, red). El mensaje es apto para mostrar a un admin.

    cost_usd: lo que el proveedor ya cobró por la corrida fallida (None = nada, p. ej. si no arrancó).
    """

    cost_usd: float | None = None


class ProviderNotConfigured(ProviderError):
    pass


# --------------------------------------------------------------------------- URLs
def normalize_group_url(url: str | None) -> str | None:
    """https://www.facebook.com/groups/<id o alias> o None si no es la URL de un grupo."""
    m = GROUP_URL_RE.match((url or "").strip())
    if not m:
        return None
    return f"https://www.facebook.com/groups/{m.group(1)}"


def normalize_post_url(url: str | None) -> str | None:
    """URL canónica de una publicación de Facebook (sin query ni fragmento) para deduplicar; None si no es de Facebook."""
    raw = (url or "").strip()
    if not raw:
        return None
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in FACEBOOK_HOSTS:
        return None
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    if host in ("l.facebook.com",) or not path:
        return None
    # Los enlaces /share/p/<id>, /permalink.php?story_fbid=... y /photo.php?fbid=... dependen de la query
    query = ""
    if path in QUERY_ID_PATHS:
        keep = [p for p in (parsed.query or "").split("&") if p.split("=")[0] in ("story_fbid", "fbid", "id", "v")]
        query = "?" + "&".join(sorted(keep)) if keep else ""
        if not query:
            return None
    canonical_host = "fb.watch" if host == "fb.watch" else "www.facebook.com"
    return f"https://{canonical_host}{path}{query}"[:500]


def post_url_problem(url: str | None) -> str | None:
    """Motivo (en español) por el que el enlace no sirve como publicación de Facebook; None si sirve.

    Igual que urlProblem() en app/compartir.js: se rechazan la raíz de un grupo (/groups/<id>) y sus
    subpáginas, el inicio (/, /home.php), /marketplace, /watch sin video y los perfiles o páginas (/<usuario>).
    """
    canonical = normalize_post_url(url)
    if not canonical:
        return NOT_FACEBOOK_PROBLEM
    parsed = urlparse(canonical)
    if parsed.hostname == "fb.watch" or parsed.path in QUERY_ID_PATHS:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    first = segments[0].lower() if segments else ""
    if first == "groups" and (len(segments) <= 2 or segments[2].lower() in GROUP_SUBPAGES):
        return GROUP_LINK_PROBLEM
    if first in ("home.php", "marketplace", "watch", "search"):
        return GROUP_LINK_PROBLEM
    if len(segments) == 1:  # /<usuario>, /profile.php o el nombre de una página
        return PROFILE_LINK_PROBLEM
    return None


# --------------------------------------------------------------------------- datos personales
# Correos primero: si no, el dominio ("gmail.com") se quitaría como enlace y dejaría "usuario@"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Enlaces con esquema, con www. o con dominio suelto (m.me/juan, facebook.com/juan.perez, instagram.com/juan,
# wa.me/52..., bit.ly/..., linktr.ee/...). El enlace a la publicación original se guarda aparte.
_URL_RE = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|\b(?:[a-z0-9-]+\.)+(?:com|mx|me|net|org|ly|gl|link|ee|io|co|app|page|info|watch|bio|lat|tv|gg)\b(?:/\S*)?",
    re.IGNORECASE,
)
_HANDLE_RE = re.compile(r"(?<![\w.])@[\w.]{2,}")
# Corridas de dígitos con separadores de teléfono/tarjeta (espacios, puntos, guiones, paréntesis; prefijo +52)
_NUMBER_RUN_RE = re.compile(r"\+?\(?\d(?:[ \t().\-]{0,3}\d)*\)?")
# Fechas que no son teléfonos: 2025 10 12, 2025-10-12, 12-10-2025, 12.10.2025
_DATE_YMD_RE = re.compile(r"^(?:19|20)\d{2}[ \t.\-]{1,3}(?:0?[1-9]|1[0-2])[ \t.\-]{1,3}(?:0?[1-9]|[12]\d|3[01])$")
_DATE_DMY_RE = re.compile(r"^(?:0?[1-9]|[12]\d|3[01])[ \t.\-]{1,3}(?:0?[1-9]|1[0-2])[ \t.\-]{1,3}(?:19|20)\d{2}$")
# Número de casa o interior ("#123", "número 45", "No. 12 int. 3"): la calle se queda (zona aproximada)
_HOUSE_NUMBER_RE = re.compile(
    r"(?:#|\bn[uú]m(?:ero)?\.?|\bNo\.|\bno\.)\s*\d{1,5}[a-z]?"
    r"(?:\s*(?:int(?:erior)?\.?|depto\.?|dpto\.?|departamento)\s*[\w-]{1,4})?",
)
# Nombres de contacto: "Contacto: Juan Pérez", "pregunta por Lupita", "comunícate con Sra. María", "Atte. Ana".
# Contrato L-fb (contenido-importado.html): se guardan sin nombres de personas, así que también se quitan los que
# siguen a "soy", "me llamo", "mi nombre es", "con", las firmas y los pares de nombre y apellido (aunque a veces
# "soy Rocky" sea el perrito hablando: el nombre del perro no es indispensable para buscarlo).
_PERSON_NAME = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:[ \t]+(?:de[ \t]+(?:la[ \t]+|los[ \t]+)?)?[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){0,3}"
_CONTACT_NAME_RE = re.compile(
    r"(?i:\b(?:(?:contacto|due[ñn][oa])\s*:\s*"
    r"|(?:contactar\s+a|comun[ií]ca(?:te|rse)\s+con|preg[uú]nta(?:r)?\s+por|informes\s+con|info\s+con"
    r"|habla(?:r)?\s+con|llama(?:r)?\s+a)\s+"
    r"|(?:atte|atentamente)\b\.?\s*:?\s*))"
    r"(?:(?:Sra?|Srta|Lic|Ing|Dra?|Prof|Don|Doña)\.?\s+)?" + _PERSON_NAME
)
_HONORIFIC_NAME_RE = re.compile(r"\b(?:Sra?|Srta|Lic|Ing|Dra?|Prof)\.\s*" + _PERSON_NAME)
# "soy Juan", "me llamo Ana López", "mi nombre es Rosa"
_SELF_NAME_RE = re.compile(r"(?i:\b(?:soy|me\s+llamo|mi\s+nombre\s+es)\s+)(?:(?:Sra?|Srta|Lic|Ing|Dra?|Prof)\.?\s+)?"
                           + _PERSON_NAME)
# "con Juan", "con la Sra. Rosa" (solo si sigue una palabra con mayúscula que no es parte de la descripción del perro)
_WITH_NAME_RE = re.compile(r"(?i:\bcon\s+(?:(?:la|el)\s+)?)(?:(?:Sra?|Srta|Lic|Ing|Dra?|Prof|Don|Doña)\.?\s+)?("
                           + _PERSON_NAME + ")")
_NOT_NAMES = {
    "collar", "placa", "chip", "microchip", "correa", "pechera", "arnes", "sueter", "ropa", "mancha", "manchas", "cola",
    "orejas", "ojos", "pelo", "cicatriz", "mono", "cadena", "su", "sus", "un", "una", "mucho", "mucha", "miedo", "hambre",
    "frio", "dios", "cuidado", "gusto", "amor", "todo", "toda", "ella", "el", "ellos", "nosotros", "nadie", "alguien",
    "quien", "esta", "este", "ese", "esa", "patitasfind", "guauwoow", "facebook", "whatsapp",
}
# Firmas: "Saludos, Juan", "Gracias. María López", "— Ana", o una última línea que solo trae un nombre propio
_SIGN_OFF_RE = re.compile(r"(?i:\b(?:saludos|gracias|bendiciones|besos|abrazos|cordialmente|att|atte)\b[.,:!]*\s+)"
                          + _PERSON_NAME + r"\s*[.!]*\s*$", re.MULTILINE)
_DASH_SIGNATURE_RE = re.compile(r"^\s*[-–—~]+\s*" + _PERSON_NAME + r"\s*$", re.MULTILINE)
_NAME_LINE_RE = re.compile(r"^\s*" + _PERSON_NAME + r"\s*[.!]*\s*$")
# Pares de nombre y apellido que empiezan con un nombre de pila común ("Juan Pérez", "María de la Luz Gómez")
_NAME_PAIR_RE = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+)((?:[ \t]+(?:de[ \t]+(?:la[ \t]+|los[ \t]+)?)?"
                           r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){1,3})")
_GIVEN_NAMES = frozenset(unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode() for n in """
    juan jose maria guadalupe lupita ana luis carlos jorge miguel pedro francisco paco antonio manuel jesus javier
    alejandro alejandra fernando fernanda ricardo roberto daniel daniela david eduardo sergio raul rafael mario arturo
    alberto enrique hector oscar pablo diego andres gabriel gabriela adriana patricia veronica laura monica claudia rosa
    martha marta elena isabel carmen sofia valeria mariana karla karina paola andrea lucia teresa leticia silvia beatriz
    alicia gloria norma angelica margarita yolanda araceli diana lorena erika brenda jessica jazmin ximena regina camila
    victoria susana cecilia irma elizabeth juana josefina sandra liliana gerardo ivan omar cesar hugo victor alfredo
    ramon salvador ignacio gustavo julio emilio ruben marco marcos armando joaquin rodrigo santiago mateo sebastian
    leonardo emiliano nicolas esteban alan kevin brian luz dulce esperanza consuelo dolores rocio lourdes fabiola
""".split())
_SPACES_RE = re.compile(r"[ \t]{2,}")
_ORPHAN_PUNCT_RE = re.compile(r"[ \t]+([,.;:!?])")
_LEADING_PUNCT_RE = re.compile(r"^[,.;:!?]+[ \t]*")
_DOUBLE_PUNCT_RE = re.compile(r"(?<![.])[,.;:]{2}(?![.])")  # "placa.." o ".," que deja un nombre quitado


def _fold(word: str) -> str:
    return unicodedata.normalize("NFKD", word or "").encode("ascii", "ignore").decode().lower()


def _with_name_sub(match: re.Match) -> str:
    first = match.group(1).split()[0]
    return match.group(0) if _fold(first) in _NOT_NAMES else ""


def _name_pair_sub(match: re.Match) -> str:
    return "" if _fold(match.group(1)) in _GIVEN_NAMES else match.group(0)


def strip_person_names(text: str) -> str:
    """Quita nombres de personas con heurísticas (contrato L-fb). Idempotente."""
    clean = _SELF_NAME_RE.sub("", text)
    clean = _WITH_NAME_RE.sub(_with_name_sub, clean)
    clean = _SIGN_OFF_RE.sub("", clean)
    clean = _DASH_SIGNATURE_RE.sub("", clean)
    clean = _NAME_PAIR_RE.sub(_name_pair_sub, clean)
    lines = [line for line in clean.splitlines()]
    # Firma al final: una última línea que solo trae un nombre propio (p. ej. "María López")
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) > 1 and _NAME_LINE_RE.match(lines[-1]) and _fold(lines[-1].split()[0]) in _GIVEN_NAMES:
        lines.pop()
    return "\n".join(lines)


def _looks_like_date_or_years(raw: str) -> bool:
    text = raw.strip("()+ \t")
    if _DATE_YMD_RE.match(text) or _DATE_DMY_RE.match(text):
        return True
    groups = re.findall(r"\d+", text)
    return len(groups) > 1 and all(len(g) == 4 and g[:2] in ("19", "20") for g in groups)  # "2023 2024"


def _number_sub(match: re.Match) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 16:  # tarjeta (16), CLABE (18) u otra cuenta: siempre fuera
        return ""
    if 8 <= len(digits) <= 15 and not _looks_like_date_or_years(raw):  # teléfono (con o sin lada / +52)
        return ""
    return raw


def strip_pii(text: str | None) -> str:
    """Quita datos personales de una publicación antes de guardarla (el enlace a la publicación va aparte).

    Fuera: correos, enlaces (también sin https: m.me/..., facebook.com/...), @usuarios, teléfonos de 8 a 15
    dígitos, tarjetas y CLABE (16 a 19 dígitos, con o sin espacios o guiones), números de casa y nombres de
    personas ("Contacto: Juan Pérez", "pregunta por Lupita", "soy Ana", "con Rosa", firmas y pares de nombre y
    apellido). Se conservan fechas, años, edades y códigos postales.
    """
    if not text:
        return ""
    clean = _EMAIL_RE.sub("", text)
    clean = _URL_RE.sub("", clean)
    clean = _HANDLE_RE.sub("", clean)
    clean = _NUMBER_RUN_RE.sub(_number_sub, clean)
    clean = _HOUSE_NUMBER_RE.sub("", clean)
    clean = _CONTACT_NAME_RE.sub("", clean)
    clean = _HONORIFIC_NAME_RE.sub("", clean)
    clean = strip_person_names(clean)
    clean = _SPACES_RE.sub(" ", clean)
    clean = _ORPHAN_PUNCT_RE.sub(r"\1", clean)
    clean = _DOUBLE_PUNCT_RE.sub(lambda m: m.group(0)[-1] if m.group(0)[-1] == "." else m.group(0)[0], clean)
    return "\n".join(_LEADING_PUNCT_RE.sub("", line.strip()) for line in clean.splitlines()).strip()


# --------------------------------------------------------------------------- proveedores
class BaseProvider:
    """Interfaz: fetch_posts(group_url, since, limit) -> [{post_url, text, created_at, image_urls}].

    created_at es datetime UTC sin tzinfo (o None) e image_urls son URLs https de fotos. max_charge_usd es un
    tope de gasto para la corrida (los proveedores que no lo soporten lo ignoran). Después de cada llamada:
    last_run_id (referencia), last_run_cost_usd (costo real si el proveedor lo informa; None = estimar) y
    last_run_partial (True si la corrida se cortó y faltan publicaciones).
    """

    name = "base"
    last_run_id: str | None = None
    last_run_cost_usd: float | None = None
    last_run_partial: bool = False

    def fetch_posts(self, group_url: str, since: datetime.datetime, limit: int,
                    max_charge_usd: float | None = None) -> list[dict]:
        raise NotImplementedError


# Nombres de campos del actor apify/facebook-groups-scraper (verificados en apify.com/apify/facebook-groups-scraper,
# su pestaña "Input schema" y docs.apify.com/api/v2 el 2026-10-17). Si Apify los renombra, solo se cambia este dict.
#  - entrada: startUrls [{url}], resultsLimit, viewOption ("CHRONOLOGICAL"), onlyPostsNewerThan (YYYY-MM-DD, ISO
#    completo o parcial, o relativo como "2 days"; siempre UTC)
#  - salida (una fila por publicación): url (permalink), text, time (ISO 8601), facebookUrl (grupo), user, likesCount...
#    Los medios (fotos/miniaturas/OCR, documentados en el README) no aparecen en la fila de ejemplo de la ficha,
#    así que se aceptan los contenedores y las rutas que usan los actores de Facebook de Apify.
#  - API (docs.apify.com/api/v2, "Run Actor", "Get run", "Get dataset items", "Delete dataset"):
#      POST /v2/acts/<usuario~actor>/runs?timeout&maxItems&maxTotalChargeUsd&waitForFinish -> 201 {data: Run}
#      GET  /v2/actor-runs/<id>?waitForFinish (máx. 60 s) -> {data: Run}; Run.status READY|RUNNING|SUCCEEDED|
#           FAILED|TIMING-OUT|TIMED-OUT|ABORTING|ABORTED; Run.defaultDatasetId; Run.usageTotalUsd (costo real)
#      GET  /v2/datasets/<id>/items?clean=true&format=json&limit -> lista de filas
#      DELETE /v2/datasets/<id> -> 204 (purga: no quedan copias de las publicaciones en Apify)
#      POST /v2/actor-runs/<id>/abort (si la corrida no termina a tiempo)
#    Se usa la corrida asíncrona y no run-sync-get-dataset-items porque esta última no devuelve el id de la
#    corrida ni del dataset (solo encabezados X-Apify-Pagination-*): sin ellos no se puede borrar el dataset
#    ni leer el costo real. Autenticación: "Authorization: Bearer <token>".
APIFY_FIELDS = {
    "input": {"start_urls": "startUrls", "url": "url", "results_limit": "resultsLimit", "view_option": "viewOption",
              "only_newer_than": "onlyPostsNewerThan"},
    "view_option": "CHRONOLOGICAL",
    "output": {
        "post_url": ("url", "postUrl", "permalink"),
        "text": ("text", "message"),
        "created_at": ("time", "timestamp", "date"),
        "media": ("attachments", "media", "images"),
        # Dentro de cada medio: ruta con puntos = anidado (photo_image.uri). "url" solo si apunta a un CDN de Facebook.
        "image_url": ("photo_image.uri", "image.uri", "fullImageUrl", "imageUrl", "thumbnail", "url"),
    },
    "run": {"id": "id", "status": "status", "dataset": "defaultDatasetId", "cost": "usageTotalUsd",
            "message": "statusMessage", "store": "defaultKeyValueStoreId"},
}
_IMAGE_HOST_RE = re.compile(r"^https://[^/]*\.(?:fbcdn\.net|fbsbx\.com)/", re.IGNORECASE)


def _first(item: dict, keys: tuple[str, ...]):
    for key in keys:
        value = item
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value not in (None, "", [], {}):
            return value
    return None


def parse_datetime(value) -> datetime.datetime | None:
    """ISO 8601 ("2025-12-10T04:37:15.000Z") o epoch (segundos) -> datetime UTC sin tzinfo (como el resto de la BD)."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.datetime.utcfromtimestamp(float(value))
        raw = str(value).strip()
        if raw.isdigit():
            return datetime.datetime.utcfromtimestamp(float(raw))
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, OverflowError, OSError):
        return None


def parse_apify_item(item: dict) -> dict | None:
    """Fila del dataset de Apify -> {post_url, text, created_at, image_urls}. None si no trae URL de publicación."""
    if not isinstance(item, dict):
        return None
    out = APIFY_FIELDS["output"]
    post_url = _first(item, out["post_url"])
    if not isinstance(post_url, str) or not post_url.strip():
        return None
    images: list[str] = []
    media = _first(item, out["media"]) or []
    if isinstance(media, dict):
        media = [media]
    for entry in media if isinstance(media, list) else []:
        url = entry if isinstance(entry, str) else _first(entry, out["image_url"]) if isinstance(entry, dict) else None
        if isinstance(url, str) and _IMAGE_HOST_RE.match(url) and url not in images:
            images.append(url)
        if len(images) >= MAX_IMAGES_PER_POST:
            break
    text = _first(item, out["text"])
    return {
        "post_url": post_url.strip(),
        "text": text if isinstance(text, str) else "",
        "created_at": parse_datetime(_first(item, out["created_at"])),
        "image_urls": images,
    }


class ApifyProvider(BaseProvider):
    """Corre el actor (asíncrono, con espera), lee su dataset, lo borra en Apify y devuelve las publicaciones."""

    name = "apify"

    def __init__(self, token: str, actor: str | None = None, run_timeout: int = APIFY_RUN_TIMEOUT,
                 http_timeout=APIFY_HTTP_TIMEOUT, poll_margin: int = APIFY_POLL_MARGIN):
        self.token = token
        self.actor = (actor or settings.apify_fb_groups_actor).strip()
        self.run_timeout = run_timeout
        self.http_timeout = http_timeout
        self.poll_margin = poll_margin
        self.last_run_id = None
        self.last_run_cost_usd = None
        self.last_run_partial = False
        self.last_dataset_deleted: bool | None = None

    @property
    def endpoint(self) -> str:
        # En la URL el actor va como usuario~nombre
        return f"{APIFY_API}/acts/{self.actor.replace('/', '~')}/runs"

    def build_params(self, limit: int, max_charge_usd: float | None = None) -> dict:
        params = {"timeout": self.run_timeout, "maxItems": int(limit), "waitForFinish": APIFY_WAIT_SECONDS}
        if max_charge_usd is not None and max_charge_usd > 0:
            # Tope de gasto de ESTA corrida (lo apartado del presupuesto), no lo que queda del día
            params["maxTotalChargeUsd"] = f"{max_charge_usd:.4f}"
        return params

    def build_input(self, group_url: str, since: datetime.datetime, limit: int) -> dict:
        f = APIFY_FIELDS["input"]
        return {
            f["start_urls"]: [{f["url"]: group_url}],
            f["results_limit"]: int(limit),
            f["view_option"]: APIFY_FIELDS["view_option"],
            f["only_newer_than"]: since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    # ---- HTTP
    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        try:
            resp = requests.request(method, url, headers={"Authorization": f"Bearer {self.token}"},
                                    timeout=self.http_timeout, **kwargs)
        except requests.RequestException as exc:
            raise ProviderError(f"No se pudo conectar con Apify: {exc.__class__.__name__}") from exc
        if resp.status_code in (401, 403):
            raise ProviderError("Apify rechazó el token (revisa APIFY_TOKEN y los permisos del actor).")
        if resp.status_code == 402:
            raise ProviderError("Apify no tiene saldo o el plan no cubre este actor.")
        if resp.status_code == 404:
            raise ProviderError("Apify no encontró el actor o la corrida (revisa APIFY_FB_GROUPS_ACTOR).")
        if resp.status_code == 408:
            raise ProviderError("Apify tardó demasiado en leer el grupo; se reintenta en la siguiente corrida.")
        if resp.status_code == 429:
            raise ProviderError("Apify limitó las peticiones; se reintenta en la siguiente corrida.")
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = (resp.json().get("error") or {}).get("message") or ""
            except (ValueError, AttributeError):
                pass
            logger.error("Apify %s: %s", resp.status_code, (detail or resp.text or "")[:300])
            raise ProviderError(f"Apify respondió {resp.status_code}" + (f": {detail[:200]}" if detail else "."))
        return resp

    def _json(self, resp: requests.Response):
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError("Apify devolvió una respuesta que no es JSON.") from exc

    def _run_data(self, resp: requests.Response) -> dict:
        payload = self._json(resp)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get(APIFY_FIELDS["run"]["id"]):
            raise ProviderError("Apify devolvió un formato inesperado (falta la corrida).")
        return data

    def _note_cost(self, run: dict) -> None:
        cost = run.get(APIFY_FIELDS["run"]["cost"])
        if isinstance(cost, (int, float)) and cost >= 0:
            self.last_run_cost_usd = round(float(cost), 4)

    def _wait(self, run: dict) -> dict:
        """Espera a que la corrida termine; si pasa el tiempo, la aborta y avisa."""
        f = APIFY_FIELDS["run"]
        deadline = time.monotonic() + self.run_timeout + self.poll_margin
        while run.get(f["status"]) not in APIFY_TERMINAL:
            if time.monotonic() > deadline:
                try:
                    self._request("POST", f"{APIFY_API}/actor-runs/{run[f['id']]}/abort")
                except ProviderError as exc:
                    logger.warning("No se pudo abortar la corrida de Apify %s: %s", run[f["id"]], exc)
                raise ProviderError("Apify tardó demasiado en leer el grupo; se reintenta en la siguiente corrida.")
            run = self._run_data(self._request("GET", f"{APIFY_API}/actor-runs/{run[f['id']]}",
                                               params={"waitForFinish": APIFY_WAIT_SECONDS}))
            self._note_cost(run)
        return run

    def _delete_dataset(self, dataset_id: str | None) -> None:
        """Purga en Apify: borra el dataset de la corrida (best effort; nunca lanza). Si falla, queda pendiente y se
        reintenta en la siguiente corrida y en la tarea diaria (conservación cero en el proveedor)."""
        if not dataset_id:
            return
        try:
            self._request("DELETE", f"{APIFY_API}/datasets/{dataset_id}")
            self.last_dataset_deleted = True
        except ProviderError as exc:
            self.last_dataset_deleted = False
            _remember_pending_delete(f"datasets/{dataset_id}")
            logger.warning("No se pudo borrar el dataset %s en Apify (se reintenta en la siguiente corrida): %s",
                           dataset_id, exc)

    def _delete_key_value_store(self, store_id: str | None) -> None:
        """Borra el almacén clave-valor de la corrida (entrada y registros del actor; best effort)."""
        if not store_id:
            return
        try:
            self._request("DELETE", f"{APIFY_API}/key-value-stores/{store_id}")
        except ProviderError as exc:
            _remember_pending_delete(f"key-value-stores/{store_id}")
            logger.warning("No se pudo borrar el almacén %s en Apify: %s", store_id, exc)

    def retry_pending_deletes(self, limit: int = 20) -> int:
        """Reintenta los borrados que fallaron antes. Devuelve cuántos se completaron."""
        done = 0
        for path in _pending_deletes(limit):
            try:
                self._request("DELETE", f"{APIFY_API}/{path}")
                _forget_pending_delete(path)
                done += 1
            except ProviderError as exc:
                logger.warning("Sigue pendiente el borrado de %s en Apify: %s", path, exc)
        return done

    def fetch_posts(self, group_url: str, since: datetime.datetime, limit: int,
                    max_charge_usd: float | None = None) -> list[dict]:
        f = APIFY_FIELDS["run"]
        self.last_run_id = None
        self.last_run_cost_usd = None
        self.last_run_partial = False
        self.last_dataset_deleted = None
        self.retry_pending_deletes()
        run = self._run_data(self._request("POST", self.endpoint, json=self.build_input(group_url, since, limit),
                                           params=self.build_params(limit, max_charge_usd)))
        self.last_run_id = str(run[f["id"]])
        dataset_id = run.get(f["dataset"])
        store_id = run.get(f["store"])
        self._note_cost(run)
        try:
            run = self._wait(run)
            status = run.get(f["status"])
            dataset_id = run.get(f["dataset"]) or dataset_id
            if status == "FAILED":
                msg = str(run.get(f["message"]) or "")[:200]
                raise ProviderError("La corrida de Apify falló" + (f": {msg}" if msg else "."))
            # TIMED-OUT / ABORTED: Apify ya cobró lo que leyó; se aprovecha y se marca como incompleta
            self.last_run_partial = status != "SUCCEEDED"
            if not dataset_id:
                raise ProviderError("Apify devolvió un formato inesperado (falta el dataset de la corrida).")
            items = self._json(self._request("GET", f"{APIFY_API}/datasets/{dataset_id}/items",
                                             params={"clean": "true", "format": "json", "limit": int(limit)}))
            if not isinstance(items, list):
                raise ProviderError("Apify devolvió un formato inesperado (se esperaba una lista de publicaciones).")
        except ProviderError as exc:
            # La corrida arrancó: al menos se cobró el arranque
            exc.cost_usd = self.last_run_cost_usd if self.last_run_cost_usd is not None else cost_for(0)
            raise
        finally:
            self._delete_dataset(dataset_id)
            self._delete_key_value_store(store_id or run.get(f["store"]))
        posts = []
        for item in items:
            post = parse_apify_item(item)
            if post:
                posts.append(post)
        return posts


def _pending_key() -> str:
    return f"{KEY_PREFIX}:pending-delete"


def _remember_pending_delete(path: str) -> None:
    r = cache._get_redis()
    if r is not None:
        try:
            r.sadd(_pending_key(), path)
            r.expire(_pending_key(), SPEND_KEY_TTL)
            return
        except Exception:  # noqa: BLE001
            pass
    with _mem_lock:
        _mem_pending.add(path)


def _forget_pending_delete(path: str) -> None:
    r = cache._get_redis()
    if r is not None:
        try:
            r.srem(_pending_key(), path)
        except Exception:  # noqa: BLE001
            pass
    with _mem_lock:
        _mem_pending.discard(path)


def _pending_deletes(limit: int = 20) -> list[str]:
    paths: set[str] = set()
    r = cache._get_redis()
    if r is not None:
        try:
            paths |= {p.decode() if isinstance(p, bytes) else str(p) for p in (r.srandmember(_pending_key(), limit) or [])}
        except Exception:  # noqa: BLE001
            pass
    with _mem_lock:
        paths |= set(list(_mem_pending)[:limit])
    return sorted(paths)[:limit]


def get_provider() -> BaseProvider | None:
    """Proveedor configurado o None (importación apagada con FB_GROUPS_ENABLED=false o APIFY_TOKEN vacío)."""
    if not settings.fb_groups_active:
        return None
    return ApifyProvider(settings.apify_token)


# --------------------------------------------------------------------------- presupuesto diario (USD)
_mem_lock = threading.Lock()
_mem_spend: dict[str, float] = {}
_mem_pending: set[str] = set()  # borrados en Apify que fallaron (si Redis no está disponible)
_warned_unconfigured = False
_warned_budget_day: str | None = None
_EPSILON = 1e-9


def per_post_cost() -> float:
    return max(0.0, settings.fb_groups_cost_per_1000_posts_usd) / 1000.0


def per_run_cost() -> float:
    return max(0.0, settings.fb_groups_cost_per_run_usd)


def cost_for(posts: int, runs: int = 1) -> float:
    """Costo estimado en USD de una corrida con `posts` publicaciones (precio por publicación + arranque)."""
    return round(max(0, posts) * per_post_cost() + max(0, runs) * per_run_cost(), 4)


def day_key(kind: str, day: datetime.date | None = None) -> str:
    day = day or datetime.datetime.utcnow().date()
    return f"{KEY_PREFIX}:{kind}:{day.isoformat()}"


def spend_key(day: datetime.date | None = None) -> str:
    return day_key("spend", day)


def add_daily_count(kind: str, n: int) -> None:
    """Suma al contador del día ("posts" leídas o "reports" creados) para el historial del panel."""
    if n <= 0:
        return
    key = day_key(kind)
    r = cache._get_redis()
    if r is not None:
        try:
            pipe = r.pipeline(transaction=False)
            pipe.incrby(key, int(n))
            pipe.expire(key, SPEND_KEY_TTL)
            pipe.execute()
            return
        except Exception:  # noqa: BLE001
            pass
    with _mem_lock:
        _mem_spend[key] = _mem_spend.get(key, 0) + int(n)


def daily_count(kind: str, day: datetime.date | None = None) -> int:
    key = day_key(kind, day)
    r = cache._get_redis()
    if r is not None:
        try:
            return int(float(r.get(key) or 0))
        except Exception:  # noqa: BLE001
            pass
    with _mem_lock:
        return int(_mem_spend.get(key, 0))


def spent_today() -> float:
    return spent_on()


def spent_on(day: datetime.date | None = None) -> float:
    """Gasto (USD) de un día UTC; hoy si no se indica. Incluye lo apartado por corridas en curso."""
    key = spend_key(day)
    r = cache._get_redis()
    if r is not None:
        try:
            return round(float(r.get(key) or 0.0), 4)
        except Exception:  # noqa: BLE001 - Redis caído: se usa la memoria del proceso
            pass
    with _mem_lock:
        return round(_mem_spend.get(key, 0.0), 4)


def add_spend(usd: float) -> float:
    """Suma (o resta, si es negativo) gasto al día de hoy. Devuelve el acumulado."""
    key = spend_key()
    r = cache._get_redis()
    if r is not None:
        try:
            pipe = r.pipeline(transaction=False)
            pipe.incrbyfloat(key, float(usd))
            pipe.expire(key, SPEND_KEY_TTL)
            return round(float(pipe.execute()[0]), 4)
        except Exception:  # noqa: BLE001
            pass
    with _mem_lock:
        _mem_spend[key] = _mem_spend.get(key, 0.0) + float(usd)
        return round(_mem_spend[key], 4)


def try_reserve(usd: float) -> bool:
    """Aparta `usd` del presupuesto de hoy de forma atómica. False (sin apartar nada) si no cabe.

    INCRBYFLOAT primero y, si el nuevo total rebasa el presupuesto, se regresa: dos corridas en paralelo
    (CELERY_CONCURRENCY > 1) nunca apartan juntas más que FB_GROUPS_DAILY_BUDGET_USD.
    """
    usd = max(0.0, float(usd))
    budget = settings.fb_groups_daily_budget_usd
    key = spend_key()
    r = cache._get_redis()
    if r is not None:
        try:
            pipe = r.pipeline(transaction=False)
            pipe.incrbyfloat(key, usd)
            pipe.expire(key, SPEND_KEY_TTL)
            total = float(pipe.execute()[0])
            if total > budget + _EPSILON:
                r.incrbyfloat(key, -usd)
                return False
            return True
        except Exception:  # noqa: BLE001 - Redis caído: se usa la memoria del proceso
            pass
    with _mem_lock:
        total = _mem_spend.get(key, 0.0) + usd
        if total > budget + _EPSILON:
            return False
        _mem_spend[key] = total
        return True


def reset_spend() -> None:
    """Pone en cero el gasto y los contadores de hoy (pruebas y mantenimiento)."""
    keys = (spend_key(), day_key("posts"), day_key("reports"))
    cache.delete(*keys)
    with _mem_lock:
        for key in keys:
            _mem_spend.pop(key, None)


def remaining_budget() -> float:
    return round(settings.fb_groups_daily_budget_usd - spent_today(), 4)


def affordable_posts(limit: int | None = None) -> int:
    """Cuántas publicaciones caben hoy en el presupuesto en una corrida (como máximo `limit`; 0 = agotado)."""
    limit = limit or settings.fb_groups_max_posts_per_run
    available = remaining_budget() - per_run_cost()
    if available < -_EPSILON:
        return 0
    per_post = per_post_cost()
    if per_post <= 0:
        return limit
    return max(0, min(limit, int((available + _EPSILON) / per_post)))


def warn_unconfigured_once() -> None:
    """Avisa en los logs una sola vez por proceso (y por día entre procesos) que falta APIFY_TOKEN."""
    global _warned_unconfigured
    if _warned_unconfigured:
        return
    _warned_unconfigured = True
    if cache.add("fbg:unconfigured-warned", 86400):
        logger.warning("Grupos de Facebook: proveedor no configurado (APIFY_TOKEN vacío); las lecturas se omiten.")


def warn_budget_once() -> None:
    global _warned_budget_day
    today = datetime.datetime.utcnow().date().isoformat()
    if _warned_budget_day == today:
        return
    _warned_budget_day = today
    logger.warning("Grupos de Facebook: presupuesto diario agotado (%.2f de %.2f USD); se detienen las lecturas hasta mañana.",
                   spent_today(), settings.fb_groups_daily_budget_usd)


# --------------------------------------------------------------------------- selección de grupos
def last_touch(group: FacebookGroup) -> datetime.datetime | None:
    """Último intento de lectura (correcto o con error)."""
    times = [t for t in (group.last_fetched_at, group.last_attempt_at) if t]
    return max(times) if times else None


def is_due(group: FacebookGroup, now: datetime.datetime | None = None) -> bool:
    """True si el grupo no se ha intentado leer en FB_GROUPS_FETCH_INTERVAL_HOURS (los errores también cuentan)."""
    last = last_touch(group)
    if last is None:
        return True
    now = now or datetime.datetime.utcnow()
    return last < now - datetime.timedelta(hours=settings.fb_groups_fetch_interval_hours)


def groups_due(db: Session, state: str | None = None, now: datetime.datetime | None = None) -> list[FacebookGroup]:
    """Grupos activos con URL que toca leer: los del estado (más los sin estado) o todos si state es None."""
    now = now or datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(hours=settings.fb_groups_fetch_interval_hours)
    q = db.query(FacebookGroup).filter(
        FacebookGroup.kind == "group", FacebookGroup.is_active == True,  # noqa: E712
        FacebookGroup.group_url.isnot(None),
        or_(FacebookGroup.last_fetched_at.is_(None), FacebookGroup.last_fetched_at < cutoff),
        or_(FacebookGroup.last_attempt_at.is_(None), FacebookGroup.last_attempt_at < cutoff),
    )
    if state:
        q = q.filter(or_(FacebookGroup.state == state, FacebookGroup.state.is_(None)))
    last = func.coalesce(FacebookGroup.last_attempt_at, FacebookGroup.last_fetched_at)
    return q.order_by(last.asc().nullsfirst(), FacebookGroup.id).all()


def trigger_zone_fetch(state: str | None, background_tasks=None) -> str | None:
    """Encarga la lectura de los grupos del estado (tras crear un reporte desde la app o WhatsApp).

    No hace nada sin estado conocido o sin proveedor; nunca lanza (crear el reporte no debe fallar por esto).
    """
    if not state or not settings.fb_groups_active:
        return None
    try:
        return dispatch("app.tasks.facebook_groups.fetch_zone", state, background_tasks=background_tasks)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo encargar la lectura de grupos de Facebook para %s", state)
        return None


# --------------------------------------------------------------------------- ingesta
def ingest_group(db: Session, group: FacebookGroup, provider: BaseProvider, *, now: datetime.datetime | None = None,
                 limit: int | None = None, since: datetime.datetime | None = None,
                 time_budget_seconds: float = GROUP_INGEST_TIME_BUDGET) -> dict:
    """Lee las publicaciones nuevas de un grupo y crea reportes. Devuelve {posts, created, cost, since, error, skipped}.

    - Antes de la corrida se aparta del presupuesto, de forma atómica, su costo máximo (limit × precio + arranque);
      ese mismo monto es el tope de gasto que se le pasa al proveedor. Si no cabe, no se lee (skipped).
    - Al terminar se ajusta con el costo real del proveedor (o la estimación por publicaciones devueltas).
    - since = última lectura correcta (last_fetched_at), con tope FB_GROUPS_LOOKBACK_DAYS. Un error del proveedor
      se guarda en last_error y en last_attempt_at (el grupo no se reintenta antes del intervalo) pero NO mueve
      last_fetched_at: la siguiente lectura vuelve a pedir desde la última correcta y no se pierden publicaciones.
    time_budget_seconds cuenta desde que empieza (incluye la espera al proveedor).
    """
    deadline = time.monotonic() + time_budget_seconds
    now = now or datetime.datetime.utcnow()
    limit = max(1, int(limit or settings.fb_groups_max_posts_per_run))
    lookback = now - datetime.timedelta(days=settings.fb_groups_lookback_days)
    if since is None:
        since = max(group.last_fetched_at, lookback) if group.last_fetched_at else lookback
    result = {"group_id": group.id, "posts": 0, "created": [], "cost": 0.0, "since": since, "error": None,
              "skipped": None}

    reserved = cost_for(limit)
    if not try_reserve(reserved):
        warn_budget_once()
        result["skipped"] = BUDGET_EXHAUSTED
        return result
    try:
        posts = provider.fetch_posts(group.group_url, since, limit, max_charge_usd=reserved)
    except ProviderError as exc:
        charged = max(0.0, float(exc.cost_usd or 0.0))
        add_spend(charged - reserved)
        group.last_attempt_at = now
        group.last_error = str(exc)[:500]
        group.provider = provider.name
        group.provider_ref = (getattr(provider, "last_run_id", None) or group.provider_ref)
        group.cost_estimate_total = Decimal(str(group.cost_estimate_total or 0)) + Decimal(str(charged))
        db.commit()
        logger.warning("Grupo de Facebook %s (%s): %s", group.id, group.name, exc)
        result.update(error=str(exc), cost=charged)
        return result
    # Costo real de la corrida si el proveedor lo informa; si no, lo estimado por lo que devolvió
    real = getattr(provider, "last_run_cost_usd", None)
    cost = round(float(real), 4) if isinstance(real, (int, float)) else cost_for(len(posts))
    add_spend(cost - reserved)
    epoch = datetime.datetime.min
    # De la más antigua a la más reciente: si se acaba el tiempo, la siguiente corrida retoma desde la última procesada
    batch = sorted(posts[:limit], key=lambda p: p.get("created_at") or epoch)

    created: list[int] = []
    newest = group.last_post_at
    partial = bool(getattr(provider, "last_run_partial", False))
    # Corrida incompleta (el proveedor agotó su tiempo): no se avanza la marca, se vuelve a pedir desde `since`
    fetched_until = since if partial else now
    for post in batch:
        created_at = post.get("created_at")
        if time.monotonic() > deadline:
            fetched_until = max(since, created_at or since)
            logger.warning("Ingesta del grupo %s cortada por tiempo; las publicaciones restantes se leen en la siguiente corrida.",
                           group.id)
            break
        if created_at and created_at < since:
            continue  # publicaciones fijadas o viejas que el proveedor devuelve de todos modos
        if created_at and (newest is None or created_at > newest):
            newest = created_at
        raw_url = (post.get("post_url") or "").strip()
        post_url = normalize_post_url(raw_url) or raw_url[:500]
        if not post_url or (normalize_post_url(raw_url) and post_url_problem(post_url)):
            continue  # sin URL de publicación no se puede deduplicar ni enlazar: se descarta
        text = strip_pii(post.get("text"))
        kind = facebook_monitor.classify_post(text)
        if not kind:
            continue
        report = facebook_monitor.create_report_from_post(
            db, text=text, image_urls=list(post.get("image_urls") or [])[:MAX_IMAGES_PER_POST], report_type=kind,
            city=group.city, state=group.state, post_url=post_url, require_dog=True, posted_at=created_at,
        )
        if report:
            created.append(report.id)

    group.last_fetched_at = fetched_until if fetched_until > (group.last_fetched_at or epoch) else group.last_fetched_at
    group.last_attempt_at = now
    group.last_post_at = newest
    group.last_error = PARTIAL_RUN_ERROR if partial else None
    group.provider = provider.name
    group.provider_ref = (getattr(provider, "last_run_id", None) or None)
    group.posts_fetched_total = (group.posts_fetched_total or 0) + len(posts)
    group.reports_created_total = (group.reports_created_total or 0) + len(created)
    group.cost_estimate_total = Decimal(str(group.cost_estimate_total or 0)) + Decimal(str(cost))
    add_daily_count("posts", len(posts))
    add_daily_count("reports", len(created))
    db.commit()
    result.update(posts=len(posts), created=created, cost=cost, error=PARTIAL_RUN_ERROR if partial else None)
    return result


# --------------------------------------------------------------------------- caducidad y purga
def _ttl_days(source: str) -> int:
    return settings.fb_volunteer_post_ttl_days if source == "volunteer" else settings.fb_groups_post_ttl_days


def _content_date():
    """La caducidad cuenta desde la fecha de la publicación original (o la importación, si no se conoce)."""
    return func.coalesce(LostReport.external_posted_at, LostReport.created_at)


def is_imported(report: LostReport) -> bool:
    return report.source in IMPORTED_SOURCES


def is_withdrawn(report: LostReport) -> bool:
    """Importado y caducado o purgado: ya no es público (solo lo ven quien lo envió y los admins)."""
    return is_imported(report) and (report.status == "expired" or report.purged_at is not None)


def expire_imported_reports(db: Session, days: int | None = None, now: datetime.datetime | None = None,
                            report_ids: list[int] | None = None) -> list[int]:
    """Pasa a "expired" los reportes importados (fuente facebook o volunteer) cuya publicación tiene más de
    FB_GROUPS_POST_TTL_DAYS / FB_VOLUNTEER_POST_TTL_DAYS días (contados desde la publicación original)."""
    now = now or datetime.datetime.utcnow()
    expired: list[int] = []
    for source in IMPORTED_SOURCES:
        cutoff = now - datetime.timedelta(days=days or _ttl_days(source))
        q = db.query(LostReport).filter(LostReport.source == source, LostReport.status == "active",
                                        _content_date() < cutoff)
        if report_ids is not None:
            q = q.filter(LostReport.id.in_(report_ids))
        for report in q.order_by(LostReport.id).limit(2000).all():
            report.status = "expired"
            report.updated_at = now
            expired.append(report.id)
    if expired:
        db.commit()
        logger.info("Reportes importados de Facebook expirados: %s", len(expired))
    return expired


def purge_report_content(db: Session, report: LostReport, now: datetime.datetime | None = None) -> int:
    """Borrado real de un reporte importado (contrato L-fb): texto, nombre, fotos y miniaturas (si nadie más usa
    los archivos), análisis de IA, firma de las fotos, teléfono, colonia y coordenadas. Solo queda la constancia de
    existencia y retiro: id, fuente, tipo, estado (entidad), el enlace (para no volver a importarla y atender
    retiros) y las fechas. Devuelve cuántos archivos se borraron."""
    from app.services.account_deletion import delete_upload_files

    now = now or datetime.datetime.utcnow()
    photos = list(report.photos or [])
    report.description = PURGED_DESCRIPTION
    report.dog_name = PURGED_NAME
    report.photos = []
    report.ai_analysis = None
    report.photo_signature = None
    report.contact_phone = None
    report.city = None
    report.latitude = None
    report.longitude = None
    report.purged_at = now
    if report.status == "active":
        report.status = "expired"
    report.updated_at = now
    db.flush()
    # user_id=0: ningún usuario tiene ese id, así que cuenta cualquier otro contenido que use el archivo
    return delete_upload_files(db, 0, photos) if photos else 0


def purge_imported_reports(db: Session, now: datetime.datetime | None = None,
                           report_ids: list[int] | None = None) -> list[int]:
    """Purga los reportes importados (facebook | volunteer) caducados hace FB_IMPORTED_PURGE_AFTER_DAYS días y los
    que su autor pidió retirar hace más de AUTHOR_REMOVAL_PURGE_HOURS, con el correo confirmado (si el admin no
    descartó la solicitud; solicitudes.imported_removal_ready)."""
    now = now or datetime.datetime.utcnow()
    purged: list[int] = []
    conditions = []
    for source in IMPORTED_SOURCES:
        cutoff = now - datetime.timedelta(days=_ttl_days(source) + max(0, settings.fb_imported_purge_after_days))
        conditions.append(and_(LostReport.source == source, _content_date() < cutoff))
    # Mismo plazo que el centro de solicitudes (IMPORTED_REMOVAL_PURGE_HOURS, 48 h) y nunca más de 72 h; la tarea
    # horaria purge_author_removals lo aplica con margen
    removal_hours = min(AUTHOR_REMOVAL_PURGE_HOURS, settings.imported_removal_purge_hours or AUTHOR_REMOVAL_PURGE_HOURS)
    removal_cutoff = now - datetime.timedelta(hours=max(0, removal_hours))
    # Solo los retiros que ya proceden (persona autora con el correo confirmado, o aprobados por el equipo): un
    # «aparezco», un «otro» o un correo sin confirmar no borran por sí solos una alerta ajena
    from app.services.solicitudes import ready_removal_report_ids

    removals = select(ContentReport.target_id).where(
        ContentReport.target_type == "lost_report", ContentReport.reason == AUTHOR_REMOVAL_REASON,
        ContentReport.status != "dismissed", ContentReport.created_at < removal_cutoff,
        ContentReport.id.in_(ready_removal_report_ids()),
    )
    conditions.append(and_(LostReport.source.in_(IMPORTED_SOURCES), LostReport.is_hidden == True,  # noqa: E712
                           LostReport.id.in_(removals)))
    q = db.query(LostReport).filter(LostReport.purged_at.is_(None), or_(*conditions))
    if report_ids is not None:
        q = q.filter(LostReport.id.in_(report_ids))
    files = 0
    for report in q.order_by(LostReport.id).limit(1000).all():
        files += purge_report_content(db, report, now)
        purged.append(report.id)
    if purged:
        db.commit()
        logger.info("Reportes importados purgados (texto y fotos): %s; archivos borrados: %s", len(purged), files)
    return purged


# --------------------------------------------------------------------------- voluntarios
def create_volunteer_report(db: Session, user: User, *, url: str, text: str, city: str | None, state: str | None,
                            report_type: str | None, photos: list[str] | None,
                            consent_version: str | None = None) -> LostReport | None:
    """Reporte con fuente "volunteer" a partir de una publicación que pegó un voluntario. None si la URL ya existe.

    ValueError (mensaje en español) si el enlace no es de una publicación de Facebook (p. ej. la raíz del grupo).
    """
    problem = post_url_problem(url)
    if problem:
        raise ValueError(problem)
    post_url = normalize_post_url(url)
    clean = strip_pii(text)
    kind = report_type if report_type in ("lost", "found") else (facebook_monitor.classify_post(clean) or "found")
    return facebook_monitor.create_report_from_post(
        db, text=clean, image_urls=[], local_photos=list(photos or []), report_type=kind, city=city,
        state=estados_mx.derive_state(state, city), post_url=post_url, require_dog=False,
        source="volunteer", reporter_id=user.id, consent_version=consent_version or settings.legal_terms_version,
    )


# --------------------------------------------------------------------------- retiro sin cuenta
def find_imported_report(db: Session, report_id: int | None = None, url: str | None = None) -> LostReport | None:
    """Reporte importado por id o por el enlace a la publicación original."""
    if report_id:
        return db.query(LostReport).filter(LostReport.id == report_id).first()
    if url:
        return facebook_monitor.find_by_post_url(db, url)
    return None
