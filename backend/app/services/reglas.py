"""Reglas de negocio con efecto legal: lo que prometen las páginas del centro legal, en un solo lugar.

Adopción (adopcion-responsable, cero-venta, perdidos-y-encontrados; contrato L-adopcion):
- Las fichas de adopción que mencionan cobros o venta (cuota, costo, precio, $, donativo sugerido, apartado,
  recuperación, venta, depósito) o rifas y animales como premio se RETIENEN para revisión humana: se ocultan,
  se le explica el motivo a quien publica y entran a la cola de moderación (ContentReport "retencion_automatica").
- Un perro encontrado (ligado a un reporte de «encontrado» o declarado como encontrado) no puede ofrecerse en
  adopción antes de FOUND_DOG_HOLD_DAYS días naturales, con el microchip revisado y aviso a la autoridad local.
Tienda (productos-prohibidos, terminos-tienda, envios-devoluciones-garantias; contrato L-tienda):
- Categoría y garantía obligatorias (consumidor-ecommerce-04 y 12); garantía de 90 días o más si se ofrece.
- Lista de productos prohibidos: categoría + palabras clave; lo que coincide se retiene para revisión.
- Bonificación de 20 % (LFPC arts. 92 y 92 Ter) cuando procede una reclamación por defecto o porque el producto no
  corresponde: obligación del refugio vendedor, registrada en el pedido, con seguimiento del equipo.
- Comprobante del pedido con los datos que pide la LFPC (art. 76 Bis; consumidor-ecommerce-07).
- Recordatorio a los refugios de las facturas (CFDI) pedidas hace más de 24 h (terminos-tienda 8.2).
Donativos (donativos, prevencion-lavado; contrato L-donativos):
- Sin puntos de ranking, sin autodonaciones, tope por donativo y tope diario por cuenta, aviso de no deducible y
  alertas de la ley antilavado (acumulado de 6 meses por donante y refugio contra el umbral de 1,605 UMA).
Facebook (contenido-importado; contrato L-fb): etiqueta del contenido importado.
"""
import datetime
import logging
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    ContentReport, Dog, Donation, DonationAmlFlag, LostReport, Order, OrderBonus, OrderInvoice, Product, Refuge, User,
)
from app.services.audit import record_admin_action
from app.utils.notifications import create_notification

logger = logging.getLogger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")
CENT = Decimal("0.01")
ADMIN_ROLES = ("admin", "superadmin")

# --------------------------------------------------------------------------- texto
# Letras de otros alfabetos que se ven iguales a las latinas («cuоta» con o cirílica) y caracteres invisibles: se
# llevan a su «esqueleto» latino antes de buscar, para que no se evada el filtro con letras parecidas
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "к": "k", "м": "m", "т": "t", "н": "h",
    "в": "b", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "l", "һ": "h", "ԛ": "q", "ԝ": "w", "ү": "y", "ɡ": "g",
    "А": "a", "Е": "e", "О": "o", "Р": "p", "С": "c", "У": "y", "Х": "x", "К": "k", "М": "m", "Т": "t", "Н": "h",
    "В": "b", "І": "i", "Ј": "j", "Ѕ": "s",
    "α": "a", "ε": "e", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ι": "i", "κ": "k", "ν": "v", "μ": "u",
    "Α": "a", "Ε": "e", "Ο": "o", "Ρ": "p", "Τ": "t", "Υ": "y", "Χ": "x", "Ι": "i", "Κ": "k", "Ν": "n", "Μ": "m",
    "Β": "b", "Η": "h", "Ζ": "z",
    "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "", "\ufeff": "", "\u00ad": "",
})
# Números escritos entre letras para evadir («c0sto», «cu0ta»)
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a"}
_LEET_RE = re.compile(r"(?<=[a-z])[0134578@](?=[a-z])")


def _nfkc(text: str | None) -> str:
    """NFKC (el «＄» de ancho completo pasa a «$» y los dígitos a ASCII) y esqueleto de letras parecidas."""
    return unicodedata.normalize("NFKC", text or "").translate(_CONFUSABLES)


def _norm(text: str | None) -> str:
    """Minúsculas, sin acentos, con NFKC y letras parecidas llevadas a las latinas (las palabras se buscan igual con
    o sin tilde y con letras de otros alfabetos)."""
    plain = unicodedata.normalize("NFKD", _nfkc(text)).encode("ascii", "ignore").decode().lower()
    return _LEET_RE.sub(lambda m: _LEET.get(m.group(0), m.group(0)), plain)


def _matches(patterns, *texts) -> list[str]:
    joined = _nfkc("\n".join(t for t in texts if t))
    norm = _norm(joined)
    found = []
    for label, regex in patterns:
        if regex.search(norm) or (label == "$" and "$" in joined):
            found.append(label)
    return sorted(set(found))


def _re(pattern: str) -> re.Pattern:
    return re.compile(pattern)


# --------------------------------------------------------------------------- retenciones para revisión humana
HOLD_REPORT_REASON = "retencion_automatica"  # motivo de ContentReport (sin reportante: lo crea el sistema)
HOLD_RELEASED = "liberado"
HOLD_REJECTED = "rechazado"
HOLD_LABELS = {
    "cobro_adopcion": "Menciona cobros o venta",
    "rifa": "Menciona rifas, sorteos o premios",
    "producto_prohibido": "Coincide con la lista de productos prohibidos",
    "categoria_con_requisitos": "Categoría que se revisa antes de publicarse",
    "reedicion": "Se editó después de un rechazo",
}

_NUMBER_WORDS = ("un|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|veinte|veinticinco|"
                 "treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa|cien|ciento|doscientos|trescientos|"
                 "cuatrocientos|quinientos|seiscientos|setecientos|ochocientos|novecientos|mil")
# Montos: un número junto a $ o a pesos (o escrito con letra). Se guardan con las palabras detectadas para que una
# edición que agrega o cambia un monto vuelva a revisión aunque las palabras ya se hubieran aprobado
_AMOUNT_RE = re.compile(r"\$\s*(\d[\d.,]*)|(\d[\d.,]*)\s*(?:pesos|pesitos|mxn|varos|baros|lucas)\b"
                        r"|\b((?:(?:" + _NUMBER_WORDS + r")\s+(?:y\s+)?)*(?:" + _NUMBER_WORDS + r"))\s+"
                        r"(?:pesos|pesitos|varos|baros|lucas|mxn)\b"
                        r"|\b(?:cooperacion|aportacion|ayuda|donativo|donacion|cuota|apoyo)\s+(?:de\s+|por\s+)?"
                        r"\$?\s*(\d[\d.,]*)")
AMOUNT_PREFIX = "monto "


def money_amounts(*texts) -> list[str]:
    """Montos de dinero que menciona el texto («monto 500», «monto quinientos»), sin repetir."""
    joined = _nfkc("\n".join(t for t in texts if t))
    plain = unicodedata.normalize("NFKD", joined).encode("ascii", "ignore").decode().lower()
    plain = _LEET_RE.sub(lambda m: _LEET.get(m.group(0), m.group(0)), plain)
    out = set()
    for m in _AMOUNT_RE.finditer(plain):
        value = next((g for g in m.groups() if g), "")
        value = re.sub(r"[.,](?=\d{3}\b)", "", value).strip(".,")  # 1,500 -> 1500
        if value:
            out.add(AMOUNT_PREFIX + " ".join(value.split()))
    return sorted(out)


# Fichas de adopción (contrato L-adopcion): palabras de cobro o venta
ADOPTION_FEE_PATTERNS = [
    ("cuota", _re(r"\bcuotas?\b")),
    ("costo", _re(r"\bcostos?\b")),
    ("precio", _re(r"\bprecios?\b")),
    ("$", _re(r"(?!x)x")),  # el signo de pesos se busca en el texto original (ver _matches)
    ("donativo sugerido", _re(r"\b(donativo|donacion|aportacion|cooperacion)\s+(sugerid[oa]|voluntari[oa]|minim[oa])\b")),
    ("apartado", _re(r"\b(apartad[oa]s?|apartar(lo|la|los|las)?|se aparta[n]?|apartalo|apartala)\b")),
    ("recuperación", _re(r"\brecuperacion\b")),
    ("venta", _re(r"\b(ventas?|vendo|vende[n]?|vender(lo|la|los|las)?|vendemos|se venden?|a la venta)\b")),
    ("depósito", _re(r"\b(deposit(o|ar|en|as)|transferencia|anticipo)\b")),
    ("pesos", _re(r"\d\s*(pesos|pesitos|mxn|varos|baros|lucas)\b|\bpesitos\b")),
    # «cooperación de 300», «aportación $500», «ayuda de 200»: piden un monto aunque no digan «sugerido»
    ("cooperación con monto", _re(r"\b(cooperacion|aportacion|ayuda|donativo|donacion|cuota|apoyo)\s+(de\s+|por\s+)?"
                                  r"(\$\s*)?\d")),
    ("monto en palabras", _re(r"\b(" + _NUMBER_WORDS + r")(\s+(y\s+)?(" + _NUMBER_WORDS + r"))*\s+"
                              r"(pesos|pesitos|varos|baros|lucas|mxn)\b")),
]
# Rifas, sorteos y animales como premio (LFJS arts. 3 y 4; LPBA CDMX art. 25 fr. III)
RAFFLE_PATTERNS = [
    ("rifa", _re(r"\b(rifas?|rifamos|rifar(lo|la)?|rifare)\b")),
    ("sorteo", _re(r"\b(sorteos?|sorteamos|sortear(lo|la)?)\b")),
    ("boletos", _re(r"\bboletos?\b")),
    ("lotería", _re(r"\bloteria\b")),
    ("premio", _re(r"\b(premios?|como premio|de premio|al ganador|la ganadora|el ganador|gana un perr\w*|adopta y gana)\b")),
]
HOLD_ADOPTION_MESSAGE = (
    "Tu publicación quedó en revisión porque menciona cobros o venta ({terms}). En GuauWoow adoptar es gratis: "
    "no se piden cuotas, «donativos sugeridos», apartados ni depósitos por un perro. Un moderador la revisa (a más "
    "tardar en {days} días hábiles) y, si no pide dinero, la publicamos tal cual. Si quieres contar gastos "
    "veterinarios, descríbelos sin pedir dinero."
)
HOLD_RAFFLE_MESSAGE = (
    "Tu publicación quedó en revisión porque menciona rifas, sorteos o premios ({terms}). En GuauWoow no se "
    "permiten rifas ni usar animales como premio. Un moderador la revisa y, si es un error, la publicamos tal cual."
)


def adoption_terms(*texts) -> tuple[str | None, list[str]]:
    """(motivo, palabras) de una ficha de adopción; (None, []) si no menciona cobros ni rifas."""
    raffle = _matches(RAFFLE_PATTERNS, *texts)
    fee = _matches(ADOPTION_FEE_PATTERNS, *texts)
    amounts = money_amounts(*texts) if (fee or raffle) else []
    if raffle:
        return "rifa", sorted(set(raffle + fee + amounts))
    if fee:
        return "cobro_adopcion", sorted(set(fee + amounts))
    return None, []


def dog_texts(obj) -> tuple:
    get = (lambda k: obj.get(k)) if isinstance(obj, dict) else (lambda k: getattr(obj, k, None))
    return tuple(get(k) for k in ("name", "breed", "color", "description"))


def hold_message(reason: str | None, terms: list[str]) -> str | None:
    if not reason:
        return None
    shown = ", ".join(f"«{t}»" for t in terms if not t.startswith(AMOUNT_PREFIX)) if terms else ""
    if reason == "cobro_adopcion":
        return HOLD_ADOPTION_MESSAGE.format(terms=shown, days=settings.moderation_review_business_days)
    if reason == "rifa":
        return HOLD_RAFFLE_MESSAGE.format(terms=shown)
    if reason == "producto_prohibido":
        return PRODUCT_HOLD_MESSAGE.format(terms=shown)
    if reason == "categoria_con_requisitos":
        return PRODUCT_CATEGORY_MESSAGE
    if reason == "reedicion":
        return "Editaste una publicación que el equipo había rechazado: queda en revisión hasta que la revisemos de nuevo."
    return "Tu publicación quedó en revisión."


def review_status(obj) -> str | None:
    """"en_revision" | "rechazado" | None (publicada). Solo cuenta mientras siga oculta."""
    hold = getattr(obj, "review_hold", None)
    if not hold or hold == HOLD_RELEASED or not getattr(obj, "is_hidden", False):
        return None
    return "rechazado" if hold == HOLD_REJECTED else "en_revision"


def review_info(obj) -> dict | None:
    status = review_status(obj)
    if not status:
        return None
    terms = list(getattr(obj, "review_terms", None) or [])
    reason = obj.review_hold if status == "en_revision" else None
    message = hold_message(reason, terms) if reason else (
        "El equipo revisó esta publicación y no la aprobó. Si la corriges, vuelve a revisión.")
    return {"status": status, "reason": reason, "label": HOLD_LABELS.get(reason or "", "Rechazada"), "terms": terms,
            "message": message, "since": getattr(obj, "review_hold_at", None)}


def _owner_of(db: Session, target_type: str, obj) -> User | None:
    if target_type == "dog":
        uid = obj.owner_id
    elif target_type == "product":
        refuge = obj.refuge or db.query(Refuge).filter(Refuge.id == obj.refuge_id).first()
        uid = refuge.user_id if refuge else None
    else:
        uid = getattr(obj, "reporter_id", None)
    return db.query(User).filter(User.id == uid).first() if uid else None


def _target_url(target_type: str, obj) -> str:
    return {"dog": f"/app/?dog={obj.id}", "product": "/app/?shop=productos"}.get(target_type, "/app/")


def _alert_admins(db: Session, kind: str, title: str, body: str, data: dict) -> None:
    admins = db.query(User.id).filter(User.role.in_(ADMIN_ROLES), User.is_active == True)  # noqa: E712
    for (uid,) in admins.order_by(User.id.desc()).limit(100):
        create_notification(db, user_id=uid, type=kind, title=title, body=body, data=data, commit=False)


def apply_hold(db: Session, target_type: str, obj, reason: str, terms: list[str]) -> dict:
    """Oculta el contenido, lo manda a la cola de moderación y avisa a quien lo publicó (sin commit)."""
    now = datetime.datetime.utcnow()
    obj.is_hidden = True
    obj.review_hold = reason
    obj.review_terms = list(terms or [])
    obj.review_hold_at = now
    db.flush()
    message = hold_message(reason, terms)
    details = f"{HOLD_LABELS.get(reason, reason)}." + (f" Palabras: {', '.join(terms)}." if terms else "")
    report = db.query(ContentReport).filter(
        ContentReport.target_type == target_type, ContentReport.target_id == obj.id,
        ContentReport.reason == HOLD_REPORT_REASON, ContentReport.status == "open").first()
    if report:
        report.details = details[:1000]
    else:
        report = ContentReport(reporter_id=None, target_type=target_type, target_id=obj.id, reason=HOLD_REPORT_REASON,
                               details=details[:1000], status="open")
        db.add(report)
    # Plazo de la promesa de HOLD_ADOPTION_MESSAGE: entra a la cola con su prioridad («Estafas y venta» si pide
    # dinero o es una rifa) y su vencimiento, para que la cola lo marque como vencido si nadie lo revisa
    from app.services import legal_moderation as lm

    report.priority = 2 if reason in ("cobro_adopcion", "rifa") else 3
    report.due_at = report.due_at or lm.add_business_days(now, settings.moderation_review_business_days)
    title = getattr(obj, "name", None) or f"#{obj.id}"
    _alert_admins(db, "moderation_alert", "Publicación retenida para revisión 🔎",
                  f"«{title}» ({target_type}) quedó retenida: {details} Revísala en el panel (Reglas > Retenciones).",
                  {"target_type": target_type, "target_id": obj.id, "reason": reason})
    owner = _owner_of(db, target_type, obj)
    if owner and owner.is_active:
        from app.services.notify import notify_user

        notify_user(db, owner, "content_held", "Tu publicación está en revisión", message,
                    url=_target_url(target_type, obj), email=True,
                    data={"target_type": target_type, "target_id": obj.id, "reason": reason}, commit=False)
    return review_info(obj) or {}


def check_hold(db: Session, target_type: str, obj, reason: str | None, terms: list[str], *, force: bool = False) -> dict | None:
    """Aplica la retención si hace falta. Las palabras que el equipo ya aprobó (liberado) no vuelven a retener;
    editar algo rechazado lo regresa a revisión. Devuelve review_info o None (sin commit)."""
    previous = getattr(obj, "review_hold", None)
    if previous == HOLD_REJECTED and getattr(obj, "is_hidden", False):
        return apply_hold(db, target_type, obj, reason or "reedicion", terms)
    approved = set(getattr(obj, "review_terms", None) or []) if previous == HOLD_RELEASED else set()
    new_terms = [t for t in terms if t not in approved]
    currently_held = review_status(obj) == "en_revision"
    if reason and (new_terms or force or currently_held):
        return apply_hold(db, target_type, obj, reason, terms)
    return review_info(obj)


def _resolve_hold_reports(db: Session, target_type: str, obj, admin: User, status: str, action: str | None,
                          notes: str | None) -> list[int]:
    now = datetime.datetime.utcnow()
    rows = db.query(ContentReport).filter(
        ContentReport.target_type == target_type, ContentReport.target_id == obj.id,
        ContentReport.reason == HOLD_REPORT_REASON, ContentReport.status == "open").all()
    for r in rows:
        r.status, r.action, r.admin_notes, r.resolved_by, r.resolved_at = status, action, notes, admin.id, now
    return [r.id for r in rows]


def load_hold_target(db: Session, target_type: str, target_id: int):
    model = {"dog": Dog, "product": Product}.get(target_type)
    if model is None:
        raise HTTPException(status_code=400, detail="Solo se retienen perros en adopción y productos.")
    obj = db.query(model).filter(model.id == target_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="No encontramos esa publicación.")
    return obj


def decide_hold(db: Session, target_type: str, target_id: int, admin: User, decision: str, notes: str | None,
                request: Request | None = None) -> dict:
    """liberar: se publica y sus palabras quedan aprobadas; rechazar: sigue oculta y se avisa el motivo."""
    obj = load_hold_target(db, target_type, target_id)
    if not obj.review_hold or obj.review_hold == HOLD_RELEASED:
        raise HTTPException(status_code=409, detail="Esta publicación no está retenida.")
    notes = " ".join((notes or "").split())[:1000] or None
    if decision == "rechazar" and (not notes or len(notes) < 10):
        raise HTTPException(status_code=400, detail="Explica el motivo del rechazo (mínimo 10 caracteres): se le "
                                                    "muestra a quien publicó.")
    owner = _owner_of(db, target_type, obj)
    title = getattr(obj, "name", None) or f"#{obj.id}"
    previous = obj.review_hold
    if decision == "liberar":
        obj.is_hidden = False
        obj.review_hold = HOLD_RELEASED
        reports = _resolve_hold_reports(db, target_type, obj, admin, "dismissed", None, notes)
        body = f"Revisamos «{title}» y ya está publicada. Gracias por tu paciencia."
        kind, head = "content_released", "Tu publicación ya está visible"
    elif decision == "rechazar":
        hold_report = db.query(ContentReport).filter(
            ContentReport.target_type == target_type, ContentReport.target_id == obj.id,
            ContentReport.reason == HOLD_REPORT_REASON, ContentReport.status == "open").order_by(ContentReport.id).first()
        obj.is_hidden = True
        obj.review_hold = HOLD_REJECTED
        reports = _resolve_hold_reports(db, target_type, obj, admin, "resolved", "hide_content", notes)
        action = _record_rejection(db, target_type, obj, owner, admin, previous, notes, hold_report)
        record_admin_action(db, admin, f"hold.{decision}", target_type, obj.id, request=request,
                            details={"from": previous, "terms": obj.review_terms, "notes": notes, "reports": reports,
                                     "moderation_action": action.folio})
        db.commit()  # el aviso con la regla, el origen, el folio MOD y cómo apelar lo manda record_action
        return held_row(db, target_type, obj)
    else:
        raise HTTPException(status_code=400, detail="La decisión debe ser «liberar» o «rechazar».")
    record_admin_action(db, admin, f"hold.{decision}", target_type, obj.id, request=request,
                        details={"from": previous, "terms": obj.review_terms, "notes": notes, "reports": reports})
    if owner and owner.is_active:
        from app.services.notify import notify_user

        notify_user(db, owner, kind, head, body, url=_target_url(target_type, obj), email=True,
                    data={"target_type": target_type, "target_id": obj.id}, commit=False)
    db.commit()
    return held_row(db, target_type, obj)


HOLD_RULES = {
    "cobro_adopcion": "venta_animal",
    "rifa": "Lineamientos de la comunidad: rifas, sorteos o animales como premio",
    "producto_prohibido": "Productos prohibidos en la tienda",
    "categoria_con_requisitos": "Productos prohibidos en la tienda: categoría con requisitos",
    "reedicion": "venta_animal",
}


def _record_rejection(db: Session, target_type: str, obj, owner: User | None, admin: User, previous: str | None,
                      notes: str | None, hold_report: ContentReport | None):
    """Rechazo de una retención = medida de moderación (moderacion.html §6; Decreto NNA art. 5 fr. II): copia
    cifrada en la bóveda, folio MOD con declaración de motivos y enlace para apelar."""
    from app.services import evidence, legal_moderation as lm

    record = evidence.capture(
        db, kind="contenido_retirado", target_type=target_type, target_id=obj.id, obj=obj,
        owner_user_id=owner.id if owner else None, reason=(previous or HOLD_REPORT_REASON)[:60], report=hold_report,
        decision={"action": "hide_content", "review_hold": previous, "terms": list(obj.review_terms or []),
                  "notes": notes, "actor_id": admin.id},
        actor_id=admin.id,
    )
    rule = HOLD_RULES.get(previous or "", "venta_animal" if target_type == "dog" else "Productos prohibidos en la tienda")
    return lm.record_action(
        db, user=owner, target_type=target_type, target_id=obj.id, action="hide_content", rule=rule,
        detection="filtro", actor=admin, title=getattr(obj, "name", None) or f"#{obj.id}", report=hold_report,
        evidence_record=record, notes=notes, details={"review_hold": previous, "hidden": True},
    )


def held_row(db: Session, target_type: str, obj) -> dict:
    owner = _owner_of(db, target_type, obj)
    return {
        "target_type": target_type, "target_id": obj.id, "title": getattr(obj, "name", None),
        "description": (getattr(obj, "description", None) or "")[:500], "photo": (getattr(obj, "photos", None) or [None])[0],
        "review_hold": obj.review_hold, "review_terms": list(obj.review_terms or []),
        "label": HOLD_LABELS.get(obj.review_hold or "", obj.review_hold), "since": obj.review_hold_at,
        "is_hidden": obj.is_hidden, "category": getattr(obj, "category", None),
        "owner": {"id": owner.id, "full_name": owner.full_name} if owner else None,
    }


def list_holds(db: Session, status: str = "en_revision", limit: int = 200) -> list[dict]:
    rows = []
    for target_type, model in (("dog", Dog), ("product", Product)):
        q = db.query(model).filter(model.review_hold.isnot(None))
        if status == "en_revision":
            q = q.filter(model.review_hold.notin_((HOLD_RELEASED, HOLD_REJECTED)), model.is_hidden == True)  # noqa: E712
        elif status in (HOLD_RELEASED, HOLD_REJECTED):
            q = q.filter(model.review_hold == status)
        rows += [held_row(db, target_type, o) for o in q.order_by(model.review_hold_at.desc()).limit(limit).all()]
    rows.sort(key=lambda r: r["since"] or datetime.datetime.min, reverse=True)
    return rows[:limit]


# --------------------------------------------------------------------------- perros encontrados
MICROCHIP_RESULTS = {
    "sin_chip": "No tiene microchip",
    "chip_sin_registro": "Tiene microchip sin datos de contacto",
    "chip_tutor_contactado": "Tiene microchip y se contactó a su familia",
}
FOUND_HOLD_TEXT = ("Un perro encontrado no puede ofrecerse en adopción antes de {days} días naturales desde que se "
                   "encontró, con el reporte de «encontrado» activo, su microchip revisado en una clínica y aviso a "
                   "la autoridad local (perdidos-y-encontrados, sección 6).")


def is_found_dog(dog) -> bool:
    return bool(getattr(dog, "found_at", None) or getattr(dog, "found_report_id", None))


def found_hold_until(dog) -> datetime.datetime | None:
    found_at = getattr(dog, "found_at", None)
    return found_at + datetime.timedelta(days=settings.found_dog_hold_days) if found_at else None


def found_hold_missing(db: Session | None, dog, now: datetime.datetime | None = None) -> list[str]:
    """Requisitos pendientes para publicar en adopción un perro encontrado ([] = puede publicarse).

    El plazo corre desde el reporte de «encontrado» ligado: tiene que estar publicado (y activo) todo ese tiempo
    para que su familia pueda encontrarlo. Sin reporte ligado falta "reporte".
    """
    if not is_found_dog(dog):
        return []
    now = now or datetime.datetime.utcnow()
    missing = []
    if not dog.found_report_id:
        missing.append("reporte")
    until = found_hold_until(dog)
    if until is None or now < until:
        missing.append("plazo")
    if not dog.microchip_checked_at:
        missing.append("microchip")
    if not dog.authority_notified_at:
        missing.append("autoridad")
    if db is not None and dog.found_report_id:
        report = db.query(LostReport).filter(LostReport.id == dog.found_report_id).first()
        if report is not None and report.status == "resolved":
            missing.append("reencuentro")  # el reporte se cerró: volvió con su familia
        elif report is None or not found_report_published(report, until):
            missing.append("reporte_activo")  # se ocultó, se borró o caducó antes de cumplir el plazo
    return missing


def found_report_published(report, until: datetime.datetime | None) -> bool:
    """El reporte de «encontrado» siguió publicado hasta cumplir el plazo: no está oculto ni borrado, y no caducó
    (si caducó, tuvo que ser después del plazo; su última actividad marca desde cuándo dejó de estar vigente)."""
    if report.is_hidden or report.purged_at is not None:
        return False
    if report.status == "expired":
        last = report.last_activity_at or report.created_at
        expired_at = last + datetime.timedelta(days=settings.report_expiry_days) if last else None
        return bool(until and expired_at and expired_at >= until)
    return report.status in ("active", "resolved")


def found_hold_active(dog, db: Session | None = None) -> bool:
    return bool(found_hold_missing(db, dog))


def found_hold_info(db: Session | None, dog) -> dict | None:
    if not is_found_dog(dog):
        return None
    missing = found_hold_missing(db, dog)
    until = found_hold_until(dog)
    labels = {
        "reporte": "publicar un reporte de «encontrado» y ligarlo a esta ficha",
        "plazo": f"esperar hasta el {_fmt_local(until)}" if until and dog.found_report_id else
                 f"que pasen {settings.found_dog_hold_days} días con el reporte publicado",
        "microchip": "revisar su microchip en una clínica",
        "autoridad": "avisar a la autoridad local y guardar la constancia",
        "reencuentro": "el reporte se cerró como reencuentro: ya volvió con su familia",
        "reporte_activo": "volver a publicar el reporte de «encontrado»: se ocultó, se borró o caducó antes de "
                          "cumplir el plazo",
    }
    message = None
    if missing:
        message = ("Todavía no puede ofrecerse en adopción. Falta: " + "; ".join(labels[m] for m in missing) + ". "
                   + FOUND_HOLD_TEXT.format(days=settings.found_dog_hold_days))
    return {"active": bool(missing), "until": until, "missing": missing, "message": message,
            "found_report_id": dog.found_report_id, "found_at": dog.found_at,
            "microchip_checked_at": dog.microchip_checked_at, "microchip_result": dog.microchip_result,
            "authority_notified_at": dog.authority_notified_at, "authority_notice": dog.authority_notice,
            "hold_days": settings.found_dog_hold_days}


def _fmt_local(utc_naive: datetime.datetime | None) -> str:
    if not utc_naive:
        return ""
    return utc_naive.replace(tzinfo=datetime.timezone.utc).astimezone(MX_TZ).strftime("%d/%m/%Y")


def apply_found_fields(db: Session, dog, data: dict, user: User, creating: bool) -> None:
    """Toma de `data` los campos de perro encontrado y los aplica al perro (valida el reporte ligado).

    data: found_report_id, was_found, microchip_checked, microchip_result, authority_notified, authority_notice.
    El plazo cuenta desde la publicación del reporte de «encontrado» ligado (no se puede acortar declarando otra
    fecha). Un perro ya marcado como encontrado no puede desmarcarse ni cambiar de reporte.
    """
    now = datetime.datetime.utcnow()
    report_id = data.pop("found_report_id", None)
    was_found = data.pop("was_found", None)
    chip = data.pop("microchip_checked", None)
    chip_result = data.pop("microchip_result", None)
    notified = data.pop("authority_notified", None)
    notice = data.pop("authority_notice", None)
    if report_id:
        report = db.query(LostReport).filter(LostReport.id == report_id).first()
        if not report or report.report_type != "found":
            raise HTTPException(status_code=400, detail="Liga el perro a uno de tus reportes de «encontrado».")
        if report.reporter_id != user.id and user.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Solo puedes ligar tus propios reportes de «encontrado».")
        if dog.found_report_id and dog.found_report_id != report.id:
            raise HTTPException(status_code=400, detail="Este perro ya está ligado a otro reporte de «encontrado».")
        if dog.found_report_id != report.id:
            if report.is_hidden or report.purged_at is not None or report.status != "active":
                raise HTTPException(status_code=400, detail=(
                    "Liga un reporte de «encontrado» que esté publicado y activo: tu familia tiene que poder verlo."))
            other = db.query(Dog.id).filter(Dog.found_report_id == report.id)
            if dog.id is not None:
                other = other.filter(Dog.id != dog.id)
            if other.first():
                raise HTTPException(status_code=409, detail="Ese reporte de «encontrado» ya está ligado a otra ficha.")
        dog.found_report_id = report.id
        # El plazo corre desde lo más reciente: el reporte o la ficha (un reporte viejo no acorta la espera de un
        # perro que se publica hoy)
        dog.found_at = max(report.created_at or now, getattr(dog, "created_at", None) or now)
    if was_found and not dog.found_at:
        dog.found_at = now  # declarado como encontrado sin reporte: falta publicarlo y ligarlo
    if chip is True and not dog.microchip_checked_at:
        dog.microchip_checked_at = now
    elif chip is False:
        dog.microchip_checked_at = None
    if chip_result is not None:
        if chip_result not in MICROCHIP_RESULTS:
            raise HTTPException(status_code=400, detail="Resultado del microchip inválido.")
        dog.microchip_result = chip_result
    if notified is True:
        text = " ".join((notice or dog.authority_notice or "").split())
        if len(text) < 3:
            raise HTTPException(status_code=400, detail="Escribe a qué autoridad avisaste (y el folio, si te lo dieron).")
        dog.authority_notice = text[:255]
        dog.authority_notified_at = dog.authority_notified_at or now
    elif notified is False:
        dog.authority_notified_at = None
    elif notice is not None and dog.authority_notified_at:
        dog.authority_notice = " ".join(notice.split())[:255] or dog.authority_notice


def notify_found_holds_ending(db: Session, now: datetime.datetime | None = None) -> int:
    """Aviso diario a quien resguarda un perro encontrado el día en que se cumple el plazo de espera."""
    now = now or datetime.datetime.utcnow()
    start = now - datetime.timedelta(days=settings.found_dog_hold_days + 1)
    end = now - datetime.timedelta(days=settings.found_dog_hold_days)
    dogs = db.query(Dog).filter(Dog.found_at.isnot(None), Dog.found_at > start, Dog.found_at <= end,
                                Dog.status != "adopted").limit(500).all()
    sent = 0
    from app.services.notify import notify_user

    for dog in dogs:
        owner = db.query(User).filter(User.id == dog.owner_id).first()
        if not owner or not owner.is_active:
            continue
        missing = [m for m in found_hold_missing(db, dog, now) if m != "plazo"]
        body = (f"Ya pasaron {settings.found_dog_hold_days} días desde que encontraste a {dog.name}. "
                + ("Si nadie lo reclamó, ya puedes publicarlo en adopción desde Mis publicaciones."
                   if not missing else "Para publicarlo en adopción todavía falta revisar su microchip y avisar a la "
                                       "autoridad local; márcalo en su ficha."))
        notify_user(db, owner, "found_hold_ended", "Plazo de resguardo cumplido", body, url=f"/app/?dog={dog.id}",
                    email=True, data={"dog_id": dog.id}, commit=False)
        sent += 1
    db.commit()
    return sent


# --------------------------------------------------------------------------- tienda: productos
PRODUCT_CATEGORIES = {
    # clave: (etiqueta, se revisa antes de publicarse)
    "promocionales": ("Artículos promocionales del Refugio (playeras, tazas, bolsas, calcomanías)", False),
    "ropa_textiles": ("Ropa para perro y textiles", False),
    "accesorios_juguetes": ("Accesorios seguros y juguetes (correas, platos, camas, placas)", False),
    "impresos": ("Impresos (calendarios, libros, postales)", False),
    "electronicos": ("Electrónicos (por ejemplo, localizadores)", True),
    "alimento_industrializado": ("Alimento industrializado para perros", True),
    "masticables_carnaza": ("Masticables de carnaza sin relleno", True),
    "higiene_belleza": ("Higiene y belleza sin efecto terapéutico", True),
    "otro": ("Otro (lo revisamos antes de publicarlo)", True),
}
FOOD_CATEGORIES = ("alimento_industrializado", "masticables_carnaza")
NO_WARRANTY = "Sin garantía adicional"
MIN_WARRANTY_DAYS = 90  # LFPC art. 77
PRODUCT_HOLD_MESSAGE = (
    "Tu producto quedó en revisión porque coincide con la lista de productos prohibidos ({terms}). No se venden "
    "animales, medicamentos, vacunas ni productos con receta, collares de descarga, ahorque o púas, rifas, productos "
    "ligados a una adopción ni marcas o personajes sin licencia. Un moderador lo revisa; si es un error, lo publicamos "
    "tal cual. Consulta /app/legal/productos-prohibidos.html."
)
PRODUCT_CATEGORY_MESSAGE = (
    "Tu producto quedó en revisión porque su categoría tiene requisitos (alimentos y premios con número de SENASICA, "
    "electrónicos con instructivo y garantía NOM-024, higiene sin efecto terapéutico u «Otro»). Incluye en la "
    "descripción y en las fotos la etiqueta y el número de regulación; un moderador lo revisa antes de publicarlo."
)
PRODUCT_PROHIBITED_PATTERNS = [
    ("animales vivos", _re(r"\banimal(es)? viv[oa]s?\b|\b(venta|vendo|se venden?|vendemos)\s+(de\s+)?(\w+\s+)?"
                          r"(perr|cachorr|gat|animal|mascot|conej|hurones?|aves?\b|pericos?)"
                          r"|\b(perr|cachorr|gatit|mascot)\w*\s+(\w+\s+)?(en venta|a la venta|se vende)")),
    ("ligado a una adopción", _re(r"\b(cuota|anticipo|apartado|reembolso|donativo sugerido|costo|pago)s? de adopcion\b"
                                  r"|\badopta y gana\b|\bcompra y (te )?llevas?\b|\bincluye (un )?(perr|cachorr)")),
    ("rifas o sorteos", _re(r"\b(rifas?|sorteos?|boletos?|loteria)\b")),
    ("medicamentos", _re(r"\b(medicamentos?|medicinas?|vacunas?|antiparasitari\w*|desparasitante\w*|antipulgas"
                         r"|pipetas?|ivermectina|antibiotic\w*|con receta|receta medica|inyecci\w+|pastillas?|jarabes?"
                         r"|tabletas? (masticables? )?para|suplementos?|vitaminas?)\b")),
    ("collares que lastiman", _re(r"\bcollar(es)? (de |para )?(ahorque|ahorcador|castigo|puas|picos|descarga\w*"
                                  r"|choque\w*|electric\w*|adiestramiento electr\w*)|\b(e-?collar|shock)\b")),
    ("afirmaciones de salud", _re(r"\b(cura[ns]?|curar|previene[n]?|prevenir|recomendado por (los )?veterinarios"
                                  r"|aprobado por (los )?veterinarios|terapeutic\w*|medicinal\w*)\b")),
    ("facturas", _re(r"\b(venta|vendo|compra|compro|se venden?)\s+(de\s+)?facturas?\b|\bfacturas? (a la venta|en venta)\b")),
    ("marcas sin licencia", _re(r"\b(replica|replicas|imitacion|clon|piratas?|tipo (nike|adidas|gucci|chanel|disney))\b"
                                r"|\b(disney|marvel|pokemon|pikachu|hello kitty|sanrio|star wars|mickey|minnie|snoopy"
                                r"|paw patrol|patrulla canina|bluey|harry potter|looney tunes|bob esponja|minecraft"
                                r"|fortnite|nike|adidas|gucci|louis vuitton|chanel|supreme|nfl|nba|real madrid"
                                r"|club america|chivas|cruz azul|rayados)\b")),
    ("trámites gratuitos", _re(r"\bruac\b|\bgestion de (tramites?|registro)\b")),
    ("frases exageradas", _re(r"\b(lo mejor|lo unico|el mejor|la mejor|los mejores|las mejores|numero 1|no\. 1)\b")),
]
_HOMEMADE_FOOD = _re(r"\b(caser[oa]s?|hech[oa]s? en casa)\b.*\b(premios?|galletas?|alimentos?|croquetas?|snacks?)\b"
                     r"|\b(premios?|galletas?|alimentos?|croquetas?|snacks?)\b.*\b(caser[oa]s?|hech[oa]s? en casa)\b"
                     r"|\b(relleno|rellenos|recubiert[oa]s?|recubrimiento)\b")
_HUNDRED_PERCENT = _re(r"\b100\s*%\s*(para|llega|va|de lo recaudado|de la venta|de las ganancias)")


def product_terms(category: str | None, *texts) -> list[str]:
    terms = _matches(PRODUCT_PROHIBITED_PATTERNS, *texts)
    norm = _norm("\n".join(t for t in texts if t))
    if _HOMEMADE_FOOD.search(norm) and (category in FOOD_CATEGORIES or re.search(r"\b(premio|galleta|alimento|croqueta|snack)", norm)):
        terms.append("alimentos caseros o con relleno")
    if settings.mercadopago_marketplace_fee_percent > 0 and _HUNDRED_PERCENT.search(norm):
        terms.append("«100 % para el Refugio» con comisión")
    return sorted(set(terms))


def product_review(category: str | None, *texts) -> tuple[str | None, list[str]]:
    """(motivo, palabras) de la revisión de un producto; (None, []) si se publica de inmediato."""
    terms = product_terms(category, *texts)
    if terms:
        return "producto_prohibido", terms
    if category in PRODUCT_CATEGORIES and PRODUCT_CATEGORIES[category][1]:
        return "categoria_con_requisitos", [PRODUCT_CATEGORIES[category][0]]
    return None, []


def validate_product_fields(category: str | None, warranty_text: str | None, warranty_days: int | None) -> str:
    """Categoría y garantía obligatorias (consumidor-ecommerce-04 y 12). Devuelve el texto de garantía limpio."""
    if not category or category not in PRODUCT_CATEGORIES:
        raise HTTPException(status_code=400, detail="Elige la categoría del producto (lista de productos permitidos).")
    text = " ".join((warranty_text or "").split())
    if warranty_days is not None and warranty_days < MIN_WARRANTY_DAYS:
        raise HTTPException(status_code=400, detail=f"Si ofreces garantía, debe ser de {MIN_WARRANTY_DAYS} días o más "
                                                    "desde la entrega (LFPC art. 77). Si no, marca «Sin garantía adicional».")
    if warranty_days is None and not text:
        raise HTTPException(status_code=400, detail="Indica la garantía del producto o marca «Sin garantía adicional».")
    if warranty_days is not None and len(text) < 15:
        raise HTTPException(status_code=400, detail="Describe la garantía: qué cubre, quién la otorga y cómo hacerla "
                                                    "válida (mínimo 15 caracteres).")
    return (text or NO_WARRANTY)[:2000]


def warranty_label(product) -> str:
    days = getattr(product, "warranty_days", None)
    if days:
        return f"Garantía: {days} días desde la entrega"
    return NO_WARRANTY


# --------------------------------------------------------------------------- tienda: identidad del vendedor
def seller_identity(refuge: Refuge) -> dict:
    """Datos de identidad y fiscales del refugio vendedor que se muestran antes de pagar (terminos-tienda 1.3)."""
    profile = refuge.fiscal_profile
    donataria = bool(profile and profile.is_donataria)
    return {
        "refuge_id": refuge.id, "name": refuge.name, "city": refuge.city,
        "legal_name": profile.legal_name if profile else None, "rfc": profile.rfc if profile else None,
        "person_type": profile.person_type if profile else None, "is_donataria": donataria,
        "fiscal_complete": bool(profile and profile.rfc and profile.legal_name),
        # Ventas de donatarias: exentas de IVA (donativos-08); las demás muestran el IVA incluido en el precio
        "iva": "exento" if donataria else "incluido",
        "invoices_by": "El Refugio vendedor emite tu factura (CFDI); pídela en Mis pedidos.",
    }


def iva_included(total, iva: str) -> Decimal:
    total = Decimal(str(total or 0))
    if iva != "incluido" or total <= 0:
        return Decimal("0.00")
    return (total - total / Decimal("1.16")).quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- tienda: comprobante
PROFECO = {"name": "Procuraduría Federal del Consumidor (PROFECO)", "phone": "55 5568 8722 y 800 468 8722",
           "site": "https://www.gob.mx/profeco"}
RECEIPT_NOTICE = "Este comprobante no es una factura (CFDI). La factura la emite el Refugio vendedor: pídela en Mis pedidos."


def operator_identity() -> dict:
    return {"legal_name": settings.emisor_nombre or "GuauWoow", "rfc": settings.emisor_rfc,
            "address": settings.operator_address, "phone": settings.operator_phone or settings.support_whatsapp,
            "email": settings.support_email, "site": settings.public_base_url or settings.public_url("")}


def order_receipt(db: Session, order: Order) -> dict:
    """Comprobante electrónico del pedido (consumidor-ecommerce-07): HTML en la app y resumen por correo."""
    from app.services import order_flow

    refuge = order.refuge or db.query(Refuge).filter(Refuge.id == order.refuge_id).first()
    seller = seller_identity(refuge) if refuge else None
    items = []
    for item in order.items:
        product = item.product
        items.append({
            "product_id": item.product_id, "name": product.name if product else f"Producto #{item.product_id}",
            "quantity": item.quantity, "unit_price": item.unit_price,
            "total": (Decimal(item.unit_price) * item.quantity).quantize(CENT),
            "category": PRODUCT_CATEGORIES.get(getattr(product, "category", None) or "", ("",))[0] or None,
            "warranty": (getattr(product, "warranty_text", None) or NO_WARRANTY) if product else NO_WARRANTY,
            "warranty_days": getattr(product, "warranty_days", None) if product else None,
            "is_perishable": bool(getattr(product, "is_perishable", False)) if product else False,
        })
    total = Decimal(order.total)
    iva = seller["iva"] if seller else "incluido"
    deadlines = order_flow.return_deadlines(order)
    base = settings.public_url("")
    return {
        "folio": f"PF-{order.id:06d}", "order_id": order.id, "status": order.status,
        "status_label": order_flow.STATUS_LABELS.get(order.status, order.status),
        "created_at": order.created_at, "paid_at": order.paid_at, "operator": operator_identity(), "seller": seller,
        "items": items, "subtotal": order.subtotal, "shipping_total": order.shipping_total, "total": total,
        "currency": settings.currency, "iva": iva, "iva_amount": iva_included(total, iva),
        "payment": {"provider": "Mercado Pago" if order.provider == "mercadopago" else (order.provider or "Mercado Pago"),
                    "payment_id": order.provider_payment_id, "mode": order.payment_mode,
                    "collector": "Cuenta de Mercado Pago del Refugio vendedor" if order.payment_mode == "split" else None},
        "shipping": {"name": order.shipping_name, "address": order.shipping_address, "phone": order.shipping_phone},
        "dispatch_due_at": order_flow.dispatch_deadline(order), "handling_days": order_flow.order_handling_days(order),
        "tracking": {"carrier": order.carrier, "tracking_number": order.tracking_number, "tracking_url": order.tracking_url},
        "rights": {
            "cancel": "Puedes cancelar sin costo mientras el pedido no se haya enviado (Mis pedidos > Cancelar pedido).",
            "revocation": (f"Tienes {settings.return_window_days} días hábiles desde que recibes el producto para "
                           "revocar la compra sin dar explicaciones; el envío de regreso corre por tu cuenta (LFPC "
                           "art. 56)."),
            "claims": ("Si llega dañado, defectuoso o no corresponde, tienes dos meses para reclamar: eliges reposición "
                       "o devolución, sin costo de envío, más una bonificación de al menos 20 % (LFPC arts. 92, 92 "
                       "Ter y 93)."),
            "revocation_until": deadlines.get("revocation_until"), "claim_until": deadlines.get("claim_until"),
            "how": "Desde Mis pedidos > «Devolver o reportar un problema» o en Atención y quejas.",
        },
        "terms": {"version": order.terms_version, "hash": order.terms_hash, "accepted_at": order.terms_accepted_at,
                  "url": f"{base}/app/legal/terminos-tienda.html",
                  "returns_url": f"{base}/app/legal/envios-devoluciones-garantias.html",
                  "history_url": f"{base}/app/legal/historial.html"},
        "invoice": {"how": "Pide tu factura (CFDI) en Mis pedidos > «¿Necesitas factura?»; nuestra meta es que la "
                           "recibas en 24 horas.", "status": order.invoice.status if order.invoice else None},
        "bonus": bonus_out(order.bonus) if getattr(order, "bonus", None) else None,
        "profeco": PROFECO, "notice": RECEIPT_NOTICE,
    }


def receipt_text(receipt: dict) -> str:
    """Resumen del comprobante para el correo de pago confirmado (texto plano: cada línea es un renglón)."""
    seller = receipt.get("seller") or {}
    op = receipt["operator"]
    lines = [
        f"Folio: {receipt['folio']} (pedido #{receipt['order_id']})",
        f"Vende y cobra: {seller.get('name') or 'el refugio'}"
        + (f" · {seller['legal_name']} · RFC {seller['rfc']}" if seller.get("legal_name") and seller.get("rfc") else ""),
    ]
    for item in receipt["items"]:
        lines.append(f"• {item['quantity']} × {item['name']}: ${Decimal(item['total']):.2f}")
    ship = Decimal(receipt.get("shipping_total") or 0)
    lines.append(f"Envío: {'$%.2f' % ship if ship > 0 else 'gratis'}")
    lines.append(f"Total pagado: ${Decimal(receipt['total']):.2f} {receipt['currency']}"
                 + (f" (IVA incluido: ${Decimal(receipt['iva_amount']):.2f})" if receipt["iva"] == "incluido" else
                    " (venta exenta de IVA)"))
    pay = receipt["payment"]
    lines.append(f"Medio de pago: {pay['provider']}" + (f" · ID de pago {pay['payment_id']}" if pay.get("payment_id") else ""))
    if receipt.get("dispatch_due_at"):
        lines.append(f"El refugio lo envía a más tardar el {_fmt_local(receipt['dispatch_due_at'])} y verás la guía en Mis pedidos.")
    lines += [
        f"Entrega en: {receipt['shipping'].get('address') or ''}",
        receipt["rights"]["cancel"], receipt["rights"]["revocation"], receipt["rights"]["claims"],
        receipt["invoice"]["how"],
        f"Condiciones aceptadas: versión {receipt['terms'].get('version') or '-'} ({receipt['terms']['url']}).",
        f"Opera la tienda: {op['legal_name']}" + (f" · RFC {op['rfc']}" if op.get("rfc") else "")
        + (f" · {op['address']}" if op.get("address") else "") + (f" · {op['email']}" if op.get("email") else ""),
        f"También puedes acudir a {PROFECO['name']}: {PROFECO['phone']} · {PROFECO['site']}",
        RECEIPT_NOTICE,
    ]
    return "\n".join(lines)


def send_receipt_email(db: Session, order: Order) -> bool:
    """Correo con el comprobante al confirmarse el pago (nunca rompe el flujo de pago)."""
    try:
        from app.services import notify

        user = db.query(User).filter(User.id == order.user_id).first()
        if not user or not notify.can_email(user):
            return False
        receipt = order_receipt(db, order)
        notify._dispatch("app.tasks.notifications.send_notification_email", user.email,
                         f"Comprobante de tu pedido {receipt['folio']}", receipt_text(receipt),
                         f"/app/?order={order.id}&receipt=1")
        return True
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo enviar el comprobante del pedido %s", order.id)
        return False


# --------------------------------------------------------------------------- tienda: bonificación (LFPC 92 Ter)
DEFECT_REASONS = ("defectuoso", "no_corresponde")
BONUS_PERCENT = Decimal("20")
BONUS_RESOLUTION_DAYS = 15  # la reclamación se resuelve en 15 días (LFPC art. 93)
BONUS_STATUSES = ("pendiente", "pagada", "improcedente")


def bonus_out(bonus: OrderBonus | None) -> dict | None:
    if bonus is None:
        return None
    return {"id": bonus.id, "order_id": bonus.order_id, "refuge_id": bonus.refuge_id, "reason": bonus.reason,
            "base_amount": bonus.base_amount, "percent": bonus.percent, "amount": bonus.amount, "status": bonus.status,
            "covered_items": bonus.covered_items,
            "due_at": bonus.due_at, "paid_at": bonus.paid_at, "payment_reference": bonus.payment_reference,
            "note": bonus.note, "created_at": bonus.created_at}


def _item_row(item) -> dict:
    return {"order_item_id": item.id, "product_id": item.product_id, "quantity": item.quantity,
            "unit_price": str(Decimal(item.unit_price).quantize(CENT))}


def _bonus_base(order: Order, refunded=None, item_ids: list[int] | None = None,
                previous: list | None = None) -> tuple[Decimal, list | None]:
    """(base, partidas) de la bonificación: el precio de lo que se reclamó, nunca el envío.

    - Devolución completa aprobada (refunded None): todo el pedido, todas sus partidas.
    - Reembolso del equipo con partidas señaladas (item_ids): el precio de esas partidas (se suman a las de antes).
    - Reembolso del equipo sin partidas: lo reembolsado hasta ahora, con tope en el precio de los productos (el
      envío no cuenta). Si cubre todo el pedido, son todas sus partidas.
    """
    items = list(order.items or [])
    subtotal = Decimal(order.subtotal if order.subtotal is not None
                       else Decimal(order.total) - Decimal(order.shipping_total or 0))
    if refunded is None:
        return subtotal, [_item_row(i) for i in items]
    if item_ids:
        chosen = {int(x) for x in item_ids} | {int(r["order_item_id"]) for r in (previous or [])
                                                if isinstance(r, dict) and r.get("order_item_id")}
        covered = [i for i in items if i.id in chosen]
        if covered:
            base = sum((Decimal(i.unit_price) * i.quantity for i in covered), Decimal("0"))
            return min(base, subtotal), [_item_row(i) for i in covered]
    base = min(Decimal(refunded or 0), subtotal)
    return base, ([_item_row(i) for i in items] if base >= subtotal else (previous or None))


def register_bonus(db: Session, order: Order, by: str = "system", refunded=None,
                   item_ids: list[int] | None = None) -> OrderBonus | None:
    """Registra la bonificación de una reclamación procedente por defecto o porque no corresponde (sin commit), sobre
    el precio de lo reclamado (_bonus_base). Si ya existe y sigue pendiente, un reembolso posterior la aumenta.
    Avisa al comprador, al refugio vendedor y al equipo."""
    if order.return_reason not in DEFECT_REASONS:
        return None
    existing = db.query(OrderBonus).filter(OrderBonus.order_id == order.id).first()
    if existing and existing.status != "pendiente":
        return existing
    base, covered = _bonus_base(order, refunded, item_ids, existing.covered_items if existing else None)
    base = base.quantize(CENT)
    amount = (base * BONUS_PERCENT / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    from app.services import payment_flow as pf

    if existing:
        if base <= Decimal(existing.base_amount):
            return existing
        existing.base_amount, existing.amount, existing.covered_items = base, amount, covered
        pf.add_timeline(order, "bonus_registered", f"La bonificación sube a {pf._money(amount)} MXN (20 % de "
                                                   f"{pf._money(base)} MXN reclamados).", by=by)
        return existing
    if base <= 0:
        return None
    now = datetime.datetime.utcnow()
    bonus = OrderBonus(order_id=order.id, refuge_id=order.refuge_id, user_id=order.user_id, reason=order.return_reason,
                       base_amount=base, percent=BONUS_PERCENT, amount=amount, status="pendiente",
                       covered_items=covered, due_at=now + datetime.timedelta(days=BONUS_RESOLUTION_DAYS))
    db.add(bonus)
    db.flush()
    order.bonus = bonus

    money = pf._money(amount)
    pf.add_timeline(order, "bonus_registered", f"Bonificación de {money} MXN (20 % del precio, LFPC art. 92 Ter) a "
                                               "cargo del refugio vendedor.", by=by)
    pf.notify_order_user(db, order.user_id, "order_bonus_registered", "Tu bonificación quedó registrada",
                         f"Tu reclamación del pedido #{order.id} procede. Además de la reposición o el reembolso, el "
                         f"refugio vendedor debe pagarte una bonificación de al menos {money} MXN (20 % del precio "
                         "pagado, LFPC art. 92 Ter). Queda registrada en tu pedido y le damos seguimiento; te avisamos "
                         "cuando se pague.", order, extra={"bonus_id": bonus.id})
    pf._notify_refuges_of_order(db, order, "order_bonus_due", "Debes pagar una bonificación",
                                f"La reclamación del pedido #{order.id} ({order.return_reason.replace('_', ' ')}) procede. "
                                f"Además del reembolso o la reposición, la ley te obliga a pagar al comprador una "
                                f"bonificación de al menos {money} MXN (20 % del precio, LFPC art. 92 Ter) antes del "
                                f"{_fmt_local(bonus.due_at)}. Págala (por ejemplo, con una transferencia o un reembolso "
                                "parcial adicional) y registra la referencia en Mi tienda > Pedidos.")
    _alert_admins(db, "order_bonus_due", "Bonificación por seguir",
                  f"Pedido #{order.id}: bonificación de {money} MXN a cargo del refugio (vence el {_fmt_local(bonus.due_at)}).",
                  {"order_id": order.id, "bonus_id": bonus.id})
    return bonus


def report_bonus_paid(db: Session, order: Order, refuge: Refuge, reference: str, note: str | None) -> dict:
    """El refugio vendedor registra que pagó la bonificación (con referencia). El equipo puede revisarla."""
    bonus = db.query(OrderBonus).filter(OrderBonus.order_id == order.id).first()
    if not bonus or order.refuge_id != refuge.id:
        raise HTTPException(status_code=404, detail="Este pedido no tiene una bonificación pendiente.")
    if bonus.status != "pendiente":
        raise HTTPException(status_code=409, detail="Esta bonificación ya se cerró.")
    reference = " ".join((reference or "").split())
    if len(reference) < 4:
        raise HTTPException(status_code=400, detail="Escribe la referencia del pago (folio de la transferencia o del "
                                                    "reembolso en Mercado Pago).")
    return _close_bonus(db, order, bonus, "pagada", reference, note, by="refuge", actor=None)


def _close_bonus(db: Session, order: Order, bonus: OrderBonus, status: str, reference: str | None, note: str | None,
                 by: str, actor: User | None) -> dict:
    from app.services import payment_flow as pf

    bonus.status = status
    bonus.payment_reference = (reference or bonus.payment_reference or "")[:255] or None
    bonus.note = " ".join((note or "").split())[:2000] or bonus.note
    bonus.paid_at = datetime.datetime.utcnow() if status == "pagada" else None
    bonus.resolved_by = actor.id if actor else None
    money = pf._money(bonus.amount)
    if status == "pagada":
        pf.add_timeline(order, "bonus_paid", f"Bonificación de {money} MXN pagada. Referencia: {bonus.payment_reference}.", by=by)
        pf.notify_order_user(db, order.user_id, "order_bonus_paid", "Se pagó tu bonificación",
                             f"El refugio registró el pago de tu bonificación de {money} MXN del pedido #{order.id} "
                             f"(referencia {bonus.payment_reference}). Si no la recibiste, avísanos desde Atención y quejas.",
                             order, extra={"bonus_id": bonus.id})
    elif status == "improcedente":
        pf.add_timeline(order, "bonus_waived", f"La bonificación no procede: {bonus.note}", by=by)
        pf.notify_order_user(db, order.user_id, "order_bonus_waived", "Revisamos tu bonificación",
                             f"Revisamos la bonificación del pedido #{order.id} y no procede: {bonus.note} Si no estás de "
                             "acuerdo, escríbenos desde Atención y quejas o acude a PROFECO.", order,
                             extra={"bonus_id": bonus.id})
    db.commit()
    db.refresh(bonus)
    return bonus_out(bonus)


def resolve_bonus(db: Session, bonus_id: int, admin: User, action: str, reference: str | None, note: str | None,
                  request: Request | None = None) -> dict:
    """Seguimiento del equipo: marcar pagada (con referencia), improcedente (con evidencia) o reabrir."""
    bonus = db.query(OrderBonus).filter(OrderBonus.id == bonus_id).first()
    if not bonus:
        raise HTTPException(status_code=404, detail="No encontramos esa bonificación.")
    order = db.query(Order).filter(Order.id == bonus.order_id).first()
    previous = bonus.status
    if action == "marcar_pagada":
        if not reference or len(reference.strip()) < 4:
            raise HTTPException(status_code=400, detail="Escribe la referencia del pago.")
        status = "pagada"
    elif action == "improcedente":
        if not note or len(note.strip()) < 10:
            raise HTTPException(status_code=400, detail="Explica con evidencia por qué no procede (mínimo 10 caracteres).")
        status = "improcedente"
    elif action == "reabrir":
        status = "pendiente"
    else:
        raise HTTPException(status_code=400, detail="Acción inválida: marcar_pagada, improcedente o reabrir.")
    record_admin_action(db, admin, f"bonus.{action}", "order_bonus", bonus.id, request=request,
                        details={"order_id": bonus.order_id, "from": previous, "to": status, "reference": reference,
                                 "note": note})
    if status == "pendiente":
        bonus.status, bonus.paid_at, bonus.reminded_at = "pendiente", None, None
        db.commit()
        db.refresh(bonus)
        return bonus_out(bonus)
    return _close_bonus(db, order, bonus, status, reference, note, by="admin", actor=admin)


def remind_overdue_bonuses(db: Session, now: datetime.datetime | None = None) -> int:
    """Diario: bonificaciones pendientes vencidas => recordatorio al refugio y aviso al equipo (una vez por semana)."""
    from app.services import payment_flow as pf

    now = now or datetime.datetime.utcnow()
    week = now - datetime.timedelta(days=7)
    rows = db.query(OrderBonus).filter(OrderBonus.status == "pendiente", OrderBonus.due_at < now,
                                       (OrderBonus.reminded_at.is_(None)) | (OrderBonus.reminded_at < week)).limit(500).all()
    for bonus in rows:
        order = db.query(Order).filter(Order.id == bonus.order_id).first()
        if not order:
            continue
        bonus.reminded_at = now
        money = pf._money(bonus.amount)
        pf._notify_refuges_of_order(db, order, "order_bonus_overdue", "Bonificación vencida",
                                    f"Venció el plazo para pagar la bonificación de {money} MXN del pedido #{order.id}. "
                                    "Págala y registra la referencia en Mi tienda > Pedidos.")
        _alert_admins(db, "order_bonus_overdue", "Bonificación vencida",
                      f"Pedido #{order.id}: el refugio no ha registrado el pago de la bonificación de {money} MXN.",
                      {"order_id": order.id, "bonus_id": bonus.id})
    db.commit()
    return len(rows)


# --------------------------------------------------------------------------- tienda: facturas en 24 h
INVOICE_SLA_HOURS = 24  # terminos-tienda 8.2: meta de entrega de la factura
INVOICE_ESCALATE_HOURS = 72


def remind_invoice_requests(db: Session, now: datetime.datetime | None = None) -> dict:
    """Cada hora: solicitudes de factura sin emitir a las 24 h => recordatorio al refugio; a las 72 h => equipo."""
    from app.services import payment_flow as pf

    now = now or datetime.datetime.utcnow()
    result = {"reminded": 0, "escalated": 0}
    due = db.query(OrderInvoice).filter(
        OrderInvoice.status == "requested", OrderInvoice.reminded_at.is_(None),
        OrderInvoice.requested_at < now - datetime.timedelta(hours=INVOICE_SLA_HOURS)).limit(500).all()
    for inv in due:
        order = db.query(Order).filter(Order.id == inv.order_id).first()
        inv.reminded_at = now
        if order:
            pf._notify_refuges_of_order(db, order, "invoice_overdue", "Factura pendiente (más de 24 h)",
                                        f"El comprador del pedido #{order.id} pidió su factura hace más de "
                                        f"{INVOICE_SLA_HOURS} horas. Nuestra meta es entregarla en 24 h: emítela y súbela "
                                        "(XML y PDF) en Mi tienda > Facturas, o recházala con el motivo.", tab="facturas")
        result["reminded"] += 1
    late = db.query(OrderInvoice).filter(
        OrderInvoice.status == "requested", OrderInvoice.escalated_at.is_(None),
        OrderInvoice.requested_at < now - datetime.timedelta(hours=INVOICE_ESCALATE_HOURS)).limit(500).all()
    for inv in late:
        inv.escalated_at = now
        _alert_admins(db, "invoice_overdue", "Factura atrasada",
                      f"La factura del pedido #{inv.order_id} lleva más de {INVOICE_ESCALATE_HOURS} h sin emitirse.",
                      {"order_id": inv.order_id})
        result["escalated"] += 1
    db.commit()
    return result


# --------------------------------------------------------------------------- donativos
DONATION_COUNTED = ("pending", "approved", "amount_mismatch")
AML_WINDOW_DAYS = 183  # «periodos de seis meses» (LFPIORPI art. 17, penúltimo párrafo)
NOT_DEDUCTIBLE = ("Este refugio no es donataria autorizada: tu donativo no es deducible de impuestos y no puede "
                  "emitirte un CFDI de donativo.")
DEDUCTIBLE = ("Este refugio declara ser donataria autorizada: tu donativo es deducible solo si le pides tu CFDI de "
              "donativo (aplican los límites del SAT). GuauWoow no emite recibos deducibles.")


def donation_tax_notice(refuge: Refuge) -> dict:
    deducible = bool(refuge.is_donataria)
    return {"deducible": deducible, "aviso_fiscal": DEDUCTIBLE if deducible else NOT_DEDUCTIBLE}


def _mx_day_bounds(now: datetime.datetime) -> tuple[datetime.datetime, datetime.datetime]:
    local = now.replace(tzinfo=datetime.timezone.utc).astimezone(MX_TZ)
    start = datetime.datetime.combine(local.date(), datetime.time(0, 0), tzinfo=MX_TZ)
    end = start + datetime.timedelta(days=1)
    to_utc = lambda d: d.astimezone(datetime.timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(start), to_utc(end)


def money_text(value) -> str:
    return f"${Decimal(str(value)):,.2f}"


def check_donation_limits(db: Session, user: User, refuge: Refuge, amount: Decimal,
                          now: datetime.datetime | None = None) -> None:
    """Topes por donativo y por día, y nada de autodonaciones (donativos §8; prevencion-lavado §4)."""
    if refuge.user_id == user.id:  # donativos-16: nadie se dona a sí mismo
        raise HTTPException(status_code=400, detail="No puedes donar a tu propio refugio.")
    cap = Decimal(str(settings.donation_max_mxn))
    if amount > cap:
        raise HTTPException(status_code=400, detail=(
            f"El tope por donativo es de {money_text(cap)} MXN. Si quieres donar más, ponte en contacto directo con el "
            "refugio: ese donativo se hace fuera de GuauWoow."))
    now = now or datetime.datetime.utcnow()
    start, end = _mx_day_bounds(now)
    today = db.query(func.coalesce(func.sum(Donation.amount), 0)).filter(
        Donation.user_id == user.id, Donation.status.in_(DONATION_COUNTED),
        Donation.created_at >= start, Donation.created_at < end).scalar() or 0
    daily = Decimal(str(settings.donation_daily_max_mxn))
    if Decimal(str(today)) + amount > daily:
        left = max(Decimal("0"), daily - Decimal(str(today)))
        raise HTTPException(status_code=400, detail=(
            f"Rebasarías el tope diario de donativos de {money_text(daily)} MXN por cuenta "
            f"(hoy puedes donar hasta {money_text(left)} MXN más). Inténtalo mañana o contacta directo al refugio."))


def aml_thresholds() -> list[tuple[str, Decimal]]:
    uma = Decimal(str(settings.uma_daily_mxn))
    ident = (uma * settings.donation_identification_uma).quantize(CENT)
    notice = (uma * settings.donation_notice_uma).quantize(CENT)
    return [("aproximacion", (ident / 2).quantize(CENT)), ("identificacion", ident), ("aviso", notice)]


def check_aml_thresholds(db: Session, donation: Donation, now: datetime.datetime | None = None) -> list[DonationAmlFlag]:
    """Tras aprobar un donativo: acumulado de 6 meses de esa cuenta a ese refugio contra los umbrales de la
    LFPIORPI. Crea una alerta por nivel (una vez por periodo) y avisa al refugio y al equipo (sin commit)."""
    now = now or datetime.datetime.utcnow()
    since = now - datetime.timedelta(days=AML_WINDOW_DAYS)
    rows = db.query(Donation.id, Donation.amount).filter(
        Donation.user_id == donation.user_id, Donation.refuge_id == donation.refuge_id, Donation.status == "approved",
        func.coalesce(Donation.approved_at, Donation.created_at) >= since).all()
    ids = {i for i, _ in rows} | {donation.id}
    total = sum((Decimal(str(a)) for i, a in rows if i != donation.id), Decimal("0")) + Decimal(str(donation.amount))
    created = []
    refuge = db.query(Refuge).filter(Refuge.id == donation.refuge_id).first()
    for level, threshold in aml_thresholds():
        if total < threshold:
            continue
        exists = db.query(DonationAmlFlag.id).filter(
            DonationAmlFlag.user_id == donation.user_id, DonationAmlFlag.refuge_id == donation.refuge_id,
            DonationAmlFlag.level == level, DonationAmlFlag.created_at >= since).first()
        if exists:
            continue
        flag = DonationAmlFlag(user_id=donation.user_id, refuge_id=donation.refuge_id, level=level, total=total,
                               threshold=threshold, window_start=since, donation_ids=sorted(ids))
        db.add(flag)
        created.append(flag)
        donor = donation.donor_display_name
        folios = ", ".join(f"#{i}" for i in sorted(ids)[-10:])
        what = {
            "aproximacion": "se acercan a la mitad del umbral de identificación",
            "identificacion": "alcanzan el umbral de identificación",
            "aviso": "alcanzan el umbral de aviso a la autoridad",
        }[level]
        if refuge:
            create_notification(
                db, user_id=refuge.user_id, type="donation_aml_threshold", title="Aviso de la ley antilavado",
                body=(f"Los donativos de {donor} a {refuge.name} en los últimos 6 meses suman {money_text(total)} MXN y "
                      f"{what} ({money_text(threshold)} MXN). Si tu refugio es asociación civil, la LFPIORPI (art. 17 fr. "
                      "XIII y art. 18) te obliga a identificar a quien dona a partir de 1,605 UMA acumuladas, integrar su "
                      f"expediente y, desde 3,210 UMA, presentar aviso. Folios: {folios}."),
                data={"refuge_id": refuge.id, "level": level, "donation_ids": sorted(ids)}, commit=False)
        _alert_admins(db, "donation_aml_threshold", "Alerta antilavado en donativos",
                      f"La cuenta #{donation.user_id} acumula {money_text(total)} MXN en 6 meses al refugio "
                      f"#{donation.refuge_id} ({level}: {money_text(threshold)} MXN).",
                      {"user_id": donation.user_id, "refuge_id": donation.refuge_id, "level": level})
    return created


def list_aml_flags(db: Session, pending_only: bool = True, limit: int = 200) -> list[dict]:
    q = db.query(DonationAmlFlag)
    if pending_only:
        q = q.filter(DonationAmlFlag.reviewed_at.is_(None))
    out = []
    for f in q.order_by(DonationAmlFlag.created_at.desc()).limit(limit).all():
        user = db.query(User).filter(User.id == f.user_id).first()
        refuge = db.query(Refuge).filter(Refuge.id == f.refuge_id).first()
        out.append({"id": f.id, "level": f.level, "total": f.total, "threshold": f.threshold,
                    "window_start": f.window_start, "donation_ids": f.donation_ids, "created_at": f.created_at,
                    "reviewed_at": f.reviewed_at, "note": f.note,
                    "user": {"id": user.id, "full_name": user.full_name, "email": user.email} if user else None,
                    "refuge": {"id": refuge.id, "name": refuge.name} if refuge else None})
    return out


def review_aml_flag(db: Session, flag_id: int, admin: User, note: str | None, request: Request | None = None) -> dict:
    flag = db.query(DonationAmlFlag).filter(DonationAmlFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(status_code=404, detail="No encontramos esa alerta.")
    flag.reviewed_at = datetime.datetime.utcnow()
    flag.reviewed_by = admin.id
    flag.note = " ".join((note or "").split())[:2000] or None
    record_admin_action(db, admin, "donation_aml.review", "donation_aml_flag", flag.id, request=request,
                        details={"note": flag.note})
    db.commit()
    return {"id": flag.id, "reviewed_at": flag.reviewed_at, "note": flag.note}


def record_acceptance_if_available(db: Session, user: User, slug: str, method: str, request: Request | None) -> None:
    """Constancia en la bitácora de aceptaciones (K-ACEPT) si el servicio ya existe; nunca rompe el flujo."""
    try:
        from app.services import legal_acceptance
    except ImportError:
        return
    try:
        legal_acceptance.record_acceptance(db, user, slug, method, request)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo registrar la aceptación de %s", slug)


# --------------------------------------------------------------------------- contenido importado
IMPORT_NOTICE = "Importado de una publicación pública; su autor no es usuario de GuauWoow"
IMPORTED_SOURCES = ("facebook", "volunteer")


def import_notice(report) -> str | None:
    return IMPORT_NOTICE if getattr(report, "source", None) in IMPORTED_SOURCES else None


# --------------------------------------------------------------------------- tareas diarias
def run_daily(db: Session, now: datetime.datetime | None = None) -> dict:
    """Bonificaciones vencidas y fin del resguardo de perros encontrados (Celery beat, diaria)."""
    result = {}
    for name, fn in (("bonuses_overdue", remind_overdue_bonuses), ("found_holds_ended", notify_found_holds_ending)):
        try:
            result[name] = fn(db, now)
        except Exception:  # noqa: BLE001 - una regla con problemas no detiene a las demás
            db.rollback()
            logger.exception("Falló la tarea diaria %s", name)
            result[name] = "error"
    return result
