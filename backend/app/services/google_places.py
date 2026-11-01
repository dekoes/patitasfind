"""Google Places API (New) para el directorio de veterinarias: búsqueda de la ficha de una clínica y
lectura EN TIEMPO REAL de su calificación y reseñas de Google.

Reglas que se cumplen aquí (verificadas el 2026-10-17):
- Peticiones: Place Details (New) GET https://places.googleapis.com/v1/places/{PLACE_ID} y Text Search (New)
  POST https://places.googleapis.com/v1/places:searchText, con las cabeceras X-Goog-Api-Key y X-Goog-FieldMask
  (la máscara es obligatoria y determina el SKU que se cobra):
  https://developers.google.com/maps/documentation/places/web-service/place-details
  https://developers.google.com/maps/documentation/places/web-service/text-search
- Campos del recurso Place y de cada Review (rating, userRatingCount, googleMapsUri, reviews[].authorAttribution
  {displayName, uri, photoUri}, relativePublishTimeDescription, text/originalText, flagContentUri, googleMapsUri):
  https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places
  "List of reviews about this place, sorted by relevance. A maximum of 5 reviews can be returned."
- Políticas (https://developers.google.com/maps/documentation/places/web-service/policies):
  "You must not pre-fetch, cache, or store Places API content beyond the allowed exceptions"; la única excepción
  es el place ID ("You can therefore store place ID values indefinitely"). Por eso aquí NO se guardan reseñas,
  calificaciones ni autores (ni en la base, ni en Redis, ni en logs): cada vista del perfil consulta a Google.
  "You must always credit the author when displaying photos or reviews"; "end-users must always have access to
  view the individual source photo or review on Google Maps using the provided googleMapsUri"; "Include a clear
  notice that describes how reviews are being ordered and filtered" (por defecto, relevancia); atribución
  "Google Maps" (logotipo o texto) cuando el contenido no va sobre un mapa de Google.
- Place IDs: "Place IDs may change over time"; se refrescan sin costo con Place Details pidiendo solo "id"
  (SKU IDs Only): https://developers.google.com/maps/documentation/places/web-service/place-id
- URL a Google Maps construida con el place_id (sin guardar contenido de Google):
  https://developers.google.com/maps/documentation/urls/get-started ("query=PLACE_NAME&query_place_id=PLACE_ID").

Todo se consulta desde el servidor (nunca desde el navegador): Google no recibe la IP ni identificadores de los
usuarios de GuauWoow (dominio datos-personales). Las llamadas tienen tiempo límite y un tope diario
(GOOGLE_PLACES_DAILY_LIMIT) porque el detalle con reseñas se cobra en el SKU Enterprise + Atmosphere.
"""
import datetime
import logging
from urllib.parse import quote_plus

import requests

from app.config import settings
from app.services import ratelimit

logger = logging.getLogger(__name__)

PLACES_BASE = "https://places.googleapis.com/v1"
TIMEOUT_SECONDS = 6.0
LANGUAGE = "es"
REGION = "MX"
MAX_REVIEWS = 5  # lo que devuelve Google como máximo; se muestran tal cual
SEARCH_RADIUS_M = 20_000.0
SEARCH_RESULTS = 5

# Máscaras de campos: solo lo que se usa (el SKU cobrado es el del campo más caro de la máscara)
FIELDS_DETAIL = "id,googleMapsUri,rating,userRatingCount,reviews"  # Enterprise + Atmosphere (reviews)
FIELDS_ID_ONLY = "id"  # IDs Only: refresco de place_id sin costo
FIELDS_SEARCH = "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount"

ORDER_NOTICE = (
    "Reseñas de Google Maps ordenadas por relevancia según Google (máximo 5). Google no verifica las reseñas. "
    "GuauWoow no las guarda, modera ni responde: para reportar una usa el enlace de Google."
)
TRANSLATED_NOTICE = "Algunas reseñas fueron traducidas automáticamente por Google; se muestra también el texto original."
NOT_CONFIGURED = "La búsqueda en Google Maps no está configurada (falta GOOGLE_MAPS_API_KEY)."
_BUDGET_KEY = "gplaces:daily"
_budget_warned_day: str | None = None


class PlacesError(RuntimeError):
    """Google no respondió o respondió con error (no se exponen detalles al público)."""


class PlacesNotConfigured(PlacesError):
    pass


class PlaceNotFound(PlacesError):
    pass


def enabled() -> bool:
    return settings.google_places_enabled


def _http(method: str, url: str, headers: dict, json: dict | None = None, params: dict | None = None):
    """Única salida HTTP del módulo (las pruebas la sustituyen). Devuelve (status_code, cuerpo JSON o {})."""
    resp = requests.request(method, url, headers=headers, json=json, params=params, timeout=TIMEOUT_SECONDS)
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {}
    return resp.status_code, body


def _call(method: str, path: str, field_mask: str, json: dict | None = None, params: dict | None = None) -> dict:
    if not enabled():
        raise PlacesNotConfigured(NOT_CONFIGURED)
    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": field_mask,
        "Content-Type": "application/json",
    }
    try:
        status, body = _http(method, f"{PLACES_BASE}{path}", headers, json=json, params=params)
    except requests.RequestException as exc:
        logger.warning("Google Places sin respuesta (%s %s): %s", method, path, exc.__class__.__name__)
        raise PlacesError("Google Maps no respondió.") from exc
    if status == 404:
        raise PlaceNotFound("Google ya no tiene ese lugar.")
    if status >= 400:
        # Solo el código y el estado del error (nunca contenido de Google) van al log
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        logger.warning("Google Places respondió %s (%s) en %s %s", status, err.get("status"), method, path)
        raise PlacesError(f"Google Maps respondió con error {status}.")
    return body if isinstance(body, dict) else {}


def maps_url(place_id: str, name: str | None) -> str:
    """Enlace a Google Maps construido con el place_id (Maps URLs: api=1&query=...&query_place_id=...)."""
    query = quote_plus((name or "").strip() or place_id)
    return f"https://www.google.com/maps/search/?api=1&query={query}&query_place_id={quote_plus(place_id)}"


def budget_available() -> bool:
    """Cuenta una consulta de detalle contra el tope diario; False (sin contar) cuando ya se agotó."""
    limit = max(0, int(settings.google_places_daily_limit or 0))
    if limit == 0:
        return False
    ok = ratelimit.hit(_BUDGET_KEY, limit=limit, window_seconds=86_400)
    if not ok:
        global _budget_warned_day
        today = datetime.date.today().isoformat()
        if _budget_warned_day != today:
            _budget_warned_day = today
            logger.warning("Tope diario de consultas a Google Places alcanzado (%s); los perfiles se muestran sin "
                           "reseñas de Google hasta mañana.", limit)
    return ok


def search_text(query: str, lat: float | None, lon: float | None) -> list[dict]:
    """Candidatos cerca de la clínica: [{place_id, name, address, rating, ratings_total}]."""
    body = {"textQuery": query, "languageCode": LANGUAGE, "regionCode": REGION, "pageSize": SEARCH_RESULTS,
            "includedType": "veterinary_care"}
    if lat is not None and lon is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": SEARCH_RADIUS_M}}
    data = _call("POST", "/places:searchText", FIELDS_SEARCH, json=body)
    out = []
    for place in data.get("places") or []:
        if not place.get("id"):
            continue
        out.append({
            "place_id": place["id"],
            "name": (place.get("displayName") or {}).get("text"),
            "address": place.get("formattedAddress"),
            "rating": place.get("rating"),
            "ratings_total": place.get("userRatingCount"),
        })
    return out[:SEARCH_RESULTS]


def refresh_place_id(place_id: str) -> str | None:
    """Devuelve el place_id vigente (puede cambiar) o None si Google responde NOT_FOUND. Sin costo (IDs Only)."""
    try:
        data = _call("GET", f"/places/{place_id}", FIELDS_ID_ONLY, params={"languageCode": LANGUAGE})
    except PlaceNotFound:
        return None
    return data.get("id") or place_id


def _review(raw: dict) -> dict:
    author = raw.get("authorAttribution") or {}
    text = raw.get("text") or {}
    original = raw.get("originalText") or {}
    return {
        "author_name": author.get("displayName"),
        "author_url": author.get("uri"),
        "profile_photo_url": author.get("photoUri"),
        "rating": raw.get("rating"),
        "text": text.get("text"),
        "original_text": original.get("text") if original.get("text") != text.get("text") else None,
        "language": text.get("languageCode"),
        "relative_time": raw.get("relativePublishTimeDescription"),
        "publish_time": raw.get("publishTime"),
        "google_maps_url": raw.get("googleMapsUri"),
        "flag_content_url": raw.get("flagContentUri"),
    }


def unavailable_block(place_id: str, fallback_maps_url: str | None = None) -> dict:
    """Bloque sin contenido de Google (available=False): solo el enlace a Google Maps construido con el place_id."""
    return {
        "place_id": place_id, "available": False, "rating": None, "ratings_total": None, "reviews": [],
        "google_maps_url": fallback_maps_url or maps_url(place_id, None), "attribution": "Google Maps",
        "order_notice": ORDER_NOTICE, "translated_notice": None, "fetched_at": None,
    }


def fetch_place_block(place_id: str, fallback_maps_url: str | None = None) -> dict:
    """Bloque "Reseñas de Google" para el perfil, pedido en tiempo real. NUNCA se persiste ni se cachea.

    Si no hay llave, no hay presupuesto diario o Google falla, devuelve el bloque con available=False (y el enlace
    a Maps construido con el place_id) para que la app pueda seguir enlazando a Google Maps.
    """
    block = unavailable_block(place_id, fallback_maps_url)
    if not enabled() or not budget_available():
        return block
    try:
        data = _call("GET", f"/places/{place_id}", FIELDS_DETAIL, params={"languageCode": LANGUAGE, "regionCode": REGION})
    except PlacesError:
        return block
    reviews = [_review(r) for r in (data.get("reviews") or [])[:MAX_REVIEWS]]  # tal como llegan, mismo orden
    block.update({
        "available": True,
        "rating": data.get("rating"),
        "ratings_total": data.get("userRatingCount"),
        "reviews": reviews,
        "google_maps_url": data.get("googleMapsUri") or block["google_maps_url"],
        # "Make end users aware when a review has been translated from its original language" (políticas)
        "translated_notice": TRANSLATED_NOTICE if any(r["original_text"] for r in reviews) else None,
        "fetched_at": datetime.datetime.utcnow(),
    })
    return block
