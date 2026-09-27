"""Envío de correos (opcional). Si no hay SMTP configurado, send_mail devuelve False."""
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


def mail_configured():
    c = current_app.config
    return bool(c.get("SMTP_HOST") and c.get("MAIL_FROM"))


def send_mail(destinatarios, asunto, texto, html=None):
    if not mail_configured() or not destinatarios:
        return False
    c = current_app.config
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = c["MAIL_FROM"]
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(c["SMTP_HOST"], int(c.get("SMTP_PORT") or 587), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if c.get("SMTP_USER"):
                smtp.login(c["SMTP_USER"], c.get("SMTP_PASSWORD") or "")
            smtp.send_message(msg)
        return True
    except Exception as exc:  # pragma: no cover - depende del servidor de correo
        current_app.logger.warning("No se pudo enviar el correo: %s", exc)
        return False
