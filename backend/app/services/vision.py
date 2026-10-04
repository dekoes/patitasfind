"""Análisis de fotos de perros.

Dos capas independientes:
1. Firma visual local (siempre disponible): dHash de 64 bits (imagen completa y recorte
   central) + histograma de color RGB 4x4x4. Solo requiere Pillow.
2. Análisis con un modelo de visión (opcional, requiere AI_API_KEY): raza, tamaño, colores,
   pelaje, señas particulares, edad aproximada y descripción en español. Se usa cualquier API
   compatible con OpenAI Chat Completions (por defecto Qwen3-VL de Alibaba Model Studio; también
   Z.ai GLM-4.6V). No dependemos de `response_format`: se pide "responde SOLO con JSON" y la
   respuesta se extrae y valida de forma tolerante.

La similitud combina ambas: si hay atributos de IA en los dos lados pesa 55% atributos y
45% visual; si no, solo la parte visual (modo "hash-only").
"""
import base64
import hashlib
import io
import json
import logging
import re
import time
import unicodedata

import requests
from PIL import Image, ImageOps

from app import cache
from app.config import settings

logger = logging.getLogger(__name__)

SIZES = ["Pequeño", "Mediano", "Grande"]

SYSTEM_PROMPT = (
    "Eres un asistente de PatitasFind, una plataforma mexicana para reunir perros perdidos con sus familias "
    "y promover la adopción. Analizas una foto y describes al perro con precisión para poder compararlo con "
    "otros reportes. Responde siempre en español de México. Si la foto no muestra un perro, marca is_dog=false "
    "y llena los demás campos con cadenas vacías o listas vacías (size='Mediano'). Para breed_guess usa nombres "
    "comunes en México (p. ej. 'Mestizo', 'Chihuahua', 'Labrador', 'Pastor Alemán', 'Schnauzer'); si parece cruza, "
    "escribe 'Mestizo' seguido de la raza dominante entre paréntesis. colors: colores del pelaje en español "
    "(p. ej. 'café', 'negro', 'blanco', 'dorado', 'gris', 'atigrado'). distinctive_marks: señas útiles para "
    "identificarlo (manchas, orejas caídas o paradas, collar, cicatrices, cola cortada). approx_age: 'cachorro', "
    "'joven', 'adulto' o 'senior'. description_es: 1 o 2 oraciones claras y cálidas que sirvan para un anuncio."
)

_memory_cache: dict[str, dict] = {}


class AINotConfigured(RuntimeError):
    pass


# --------------------------------------------------------------------------- firma visual
def _dhash(img: Image.Image) -> str:
    small = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            left = px[row * 9 + col]
            right = px[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def _histogram(img: Image.Image) -> list[float]:
    small = img.convert("RGB").resize((64, 64))
    bins = [0] * 64
    for r, g, b in small.getdata():
        bins[(r // 64) * 16 + (g // 64) * 4 + (b // 64)] += 1
    total = float(sum(bins)) or 1.0
    return [round(v / total, 4) for v in bins]


def image_signature(data: bytes) -> dict | None:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo calcular la firma de la imagen: %s", exc)
        return None
    w, h = img.size
    crop = img.crop((int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))) if w > 20 and h > 20 else img
    return {"dhash": [_dhash(img), _dhash(crop)], "hist": _histogram(img)}


def _hamming_sim(a: str, b: str) -> float:
    try:
        return 1.0 - bin(int(a, 16) ^ int(b, 16)).count("1") / 64.0
    except ValueError:
        return 0.0


def _hist_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(min(x, y) for x, y in zip(a, b))


def visual_similarity(sig_a: dict | None, sig_b: dict | None) -> float | None:
    """0..1 o None si alguna firma falta. Compara todas las fotos y toma el mejor par."""
    photos_a = (sig_a or {}).get("photos") or []
    photos_b = (sig_b or {}).get("photos") or []
    if not photos_a or not photos_b:
        return None
    best = 0.0
    for pa in photos_a:
        for pb in photos_b:
            hash_sim = max(_hamming_sim(x, y) for x in pa.get("dhash", []) for y in pb.get("dhash", [])) if pa.get("dhash") and pb.get("dhash") else 0.0
            # Imágenes sin relación rondan 0.5 de similitud de hash: se reescala
            hash_score = max(0.0, (hash_sim - 0.55) / 0.45)
            hist_score = max(0.0, (_hist_sim(pa.get("hist"), pb.get("hist")) - 0.3) / 0.7)
            best = max(best, 0.6 * hash_score + 0.4 * hist_score)
    return min(1.0, best)


# --------------------------------------------------------------------------- atributos
_COLOR_MAP = {
    "cafe": "cafe", "marron": "cafe", "chocolate": "cafe", "brown": "cafe", "canela": "cafe", "rojizo": "cafe",
    "negro": "negro", "black": "negro",
    "blanco": "blanco", "white": "blanco",
    "gris": "gris", "gray": "gris", "grey": "gris", "plateado": "gris", "azul": "gris",
    "dorado": "claro", "golden": "claro", "amarillo": "claro", "crema": "claro", "beige": "claro", "arena": "claro",
    "miel": "claro", "rubio": "claro", "leonado": "claro", "fawn": "claro",
    "atigrado": "atigrado", "manchado": "manchado", "tricolor": "tricolor", "pinto": "manchado",
}
_STOP = {"de", "la", "el", "en", "y", "con", "los", "las", "un", "una", "del", "al", "muy", "color"}


def _norm(text) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower().strip()


def _tokens(text) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", _norm(text)) if len(t) > 2 and t not in _STOP}


def _colors(values) -> set[str]:
    out = set()
    for v in values or []:
        for t in re.findall(r"[a-z]+", _norm(v)):
            if t in _COLOR_MAP:
                out.add(_COLOR_MAP[t])
    return out


def _size_key(value) -> str:
    v = _norm(value)
    if v.startswith("gran") or v in ("large", "big"):
        return "grande"
    if v.startswith("peq") or v == "small":
        return "pequeno"
    if v.startswith("med") or v == "medium":
        return "mediano"
    return ""


def attribute_similarity(a: dict | None, b: dict | None) -> float | None:
    if not a or not b:
        return None
    parts, weights = [], []

    breed_a, breed_b = _tokens(a.get("breed_guess")), _tokens(b.get("breed_guess"))
    if breed_a and breed_b:
        mixed = {"mestizo", "criollo", "cruza", "mixed"}
        if breed_a & breed_b - mixed:
            s = 1.0
        elif (breed_a & mixed) or (breed_b & mixed):
            s = 0.5
        else:
            s = 0.0
        parts.append(s); weights.append(0.35)

    sa, sb = _size_key(a.get("size")), _size_key(b.get("size"))
    if sa and sb:
        order = ["pequeno", "mediano", "grande"]
        diff = abs(order.index(sa) - order.index(sb))
        parts.append({0: 1.0, 1: 0.4}.get(diff, 0.0)); weights.append(0.25)

    ca, cb = _colors(a.get("colors")), _colors(b.get("colors"))
    if ca and cb:
        parts.append(len(ca & cb) / len(ca | cb)); weights.append(0.30)

    ma = set().union(*[_tokens(m) for m in a.get("distinctive_marks") or []]) if a.get("distinctive_marks") else set()
    mb = set().union(*[_tokens(m) for m in b.get("distinctive_marks") or []]) if b.get("distinctive_marks") else set()
    if ma and mb:
        parts.append(min(1.0, 2 * len(ma & mb) / len(ma | mb))); weights.append(0.10)

    if not weights:
        return None
    return sum(p * w for p, w in zip(parts, weights)) / sum(weights)


def combined_score(sig_a, attrs_a, sig_b, attrs_b) -> int:
    visual = visual_similarity(sig_a, sig_b)
    attrs = attribute_similarity(attrs_a, attrs_b)
    if visual is not None and attrs is not None:
        score = 0.55 * attrs + 0.45 * visual
    elif visual is not None:
        score = visual
    elif attrs is not None:
        score = attrs * 0.8  # sin evidencia visual, se castiga un poco
    else:
        score = 0.0
    return int(round(max(0.0, min(1.0, score)) * 100))


# --------------------------------------------------------------------------- IA de visión
def is_configured() -> bool:
    return settings.ai_enabled


def _prepare_image(data: bytes) -> tuple[str, str]:
    """Reduce a máx. 1024 px y recodifica como JPEG (menos tokens, formato soportado)."""
    img = Image.open(io.BytesIO(data))
    img.load()
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def _cache_key(key: str) -> str:
    return f"vision:v2:{settings.ai_model}:" + hashlib.sha256(key.encode()).hexdigest()


def _extra_body() -> dict:
    if not settings.ai_extra_body:
        return {}
    try:
        extra = json.loads(settings.ai_extra_body)
        return extra if isinstance(extra, dict) else {}
    except json.JSONDecodeError:
        logger.warning("AI_EXTRA_BODY no es JSON válido; se ignora.")
        return {}


def _message_text(content) -> str:
    """El contenido puede venir como texto o como lista de partes [{type: text, text: ...}]."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def extract_json(text: str) -> dict | None:
    """Obtiene el primer objeto JSON de una respuesta de texto (tolera ```json, <think> y texto extra)."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"```(?:json|JSON)?", "", text).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _as_str(value, limit: int = 300) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v)
    return str(value).strip()[:limit]


def _as_list(value, limit: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [v for v in re.split(r"[,;/]| y ", value)]
    if not isinstance(value, (list, tuple)):
        value = [value]
    out = []
    for v in value:
        s = _as_str(v, 80)
        if s and s.lower() not in (o.lower() for o in out):
            out.append(s)
    return out[:limit]


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _norm(value) in ("true", "si", "yes", "1", "verdadero")


def _normalize_size(value) -> str:
    return {"pequeno": "Pequeño", "mediano": "Mediano", "grande": "Grande"}.get(_size_key(value), "Mediano")


_AGES = {"cachorro": "cachorro", "puppy": "cachorro", "joven": "joven", "young": "joven",
         "adulto": "adulto", "adult": "adulto", "senior": "senior", "viejo": "senior", "mayor": "senior"}


def normalize_analysis(raw: dict) -> dict:
    """Valida y normaliza los campos que devuelve el modelo."""
    age_raw = _norm(raw.get("approx_age"))
    age = next((v for k, v in _AGES.items() if k in age_raw), _as_str(raw.get("approx_age"), 40))
    result = {
        "is_dog": _as_bool(raw.get("is_dog", True)),
        "breed_guess": _as_str(raw.get("breed_guess") or raw.get("breed"), 80),
        "size": _normalize_size(raw.get("size")),
        "colors": [c.lower() for c in _as_list(raw.get("colors") or raw.get("color"))],
        "coat": _as_str(raw.get("coat"), 80),
        "distinctive_marks": _as_list(raw.get("distinctive_marks")),
        "approx_age": age,
        "description_es": _as_str(raw.get("description_es") or raw.get("description"), 600),
    }
    if not result["is_dog"]:
        result.update({"breed_guess": "", "colors": [], "coat": "", "distinctive_marks": [], "approx_age": ""})
    return result


USER_PROMPT = (
    "Analiza al perro de esta foto. Responde SOLO con un objeto JSON válido (sin texto adicional, sin ```), "
    "exactamente con este esquema:\n"
    '{"is_dog": true, "breed_guess": "string", "size": "Pequeño|Mediano|Grande", "colors": ["string"], '
    '"coat": "string", "distinctive_marks": ["string"], "approx_age": "cachorro|joven|adulto|senior", '
    '"description_es": "string"}'
)


class _Retryable(Exception):
    pass


def _post_chat(payload: dict, deadline: float) -> dict | None:
    """POST a /chat/completions con 1 reintento en 429/5xx/errores de red (si queda tiempo)."""
    url = f"{settings.ai_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            break
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=min(settings.ai_timeout_seconds, remaining))
            if resp.status_code == 429 or resp.status_code >= 500:
                raise _Retryable(f"HTTP {resp.status_code}: {resp.text[:300]}")
            if resp.status_code >= 400:
                logger.error("La API de visión rechazó la petición (HTTP %s): %s", resp.status_code, resp.text[:300])
                return None
            return resp.json()
        except (requests.RequestException, _Retryable, ValueError) as exc:
            logger.warning("Error con la API de visión (intento %s): %s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(1.0)
    return None


def analyze_image_bytes(data: bytes, cache_key: str | None = None) -> dict | None:
    """Analiza una foto con el modelo de visión. Lanza AINotConfigured si falta la llave; None si falla."""
    if not is_configured():
        raise AINotConfigured("IA no configurada")

    key = _cache_key(cache_key or hashlib.sha256(data).hexdigest())
    if key in _memory_cache:
        return _memory_cache[key]
    cached = cache.get(key)
    if isinstance(cached, dict):
        _memory_cache[key] = cached
        return cached

    try:
        media_type, b64 = _prepare_image(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Imagen inválida para análisis IA: %s", exc)
        return None

    payload = {
        "model": settings.ai_model,
        "temperature": 0.2,
        "max_tokens": 800,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                {"type": "text", "text": USER_PROMPT},
            ]},
        ],
        **_extra_body(),
    }
    # Plazo total: un intento completo + el reintento solo si queda tiempo
    body = _post_chat(payload, deadline=time.monotonic() + settings.ai_timeout_seconds * 1.5)
    if not body:
        return None
    try:
        text = _message_text(body["choices"][0]["message"].get("content"))
    except (KeyError, IndexError, TypeError, AttributeError):
        logger.warning("Respuesta de visión inesperada: %s", str(body)[:300])
        return None
    raw = extract_json(text)
    if raw is None:
        logger.warning("La respuesta de visión no contiene JSON: %s", (text or "")[:200])
        return None
    result = normalize_analysis(raw)
    result["model"] = body.get("model") or settings.ai_model

    _memory_cache[key] = result
    cache.set(key, result, ttl=60 * 60 * 24 * 30)
    return result


def analyze_url(url: str) -> dict | None:
    from app.services.images import load_image_bytes

    data = load_image_bytes(url)
    if not data:
        return None
    result = analyze_image_bytes(data, cache_key=url)
    if result is not None:
        result = {**result, "url": url}
    return result


def signature_for_urls(urls: list[str], max_photos: int = 3) -> dict | None:
    from app.services.images import load_image_bytes

    photos = []
    for url in (urls or [])[:max_photos]:
        data = load_image_bytes(url)
        if not data:
            continue
        sig = image_signature(data)
        if sig:
            photos.append({"url": url, **sig})
    if not photos:
        return None
    return {"v": 1, "photos": photos}
