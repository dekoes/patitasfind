from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_verified_user
from app.models import User
from app.services import images, ratelimit, staydown

router = APIRouter(tags=["uploads"])
MAX_FILES = 5
DAY_SECONDS = 24 * 60 * 60


def _check_quota(user_id: int, role: str, files: int) -> None:
    """Máximo UPLOAD_DAILY_QUOTA fotos por usuario al día (los administradores están exentos)."""
    if role in ("admin", "superadmin"):
        return
    quota = settings.upload_daily_quota
    ratelimit.check(
        f"uploads:user:{user_id}", limit=quota, window_seconds=DAY_SECONDS, cost=files,
        detail=f"Llegaste al límite de {quota} fotos por día. Inténtalo de nuevo mañana.",
    )


async def _save(file: UploadFile, user_id: int | None = None) -> str:
    try:
        if file.size and file.size > images.max_bytes():
            raise images.ImageError(f"La imagen es demasiado grande. Máximo {settings.max_upload_mb} MB.")
        data = await file.read(images.max_bytes() + 1)
        try:
            return await run_in_threadpool(images.process_image_bytes, data)
        finally:
            del data  # hasta 10 MB por archivo: se libera antes de leer el siguiente
    except images.StaydownBlocked as exc:
        # Imagen idéntica a una retirada (staydown): se cuenta el intento y no se guarda nada
        await run_in_threadpool(staydown.record_hit, exc.block_id, user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except images.ImageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    finally:
        await file.close()


async def _authorize(user: User, db: Session, files: int) -> None:
    user_id, role = user.id, user.role
    # La sesión solo sirvió para autenticar: se libera la conexión antes de procesar las fotos
    await run_in_threadpool(db.close)
    await run_in_threadpool(_check_quota, user_id, role, files)


@router.post("/upload/multiple", response_model=dict)
async def upload_multiple(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Sube hasta 5 fotos (JPG, PNG o WebP, máx. 10 MB c/u). Requiere teléfono verificado."""
    if not files:
        raise HTTPException(status_code=400, detail="No se enviaron archivos.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_FILES} fotos por subida.")
    user_id = current_user.id
    await _authorize(current_user, db, len(files))
    return {"urls": [await _save(f, user_id) for f in files]}


@router.post("/upload", response_model=dict)
async def upload_single(
    file: UploadFile = File(...),
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Sube una foto (JPG, PNG o WebP, máx. 10 MB). Requiere teléfono verificado."""
    user_id = current_user.id
    await _authorize(current_user, db, 1)
    return {"url": await _save(file, user_id)}
