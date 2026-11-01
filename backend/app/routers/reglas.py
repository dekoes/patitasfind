"""Reglas de negocio con efecto legal (services/reglas.py): comprobante de compra, bonificaciones, retenciones para
revisión humana y alertas de donativos.

Público:  GET /cumplimiento/reglas (topes de donativos, categorías de productos, plazo de resguardo de perros encontrados)
Comprador: GET /orders/{id}/comprobante
Refugio:  GET /refuges/me/bonificaciones, POST /refuges/me/orders/{id}/bonificacion
Admins:   /admin/reglas/retenciones, /admin/reglas/bonificaciones, /admin/reglas/alertas-donativos,
          /admin/reglas/facturas-atrasadas
"""
import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, get_verified_user, require_admin
from app.models import Order, OrderBonus, OrderInvoice, OrderItem, Refuge, User
from app.services import reglas
from app.services.payment_flow import ADMIN_ROLES

router = APIRouter(tags=["reglas"])


class HoldDecision(BaseModel):
    decision: Literal["liberar", "rechazar"]
    notas: str | None = Field(None, max_length=1000)


class BonusPaidIn(BaseModel):
    referencia: str = Field(..., min_length=4, max_length=255)
    nota: str | None = Field(None, max_length=1000)


class BonusResolveIn(BaseModel):
    accion: Literal["marcar_pagada", "improcedente", "reabrir"]
    referencia: str | None = Field(None, max_length=255)
    nota: str | None = Field(None, max_length=2000)


class AmlReviewIn(BaseModel):
    nota: str | None = Field(None, max_length=2000)


# --------------------------------------------------------------------------- público
@router.get("/cumplimiento/reglas")
def rules_config():
    """Lo que la app muestra antes de donar, vender o publicar (sin sesión)."""
    return {
        "donations": {
            "min_mxn": 10, "max_mxn": settings.donation_max_mxn, "daily_max_mxn": settings.donation_daily_max_mxn,
            "fee_percent": settings.mercadopago_donation_fee_percent, "points": False,
        },
        "shop": {
            "fee_percent": settings.mercadopago_marketplace_fee_percent, "min_warranty_days": reglas.MIN_WARRANTY_DAYS,
            "no_warranty_text": reglas.NO_WARRANTY,
            "categories": [{"key": k, "label": label, "review": review}
                           for k, (label, review) in reglas.PRODUCT_CATEGORIES.items()],
            "invoice_sla_hours": reglas.INVOICE_SLA_HOURS, "bonus_percent": float(reglas.BONUS_PERCENT),
        },
        "adoption": {
            "found_dog_hold_days": settings.found_dog_hold_days,
            "microchip_results": [{"key": k, "label": v} for k, v in reglas.MICROCHIP_RESULTS.items()],
        },
        "import_notice": reglas.IMPORT_NOTICE,
    }


# --------------------------------------------------------------------------- comprador: comprobante
@router.get("/orders/{id}/comprobante")
def order_receipt(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Comprobante electrónico del pedido (LFPC art. 76 Bis; consumidor-ecommerce-07). No es CFDI."""
    order = (db.query(Order).options(selectinload(Order.items).selectinload(OrderItem.product),
                                     joinedload(Order.refuge), selectinload(Order.invoice))
             .filter(Order.id == id).first())
    if not order:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    if order.user_id != current_user.id and current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="No tienes acceso a este pedido.")
    if not order.paid_at:  # solo pedidos cuyo pago se confirmó (también si después se canceló o reembolsó)
        raise HTTPException(status_code=409, detail="El comprobante está disponible cuando se confirma el pago.")
    return reglas.order_receipt(db, order)


# --------------------------------------------------------------------------- refugio vendedor: bonificaciones
def _my_refuge(db: Session, user: User) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == user.id).first()
    if not refuge:
        raise HTTPException(status_code=403, detail="Solo los refugios vendedores tienen bonificaciones.")
    return refuge


@router.get("/refuges/me/bonificaciones")
def my_bonuses(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    refuge = _my_refuge(db, current_user)
    rows = (db.query(OrderBonus).filter(OrderBonus.refuge_id == refuge.id)
            .order_by(OrderBonus.created_at.desc()).limit(200).all())
    return [reglas.bonus_out(b) for b in rows]


@router.post("/refuges/me/orders/{id}/bonificacion")
def report_bonus_paid(id: int, payload: BonusPaidIn, current_user: User = Depends(get_verified_user),
                      db: Session = Depends(get_db)):
    """El refugio registra que pagó la bonificación (referencia de la transferencia o del reembolso)."""
    refuge = _my_refuge(db, current_user)
    order = db.query(Order).filter(Order.id == id).first()
    if not order or order.refuge_id != refuge.id:
        raise HTTPException(status_code=404, detail="No encontramos ese pedido.")
    return reglas.report_bonus_paid(db, order, refuge, payload.referencia, payload.nota)


# --------------------------------------------------------------------------- admins
@router.get("/admin/reglas/retenciones")
def admin_holds(status: Literal["en_revision", "liberado", "rechazado", "all"] = Query("en_revision"),
                admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Publicaciones retenidas por cobros, venta, rifas o la lista de productos prohibidos."""
    return reglas.list_holds(db, status)


@router.post("/admin/reglas/retenciones/{target_type}/{target_id}")
def admin_decide_hold(target_type: Literal["dog", "product"], target_id: int, payload: HoldDecision, request: Request,
                      admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return reglas.decide_hold(db, target_type, target_id, admin_user, payload.decision, payload.notas, request)


@router.get("/admin/reglas/bonificaciones")
def admin_bonuses(status: Literal["pendiente", "pagada", "improcedente", "all"] = Query("pendiente"),
                  admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(OrderBonus)
    if status != "all":
        q = q.filter(OrderBonus.status == status)
    rows = q.order_by(OrderBonus.due_at.asc().nullslast(), OrderBonus.id.desc()).limit(300).all()
    refuges = {r.id: r.name for r in db.query(Refuge).filter(Refuge.id.in_({b.refuge_id for b in rows if b.refuge_id}))}
    now = datetime.datetime.utcnow()
    return [{**reglas.bonus_out(b), "refuge_name": refuges.get(b.refuge_id),
             "overdue": b.status == "pendiente" and b.due_at is not None and b.due_at < now} for b in rows]


@router.post("/admin/reglas/bonificaciones/{id}")
def admin_resolve_bonus(id: int, payload: BonusResolveIn, request: Request, admin_user: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    return reglas.resolve_bonus(db, id, admin_user, payload.accion, payload.referencia, payload.nota, request)


@router.get("/admin/reglas/alertas-donativos")
def admin_aml_flags(pendientes: bool = Query(True), admin_user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    """Alertas de la ley antilavado: acumulado de 6 meses por donante y refugio (prevencion-lavado §4)."""
    return reglas.list_aml_flags(db, pending_only=pendientes)


@router.post("/admin/reglas/alertas-donativos/{id}/revisar")
def admin_review_aml_flag(id: int, payload: AmlReviewIn, request: Request, admin_user: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    return reglas.review_aml_flag(db, id, admin_user, payload.nota, request)


@router.get("/admin/reglas/facturas-atrasadas")
def admin_overdue_invoices(admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Solicitudes de factura sin emitir después de la meta de 24 h (terminos-tienda 8.2)."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=reglas.INVOICE_SLA_HOURS)
    rows = (db.query(OrderInvoice).filter(OrderInvoice.status == "requested", OrderInvoice.requested_at < cutoff)
            .order_by(OrderInvoice.requested_at.asc()).limit(300).all())
    refuges = {r.id: r.name for r in db.query(Refuge).filter(Refuge.id.in_({i.refuge_id for i in rows if i.refuge_id}))}
    now = datetime.datetime.utcnow()
    return [{"order_id": i.order_id, "refuge_id": i.refuge_id, "refuge_name": refuges.get(i.refuge_id),
             "requested_at": i.requested_at, "hours": int((now - i.requested_at).total_seconds() // 3600),
             "reminded_at": i.reminded_at, "escalated_at": i.escalated_at} for i in rows]

