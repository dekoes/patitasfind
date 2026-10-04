"""Heurística de compatibilidad adoptante-perro (0-100).

Se parte de 70 puntos y se ajusta según las respuestas del cuestionario comparadas con
el tamaño y la edad del perro. Las llaves aceptadas son flexibles (español o inglés)
porque el formulario del frontend puede evolucionar:

- Vivienda (housing/vivienda/hogar): perro Grande + departamento pequeño -25, departamento
  grande -10; casa con jardín +10 (Grande) o +5. Perro Pequeño en departamento +5.
- Espacio exterior (outdoor/patio/jardin): jardín o parque cercano +5; "ninguno" -10 si es Grande.
- Experiencia (experience/experiencia): mucha +10, alguna +5, ninguna -5 (-10 si es cachorro <1 año o Grande).
- Tiempo solo (hours_alone/horas_solo): >8 h -15, 5-8 h -5; cachorros penalizan el doble.
- Niños (children/ninos): niños pequeños + perro Grande -5.
- Otras mascotas (other_pets/mascotas): +3 si ya convive con perros.
- Presupuesto (budget/presupuesto): bajo -10, alto +5.
- Compromiso explícito (commitment/compromiso = sí/true) +5.
El resultado se acota a [0, 100].
"""
import re
import unicodedata


def _norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "si" if value else "no"
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return text.replace("-", "_").strip()


def _pick(answers: dict, *keys) -> str:
    lowered = {_norm(k): v for k, v in answers.items()}
    for key in keys:
        if key in lowered:
            return _norm(lowered[key])
    return ""


def _dog_size(dog) -> str:
    size = _norm(getattr(dog, "size", "")) if dog else ""
    if size.startswith("gran") or size in ("large", "big", "l"):
        return "grande"
    if size.startswith("peq") or size in ("small", "s"):
        return "pequeno"
    if size.startswith("med") or size in ("medium", "m"):
        return "mediano"
    return ""


def compute_compatibility(answers: dict, dog) -> int | None:
    if not answers:
        return None
    score = 70
    size = _dog_size(dog)
    age_years = getattr(dog, "age_years", None) if dog else None
    is_puppy = age_years is not None and age_years < 1

    housing = _pick(answers, "housing", "vivienda", "hogar", "home", "tipo_vivienda")
    if housing:
        is_apartment = any(w in housing for w in ("depa", "apart", "condo", "flat"))
        small_space = any(w in housing for w in ("chico", "pequen", "small", "estudio", "cuarto"))
        has_yard = any(w in housing for w in ("jardin", "patio", "yard", "garden", "casa"))
        if size == "grande":
            if is_apartment:
                score += -25 if (small_space or "grande" not in housing) else -10
            elif has_yard:
                score += 10
        elif size == "pequeno" and is_apartment:
            score += 5
        elif has_yard:
            score += 5

    outdoor = _pick(answers, "outdoor", "patio", "jardin", "exterior", "espacio_exterior")
    if outdoor:
        if any(w in outdoor for w in ("jardin", "patio", "parque", "park", "yard")):
            score += 5
        elif outdoor in ("no", "ninguno", "none") and size == "grande":
            score -= 10

    experience = _pick(answers, "experience", "experiencia", "experiencia_previa")
    if experience:
        if any(w in experience for w in ("mucha", "much", "alta", "si", "yes", "lot")):
            score += 10
        elif any(w in experience for w in ("alguna", "some", "poca", "media")):
            score += 5
        elif any(w in experience for w in ("ninguna", "none", "no")):
            score -= 10 if (is_puppy or size == "grande") else 5

    hours = _pick(answers, "hours_alone", "horas_solo", "tiempo_solo", "horas")
    if hours:
        nums = [int(n) for n in re.findall(r"\d+", hours)]
        hmax = max(nums) if nums else None
        penalty = 0
        if hmax is not None:
            if hmax > 8:
                penalty = 15
            elif hmax >= 5:
                penalty = 5
        score -= penalty * (2 if is_puppy else 1)

    children = _pick(answers, "children", "ninos", "hijos", "kids")
    if children and size == "grande" and any(w in children for w in ("pequen", "chico", "bebe", "small")):
        score -= 5

    pets = _pick(answers, "other_pets", "mascotas", "otras_mascotas", "pets")
    if pets and any(w in pets for w in ("perro", "dog")):
        score += 3

    budget = _pick(answers, "budget", "presupuesto")
    if budget:
        nums = [int(n) for n in re.findall(r"\d+", budget)]
        if "+" in budget or any(w in budget for w in ("alto", "high")) or (nums and max(nums) >= 1000):
            score += 5
        elif any(w in budget for w in ("bajo", "low", "poco")) or (nums and max(nums) < 100):
            score -= 10

    commitment = _pick(answers, "commitment", "compromiso", "acepta_seguimiento")
    if commitment in ("si", "true", "yes", "1"):
        score += 5

    return max(0, min(100, int(round(score))))
