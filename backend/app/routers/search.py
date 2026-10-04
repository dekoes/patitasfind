from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import client_ip
from app.schemas import PhotoSearchOut
from app.services import images, matching, ratelimit

router = APIRouter(tags=["search"])


@router.post("/search/by-photo", response_model=PhotoSearchOut)
async def search_by_photo(
    request: Request,
    file: UploadFile = File(...),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    city: str | None = Form(None),
    report_type: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Busca perros parecidos a la foto (reportes activos y perros en adopción). Público, con límite por IP."""
    ratelimit.check(f"search:{client_ip(request)}", limit=10, window_seconds=60)
    if report_type not in (None, "", "lost", "found", "adoption"):
        raise HTTPException(status_code=400, detail="report_type debe ser lost, found o adoption.")
    data = await file.read(images.max_bytes() + 1)
    try:
        images.open_image(data)
    except images.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    analysis, matches = await run_in_threadpool(
        matching.search_by_photo, db, data, lat, lon, city, report_type or None
    )
    return {"analysis": analysis, "matches": matches}
