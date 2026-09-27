"""Alta de personal: generación de usuario y correo a partir de nombres y apellidos."""
import re
import unicodedata

from flask import current_app

from .extensions import db
from .models import Administrador

NOMBRES_COMUNES = {
    "HENRY", "LUIS", "GABRIEL", "HERIBERTO", "JUAN", "JOSE", "CARLOS", "JORGE", "MARIA", "ANA", "PEDRO", "MANUEL",
}


def _ascii(texto):
    return unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()


def base_usuario(nombres, apellidos):
    """Juan Carlos + Alvarado Torres -> jalvaradotorres"""
    inicial = (_ascii(nombres).strip()[:1] or "").lower()
    ape = re.sub(r"[^a-z]", "", "".join(_ascii(apellidos).lower().split()))
    return re.sub(r"[^a-z0-9]", "", inicial + ape) or "usuario"


def usuario_disponible(base):
    usuario, n = base, 1
    while Administrador.query.filter(db.func.lower(Administrador.usuario) == usuario).first():
        n += 1
        usuario = f"{base}{n}"
    return usuario


def correo_personal(usuario):
    return f"{usuario}@{current_app.config['STAFF_EMAIL_DOMAIN']}"


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
