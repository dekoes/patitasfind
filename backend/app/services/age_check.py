"""Edad (L-edad): mayoría de edad al registrarse y verificación reforzada ante señales de riesgo.

- Registro: fecha de nacimiento (se rechaza a menores de 18), casilla separada de 18+ y verificación del teléfono
  por SMS (services/otp). La declaración queda en la bitácora de aceptaciones (slug "mayoria-de-edad").
- Señal de riesgo: un reporte «involucra a un menor» contra una cuenta (ContentReport target_type="user"), o la
  petición de un admin, pasa la cuenta a verificación reforzada (User.age_check_status = "required"). Mientras
  tanto la cuenta queda limitada: las acciones de escritura responden 403 code=age_check_required
  (dependencies.get_verified_user y el chat por WebSocket).
  Para que un reporte anónimo no sirva para bloquear cuentas ajenas, la limitación automática solo ocurre si lo
  envía una cuenta con teléfono verificado o si llegan reportes de varias personas distintas (cuentas o IP) en
  pocos días. Los demás, y los que señalan a un refugio aprobado o a una clínica verificada, quedan en la cola
  de Moderación legal con prioridad 0: el equipo decide y, si procede, pide la verificación desde el panel.
- Verificación reforzada por capas, sin copias de identificaciones ni biometría: un código NUEVO por SMS al
  teléfono verificado de la cuenta + volver a confirmar la fecha de nacimiento + una declaración firmada en la
  bitácora. Solo se guarda la constancia (AgeCheck: fechas, método y resultado). Tras 3 fechas que no coinciden
  pasa a revisión manual (status="review"): la cuenta sigue limitada hasta que un admin la libere.
"""
import datetime
import logging
import secrets

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import hash_otp
from app.config import settings

logger = logging.getLogger(__name__)

MIN_AGE = 18
AGE_REPORT_REASONS = {"involucra_menor"}
# Una cuenta que ya pasó la verificación no vuelve a quedar limitada por reportes automáticos en este plazo
# (evita que alguien bloquee una cuenta reportándola una y otra vez; un admin sí puede pedirla de nuevo)
RECHECK_COOLDOWN_DAYS = 90
MAX_BIRTH_DATE_MISMATCHES = 3
# Reportes anónimos o de cuentas sin teléfono verificado: limitan la cuenta solo si llegan de al menos 3 personas
# distintas (cuenta o IP) en 30 días; si no, quedan para que el equipo los revise
AGE_DISTINCT_REPORTERS = 3
AGE_REPORT_WINDOW_DAYS = 30
OPEN_STATUSES = ("required", "review")
OTP_SALT = "edad:"
DECLARATION_TEXT = (
    "Declaro, bajo protesta de decir verdad, que tengo 18 años o más y que la fecha de nacimiento que "
    "indiqué es correcta. Sé que GuauWoow es solo para personas adultas."
)
REASON_LABELS = {
    "involucra_menor": "Recibimos un reporte de que tu cuenta podría pertenecer a una persona menor de edad.",
    "solicitud_admin": "Nuestro equipo necesita confirmar que tienes 18 años o más.",
    "otra_senal": "Detectamos una señal de que tu cuenta podría pertenecer a una persona menor de edad.",
}
REVIEW_MESSAGE = ("La fecha de nacimiento no coincidió con la que registraste. Nuestro equipo revisará tu cuenta y "
                  "te escribirá; mientras tanto sigue en modo de solo lectura.")
AGE_CHECK_MESSAGE = "Confirma tu edad para seguir usando tu cuenta"
UNDERAGE = "GuauWoow es solo para personas de 18 años o más."


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _today_mx() -> datetime.date:
    """Fecha de hoy en la Ciudad de México (UTC-6, sin horario de verano desde 2022)."""
    return (_now() - datetime.timedelta(hours=6)).date()


def age_on(birth: datetime.date, today: datetime.date | None = None) -> int:
    today = today or _today_mx()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def check_birth_date(birth: datetime.date | None) -> datetime.date:
    """Valida la fecha de nacimiento del registro: obligatoria, real y de 18 años o más."""
    if birth is None:
        raise HTTPException(status_code=400, detail="Escribe tu fecha de nacimiento.")
    today = _today_mx()
    if birth > today or birth.year < 1900:
        raise HTTPException(status_code=400, detail="La fecha de nacimiento no es válida.")
    if age_on(birth, today) < MIN_AGE:
        raise HTTPException(status_code=400, detail=UNDERAGE + " No podemos crear tu cuenta.")
    return birth


# --------------------------------------------------------------------------- señal de riesgo
def _open_check(session: Session, user_id: int):
    from app.models import AgeCheck

    return (session.query(AgeCheck).filter(AgeCheck.user_id == user_id, AgeCheck.status.in_(OPEN_STATUSES))
            .order_by(AgeCheck.id.desc()).first())


def _recently_passed(session: Session, user_id: int) -> bool:
    from app.models import AgeCheck

    since = _now() - datetime.timedelta(days=RECHECK_COOLDOWN_DAYS)
    return session.query(AgeCheck.id).filter(
        AgeCheck.user_id == user_id, AgeCheck.status.in_(("passed", "cleared")), AgeCheck.resolved_at >= since,
    ).first() is not None


def require_check(session: Session, user, reason: str, content_report=None, requested_by=None,
                  note: str | None = None, force: bool = False):
    """Pasa la cuenta a verificación reforzada (no hace commit). Devuelve el AgeCheck abierto o None.

    force=True (lo pide un admin) ignora el periodo de gracia tras una verificación aprobada.
    """
    from app.models import AgeCheck, Notification

    if user is None or not user.is_active or user.role in ("admin", "superadmin"):
        return None
    existing = _open_check(session, user.id)
    if existing is not None:
        return existing
    if not force and _recently_passed(session, user.id):
        logger.info("Cuenta %s: reporte de edad ignorado (verificación aprobada hace menos de %s días).",
                    user.id, RECHECK_COOLDOWN_DAYS)
        return None
    check = AgeCheck(user_id=user.id, status="required", reason=reason, requested_by_id=getattr(requested_by, "id", None),
                     note=(note or None))
    if content_report is not None:
        check.content_report = content_report
    session.add(check)
    user.age_check_status = "required"
    session.add(Notification(
        user_id=user.id, type="age_check", title="Confirma tu edad",
        body=(REASON_LABELS.get(reason, REASON_LABELS["otra_senal"]) + " Mientras lo confirmas tu cuenta queda "
              "limitada. Solo te pediremos tu fecha de nacimiento, un código por SMS y una declaración; nunca una "
              "copia de tu identificación."),
        data={"url": "/app/#confirmar-edad"},
    ))
    return check


def _is_ally(session: Session, user_id: int) -> bool:
    """Cuenta institucional aliada (refugio aprobado o clínica verificada): un reporte no la limita sola."""
    from app.models import Refuge, Veterinary

    if session.query(Refuge.id).filter(Refuge.user_id == user_id, Refuge.status == "approved").first():
        return True
    return session.query(Veterinary.id).filter(Veterinary.owner_user_id == user_id,
                                               Veterinary.status == "verified").first() is not None


def _trusted_reporter(session: Session, report, target_id: int) -> bool:
    """Lo envía una cuenta activa con teléfono verificado (o del equipo) que no es la reportada."""
    from app.models import User

    if not report.reporter_id or int(report.reporter_id) == target_id:
        return False
    reporter = session.get(User, int(report.reporter_id))
    if reporter is None or not reporter.is_active:
        return False
    return bool(reporter.phone_verified or reporter.role in ("admin", "superadmin"))


def _distinct_reporters(session: Session, report, target_id: int) -> int:
    """Personas distintas (cuenta o, sin cuenta, IP) que reportaron la cuenta por edad en la ventana, con esta."""
    from app.models import ContentReport

    since = _now() - datetime.timedelta(days=AGE_REPORT_WINDOW_DAYS)
    rows = (session.query(ContentReport.reporter_id, ContentReport.reporter_ip)
            .filter(ContentReport.target_type == "user", ContentReport.target_id == target_id,
                    ContentReport.reason.in_(tuple(AGE_REPORT_REASONS)), ContentReport.status != "dismissed",
                    ContentReport.created_at >= since)
            .limit(200).all())
    who = set()
    for reporter_id, ip in [*rows, (report.reporter_id, report.reporter_ip)]:
        if reporter_id and int(reporter_id) == target_id:
            continue
        if reporter_id:
            who.add(f"u{reporter_id}")
        elif ip:
            who.add(f"ip{ip}")
    return len(who)


def should_auto_limit(session: Session, report, target_id: int) -> tuple[bool, str]:
    """(limitar ya, motivo para la bitácora). Ver el docstring del módulo."""
    if _is_ally(session, target_id):
        return False, "aliado"
    if _trusted_reporter(session, report, target_id):
        return True, "cuenta_verificada"
    if _distinct_reporters(session, report, target_id) >= AGE_DISTINCT_REPORTERS:
        return True, "varios_reportes"
    return False, "revision"


def flag_from_new_reports(session: Session) -> None:
    """before_flush: los reportes nuevos «involucra a un menor» contra una cuenta activan la verificación, si lo
    envía una cuenta con teléfono verificado o varias personas distintas (ver should_auto_limit). Los demás quedan
    en la cola de Moderación legal (legal_moderation.intake ya avisa al equipo con prioridad 0)."""
    from app.models import ContentReport, User

    for obj in list(session.new):
        if not isinstance(obj, ContentReport) or getattr(obj, "_age_flagged", False):
            continue
        if obj.reason not in AGE_REPORT_REASONS or obj.target_type != "user" or not obj.target_id:
            continue
        obj._age_flagged = True
        try:
            target_id = int(obj.target_id)
            limit, why = should_auto_limit(session, obj, target_id)
            if not limit:
                logger.info("Reporte de edad contra la cuenta %s: sin limitación automática (%s); queda en revisión.",
                            target_id, why)
                continue
            user = session.get(User, target_id)
            require_check(session, user, "involucra_menor", content_report=obj)
        except Exception:  # noqa: BLE001 - la señal nunca debe impedir que se guarde el reporte
            logger.exception("No se pudo activar la verificación de edad del reporte contra la cuenta %s", obj.target_id)


# --------------------------------------------------------------------------- flujo de la persona
def _mask(phone: str | None) -> str | None:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"•••• {digits[-4:]}" if digits else None


def status_for(db: Session, user) -> dict:
    check = _open_check(db, user.id) if user.age_check_status == "required" else None
    in_review = bool(check and check.status == "review")
    steps = {
        "birth_date": bool(check and check.birth_date_confirmed_at),
        "otp": bool(check and check.otp_verified_at),
        "declaration": bool(check and check.declaration_at),
    }
    return {
        "required": bool(user.age_check_required),
        "status": user.age_check_status,
        "reason": check.reason if check else None,
        "reason_label": REASON_LABELS.get(check.reason) if check else None,
        # Revisión manual (3 fechas que no coincidieron): ya no se puede completar sola; la libera el equipo
        "in_review": in_review,
        "review_message": REVIEW_MESSAGE if in_review else None,
        "requested_at": check.created_at if check else None,
        "steps": steps,
        "phone": _mask(user.phone),
        "phone_verified": bool(user.phone_verified),
        "has_birth_date": user.birth_date is not None,
        "declaration_text": DECLARATION_TEXT,
    }


def send_code(db: Session, user, ip: str) -> dict:
    """Código NUEVO por SMS al teléfono de la cuenta (no sirve un código anterior de verificación del teléfono)."""
    from app.models import PhoneVerificationLog
    from app.services import otp, sms

    check = _open_check(db, user.id)
    if check is None or not user.age_check_required:
        raise HTTPException(status_code=400, detail="Tu cuenta no tiene una verificación de edad pendiente.")
    if check.status == "review":
        raise HTTPException(status_code=409, detail=REVIEW_MESSAGE)
    if not user.phone:
        raise HTTPException(status_code=400, detail="Agrega tu número de celular en tu perfil para recibir el código.")
    provider = sms.provider()
    if provider is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="La verificación por SMS no está disponible en este momento.")
    cooldown = settings.otp_resend_cooldown_seconds
    if check.otp_sent_at and (_now() - check.otp_sent_at).total_seconds() < cooldown:
        wait = int(cooldown - (_now() - check.otp_sent_at).total_seconds()) + 1
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"Espera {wait} segundos para pedir otro código.", headers={"Retry-After": str(wait)})
    over_phone = otp._hit_limit(db, "phone", user.phone, settings.otp_max_sends_per_phone_hour)
    over_ip = otp._hit_limit(db, "ip", ip, settings.otp_max_sends_per_ip_hour)
    if over_phone or over_ip:
        raise otp._too_many()
    code = otp.generate_code()
    log = PhoneVerificationLog(user_id=user.id, phone=user.phone, ip=(ip or "")[:64], provider=provider, success=False)
    db.add(log)
    try:
        sms.send_otp(user.phone, code)
    except sms.SMSError as exc:
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    log.success = True
    # Se reutilizan las columnas del OTP con otra sal: este código no verifica el teléfono ni al revés
    user.phone_otp_hash = hash_otp(user.id, OTP_SALT + user.phone, code)
    user.phone_otp_expires_at = _now() + datetime.timedelta(minutes=settings.otp_ttl_minutes)
    user.phone_otp_attempts = 0
    user.phone_otp_sent_at = _now()
    check.otp_sent_at = _now()
    db.commit()
    response = {"sent": True, "phone": _mask(user.phone), "cooldown": cooldown}
    if provider == "dev" and settings.is_development:
        response["dev_code"] = code
    return response


def _verify_code(db: Session, user, code: str) -> None:
    from app.services import otp

    code = (code or "").strip()
    if not user.phone_otp_hash or not user.phone_otp_expires_at or user.phone_otp_expires_at <= _now():
        raise HTTPException(status_code=400, detail="El código venció o no existe. Pide uno nuevo.")
    if (user.phone_otp_attempts or 0) >= settings.otp_max_attempts:
        raise otp._too_many()
    if not secrets.compare_digest(user.phone_otp_hash, hash_otp(user.id, OTP_SALT + (user.phone or ""), code)):
        user.phone_otp_attempts = (user.phone_otp_attempts or 0) + 1
        db.commit()
        raise HTTPException(status_code=400, detail="Código incorrecto. Revisa el SMS e inténtalo de nuevo.")
    user.phone_otp_hash = None
    user.phone_otp_expires_at = None
    user.phone_otp_attempts = 0


def complete(db: Session, user, birth_date: datetime.date | None, code: str, declaration: bool,
             request: Request | None = None) -> dict:
    """Los tres pasos juntos: código nuevo por SMS, fecha de nacimiento (igual a la registrada) y declaración.

    El código se comprueba ANTES que la fecha: sin el SMS no se puede usar este paso para adivinar la fecha
    registrada, y cada intento con otra fecha gasta el código. A la 3.ª fecha distinta pasa a revisión manual."""
    from app.services.legal_acceptance import AGE_SLUG, record_acceptance
    from app.services.consent import notify_admins

    check = _open_check(db, user.id)
    if check is None or not user.age_check_required:
        raise HTTPException(status_code=400, detail="Tu cuenta no tiene una verificación de edad pendiente.")
    if check.status == "review":
        raise HTTPException(status_code=409, detail=REVIEW_MESSAGE)
    if declaration is not True:
        raise HTTPException(status_code=400, detail="Marca la declaración para continuar.")
    if birth_date is None:
        raise HTTPException(status_code=400, detail="Escribe tu fecha de nacimiento.")
    _verify_code(db, user, code)  # consume el código (sin commit hasta el final de cada rama)
    now = _now()
    check.otp_verified_at = now
    if user.birth_date is not None and birth_date != user.birth_date:
        check.attempts = (check.attempts or 0) + 1
        if check.attempts >= MAX_BIRTH_DATE_MISMATCHES:
            check.status = "review"
            check.note = ((check.note or "") + "\nLa fecha de nacimiento no coincidió 3 veces: revisión manual.").strip()
            db.commit()
            notify_admins(db, "age_check_review", "Verificación de edad para revisar",
                          f"La cuenta {user.id} escribió una fecha de nacimiento distinta a la registrada "
                          f"{MAX_BIRTH_DATE_MISMATCHES} veces. Sigue limitada hasta que la revises y la liberes "
                          "(o la suspendas).", url="/admin/#cumplimiento-edad")
            raise HTTPException(status_code=409, detail=REVIEW_MESSAGE)
        db.commit()
        left = MAX_BIRTH_DATE_MISMATCHES - check.attempts
        raise HTTPException(status_code=400, detail="La fecha no coincide con la que registraste. Revísala, pide un "
                                                    f"código nuevo e inténtalo otra vez (te quedan {left}).")
    if age_on(birth_date) < MIN_AGE:
        check.status = "failed"
        check.resolved_at = now
        check.method = "fecha_nacimiento"
        check.birth_date_confirmed_at = now
        db.commit()
        notify_admins(db, "age_check_failed", "Cuenta de una posible persona menor de edad",
                      f"La cuenta {user.id} indicó en la verificación reforzada una fecha de menos de 18 años. "
                      "Revisa y, si procede, suspéndela y borra sus datos (privacidad.html §17).",
                      url="/admin/#cumplimiento-edad")
        raise HTTPException(status_code=403, detail=UNDERAGE + " Tu cuenta queda limitada y nuestro equipo la "
                                                               "revisará.")
    legacy = user.birth_date is None  # cuenta anterior a la fecha de nacimiento: no hay con qué compararla
    if legacy:
        user.birth_date = birth_date
    check.birth_date_confirmed_at = now
    check.declaration_at = now
    check.status = "passed"
    check.method = "fecha_declarada+sms+declaracion" if legacy else "fecha_nacimiento+sms+declaracion"
    check.resolved_at = now
    user.age_check_status = "passed"
    user.adult_declared_at = user.adult_declared_at or now
    record_acceptance(db, user, AGE_SLUG, "reaceptacion", request,
                      context={"tipo": "verificacion_reforzada", "age_check_id": check.id,
                               "birth_date": birth_date.isoformat(), "fecha_previa": not legacy})
    db.commit()
    return status_for(db, user)


# --------------------------------------------------------------------------- administración
def admin_require(db: Session, user, admin, note: str | None, request: Request | None = None):
    from app.services.audit import record_admin_action

    if user.role in ("admin", "superadmin"):
        raise HTTPException(status_code=400, detail="Las cuentas de administración no pasan por esta verificación.")
    check = require_check(db, user, "solicitud_admin", requested_by=admin, note=note, force=True)
    if check is None:
        raise HTTPException(status_code=400, detail="La cuenta está desactivada.")
    db.flush()
    record_admin_action(db, admin, "age_check.require", "user", user.id, {"age_check_id": check.id, "note": note},
                        request)
    db.commit()
    return check


def admin_clear(db: Session, user, admin, note: str | None, request: Request | None = None) -> int:
    """Libera la cuenta (el equipo resolvió la señal por otro medio). Devuelve cuántas verificaciones cerró."""
    from app.models import AgeCheck
    from app.services.audit import record_admin_action

    now = _now()
    checks = db.query(AgeCheck).filter(AgeCheck.user_id == user.id, AgeCheck.status.in_(OPEN_STATUSES)).all()
    for check in checks:
        check.status = "cleared"
        check.method = "liberada_por_admin"
        check.resolved_at = now
        check.resolved_by_id = admin.id
        if note:
            check.note = ((check.note or "") + "\n" + note).strip()
    if user.age_check_status == "required":
        user.age_check_status = "cleared"
    record_admin_action(db, admin, "age_check.clear", "user", user.id,
                        {"closed": [c.id for c in checks], "note": note}, request)
    db.commit()
    return len(checks)
