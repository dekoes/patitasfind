from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import client_ip, get_optional_user
from app.models import User
from app.schemas import PhotoSearchOut
from app.services import images, matching, ratelimit, vision

router = APIRouter(tags=["search"])
HOUR_SECONDS = 60 * 60
DAY_SECONDS = 24 * HOUR_SECONDS
ANON_DAILY_DEFAULT = 30


def _anon_daily_limit() -> int:
    if settings.search_anon_daily_limit is not None:
        return settings.search_anon_daily_limit
    return 0 if settings.is_development else ANON_DAILY_DEFAULT


def _check_limits(user_id: int | None, ip: str) -> None:
    """Con sesión: por usuario y hora. Sin sesión: por IP, por minuto y por día."""
    if user_id:
        ratelimit.check(
            f"search:user:{user_id}", settings.search_user_hourly_limit, HOUR_SECONDS,
            detail="Hiciste muchas búsquedas por foto en la última hora. Espera un rato e inténtalo de nuevo.",
        )
        return
    ratelimit.check(f"search:{ip}", settings.search_anon_minute_limit, 60)
    daily = _anon_daily_limit()
    if daily > 0:
        ratelimit.check(
            f"search-day:{ip}", daily, DAY_SECONDS,
            detail="Llegaste al límite diario de búsquedas por foto sin cuenta. Inicia sesión para seguir buscando.",
        )


@router.post("/search/by-photo", response_model=PhotoSearchOut)
async def search_by_photo(
    request: Request,
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    city: str | None = Form(None),
    report_type: str | None = Form(None),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Busca perros parecidos a la foto (reportes activos y perros en adopción). Público, con límite por usuario o IP."""
    user_id = current_user.id if current_user else None
    # No se retiene la conexión a la BD mientras se valida la foto y responde la IA
    await run_in_threadpool(db.close)
    if report_type not in (None, "", "lost", "found", "adoption"):
        raise HTTPException(status_code=400, detail="report_type debe ser lost, found o adoption.")
    await run_in_threadpool(_check_limits, user_id, client_ip(request))
    try:
        data = await file.read(images.max_bytes() + 1)
    finally:
        await file.close()
    try:
        await run_in_threadpool(images.probe_image, data)
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    analysis = await vision.analyze_image_bytes_async(data) if vision.is_configured() else None
    # El análisis quedó en la caché en memoria de vision: la consulta a la BD no vuelve a llamar a la IA,
    # y si la IA falló (None) se busca solo por similitud visual.
    analysis, matches = await run_in_threadpool(
        matching.search_by_photo, db, data, lat, lon, city, report_type or None, use_ai=analysis is not None,
    )
    return {"analysis": analysis, "matches": matches}
