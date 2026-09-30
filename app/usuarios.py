"""Alta de personal: generación de usuario y correo a partir de nombres y apellidos."""
import re
import unicodedata

from .extensions import db
from .models import Administrador

NOMBRES_COMUNES = {
    "HENRY", "LUIS", "GABRIEL", "HERIBERTO", "JUAN", "JOSE", "CARLOS", "JORGE", "MARIA", "ANA", "PEDRO", "MANUEL",
}


def _ascii(texto):
    return unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()


PARTICULAS = {"de", "del", "la", "las", "los", "y", "san", "santa"}
DOMINIO_PERSONAL = "unfv.edu.pe"


def _apellidos_en_bloques(apellidos):
    """'Franco del Carpio' -> ['franco', 'delcarpio'] · 'De la Cruz Rojas' -> ['delacruz', 'rojas']."""
    bloques, pendiente = [], ""
    for p in _ascii(apellidos).lower().split():
        p = re.sub(r"[^a-z]", "", p)
        if not p:
            continue
        if p in PARTICULAS:
            pendiente += p
            continue
        bloques.append(pendiente + p)
        pendiente = ""
    if pendiente:
        bloques.append(pendiente)
    return bloques


def base_usuario(nombres, apellidos):
    """Formato UNFV: inicial del primer nombre + apellido paterno + inicial del materno.
    José Alvarado Torres -> jalvaradot · Juan Carlos Franco del Carpio -> jfrancoc"""
    inicial = re.sub(r"[^a-z]", "", _ascii(nombres).lower())[:1]
    bloques = _apellidos_en_bloques(apellidos)
    paterno = bloques[0] if bloques else ""
    # La inicial del materno es la de su palabra principal (del Carpio -> c)
    materno = ""
    if len(bloques) > 1:
        ultima = _ascii(apellidos).lower().split()[-1]
        materno = re.sub(r"[^a-z]", "", ultima)[:1] or bloques[1][:1]
    return (inicial + paterno + materno) or "usuario"


def usuario_disponible(base):
    usuario, n = base, 1
    while Administrador.query.filter(db.func.lower(Administrador.usuario) == usuario).first():
        n += 1
        usuario = f"{base}{n}"
    return usuario


def correo_personal(usuario):
    """Todo el personal usa el dominio institucional unfv.edu.pe."""
    return f"{usuario}@{DOMINIO_PERSONAL}"


def separar_nombre_horario(texto):
    """Los horarios oficiales escriben 'APELLIDO APELLIDO NOMBRES' (a veces 'NOMBRE APELLIDO APELLIDO')."""
    crudas = [p for p in re.split(r"\s+", (texto or "").replace("_", " ").strip()) if p]
    if not crudas:
        return "", ""
    # Une partículas al apellido siguiente: DEL CARPIO, DE LA CRUZ
    partes, pendiente = [], ""
    for p in crudas:
        if p in ("DE", "DEL", "LA", "LOS", "LAS"):
            pendiente = f"{pendiente} {p}".strip()
            continue
        partes.append(f"{pendiente} {p}".strip() if pendiente else p)
        pendiente = ""
    if partes[0] in NOMBRES_COMUNES and len(partes) >= 3:
        return partes[0].title(), " ".join(partes[1:]).title()
    if len(partes) >= 3:
        return " ".join(partes[2:]).title(), " ".join(partes[:2]).title()
    return "", " ".join(partes).title()
