"""Avisos a usuarios: siempre en la app y, si están configurados, por correo y por WhatsApp.

Los canales externos se despachan en segundo plano (Celery si hay Redis) y nunca rompen el flujo que
los llama: si algo falla solo se registra en el log.
"""
import html
import logging

from sqlalchemy.orm import Session

from app.config import DEMO_EMAIL, settings
from app.models import LostReport, Notification, User
from app.utils.notifications import create_notification

logger = logging.getLogger(__name__)

EMAIL_FOOTER = (
    "Recibes este correo porque tienes una cuenta en GuauWoow. "
    "Puedes cambiar tus avisos desde tu perfil en la app."
)
# Correos de verificación y de contraseña (routers/auth.py): llegan antes de que la cuenta esté confirmada
ACCOUNT_EMAIL_REASON = ("Recibes este correo porque alguien pidió crear una cuenta o restablecer la contraseña con "
                        "esta dirección en GuauWoow.")


def email_footer(reason: str = EMAIL_FOOTER) -> str:
    """Pie de cada correo (comunicaciones.html §6; LFPC art. 17): por qué lo recibes, quién lo envía (razón social y
    domicilio de EMISOR_NOMBRE y OPERATOR_ADDRESS; teléfono y correo de contacto) y el enlace al centro legal."""
    operador = ", ".join(v for v in (settings.emisor_nombre, settings.operator_address) if v)
    contacto = " · ".join(v for v in (settings.operator_phone, settings.support_email) if v)
    who = "GuauWoow" + (f", operada por {operador}" if operador else "") + "." + (f" Contacto: {contacto}." if contacto else "")
    return "\n".join((reason, who, f"Centro legal: {settings.public_url('/app/legal/')}"))


def footer_html(footer: str) -> str:
    """El pie en HTML (escapado), con el centro legal como enlace."""
    legal = settings.public_url("/app/legal/")
    lines = []
    for line in footer.splitlines():
        if line == f"Centro legal: {legal}":
            lines.append(f'Centro legal: <a href="{html.escape(legal, quote=True)}" style="color:#8a7a6a">'
                         f"{html.escape(legal)}</a>")
        else:
            lines.append(html.escape(line))
    return "<br>".join(lines)


def absolute_url(url: str | None) -> str | None:
    """Rutas internas ("/app/?report=1") a URL absoluta con PUBLIC_BASE_URL."""
    if not url:
        return None
    if url.startswith(("https://", "http://")):
        return url
    return settings.public_url(url if url.startswith("/") else f"/{url}")


def _mask(phone: str | None) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"***{digits[-4:]}" if digits else "?"


def can_email(user: User) -> bool:
    email = (user.email or "").lower()
    return bool(
        settings.smtp_enabled and email and user.is_active and not user.deleted_at
        and email != DEMO_EMAIL and not email.endswith(".invalid")
    )


def can_whatsapp(user: User) -> bool:
    """Plantillas de WhatsApp solo con permiso expreso («Avisos por WhatsApp» en Perfil → Preferencias o ALTA)."""
    return bool(settings.whatsapp_enabled and user.phone and user.phone_verified and user.is_active
                and getattr(user, "whatsapp_alerts", False))


def _dispatch(task_path: str, *args) -> None:
    from app.services.background import dispatch

    try:
        dispatch(task_path, *args)
    except Exception:  # noqa: BLE001 - un canal caído no debe tumbar la acción principal
        logger.exception("No se pudo despachar %s", task_path)


def notify_user(
    db: Session,
    user: User,
    kind: str,
    title: str,
    body: str,
    url: str | None = None,
    email: bool = False,
    whatsapp_template: str | None = None,
    template_params: list | None = None,
    data: dict | None = None,
    commit: bool = True,
) -> Notification:
    """Crea la notificación en la app y despacha correo/WhatsApp cuando aplican.

    - email=True: se envía correo si hay SMTP y la cuenta tiene un correo real.
    - whatsapp_template: nombre de la plantilla aprobada (None/vacío = sin WhatsApp). Solo a teléfonos
      verificados. Dentro de la ventana de 24 h se manda texto libre; fuera, la plantilla.
    """
    payload = dict(data or {})
    if url:
        payload.setdefault("url", url)
    notification = create_notification(
        db, user_id=user.id, type=kind, title=title, body=body, data=payload or None, commit=commit,
    )
    try:
        if email and can_email(user):
            _dispatch("app.tasks.notifications.send_notification_email", user.email, title, body, url)
        if whatsapp_template and can_whatsapp(user):
            text = f"{title}\n{body}" + (f"\n{absolute_url(url)}" if url else "")
            _dispatch("app.tasks.notifications.send_whatsapp_notification",
                      user.phone, text, whatsapp_template, [str(p) for p in (template_params or [])])
    except Exception:  # noqa: BLE001
        logger.exception("Falló el envío por canales externos de la notificación %s", kind)
    return notification


# --------------------------------------------------------------------------- correo
def render_email(title: str, body: str, url: str | None = None, cta: str = "Ver en GuauWoow",
                 footer: str | None = None) -> tuple[str, str]:
    """Devuelve (texto, html) de un correo sencillo. Todo el contenido del usuario va escapado."""
    link = absolute_url(url)
    footer = footer or email_footer()
    text = f"{title}\n\n{body}\n"
    if link:
        text += f"\n{cta}: {link}\n"
    text += f"\n--\n{footer}\n"

    esc_body = "<br>".join(html.escape(line) for line in (body or "").splitlines())
    button = ""
    if link:
        button = (
            '<tr><td style="padding-top:22px">'
            f'<a href="{html.escape(link, quote=True)}" style="display:inline-block;background:#f97316;color:#ffffff;'
            'text-decoration:none;font-weight:bold;padding:12px 22px;border-radius:999px">'
            f"{html.escape(cta)}</a></td></tr>"
        )
    html_doc = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;background:#fff7ed;font-family:Arial,Helvetica,sans-serif;color:#3b2a1a">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:560px;background:#ffffff;border-radius:16px;padding:28px">'
        '<tr><td style="font-size:20px;font-weight:bold;color:#ea580c">🐾 GuauWoow</td></tr>'
        f'<tr><td style="padding-top:16px;font-size:18px;font-weight:bold">{html.escape(title)}</td></tr>'
        f'<tr><td style="padding-top:8px;font-size:15px;line-height:1.5">{esc_body}</td></tr>'
        f"{button}"
        f'<tr><td style="padding-top:26px;font-size:12px;line-height:1.4;color:#8a7a6a">{footer_html(footer)}</td></tr>'
        "</table></td></tr></table></body></html>"
    )
    return text, html_doc


def send_email_now(to: str, title: str, body: str, url: str | None = None) -> bool:
    from app.services.email import send_email

    text, html_doc = render_email(title, body, url)
    subject = " ".join(f"{title} · GuauWoow".split())[:200]  # sin saltos de línea en el encabezado
    return send_email(to, subject, text, html_doc)


# --------------------------------------------------------------------------- WhatsApp
def send_whatsapp(phone: str | None, text: str, template_name: str | None = None, params: list | None = None) -> str | None:
    """Mensaje proactivo por WhatsApp respetando BAJA/STOP y la ventana de 24 h de Meta.

    Devuelve "text", "template" o None (no se envió).
    """
    from app.services import whatsapp_api
    from app.services.matching import is_whatsapp_opted_out

    if not phone:
        return None
    if is_whatsapp_opted_out(phone):
        logger.info("WhatsApp a %s omitido: el número se dio de baja.", _mask(phone))
        return None
    if whatsapp_api.in_service_window(phone):
        return "text" if whatsapp_api.send_text(phone, text) else None
    if template_name:
        sent = whatsapp_api.send_template(phone, template_name, settings.whatsapp_template_language, params or [])
        return "template" if sent else None
    logger.info("WhatsApp a %s omitido: fuera de la ventana de 24 h y sin plantilla configurada.", _mask(phone))
    return None


# --------------------------------------------------------------------------- avisos de coincidencias
def notify_report_match(db: Session, mine: LostReport, theirs: LostReport, score: int, dedupe: str) -> Notification | None:
    """Avisa a quien publicó `mine` que `theirs` se parece (app + correo + plantilla de WhatsApp)."""
    user = mine.reporter or db.query(User).filter(User.id == mine.reporter_id).first()
    if not user or not user.is_active:
        return None
    kind = "encontrado" if theirs.report_type == "found" else "perdido"
    return notify_user(
        db, user, "possible_match",
        title="¡Posible coincidencia!",
        body=(
            f"Encontramos un reporte de perro {kind} que se parece a {mine.dog_name} "
            f"({score}% de similitud). Revísalo."
        ),
        url=f"/app/?report={theirs.id}",
        email=True,
        whatsapp_template=settings.whatsapp_template_match,
        template_params=[f"{mine.dog_name} (reporte #{mine.id})", absolute_url(f"/app/?report={theirs.id}")],
        data={"dedupe": dedupe, "report_id": mine.id, "match_report_id": theirs.id, "score": score},
    )
