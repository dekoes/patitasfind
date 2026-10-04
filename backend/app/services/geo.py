"""Utilidades geográficas (haversine en Python, sin PostGIS)."""
import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Caja aproximada (min_lat, max_lat, min_lon, max_lon) para prefiltrar en SQL."""
    dlat = radius_km / 111.0
    dlon = radius_km / max(1e-6, 111.0 * math.cos(math.radians(lat)))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def distance_to(obj, lat: float | None, lon: float | None) -> float | None:
    if lat is None or lon is None or obj.latitude is None or obj.longitude is None:
        return None
    return round(haversine_km(lat, lon, obj.latitude, obj.longitude), 2)


def apply_distance(query, model, items_loader, lat, lon, radius_km, skip=0, limit=50, fallback_order=None):
    """Aplica la lógica de distancia común a perros y reportes.

    - Con lat/lon: filtra a los que tienen coordenadas dentro de radius_km, calcula
      distance_km y ordena por cercanía. Si no hay resultados, cae a la consulta sin
      filtro de distancia ordenada por fecha (calculando distance_km cuando se pueda).
    - Sin lat/lon: consulta normal ordenada por fecha.
    """
    order = fallback_order if fallback_order is not None else model.created_at.desc()
    if lat is not None and lon is not None:
        min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
        candidates = (
            query.filter(
                model.latitude.isnot(None), model.longitude.isnot(None),
                model.latitude.between(min_lat, max_lat), model.longitude.between(min_lon, max_lon),
            )
            .limit(5000)
            .all()
        )
        within = []
        for item in candidates:
            d = haversine_km(lat, lon, item.latitude, item.longitude)
            if d <= radius_km:
                item.distance_km = round(d, 2)
                within.append(item)
        if within:
            within.sort(key=lambda x: x.distance_km)
            return within[skip: skip + limit]
        items = query.order_by(order).offset(skip).limit(limit).all()
        for item in items:
            item.distance_km = distance_to(item, lat, lon)
        return items
    return query.order_by(order).offset(skip).limit(limit).all()
