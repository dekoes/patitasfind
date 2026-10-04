from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.dependencies import get_current_user
from app.models import User
from app.services import images, vision

router = APIRouter(tags=["ai"])


@router.post("/ai/analyze-photo")
async def analyze_photo(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    """Analiza una foto con Claude para autollenar el formulario (raza, tamaño, color, descripción)."""
    if not vision.is_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="IA no configurada")
    data = await file.read(images.max_bytes() + 1)
    try:
        images.open_image(data)
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await run_in_threadpool(vision.analyze_image_bytes, data)
    if result is None:
        raise HTTPException(status_code=502, detail="No pudimos analizar la foto en este momento. Inténtalo de nuevo.")
    colors = result.get("colors") or []
    return {**result, "color": ", ".join(colors) if colors else None, "breed": result.get("breed_guess"),
            "description": result.get("description_es")}
