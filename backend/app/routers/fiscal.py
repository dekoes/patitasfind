"""Estados de cuenta de la tienda (refugio y admins) y CFDI que emite la plataforma (admins)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Cfdi, Refuge, User
from app.schemas import CfdiOut
from app.services import invoicing, statements
from app.services.audit import record_admin_action

router = APIRouter(tags=["fiscal"])


def _my_refuge(db: Session, user: User) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == user.id).first()
    if not refuge:
        raise HTTPException(status_code=404, detail="Todavía no tienes un refugio registrado.")
    return refuge


@router.get("/refuges/me/statements")
def my_statement(period: str | None = Query(None, max_length=7), current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Estado de cuenta del mes (AAAA-MM, horario de la Ciudad de México; por defecto el mes actual).

    Con Mercado Pago split el dinero ya llegó a tu cuenta: net_received = ventas - comisión - retenciones.
    """
    refuge = _my_refuge(db, current_user)
    return statements.refuge_statement(db, refuge.id, statements.parse_period(period))


@router.get("/refuges/me/statements/export")
def export_my_statement(period: str | None = Query(None, max_length=7), current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    refuge = _my_refuge(db, current_user)
    period = statements.parse_period(period)
    body = statements.statement_csv(statements.refuge_statement(db, refuge.id, period))
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="estado-de-cuenta-{period}.csv"',
                             "Cache-Control": "no-store, private"})


@router.get("/admin/statements")
def admin_statements(period: str | None = Query(None, max_length=7), admin_user: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    """Todos los refugios con movimientos en el periodo y los totales de la plataforma (comisiones y retenciones)."""
    return statements.admin_statements(db, statements.parse_period(period))


def _cfdi_out(row: Cfdi) -> dict:
    data = CfdiOut.model_validate(row).model_dump()
    data.update(refuge_name=row.refuge.name if row.refuge else None, has_xml=bool(row.xml_document_id),
                has_pdf=bool(row.pdf_document_id))
    return data


@router.get("/admin/cfdi", response_model=list[CfdiOut])
def list_cfdi(
    period: str | None = Query(None, max_length=7),
    status: str | None = Query(None, pattern="^(pending_pac|issued|error)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Cfdi).options(joinedload(Cfdi.refuge))
    if period:
        q = q.filter(Cfdi.period == statements.parse_period(period))
    if status:
        q = q.filter(Cfdi.status == status)
    return [_cfdi_out(r) for r in q.order_by(Cfdi.period.desc(), Cfdi.id.desc()).offset(skip).limit(limit).all()]


@router.post("/admin/cfdi/generate")
def generate_cfdi(request: Request, period: str | None = Query(None, max_length=7),
                  admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Genera ya los CFDI de un periodo (por defecto el mes anterior); la tarea del día 3 hace lo mismo."""
    period = statements.parse_period(period, statements.previous_period())
    result = invoicing.generate_period_cfdis(db, period)
    record_admin_action(db, admin_user, "cfdi_generate", "cfdi", None, details=result, request=request)
    db.commit()
    return result


@router.post("/admin/cfdi/{id}/retry", response_model=CfdiOut)
def retry_cfdi(id: int, request: Request, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.query(Cfdi).filter(Cfdi.id == id).first()
    if not row:
        raise HTTPException(status_code=404, detail="No encontramos ese CFDI.")
    if row.status == "issued":
        raise HTTPException(status_code=409, detail="Este CFDI ya está timbrado.")
    if row.status == "stamping":
        raise HTTPException(status_code=409, detail="Este CFDI se quedó a mitad del timbrado. Revisa en Facturama si "
                                                    "ya existe antes de hacer cualquier cosa: reintentarlo podría "
                                                    "timbrarlo dos veces.")
    previous = row.status
    invoicing.issue_cfdi_row(db, row)
    record_admin_action(db, admin_user, "cfdi_retry", "cfdi", row.id, request=request,
                        details={"from": previous, "to": row.status, "error": row.error})
    db.commit()
    db.refresh(row)
    if row.status == "pending_pac" and not invoicing.get_adapter():
        # Sin PAC no hay nada que reintentar; se informa en lugar de fingir que se envió
        out = _cfdi_out(row)
        out["error"] = "No hay PAC configurado (PAC_PROVIDER, PAC_USER, PAC_PASSWORD, EMISOR_*)."
        return out
    return _cfdi_out(row)


@router.get("/admin/cfdi/{id}/{fmt}")
def download_cfdi(id: int, fmt: str, request: Request, admin_user: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    if fmt not in ("xml", "pdf"):
        raise HTTPException(status_code=404, detail="Formato no disponible.")
    row = db.query(Cfdi).filter(Cfdi.id == id).first()
    path = invoicing.fiscal_file_path((row.xml_document_id if fmt == "xml" else row.pdf_document_id) if row else None)
    if not path:
        raise HTTPException(status_code=404, detail="Este CFDI todavía no tiene ese archivo.")
    record_admin_action(db, admin_user, "cfdi_download", "cfdi", row.id, details={"format": fmt}, request=request)
    db.commit()
    from app.services import crypto_storage

    # Cifrado en disco: se descifra en memoria (crypto_storage)
    return crypto_storage.private_file_response(path, media_type="application/xml" if fmt == "xml" else "application/pdf",
                                                filename=f"cfdi-{row.kind}-{row.period}-{row.refuge_id}.{fmt}",
                                                content_disposition_type="attachment")
