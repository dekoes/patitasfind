"""Privacidad de ubicación: en respuestas públicas las coordenadas van aproximadas (~1 km).

Solo el dueño / quien reporta y los admins ven las coordenadas exactas (ver los esquemas *PrivateOut).
La distancia pública se calcula desde las coordenadas aproximadas para que no sirva para triangular
la ubicación exacta haciendo consultas desde varios puntos.
"""
from app.services.geo import COARSE_DECIMALS, coarse, haversine_km  # noqa: F401 - coarse se reexporta

COORD_DECIMALS = COARSE_DECIMALS  # ~1.1 km de latitud; el mismo redondeo se aplica en SQL al filtrar por radio
DISTANCE_DECIMALS = 1


def round_distance(value: float | None) -> float | None:
    return None if value is None else round(float(value), DISTANCE_DECIMALS)


def public_distance(obj, lat: float | None, lon: float | None) -> float | None:
    if lat is None or lon is None or obj.latitude is None or obj.longitude is None:
        return None
    return round_distance(haversine_km(lat, lon, coarse(obj.latitude), coarse(obj.longitude)))


def coarsen_distances(items: list, lat: float | None, lon: float | None) -> list:
    """Recalcula distance_km desde las coordenadas aproximadas.

    Si la página venía ordenada por cercanía se reordena con la distancia pública (orden estable).
    """
    if lat is None or lon is None:
        return items
    exact = [i.distance_km for i in items]
    by_distance = all(d is not None for d in exact) and all(a <= b for a, b in zip(exact, exact[1:]))
    for item in items:
        item.distance_km = public_distance(item, lat, lon)
    if by_distance and len(items) > 1:
        items = sorted(items, key=lambda i: i.distance_km if i.distance_km is not None else 1e9)
    return items


def is_owner_or_admin(user, owner_id: int | None) -> bool:
    """True para el dueño / quien reporta y para los admins (ven datos exactos y contenido no público)."""
    if user is None:
        return False
    return user.role in ("admin", "superadmin") or (owner_id is not None and user.id == owner_id)
