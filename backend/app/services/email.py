"""Envío de correos por SMTP (STARTTLS en 587, SSL en 465)."""
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    if not settings.smtp_enabled:
        # El cuerpo puede traer enlaces de un solo uso (restablecer contraseña, verificar correo):
        # solo se imprime en desarrollo, nunca en los logs de producción
        if settings.is_development:
            print(f"[email:dev] Para: {to} | Asunto: {subject}\n{text}", flush=True)
        else:
            logger.warning("SMTP no configurado; no se envió el correo «%s».", subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user or "GuauWoow <no-reply@guauwoow.com>"
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            if settings.smtp_use_tls:
                server.starttls()
        with server:
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Error enviando correo a %s: %s", to, exc)
        return False
