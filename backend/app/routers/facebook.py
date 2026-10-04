from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import require_admin
from app.models import FacebookGroup, User
from app.schemas import FacebookGroupCreate, FacebookGroupOut, FacebookImportRequest, LostReportAdminOut
from app.services.background import dispatch
from app.services.facebook_monitor import FacebookNotConfigured, create_report_from_post, ingest_page

router = APIRouter(tags=["facebook"])

NOT_CONFIGURED = "La lectura de Páginas de Facebook no está configurada (falta FACEBOOK_PAGE_ACCESS_TOKEN)."


@router.get("/facebook/groups", response_model=list[FacebookGroupOut])
def list_facebook_sources(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(FacebookGroup).order_by(FacebookGroup.created_at.desc()).all()


@router.get("/facebook/status")
def facebook_status(admin_user: User = Depends(require_admin)):
    return {"pages_enabled": settings.facebook_enabled, "graph_api_version": settings.graph_api_version}


@router.post("/facebook/groups", response_model=FacebookGroupOut, status_code=status.HTTP_201_CREATED)
def create_facebook_source(payload: FacebookGroupCreate, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    kind = payload.kind or ("page" if payload.page_id else "manual")
    if kind not in ("page", "manual"):
        raise HTTPException(status_code=400, detail="kind debe ser 'page' o 'manual'.")
    if kind == "page" and not payload.page_id:
        raise HTTPException(status_code=400, detail="Para una Página indica su page_id (ID numérico o alias).")
    source = FacebookGroup(name=payload.name, url=payload.url, page_id=payload.page_id, kind=kind, city=payload.city)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/facebook/groups/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_facebook_source(id: int, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    source = db.query(FacebookGroup).filter(FacebookGroup.id == id).first()
    if not source:
        raise HTTPException(status_code=404, detail="No encontramos esa fuente.")
    db.delete(source)
    db.commit()
    return None


def _match_new(report_ids, background_tasks):
    for rid in report_ids:
        dispatch("app.tasks.matching.match_lost_report", rid, background_tasks=background_tasks)


@router.post("/facebook/scrape")
def scrape_facebook_source(group_id: int, background_tasks: BackgroundTasks, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    source = db.query(FacebookGroup).filter(FacebookGroup.id == group_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="No encontramos esa fuente.")
    try:
        created = ingest_page(db, source)
    except FacebookNotConfigured:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _match_new(created, background_tasks)
    return {
        "group_id": group_id,
        "images_found": len(created),
        "reports_created": len(created),
        "report_ids": created,
        "message": f"Listo. {len(created)} reportes nuevos creados desde {source.name}.",
    }


@router.post("/facebook/scrape-all")
def scrape_all_facebook_sources(background_tasks: BackgroundTasks, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not settings.facebook_enabled:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    sources = db.query(FacebookGroup).filter(FacebookGroup.is_active == True, FacebookGroup.kind == "page").all()  # noqa: E712
    created, errors = [], []
    for source in sources:
        try:
            created += ingest_page(db, source)
        except (ValueError, RuntimeError) as exc:
            errors.append({"source_id": source.id, "error": str(exc)})
    _match_new(created, background_tasks)
    return {
        "groups_processed": len(sources),
        "total_reports_created": len(created),
        "errors": errors,
        "message": f"Procesadas {len(sources)} páginas. {len(created)} reportes creados.",
    }


@router.post("/facebook/import", response_model=LostReportAdminOut, status_code=status.HTTP_201_CREATED)
def manual_import(payload: FacebookImportRequest, background_tasks: BackgroundTasks, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if payload.report_type not in ("lost", "found"):
        raise HTTPException(status_code=400, detail="report_type debe ser 'lost' o 'found'.")
    if not payload.text.strip() and not payload.image_urls:
        raise HTTPException(status_code=400, detail="Pega al menos el texto o una foto de la publicación.")
    report = create_report_from_post(
        db, text=payload.text, image_urls=payload.image_urls, report_type=payload.report_type,
        city=payload.city, post_url=payload.post_url, require_dog=False,
    )
    if report is None:
        raise HTTPException(status_code=409, detail="Esa publicación ya fue importada.")
    _match_new([report.id], background_tasks)
    return report
