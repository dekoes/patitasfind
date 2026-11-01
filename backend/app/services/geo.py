"""Utilidades geográficas (haversine en Python y en SQL, sin PostGIS)."""
import math

from sqlalchemy import Float, Numeric, cast, func
from sqlalchemy.orm import defer

EARTH_RADIUS_KM = 6371.0088
DISTANCE_DECIMALS = 1
# Decimales de las coordenadas públicas (~1.1 km); privacy.COORD_DECIMALS toma este valor
COARSE_DECIMALS = 2
# Cuánto puede alejarse una coordenada exacta de su versión aproximada (medio paso de redondeo)
COARSE_MARGIN_DEG = 0.5 / 10 ** COARSE_DECIMALS + 1e-9

# Columnas JSON pesadas que ningún listado devuelve (solo las usa el matching); los esquemas
# DogOut/LostReportOut tampoco las serializan, así que diferirlas no provoca consultas extra
HEAVY_LIST_COLUMNS = ("photo_signature", "ai_analysis")


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


def distance_sql(lat_col, lon_col, lat: float, lon: float):
    """Misma fórmula que haversine_km pero en SQL (km). El argumento de asin se limita a 1."""
    dlat = func.radians(lat_col - lat)
    dlon = func.radians(lon_col - lon)
    a = (
        func.power(func.sin(dlat / 2), 2)
        + func.cos(func.radians(lat)) * func.cos(func.radians(lat_col)) * func.power(func.sin(dlon / 2), 2)
    )
    return 2 * EARTH_RADIUS_KM * func.asin(func.least(1.0, func.sqrt(a)))


def coarse(value: float | None) -> float | None:
    """Coordenada aproximada (~1 km): lo único que ve el público."""
    return None if value is None else round(float(value), COARSE_DECIMALS)


def coarse_sql(col):
    """Lo mismo que coarse() en SQL. Se redondea como numeric para que coincida con round() de Python
    (solo difieren en empates exactos como 19.425, que no se dan con coordenadas reales)."""
    return cast(func.round(cast(col, Numeric), COARSE_DECIMALS), Float)


def distance_to(obj, lat: float | None, lon: float | None, exact: bool = True) -> float | None:
    """Distancia en km desde (lat, lon); con exact=False se mide a las coordenadas aproximadas."""
    if lat is None or lon is None or obj.latitude is None or obj.longitude is None:
        return None
    obj_lat, obj_lon = (obj.latitude, obj.longitude) if exact else (coarse(obj.latitude), coarse(obj.longitude))
    return round(haversine_km(lat, lon, obj_lat, obj_lon), DISTANCE_DECIMALS)


def light_list(query, model):
    """No carga las columnas JSON pesadas en listados (no se serializan)."""
    return query.options(*(defer(getattr(model, c)) for c in HEAVY_LIST_COLUMNS if hasattr(model, c)))


def within_radius(query, model, lat: float, lon: float, radius_km: float, exact: bool = False):
    """Filtra en SQL a los que están a <= radius_km. Devuelve (query, expresión de distancia).

    La caja usa el índice (latitude, longitude); la distancia descarta las esquinas.
    Por defecto (consultas públicas) el radio y la distancia se evalúan sobre las coordenadas aproximadas,
    las mismas que se devuelven: con las exactas bastaría bisecar radius_km desde varios puntos para
    recuperar la ubicación real. Solo las consultas del dueño o de admins pasan exact=True.
    """
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
    if exact:
        lat_col, lon_col = model.latitude, model.longitude
    else:
        lat_col, lon_col = coarse_sql(model.latitude), coarse_sql(model.longitude)
        # La caja va sobre las columnas exactas (las del índice): se amplía lo que puede mover el redondeo
        min_lat, max_lat = min_lat - COARSE_MARGIN_DEG, max_lat + COARSE_MARGIN_DEG
        min_lon, max_lon = min_lon - COARSE_MARGIN_DEG, max_lon + COARSE_MARGIN_DEG
    dist = distance_sql(lat_col, lon_col, lat, lon)
    query = query.filter(
        model.latitude.isnot(None), model.longitude.isnot(None),
        model.latitude.between(min_lat, max_lat), model.longitude.between(min_lon, max_lon),
        dist <= radius_km,
    )
    return query, dist


def nearest(query, model, lat: float, lon: float, radius_km: float, skip: int = 0, limit: int = 50,
            exact: bool = False) -> list:
    """Página de resultados dentro del radio, ordenada por cercanía; filtro, orden y OFFSET/LIMIT en Postgres."""
    q, dist = within_radius(light_list(query, model), model, lat, lon, radius_km, exact=exact)
    # A igual distancia (toda una celda de ~1 km en el modo público) primero los más recientes
    rows = q.add_columns(dist.label("distance_km")).order_by(dist, model.id.desc()).offset(skip).limit(limit).all()
    items = []
    for item, d in rows:
        item.distance_km = round(float(d), DISTANCE_DECIMALS)
        items.append(item)
    return items


def apply_distance(query, model, items_loader, lat, lon, radius_km, skip=0, limit=50, fallback_order=None,
                   exact=False):
    """Aplica la lógica de distancia común a perros y reportes.

    - Con lat/lon: filtra a los que tienen coordenadas dentro de radius_km, calcula
      distance_km y ordena por cercanía (todo en SQL). Si no hay ninguno en el radio, cae a la
      consulta sin filtro de distancia ordenada por fecha (calculando distance_km cuando se pueda).
    - Sin lat/lon: consulta normal ordenada por fecha.
    - exact=False (público): radio y distancias sobre las coordenadas aproximadas (ver within_radius).
    """
    order = fallback_order if fallback_order is not None else model.created_at.desc()
    if lat is not None and lon is not None:
        items = nearest(query, model, lat, lon, radius_km, skip, limit, exact=exact)
        if items:
            return items
        if skip:
            q, _ = within_radius(query, model, lat, lon, radius_km, exact=exact)
            if q.enable_eagerloads(False).with_entities(model.id).limit(1).first() is not None:
                return []  # sí hay resultados en el radio: esta página ya pasó el final
        items = light_list(query, model).order_by(order, model.id.desc()).offset(skip).limit(limit).all()
        for item in items:
            item.distance_km = distance_to(item, lat, lon, exact=exact)
        return items
    return light_list(query, model).order_by(order, model.id.desc()).offset(skip).limit(limit).all()
