"""Informe de transparencia (contrato K-TRANSP): cifras agregadas, sin datos personales, calculadas de los
registros de la Plataforma y guardadas en caché 1 hora.

- GET  /cumplimiento/transparencia?periodo=AAAA-MM|12m&vista=general|fondos
    general (informe-transparencia.html): dinero por Refugio, moderación, solicitudes ARCO, contenido importado,
    Refugios y Clínicas verificados y solicitudes de autoridades.
    fondos (transparencia-fondos.html): dinero por Refugio y serie mensual.
- GET  /cumplimiento/transparencia/refugios/{id}   «A dónde va tu dinero» de un Refugio (12 meses)
- GET/POST /cumplimiento/transparencia/mi-refugio  el Refugio acepta o retira publicar sus cifras con su nombre

Dinero (mismas reglas que services/statements.py): ventas = pedidos cobrados en el periodo (paid_at), reembolsos en
el periodo en que ocurren y su parte de comisión y retenciones; donativos aprobados. Neto = lo que correspondió al
Refugio después de la comisión de GuauWoow y de las retenciones, antes de la comisión de Mercado Pago.
Reglas de publicación (informe-transparencia §7 y transparencia-fondos §2):
- Solo totales agregados; nunca nombres ni montos individuales de quienes donan o compran.
- Un Refugio aparece con su nombre si está verificado y es persona moral o aceptó publicarlo (donativos-22: los
  montos de personas físicas solo con su consentimiento); los demás se suman en «Otros Refugios».
- Regla de umbral (TRANSPARENCY_MIN_CASES, 5): un desglose con menos casos se publica como «menos de 5».
- Cada respuesta dice cuándo se calculó (calculado_en).
"""
import datetime
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import cache
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    AdminAuditLog, ContentReport, Donation, FacebookGroup, LostReport, Order, OrderRefund, Refuge,
    RefugeFiscalProfile, User, Veterinary,
)
from app.schemas import TransparenciaOptIn
from app.services import solicitudes as sol
from app.services import statements

router = APIRouter(tags=["cumplimiento"])

CACHE_NS = "transparencia"
CACHE_TTL = 3600  # 1 hora
MONTHS_12 = 12
MONEY_REASON_RE = re.compile(r"venta|cobro|cuota|precio|dinero|donativo_sugerido", re.IGNORECASE)
REASON_LABELS = {
    "spam": "Spam", "fraude": "Fraude o estafa", "maltrato": "Maltrato animal", "contenido_inapropiado": "Contenido inapropiado",
    "datos_falsos": "Datos falsos", "otro": "Otro motivo", "honor_reputacion": "Afecta honor o reputación",
    "resena_falsa": "Reseña falsa o pagada", "datos_personales": "Datos personales", "cedula_falsa": "Cédula falsa",
    "condiciones_sanitarias": "Condiciones sanitarias", "publicidad_enganosa": "Publicidad engañosa",
    "involucra_menor": "Involucra a una persona menor de edad", "venta_animales": "Venta de animales",
    "cobro_adopcion": "Cobro por adopción",
}
DENIAL_LABELS = sol.DENIAL_REASONS
DETECTION_LABELS = {"reporte": "Por un reporte", "equipo": "Por revisión de nuestro equipo", "filtro": "Por el filtro automático",
                    "autoridad": "Por orden de una autoridad", "aviso_derechos": "Por un aviso de derechos de autor"}
ZERO = Decimal("0")


# --------------------------------------------------------------------------- utilidades
def _min_cases() -> int:
    return max(1, int(settings.transparency_min_cases or 1))


def _money(value) -> float:
    return float(round(Decimal(value or 0), 2))


def _shift_period(period: str, months: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def period_range(periodo: str | None, now: datetime.datetime | None = None) -> tuple[str, datetime.datetime, datetime.datetime]:
    """("12m" | "AAAA-MM", inicio, fin exclusivo) en UTC sin zona; meses calendario de la Ciudad de México."""
    now = now or datetime.datetime.utcnow()
    current = statements.current_period(now)
    if periodo in (None, "", "12m"):
        start = statements.period_bounds(_shift_period(current, -(MONTHS_12 - 1)))[0]
        return "12m", start, statements.period_bounds(current)[1]
    period = statements.parse_period(periodo)
    if period > current:
        raise HTTPException(status_code=400, detail="Ese periodo todavía no empieza.")
    start, end = statements.period_bounds(period)
    return period, start, end


def months_between(start: datetime.datetime, end: datetime.datetime) -> list[str]:
    first = statements.current_period(start)
    last = statements.current_period(end - datetime.timedelta(seconds=1))
    out, p = [], first
    while p <= last:
        out.append(p)
        p = _shift_period(p, 1)
    return out


def _local_month(col):
    """AAAA-MM en horario de la Ciudad de México de una columna UTC sin zona."""
    return func.to_char(func.timezone("America/Mexico_City", func.timezone("UTC", col)), "YYYY-MM")


def _block(data: dict, k: int) -> dict:
    """Aplica la regla de umbral a un bloque de dinero."""
    if data["casos"] < k:
        return {"suprimido": True, "casos": None}
    return {key: (_money(v) if isinstance(v, Decimal) else v) for key, v in data.items()}


def _collapse(counts: dict, labels: dict, k: int) -> list[dict]:
    """Desglose por categoría con la regla de umbral: las categorías con menos de k casos se suman en «Otros»;
    si esa suma tampoco llega a k, no se publica."""
    shown, small = [], 0
    for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] or "")):
        if n >= k:
            shown.append({"clave": key, "texto": labels.get(key, (key or "Sin dato").replace("_", " ").capitalize()), "casos": n})
        else:
            small += n
    if small >= k:
        shown.append({"clave": "otros", "texto": "Otras categorías (cada una con menos de %d casos)" % k, "casos": small})
    elif small:
        shown.append({"clave": "suprimido", "texto": "Categorías con menos de %d casos (no se publican)" % k, "casos": None})
    return shown


def _empty_sales() -> dict:
    return {"casos": 0, "bruto": ZERO, "reembolsos": ZERO, "comision": ZERO, "retenciones": ZERO, "neto": ZERO}


def _empty_donations() -> dict:
    return {"casos": 0, "bruto": ZERO, "comision": ZERO, "neto": ZERO}


# --------------------------------------------------------------------------- dinero
def money_by_refuge(db: Session, start, end, refuge_id: int | None = None, by_month: bool = False) -> dict:
    """{(refuge_id, mes|None): {"ventas": {...}, "donativos": {...}, "donativos_por_la_plataforma": Decimal}}."""
    out: dict = {}

    def slot(rid, month):
        return out.setdefault((rid, month), {"ventas": _empty_sales(), "donativos": _empty_donations(),
                                             "donativos_por_la_plataforma": ZERO})

    def keys(id_col, date_col):
        return [id_col, _local_month(date_col)] if by_month else [id_col]

    def split(row, n):
        return row[0], (row[1] if by_month else None), row[n:]

    donated_at = func.coalesce(Donation.approved_at, Donation.created_at)
    ok, rk, dk = keys(Order.refuge_id, Order.paid_at), keys(OrderRefund.refuge_id, OrderRefund.created_at), \
        keys(Donation.refuge_id, donated_at)
    oq = db.query(*ok, func.count(Order.id), func.coalesce(func.sum(Order.total), 0),
                  func.coalesce(func.sum(Order.fee_amount), 0), func.coalesce(func.sum(Order.isr_retenido), 0),
                  func.coalesce(func.sum(Order.iva_retenido), 0)).filter(
        Order.refuge_id.isnot(None), Order.paid_at >= start, Order.paid_at < end)
    rq = db.query(*rk, func.coalesce(func.sum(OrderRefund.amount), 0), func.coalesce(func.sum(OrderRefund.fee_reversed), 0),
                  func.coalesce(func.sum(OrderRefund.isr_reversed), 0),
                  func.coalesce(func.sum(OrderRefund.iva_reversed), 0)).join(Order, Order.id == OrderRefund.order_id).filter(
        OrderRefund.refuge_id.isnot(None), OrderRefund.created_at >= start, OrderRefund.created_at < end,
        Order.paid_at.isnot(None))
    dq = db.query(*dk, func.count(Donation.id), func.coalesce(func.sum(Donation.amount), 0),
                  func.coalesce(func.sum(Donation.fee_amount), 0),
                  func.coalesce(func.sum(Donation.amount).filter(Donation.payment_mode == "platform"), 0)).filter(
        Donation.status == "approved", donated_at >= start, donated_at < end)
    if refuge_id is not None:
        oq, rq, dq = (oq.filter(Order.refuge_id == refuge_id), rq.filter(OrderRefund.refuge_id == refuge_id),
                      dq.filter(Donation.refuge_id == refuge_id))
    for row in oq.group_by(*ok).all():
        rid, month, (n, gross, fee, isr, iva) = split(row, len(ok))
        s = slot(rid, month)["ventas"]
        s["casos"] += n
        s["bruto"] += Decimal(gross)
        s["comision"] += Decimal(fee)
        s["retenciones"] += Decimal(isr) + Decimal(iva)
    for row in rq.group_by(*rk).all():
        rid, month, (amount, fee, isr, iva) = split(row, len(rk))
        s = slot(rid, month)["ventas"]
        s["reembolsos"] += Decimal(amount)
        s["comision"] -= Decimal(fee)
        s["retenciones"] -= Decimal(isr) + Decimal(iva)
    for row in dq.group_by(*dk).all():
        rid, month, (n, gross, fee, via_platform) = split(row, len(dk))
        bucket = slot(rid, month)
        d = bucket["donativos"]
        d["casos"] += n
        d["bruto"] += Decimal(gross)
        d["comision"] += Decimal(fee)
        bucket["donativos_por_la_plataforma"] += Decimal(via_platform)
    for bucket in out.values():
        v, d = bucket["ventas"], bucket["donativos"]
        v["neto"] = v["bruto"] - v["reembolsos"] - v["comision"] - v["retenciones"]
        d["neto"] = d["bruto"] - d["comision"]
    return out


def _add_into(target: dict, source: dict) -> None:
    for key, value in source.items():
        target[key] += value


def refuge_meta(db: Session, ids) -> dict:
    """Datos públicos de cada Refugio y si sus cifras se pueden publicar con su nombre."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    rows = (db.query(Refuge.id, Refuge.name, Refuge.city, Refuge.status, Refuge.transparency_opt_in_at,
                     RefugeFiscalProfile.person_type, RefugeFiscalProfile.is_donataria)
            .outerjoin(RefugeFiscalProfile, RefugeFiscalProfile.refuge_id == Refuge.id)
            .filter(Refuge.id.in_(ids)).all())
    approved = dict(db.query(AdminAuditLog.target_id, func.max(AdminAuditLog.created_at)).filter(
        AdminAuditLog.action == "refuge.approve", AdminAuditLog.target_type == "refuge",
        AdminAuditLog.target_id.in_(ids)).group_by(AdminAuditLog.target_id).all())
    out = {}
    for rid, name, city, status, opt_in, person_type, donataria in rows:
        publishable = status == "approved" and (person_type == "moral" or opt_in is not None)
        out[rid] = {
            "id": rid, "nombre": name, "ciudad": city, "verificado": status == "approved",
            "verificado_desde": approved.get(rid).date().isoformat() if approved.get(rid) else None,
            "forma_juridica": {"moral": "Persona moral", "fisica": "Persona física"}.get(person_type),
            "donataria_autorizada": bool(donataria), "publica_con_nombre": publishable,
        }
    return out


MONEY_KINDS = ("donativos", "ventas")
# Lo que no se publica con nombre (Refugios sin consentimiento y rubros con menos de k operaciones) solo se publica,
# y solo se puede deducir de los totales, si suma al menos este número de Refugios (donativos-22: los montos de una
# persona física no deben poder despejarse restando)
MIN_REFUGES_IN_AGGREGATE = 3
SUPPRESSED_GROUP = {"suprimido": True, "casos": None, "motivo": "pocos_refugios"}


def _safe_rest(cases: int, refuges: int, k: int) -> bool:
    return cases >= k and refuges >= MIN_REFUGES_IN_AGGREGATE


def funds_section(db: Session, start, end, k: int, with_series: bool = False) -> dict:
    """Dinero por Refugio con supresión complementaria: «Otros Refugios» reúne, por rubro, todo lo que no se publica
    con nombre (también el rubro con menos de k operaciones de un Refugio con nombre), así que totales = filas con
    nombre + «Otros». Si «Otros» no es seguro (menos de k casos o de 3 Refugios), se suprimen él y el total de ese
    rubro: nada se despeja restando."""
    data = money_by_refuge(db, start, end)
    meta = refuge_meta(db, {rid for rid, _ in data})
    totals = {"ventas": _empty_sales(), "donativos": _empty_donations()}
    rest = {"ventas": _empty_sales(), "donativos": _empty_donations()}
    rest_refuges: dict[str, set] = {kind: set() for kind in MONEY_KINDS}
    platform_refuges: set = set()
    via_platform = ZERO
    rows, unnamed = [], set()
    for (rid, _), bucket in data.items():
        for kind in MONEY_KINDS:
            _add_into(totals[kind], bucket[kind])
        if bucket["donativos_por_la_plataforma"]:
            via_platform += bucket["donativos_por_la_plataforma"]
            platform_refuges.add(rid)
        info = meta.get(rid)
        enough = bucket["donativos"]["casos"] >= k or bucket["ventas"]["casos"] >= k
        named = bool(info and info["publica_con_nombre"] and enough)
        row = ({key: info[key] for key in ("id", "nombre", "ciudad", "verificado_desde", "forma_juridica",
                                           "donataria_autorizada")} if named else None)
        if not named:  # sin consentimiento (persona física) o con menos de k operaciones de cada tipo
            unnamed.add(rid)
        for kind in MONEY_KINDS:
            block = bucket[kind]
            if named and block["casos"] >= k:
                row[kind] = _block(block, k)
                continue
            if named:
                row[kind] = {"suprimido": True, "casos": None}
            if block["casos"]:
                _add_into(rest[kind], block)
                rest_refuges[kind].add(rid)
        if named:
            rows.append(row)
    rows.sort(key=lambda r: (r["nombre"] or "").lower())
    safe = {kind: _safe_rest(rest[kind]["casos"], len(rest_refuges[kind]), k) for kind in MONEY_KINDS}
    others = None
    if unnamed or any(rest_refuges.values()):
        others = {
            # Cuántos Refugios no aparecen con nombre: solo si son 3 o más (con 1 o 2 se les podría identificar)
            "refugios": len(unnamed) if len(unnamed) >= MIN_REFUGES_IN_AGGREGATE else None,
            "refugios_minimo": MIN_REFUGES_IN_AGGREGATE,
            **{kind: (_block(rest[kind], k) if safe[kind] else dict(SUPPRESSED_GROUP)) for kind in MONEY_KINDS},
        }
    out = {
        # Totales de la plataforma: se publican siempre (también en cero), salvo que con ellos se pudiera despejar
        # lo que no se publica con nombre
        "totales": {kind: (_block(totals[kind], 0) if not rest_refuges[kind] or safe[kind] else dict(SUPPRESSED_GROUP))
                    for kind in MONEY_KINDS},
        "refugios": rows,
        "otros_refugios": others,
        "comision_tienda_porcentaje": float(settings.mercadopago_marketplace_fee_percent),
        "comision_donativos_porcentaje": float(settings.mercadopago_donation_fee_percent),
        # Donativos que se cobraron con la cuenta de la plataforma (respaldo para Refugios sin Mercado Pago):
        # si es mayor que 0, GuauWoow sí recibió ese dinero y se lo debe al Refugio. Con 1 o 2 Refugios no se
        # publica la cifra (se sabría cuánto recibió cada uno)
        "donativos_cobrados_por_la_plataforma": (_money(via_platform) if not platform_refuges
                                                 or len(platform_refuges) >= MIN_REFUGES_IN_AGGREGATE else None),
    }
    if with_series:
        out["serie_mensual"] = monthly_series(db, start, end, k)
    return out


def _complementary(series: list[dict], kind: str, k: int, named: set | None) -> None:
    """Supresión complementaria de una serie mensual (el total del periodo sí se publica): lo suprimido junto debe
    sumar k casos o más, venir de 2 meses o más y, en la serie de la plataforma (named no es None), de 3 Refugios o
    más o solo de Refugios que publican con su nombre. Si no, se suprime también el mes publicado más pequeño."""
    def ok(hidden):
        cases = sum(m["_casos"][kind] for m in hidden)
        refuges = set().union(*(m["_refugios"][kind] for m in hidden))
        enough_refuges = named is None or len(refuges) >= MIN_REFUGES_IN_AGGREGATE or refuges <= named
        return len(hidden) >= 2 and cases >= k and enough_refuges

    hidden = [m for m in series if m[kind].get("suprimido") and m["_casos"][kind]]
    while hidden and not ok(hidden):
        visible = [m for m in series if not m[kind].get("suprimido") and m["_casos"][kind]]
        if not visible:
            return
        smallest = min(visible, key=lambda m: m["_casos"][kind])
        smallest[kind] = {"suprimido": True, "casos": None}
        hidden.append(smallest)


def monthly_series(db: Session, start, end, k: int, refuge_id: int | None = None) -> list[dict]:
    """Serie por mes. Un mes se publica si tiene k casos o más y, en la serie de toda la plataforma, si esos casos
    vienen de 3 Refugios o más o todos publican con su nombre; luego se aplica la supresión complementaria."""
    data = money_by_refuge(db, start, end, refuge_id=refuge_id, by_month=True)
    named = None
    if refuge_id is None:
        named = {rid for rid, info in refuge_meta(db, {rid for rid, _ in data}).items() if info["publica_con_nombre"]}
    months = {m: {"ventas": _empty_sales(), "donativos": _empty_donations(),
                  "_refugios": {kind: set() for kind in MONEY_KINDS}} for m in months_between(start, end)}
    for (rid, month), bucket in data.items():
        if month in months:
            for kind in MONEY_KINDS:
                _add_into(months[month][kind], bucket[kind])
                if bucket[kind]["casos"]:
                    months[month]["_refugios"][kind].add(rid)
    series = []
    for m, v in sorted(months.items()):
        item = {"mes": m, "_casos": {kind: v[kind]["casos"] for kind in MONEY_KINDS}, "_refugios": v["_refugios"]}
        for kind in MONEY_KINDS:
            refuges = v["_refugios"][kind]
            if not v[kind]["casos"]:
                item[kind] = {"casos": 0}
            elif named is not None and len(refuges) < MIN_REFUGES_IN_AGGREGATE and not refuges <= named:
                item[kind] = {"suprimido": True, "casos": None}
            else:
                item[kind] = _block(v[kind], k)
        series.append(item)
    for kind in MONEY_KINDS:
        _complementary(series, kind, k, named)
    for item in series:
        item.pop("_casos")
        item.pop("_refugios")
    return series


# --------------------------------------------------------------------------- otras secciones
def _reason_labels() -> dict:
    """Catálogo de motivos de reporte (services/legal_moderation.REASONS) con respaldo local."""
    try:
        from app.services.legal_moderation import REASONS

        return {**REASON_LABELS, **REASONS}
    except ImportError:
        return REASON_LABELS


def _hold_labels() -> tuple[str, str]:
    """Motivo de ContentReport de las retenciones automáticas y la etiqueta de «menciona cobros o venta»."""
    try:
        from app.services.reglas import HOLD_LABELS, HOLD_REPORT_REASON

        return HOLD_REPORT_REASON, HOLD_LABELS.get("cobro_adopcion", "Menciona cobros o venta")
    except ImportError:  # el módulo de reglas aún no existe
        return "retencion_automatica", "Menciona cobros o venta"


def moderation_section(db: Session, start, end, k: int) -> dict:
    """Reportes recibidos por motivo y resultado, medidas por cómo se detectaron, retenciones por pedir dinero,
    suspensiones y apelaciones (moderacion.html; informe-transparencia §3)."""
    from app import models
    from app.services.facebook_groups import AUTHOR_REMOVAL_REASON

    hold_reason, money_label = _hold_labels()
    in_range = (ContentReport.created_at >= start, ContentReport.created_at < end)
    reports = db.query(ContentReport).filter(*in_range, ContentReport.reason.notin_((AUTHOR_REMOVAL_REASON, hold_reason)))
    by_reason: dict[str, int] = {}
    results = {"abiertos": 0, "atendidos": 0, "descartados": 0}
    total = 0
    for reason, st, n in (reports.with_entities(ContentReport.reason, ContentReport.status, func.count(ContentReport.id))
                          .group_by(ContentReport.reason, ContentReport.status).all()):
        total += n
        by_reason[reason] = by_reason.get(reason, 0) + n
        results[{"resolved": "atendidos", "dismissed": "descartados"}.get(st, "abiertos")] += n
    seconds = reports.filter(ContentReport.resolved_at.isnot(None)).with_entities(
        func.avg(func.extract("epoch", ContentReport.resolved_at - ContentReport.created_at))).scalar()
    # Retenciones del filtro automático (fichas que piden dinero, rifas, productos prohibidos)
    holds = db.query(ContentReport).filter(*in_range, ContentReport.reason == hold_reason)
    money_holds = holds.filter(ContentReport.details.like(f"{money_label}%"))
    money_rejected = money_holds.filter(ContentReport.status == "resolved", ContentReport.action == "hide_content").count()
    out = {
        "reportes_recibidos": total, "por_motivo": _collapse(by_reason, _reason_labels(), k), "resultados": results,
        "tiempo_medio_de_atencion_horas": round(float(seconds) / 3600, 1) if seconds else None,
        "retenidas_por_el_filtro_automatico": holds.count(), "retenidas_por_pedir_dinero": money_holds.count(),
        "cuentas_suspendidas": db.query(func.count(User.id)).filter(User.suspended_at >= start,
                                                                    User.suspended_at < end).scalar() or 0,
    }
    actions_model = getattr(models, "ModerationAction", None)
    removed_for_money = money_rejected
    if actions_model is not None:
        rows = (db.query(actions_model.action, actions_model.detection, actions_model.rule, func.count(actions_model.id))
                .filter(actions_model.created_at >= start, actions_model.created_at < end)
                .group_by(actions_model.action, actions_model.detection, actions_model.rule).all())
        by_detection: dict[str, int] = {}
        by_rule: dict[str, int] = {}
        counts = {"hide_content": 0, "suspend_user": 0, "cancel_account": 0, "copyright_removal": 0, "quarantine": 0}
        for action, detection, rule, n in rows:
            counts[action] = counts.get(action, 0) + n
            if action in ("hide_content", "copyright_removal", "quarantine"):
                by_detection[detection] = by_detection.get(detection, 0) + n
                by_rule[rule] = by_rule.get(rule, 0) + n
                if MONEY_REASON_RE.search(rule or ""):
                    removed_for_money += n
        out.update({
            "contenidos_retirados": counts["hide_content"] + counts["copyright_removal"] + counts["quarantine"],
            "retirados_por_categoria": _collapse(by_rule, _reason_labels(), k),
            "retirados_por_deteccion": _collapse(by_detection, DETECTION_LABELS, k),
            "suspensiones": counts["suspend_user"], "cuentas_canceladas": counts["cancel_account"],
        })
    else:
        out["contenidos_retirados"] = reports.filter(ContentReport.action == "hide_content").count() + money_rejected
    out["retirados_por_venta_o_cobro"] = removed_for_money
    appeals_model = getattr(models, "ModerationAppeal", None)
    if appeals_model is not None:
        rows = dict(db.query(appeals_model.status, func.count(appeals_model.id)).filter(
            appeals_model.created_at >= start, appeals_model.created_at < end).group_by(appeals_model.status).all())
        decided = rows.get("upheld", 0) + rows.get("reversed", 0)
        out["apelaciones"] = {"recibidas": sum(rows.values()), "resueltas": decided,
                              "decisiones_revertidas": rows.get("reversed", 0),
                              "porcentaje_revertidas": round(100 * rows.get("reversed", 0) / decided, 1) if decided else None}
    return out


def privacy_section(db: Session, start, end, k: int) -> dict:
    stats = sol.arco_stats(db, start, end)
    return {
        "recibidas": stats["recibidas"], "por_tipo": _collapse(stats["por_tipo"], sol.KIND_LABELS, k),
        "respondidas": stats["respondidas"], "respondidas_en_20_dias_habiles": stats["respondidas_a_tiempo"],
        "porcentaje_en_plazo": stats["porcentaje_a_tiempo"], "ampliaciones": stats["ampliaciones"],
        "negativas_por_causa": _collapse(stats["negativas_por_causa"], DENIAL_LABELS, k),
        "revocaciones": stats["revocaciones"],
    }


def imported_section(db: Session, start, end) -> dict:
    from app.services.facebook_groups import AUTHOR_REMOVAL_REASON, IMPORTED_SOURCES

    created = dict(db.query(LostReport.source, func.count(LostReport.id)).filter(
        LostReport.source.in_(IMPORTED_SOURCES), LostReport.created_at >= start, LostReport.created_at < end)
        .group_by(LostReport.source).all())
    removal_targets = db.query(ContentReport.target_id).filter(
        ContentReport.target_type == "lost_report", ContentReport.reason == AUTHOR_REMOVAL_REASON)
    removed = db.query(func.count(func.distinct(ContentReport.target_id))).filter(
        ContentReport.target_type == "lost_report", ContentReport.reason == AUTHOR_REMOVAL_REASON,
        ContentReport.status != "dismissed", ContentReport.created_at >= start, ContentReport.created_at < end).scalar() or 0
    expired = db.query(func.count(LostReport.id)).filter(
        LostReport.source.in_(IMPORTED_SOURCES), LostReport.purged_at >= start, LostReport.purged_at < end,
        LostReport.id.notin_(removal_targets)).scalar() or 0
    fetched, saved = db.query(func.coalesce(func.sum(FacebookGroup.posts_fetched_total), 0),
                              func.coalesce(func.sum(FacebookGroup.reports_created_total), 0)).one()
    return {
        "importacion_activa": bool(settings.fb_groups_enabled),
        "importadas_de_grupos": created.get("facebook", 0), "enviadas_por_voluntarios": created.get("volunteer", 0),
        "caducadas_y_borradas": expired, "retiradas_a_peticion": removed,
        # Contadores de los grupos: no se guardan por fecha, por eso es el acumulado desde el inicio
        "leidas_y_no_guardadas_acumulado": max(0, int(fetched) - int(saved)),
    }


def verified_section(db: Session) -> dict:
    refuges = db.query(func.count(Refuge.id)).filter(Refuge.status == "approved").scalar() or 0
    clinics = db.query(func.count(Veterinary.id)).filter(Veterinary.status == "verified",
                                                         Veterinary.is_hidden == False).scalar() or 0  # noqa: E712
    return {"refugios_verificados": refuges, "clinicas_verificadas": clinics}


AUTHORITY_RESULTS = {"entregado": "atendidas", "entregado_parcial": "atendidas_parcialmente", "rechazado": "rechazadas",
                     "cerrado": "cerradas"}
AUTHORITY_LABELS = {"atendidas": "Atendidas en su totalidad", "atendidas_parcialmente": "Atendidas parcialmente",
                    "rechazadas": "Rechazadas", "cerradas": "Cerradas sin entrega", "en_tramite": "En trámite"}


def authorities_section(db: Session, start, end, k: int) -> dict:
    """Requerimientos de autoridad recibidos y cómo se atendieron, y denuncias o alertas que presentamos
    (registro AuthorityRequest, autoridades.html)."""
    from app import models

    model = getattr(models, "AuthorityRequest", None)
    if model is None:
        return {"disponible": False, "recibidas": None, "por_resultado": [], "alertas_y_denuncias_enviadas": None}
    cols = model.__table__.columns
    date_col = cols["received_at"] if "received_at" in cols else cols["created_at"]
    base = db.query(model).filter(date_col >= start, date_col < end)
    incoming = base.filter(cols["direction"] == "entrante") if "direction" in cols else base
    groups: dict[str, int] = {}
    for st, n in incoming.with_entities(cols["status"], func.count()).group_by(cols["status"]).all():
        key = AUTHORITY_RESULTS.get(st, "en_tramite")
        groups[key] = groups.get(key, 0) + n
    sent = None
    if "direction" in cols:
        sent = base.filter(cols["direction"] == "saliente", cols["status"] == "denunciado").count()
    return {"disponible": True, "recibidas": sum(groups.values()), "por_resultado": _collapse(groups, AUTHORITY_LABELS, k),
            "alertas_y_denuncias_enviadas": sent}


# --------------------------------------------------------------------------- endpoints
def build_report(db: Session, periodo: str | None, vista: str, now: datetime.datetime | None = None) -> dict:
    now = now or datetime.datetime.utcnow()
    label, start, end = period_range(periodo, now)
    k = _min_cases()
    out = {
        "vista": vista, "periodo": label, "desde": start, "hasta": min(end, now), "calculado_en": now, "umbral": k,
        "fondos": funds_section(db, start, end, k, with_series=vista == "fondos"),
    }
    if vista == "general":
        out.update({
            "moderacion": moderation_section(db, start, end, k),
            "privacidad": privacy_section(db, start, end, k),
            "importados": imported_section(db, start, end),
            "verificados": verified_section(db),
            "autoridades": authorities_section(db, start, end, k),
        })
    return out


@router.get("/cumplimiento/transparencia")
def transparency(periodo: str | None = Query("12m", max_length=7), vista: str = Query("general", max_length=10),
                 db: Session = Depends(get_db)):
    """Cifras agregadas del informe de transparencia (caché 1 h; `calculado_en` dice de cuándo son)."""
    if vista not in ("general", "fondos"):
        raise HTTPException(status_code=400, detail="La vista debe ser general o fondos.")
    label = period_range(periodo)[0]  # valida antes de buscar en caché
    key = cache.make_key(CACHE_NS, vista=vista, periodo=label, k=_min_cases())
    cached = cache.get(key)
    if cached is not None:
        return cached
    from fastapi.encoders import jsonable_encoder

    data = jsonable_encoder(build_report(db, label, vista))
    cache.set(key, data, ttl=CACHE_TTL)
    return data


def refuge_report(db: Session, refuge_id: int, now: datetime.datetime | None = None) -> dict:
    now = now or datetime.datetime.utcnow()
    refuge = db.get(Refuge, refuge_id)
    if refuge is None or refuge.status != "approved":
        raise HTTPException(status_code=404, detail="No encontramos ese Refugio verificado.")
    _, start, end = period_range("12m", now)
    info = refuge_meta(db, [refuge.id])[refuge.id]
    account = refuge.payment_account
    base = {key: info[key] for key in ("id", "nombre", "ciudad", "verificado_desde", "forma_juridica",
                                       "donataria_autorizada")}
    base["cobra_con_su_cuenta_de_mercado_pago"] = bool(account and account.status == "connected")
    k = _min_cases()
    out = {"refugio": base, "periodo": "12m", "desde": start, "hasta": min(end, now), "calculado_en": now, "umbral": k,
           "publicado": info["publica_con_nombre"],
           "comision_tienda_porcentaje": float(settings.mercadopago_marketplace_fee_percent),
           "comision_donativos_porcentaje": float(settings.mercadopago_donation_fee_percent)}
    if not info["publica_con_nombre"]:
        out["mensaje"] = ("Este Refugio todavía no aceptó publicar sus cifras con su nombre. Sus donativos y ventas "
                          "están sumados en «Otros Refugios» del tablero general.")
        return out
    data = money_by_refuge(db, start, end, refuge_id=refuge.id)
    totals = {"ventas": _empty_sales(), "donativos": _empty_donations()}
    for bucket in data.values():
        _add_into(totals["ventas"], bucket["ventas"])
        _add_into(totals["donativos"], bucket["donativos"])
    out["totales"] = {"donativos": _block(totals["donativos"], k), "ventas": _block(totals["ventas"], k)}
    out["serie_mensual"] = monthly_series(db, start, end, k, refuge_id=refuge.id)
    return out


@router.get("/cumplimiento/transparencia/refugios/{refuge_id}")
def transparency_refuge(refuge_id: int, db: Session = Depends(get_db)):
    """«A dónde va tu dinero» de un Refugio: donativos y ventas de los últimos 12 meses (bruto, comisiones y neto)."""
    key = cache.make_key(CACHE_NS, refugio=refuge_id, k=_min_cases())
    cached = cache.get(key)
    if cached is not None:
        return cached
    from fastapi.encoders import jsonable_encoder

    data = jsonable_encoder(refuge_report(db, refuge_id))
    cache.set(key, data, ttl=CACHE_TTL)
    return data


def _my_refuge(db: Session, user: User) -> Refuge:
    refuge = db.query(Refuge).filter(Refuge.user_id == user.id).order_by(Refuge.id).first()
    if refuge is None:
        raise HTTPException(status_code=404, detail="No tienes un Refugio registrado.")
    return refuge


def _opt_in_out(refuge: Refuge) -> dict:
    person_type = refuge.fiscal_profile.person_type if refuge.fiscal_profile else None
    return {"refugio_id": refuge.id, "publicar": refuge.transparency_opt_in_at is not None,
            "desde": refuge.transparency_opt_in_at, "forma_juridica": person_type,
            # Una persona moral aparece con su nombre sin necesidad de aceptar (no son datos personales)
            "requiere_consentimiento": person_type != "moral"}


@router.get("/cumplimiento/transparencia/mi-refugio")
def my_refuge_transparency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _opt_in_out(_my_refuge(db, current_user))


@router.post("/cumplimiento/transparencia/mi-refugio")
def set_my_refuge_transparency(payload: TransparenciaOptIn, current_user: User = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    """El Refugio acepta (o retira) que sus cifras agregadas aparezcan con su nombre en el informe de transparencia."""
    refuge = _my_refuge(db, current_user)
    now = datetime.datetime.utcnow()
    if payload.publicar and refuge.transparency_opt_in_at is None:
        refuge.transparency_opt_in_at = now
    elif not payload.publicar:
        refuge.transparency_opt_in_at = None
    from app import models

    consent = getattr(models, "ConsentRecord", None)  # bitácora de consentimientos (contrato K-PREF), si existe
    if consent is not None:
        cols = set(consent.__table__.columns.keys())
        values = {"user_id": current_user.id, "purpose": "transparencia_refugio", "granted": bool(payload.publicar),
                  "channel": "app", "text_version": settings.legal_privacy_version, "created_at": now}
        db.add(consent(**{k: v for k, v in values.items() if k in cols}))
    db.commit()
    db.refresh(refuge)
    cache.bump(CACHE_NS)
    return _opt_in_out(refuge)
