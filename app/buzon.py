"""Buzón del alumno: el sistema deja aquí sus avisos. Para agregar un aviso nuevo basta con llamar a notificar()."""
from datetime import datetime

from .extensions import db
from .models import MensajeBuzon


def notificar(cod_alumno, titulo, cuerpo, tipo="aviso"):
    """Agrega un mensaje al buzón del alumno (no hace commit: se guarda junto con la operación que lo origina)."""
    if not cod_alumno:
        return None
    msg = MensajeBuzon(cod_alumno=cod_alumno, tipo=tipo, titulo=titulo[:150], cuerpo=cuerpo, creado_en=datetime.utcnow())
    db.session.add(msg)
    return msg


def aviso_seguridad(cod_alumno, titulo, detalle):
    """Avisos de la cuenta: siempre dicen cuándo pasó y qué hacer si no fue el alumno."""
    cuerpo = f"{detalle}\n\nSi no fuiste tú, cambia tu contraseña desde Configuración y comunícate con la Oficina de Matrícula FIIS."
    return notificar(cod_alumno, titulo, cuerpo, tipo="seguridad")
