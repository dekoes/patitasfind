from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.dependencies import get_current_user
from app.models import User
from app.services import images

router = APIRouter(tags=["uploads"])
MAX_FILES = 5


async def _save(file: UploadFile) -> str:
    try:
        data = await file.read(images.max_bytes() + 1)
        return await run_in_threadpool(images.process_image_bytes, data)
    except images.ImageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    finally:
        await file.close()


@router.post("/upload/multiple", response_model=dict)
async def upload_multiple(files: list[UploadFile] = File(...), current_user: User = Depends(get_current_user)):
    if not files:
        raise HTTPException(status_code=400, detail="No se enviaron archivos.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_FILES} fotos por subida.")
    return {"urls": [await _save(f) for f in files]}


@router.post("/upload", response_model=dict)
async def upload_single(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    return {"url": await _save(file)}
