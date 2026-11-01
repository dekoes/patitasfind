from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_verified_user
from app.models import User
from app.services import images, ratelimit, vision

router = APIRouter(tags=["ai"])
HOUR_SECONDS = 60 * 60


@router.post("/ai/analyze-photo")
async def analyze_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Analiza una foto con el modelo de visión (Qwen3-VL/GLM) para autollenar el formulario (raza, tamaño, color, descripción)."""
    user_id = current_user.id
    # La sesión solo sirvió para autenticar: no se retiene una conexión mientras responde la IA
    await run_in_threadpool(db.close)
    if not vision.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="IA no configurada")
    try:
        data = await file.read(images.max_bytes() + 1)
    finally:
        await file.close()
    try:
        await run_in_threadpool(images.probe_image, data)
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await run_in_threadpool(
        ratelimit.check, f"ai:user:{user_id}", settings.ai_user_hourly_limit, HOUR_SECONDS,
        detail="Llegaste al límite de análisis con IA por hora. Inténtalo más tarde o llena los datos a mano.",
    )
    result = await vision.analyze_image_bytes_async(data)
    del data
    if result is None:
        raise HTTPException(status_code=502, detail="No pudimos analizar la foto en este momento. Inténtalo de nuevo.")
    colors = result.get("colors") or []
    return {**result, "color": ", ".join(colors) if colors else None, "breed": result.get("breed_guess"),
            "description": result.get("description_es")}
