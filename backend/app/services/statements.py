"""Estados de cuenta mensuales por refugio (ventas, reembolsos, comisión, retenciones y donativos).

Con Mercado Pago split el dinero de cada venta llega directo a la cuenta del refugio y la plataforma solo
recibe `marketplace_fee` (comisión + retenciones); por eso NO hay "pagos a refugios" (payouts) que calcular:
net_received es lo que quedó en la cuenta del refugio antes de la comisión de Mercado Pago.

El periodo "YYYY-MM" es el mes calendario en horario de la Ciudad de México:
- Ventas: pedidos cobrados (paid_at) en el mes, aunque después se cancelen o reembolsen.
- Reembolsos (totales o parciales, order_refunds): restan en el mes EN QUE OCURREN. Así un mes ya cerrado y
  facturado no cambia; un reembolso posterior se descuenta del estado de cuenta y de los CFDI del mes siguiente
  (fiscal-tienda: "se descuenta del siguiente estado de liquidación y del CFDI de retenciones").
- Mercado Pago reparte cada reembolso en proporción entre el refugio y la plataforma (Split 1:1), así que
  la comisión y las retenciones también regresan en proporción (fee/isr/iva_reversed).
net_received = gross - refunds_total - platform_fee - isr_retenido - iva_retenido (todas netas de reembolsos).
"""
import csv
import datetime
import io
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Donation, Order, OrderRefund, Refuge
from app.services.payment_flow import IVA_RATE, money2

MX_TZ = ZoneInfo("America/Mexico_City")
PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
ZERO = Decimal("0.00")


def current_period(now: datetime.datetime | None = None) -> str:
    local = (now or datetime.datetime.utcnow()).replace(tzinfo=datetime.timezone.utc).astimezone(MX_TZ)
    return f"{local.year:04d}-{local.month:02d}"


def previous_period(now: datetime.datetime | None = None) -> str:
    year, month = map(int, current_period(now).split("-"))
    year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return f"{year:04d}-{month:02d}"


def parse_period(period: str | None, default: str | None = None) -> str:
    period = (period or default or current_period()).strip()
    if not PERIOD_RE.match(period):
        raise HTTPException(status_code=400, detail="El periodo debe tener el formato AAAA-MM, p. ej. 2026-10.")
    return period


def period_bounds(period: str) -> tuple[datetime.datetime, datetime.datetime]:
    """Inicio y fin (UTC sin zona, fin exclusivo) del mes en horario de la Ciudad de México."""
    year, month = map(int, period.split("-"))
    start = datetime.datetime(year, month, 1, tzinfo=MX_TZ)
    end = datetime.datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=MX_TZ)
    to_utc = lambda d: d.astimezone(datetime.timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(start), to_utc(end)


def fee_iva(fee_with_iva) -> Decimal:
    """IVA incluido en la comisión (la comisión se cobra con IVA incluido)."""
    fee = Decimal(fee_with_iva or 0)
    return fee - money2(fee / (1 + IVA_RATE))


def _d(value) -> Decimal:
    return money2(value or 0)


def _sales(db: Session, refuge_id: int, start, end) -> list[Order]:
    """Pedidos cobrados en el periodo (paid_at solo existe si el pago se aceptó)."""
    return (db.query(Order).filter(Order.refuge_id == refuge_id, Order.paid_at >= start, Order.paid_at < end)
            .order_by(Order.paid_at, Order.id).all())


def _refunds(db: Session, refuge_id: int, start, end) -> list[OrderRefund]:
    """Reembolsos hechos en el periodo de pedidos que sí contaron como venta."""
    return (db.query(OrderRefund).join(Order, Order.id == OrderRefund.order_id)
            .filter(OrderRefund.refuge_id == refuge_id, OrderRefund.created_at >= start, OrderRefund.created_at < end,
                    Order.paid_at.isnot(None))
            .order_by(OrderRefund.created_at, OrderRefund.id).all())


def refuge_statement(db: Session, refuge_id: int, period: str, include_orders: bool = True) -> dict:
    start, end = period_bounds(period)
    orders = _sales(db, refuge_id, start, end)
    refunds = _refunds(db, refuge_id, start, end)
    gross = sum((_d(o.total) for o in orders), ZERO)
    refunds_total = sum((_d(r.amount) for r in refunds), ZERO)
    platform_fee = sum((_d(o.fee_amount) for o in orders), ZERO) - sum((_d(r.fee_reversed) for r in refunds), ZERO)
    isr = sum((_d(o.isr_retenido) for o in orders), ZERO) - sum((_d(r.isr_reversed) for r in refunds), ZERO)
    iva = sum((_d(o.iva_retenido) for o in orders), ZERO) - sum((_d(r.iva_reversed) for r in refunds), ZERO)
    donations = (db.query(Donation).filter(
        Donation.refuge_id == refuge_id, Donation.status == "approved",
        func.coalesce(Donation.approved_at, Donation.created_at) >= start,
        func.coalesce(Donation.approved_at, Donation.created_at) < end).all())
    donations_gross = sum((_d(d.amount) for d in donations), ZERO)
    donations_fee = sum((_d(d.fee_amount) for d in donations), ZERO)
    out = {
        "period": period,
        "refuge_id": refuge_id,
        "orders_count": len(orders),
        "gross": gross,  # ventas cobradas en el mes, envío incluido
        "shipping": sum((_d(o.shipping_total) for o in orders), ZERO),  # informativo: ya está dentro de gross
        "refunds_count": len(refunds),
        "refunds_total": refunds_total,
        "net_sales": gross - refunds_total,
        "platform_fee": platform_fee,  # comisión neta de reembolsos, IVA incluido
        "fee_iva": fee_iva(platform_fee),  # informativo: ya está dentro de platform_fee
        "isr_retenido": isr,
        "iva_retenido": iva,
        "net_received": gross - refunds_total - platform_fee - isr - iva,
        "donations_count": len(donations),
        "donations_gross": donations_gross,
        "donations_fee": donations_fee,
        "donations_fee_iva": fee_iva(donations_fee),
        "donations_net": donations_gross - donations_fee,
        # Donativos cobrados con la cuenta de la plataforma (refugio sin Mercado Pago vinculado): se le deben
        "donations_via_platform": sum((_d(d.amount) for d in donations if d.payment_mode == "platform"), ZERO),
    }
    if include_orders:
        out["orders"] = [{
            "id": o.id, "paid_at": o.paid_at, "status": o.status, "subtotal": _d(o.subtotal or o.total),
            "shipping_total": _d(o.shipping_total), "total": _d(o.total), "fee_amount": _d(o.fee_amount),
            "isr_retenido": _d(o.isr_retenido), "iva_retenido": _d(o.iva_retenido),
            "net_amount": _d(o.net_amount if o.net_amount is not None else o.total),
            "refund_amount": _d(o.refund_amount) if o.refund_amount is not None else None,
        } for o in orders]
        out["refunds"] = [{
            "order_id": r.order_id, "at": r.created_at, "amount": _d(r.amount), "fee_reversed": _d(r.fee_reversed),
            "isr_reversed": _d(r.isr_reversed), "iva_reversed": _d(r.iva_reversed), "is_full": bool(r.is_full),
            "net_reversed": _d(r.amount) - _d(r.fee_reversed) - _d(r.isr_reversed) - _d(r.iva_reversed),
        } for r in refunds]
    return out


def has_activity(statement: dict) -> bool:
    return bool(statement["orders_count"] or statement["donations_count"] or statement["refunds_count"])


def admin_statements(db: Session, period: str) -> dict:
    """Todos los refugios con movimientos en el periodo + totales de la plataforma."""
    start, end = period_bounds(period)
    ids = {rid for (rid,) in db.query(Order.refuge_id).filter(
        Order.refuge_id.isnot(None), Order.paid_at >= start, Order.paid_at < end).distinct()}
    ids |= {rid for (rid,) in db.query(OrderRefund.refuge_id).filter(
        OrderRefund.refuge_id.isnot(None), OrderRefund.created_at >= start, OrderRefund.created_at < end).distinct()}
    ids |= {rid for (rid,) in db.query(Donation.refuge_id).filter(
        Donation.status == "approved", func.coalesce(Donation.approved_at, Donation.created_at) >= start,
        func.coalesce(Donation.approved_at, Donation.created_at) < end).distinct()}
    names = dict(db.query(Refuge.id, Refuge.name).filter(Refuge.id.in_(ids)).all()) if ids else {}
    rows = []
    for rid in sorted(ids):
        st = refuge_statement(db, rid, period, include_orders=False)
        if not has_activity(st):
            continue
        st["refuge_name"] = names.get(rid)
        rows.append(st)
    keys = ("orders_count", "gross", "shipping", "refunds_count", "refunds_total", "net_sales", "platform_fee",
            "fee_iva", "isr_retenido", "iva_retenido", "net_received", "donations_count", "donations_gross",
            "donations_fee", "donations_net", "donations_via_platform")
    totals = {k: sum((r[k] for r in rows), 0 if k.endswith("count") else ZERO) for k in keys}
    totals["platform_income"] = totals["platform_fee"] + totals["donations_fee"]  # comisiones (IVA incluido)
    totals["retentions_to_pay"] = totals["isr_retenido"] + totals["iva_retenido"]  # se enteran al SAT (día 17)
    return {"period": period, "refuges": rows, "totals": totals,
            # Comisiones configuradas hoy (las de cada pedido quedan en Order.fee_percent)
            "fee_percent": float(settings.mercadopago_marketplace_fee_percent),
            "donation_fee_percent": float(settings.mercadopago_donation_fee_percent)}


CSV_COLUMNS = ("tipo", "pedido", "fecha", "estado", "subtotal", "envio", "total", "comision", "isr_retenido",
               "iva_retenido", "neto_refugio")


def statement_csv(statement: dict) -> str:
    """CSV para Excel (separador coma, UTF-8 con BOM para que abra bien los acentos)."""
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for o in statement.get("orders", []):
        writer.writerow(["venta", o["id"], o["paid_at"].strftime("%Y-%m-%d %H:%M") if o["paid_at"] else "", o["status"],
                         o["subtotal"], o["shipping_total"], o["total"], o["fee_amount"], o["isr_retenido"],
                         o["iva_retenido"], o["net_amount"]])
    for r in statement.get("refunds", []):
        writer.writerow(["reembolso total" if r["is_full"] else "reembolso parcial", r["order_id"],
                         r["at"].strftime("%Y-%m-%d %H:%M") if r["at"] else "", "", "", "", -r["amount"],
                         -r["fee_reversed"], -r["isr_reversed"], -r["iva_reversed"], -r["net_reversed"]])
    writer.writerow([])
    for label, key in (("Ventas (incluye envío)", "gross"), ("Envíos (incluidos en ventas)", "shipping"),
                       ("Reembolsos", "refunds_total"), ("Comisión GuauWoow (IVA incluido)", "platform_fee"),
                       ("IVA incluido en la comisión", "fee_iva"), ("ISR retenido", "isr_retenido"),
                       ("IVA retenido", "iva_retenido"), ("Neto recibido", "net_received"),
                       ("Donativos", "donations_gross"), ("Comisión de donativos", "donations_fee")):
        writer.writerow([label, "", "", "", "", "", statement[key]])
    return buf.getvalue()
