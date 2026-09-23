"""Utilidades de autenticación y autorización por rol (alumno / admin)."""
from functools import wraps

from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, verify_jwt_in_request

from .errors import ApiError

EMAIL_DOMAIN = "unfv.edu.pe"
MIN_PASSWORD_LENGTH = 6


def institutional_email(cod_alumno):
    """Correo institucional generado automáticamente a partir del código."""
    return f"{cod_alumno}@{EMAIL_DOMAIN}"


def token_for_alumno(alumno):
    return create_access_token(identity=alumno.cod_alumno, additional_claims={"rol": "alumno"})


def token_for_admin(admin):
    return create_access_token(identity=f"admin:{admin.id_admin}", additional_claims={"rol": "admin"})


def current_role():
    return get_jwt().get("rol", "alumno")


def is_admin():
    return current_role() == "admin"


def current_admin_id():
    identity = get_jwt_identity() or ""
    if not identity.startswith("admin:"):
        return None
    try:
        return int(identity.split(":", 1)[1])
    except ValueError:
        return None


def require_self_or_admin(cod_alumno, message="Solo puede consultar su propia información académica."):
    """El alumno solo accede a sus datos; el administrador accede a todos."""
    if is_admin():
        return
    if get_jwt_identity() != cod_alumno:
        raise ApiError("acceso_denegado", message, 403)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        if not is_admin():
            raise ApiError("solo_administrador", "Esta acción está reservada al administrador.", 403)
        return fn(*args, **kwargs)

    return wrapper


def validate_new_password(password, *, forbidden=()):
    password = password or ""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ApiError("password_invalida", f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.", 400)
    if password in forbidden:
        raise ApiError("password_invalida", "La nueva contraseña no puede ser igual a tu código ni a la contraseña actual.", 400)
    return password
