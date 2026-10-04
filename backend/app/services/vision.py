"""Análisis de fotos de perros.

Dos capas independientes:
1. Firma visual local (siempre disponible): dHash de 64 bits (imagen completa y recorte
   central) + histograma de color RGB 4x4x4. Solo requiere Pillow.
2. Análisis con Claude (opcional, requiere ANTHROPIC_API_KEY): raza, tamaño, colores,
   pelaje, señas particulares, edad aproximada y descripción en español. Se usa salida
   estructurada (output_config.format con JSON Schema) para obtener JSON válido.

La similitud combina ambas: si hay atributos de IA en los dos lados pesa 55% atributos y
45% visual; si no, solo la parte visual (modo "hash-only").
"""
import base64
import hashlib
import io
import json
import logging
import re
import unicodedata

from PIL import Image, ImageOps

from app import cache
from app.config import settings

logger = logging.getLogger(__name__)

SIZES = ["Pequeño", "Mediano", "Grande"]

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "is_dog": {"type": "boolean"},
        "breed_guess": {"type": "string"},
        "size": {"type": "string", "enum": SIZES},
        "colors": {"type": "array", "items": {"type": "string"}},
        "coat": {"type": "string"},
        "distinctive_marks": {"type": "array", "items": {"type": "string"}},
        "approx_age": {"type": "string"},
        "description_es": {"type": "string"},
    },
    "required": ["is_dog", "breed_guess", "size", "colors", "coat", "distinctive_marks", "approx_age", "description_es"],
    "additionalProperties": False,
}

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

FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")

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


# --------------------------------------------------------------------------- Claude
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
    return "vision:v1:" + hashlib.sha256(key.encode()).hexdigest()


def analyze_image_bytes(data: bytes, cache_key: str | None = None) -> dict | None:
    """Analiza una foto con Claude. Lanza AINotConfigured si falta la llave; None si falla."""
    if not is_configured():
        raise AINotConfigured("IA no configurada")

    key = _cache_key(cache_key or hashlib.sha256(data).hexdigest())
    if key in _memory_cache:
        return _memory_cache[key]
    cached = cache.get(key)
    if isinstance(cached, dict):
        _memory_cache[key] = cached
        return cached

    import anthropic

    try:
        media_type, b64 = _prepare_image(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Imagen inválida para análisis IA: %s", exc)
        return None

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=90.0, max_retries=2)
    request = dict(
        model=settings.anthropic_model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        output_config={"effort": settings.anthropic_effort, "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": "Analiza al perro de esta foto y devuelve el JSON solicitado."},
            ],
        }],
    )

    try:
        response = None
        if settings.anthropic_use_fallbacks and settings.anthropic_model in FALLBACK_MODELS:
            try:
                # Si un clasificador de seguridad rechaza la petición, la API la reintenta en otro modelo
                response = client.beta.messages.create(
                    **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            except anthropic.BadRequestError as exc:
                logger.info("Fallbacks no disponibles (%s); se reintenta sin ellos.", exc.message)
        if response is None:
            response = client.messages.create(**request)
    except anthropic.APIStatusError as exc:
        logger.error("Error de la API de Anthropic (%s): %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError as exc:
        logger.error("Sin conexión con la API de Anthropic: %s", exc)
        return None

    if response.stop_reason == "refusal":
        logger.warning("Claude rechazó analizar la imagen: %s", getattr(response, "stop_details", None))
        return None
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
    if not text:
        return None
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Respuesta IA no es JSON válido: %s", text[:200])
        return None
    if result.get("size") not in SIZES:
        result["size"] = "Mediano"
    result["model"] = getattr(response, "model", settings.anthropic_model)

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
