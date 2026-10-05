"""Utilidades de autenticación y autorización por rol (alumno / admin)."""
from datetime import timedelta
from functools import wraps

from flask import current_app

from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, verify_jwt_in_request

from .errors import ApiError

EMAIL_DOMAIN = "unfv.edu.pe"
MIN_PASSWORD_LENGTH = 6


def institutional_email(cod_alumno):
    """Correo institucional generado automáticamente a partir del código."""
    return f"{cod_alumno}@{EMAIL_DOMAIN}"


def token_for_alumno(alumno):
    minutos = current_app.config["SESION_ALUMNO_MINUTOS"]
    return create_access_token(identity=alumno.cod_alumno, additional_claims={"rol": "alumno"}, expires_delta=timedelta(minutes=minutos))


def token_for_admin(admin):
    """Token del personal (admin, jefe, director, asistente, docente)."""
    return create_access_token(identity=f"staff:{admin.id_admin}", additional_claims={"rol": admin.rol or "admin"})


token_for_staff = token_for_admin
ROLES_STAFF = {"admin", "jefe", "director", "asistente", "docente"}


def current_role():
    return get_jwt().get("rol", "alumno")


def is_admin():
    return current_role() == "admin"


def is_staff():
    return current_role() in ROLES_STAFF


def current_admin_id():
    identity = get_jwt_identity() or ""
    if not identity.startswith(("admin:", "staff:")):
        return None
    try:
        return int(identity.split(":", 1)[1])
    except ValueError:
        return None


# Con la contraseña inicial solo se puede consultar el perfil y cambiarla (OWASP: forzar el cambio en el servidor)
ENDPOINTS_SIN_CAMBIO = {"auth.me", "auth.change_password"}


def usuario_de_sesion():
    """Devuelve (usuario, rol) del token actual comprobando que la cuenta siga activa y con el mismo rol."""
    from .extensions import db
    from .models import Administrador, Alumno

    rol = current_role()
    if rol in ROLES_STAFF:
        admin = db.session.get(Administrador, current_admin_id())
        if not admin or not admin.activo:
            raise ApiError("sesion_invalida", "Tu cuenta está desactivada. Vuelve a iniciar sesión.", 401)
        if admin.rol != rol:
            raise ApiError("sesion_invalida", "Tu rol cambió. Vuelve a iniciar sesión.", 401)
        return admin, admin.rol
    alumno = db.session.get(Alumno, get_jwt_identity())
    if not alumno:
        raise ApiError("sesion_invalida", "El alumno de esta sesión ya no existe.", 401)
    if alumno.estado != "activo":
        raise ApiError("sesion_invalida", "Tu cuenta está inactiva. Comunícate con la Oficina de Matrícula.", 401)
    return alumno, "alumno"


def proteger_sesion(endpoint):
    """Se ejecuta antes de cada petición con token: cuenta activa, rol vigente y cambio de contraseña obligatorio."""
    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return  # token vencido o inválido: lo responde el propio endpoint
    if not get_jwt():
        return
    user, _rol = usuario_de_sesion()
    if user.debe_cambiar_password and endpoint not in ENDPOINTS_SIN_CAMBIO:
        raise ApiError("debe_cambiar_password", "Debes cambiar tu contraseña inicial antes de continuar.", 403)


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


def roles_required(*roles):
    """Permite el acceso solo a los roles indicados (cada rol ve únicamente sus funciones)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            if current_role() not in roles:
                raise ApiError("rol_no_autorizado", "Tu rol no tiene acceso a esta función.", 403)
            return fn(*args, **kwargs)

        return wrapper

    return deco
