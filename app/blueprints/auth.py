import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from ..errors import ApiError
from ..extensions import db
from ..models import Administrador, Alumno
from ..security import current_admin_id, is_admin, token_for_admin, token_for_alumno, validate_new_password

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\-\s]{6,20}$")


def _session_payload(user, token, rol):
    body = {"access_token": token, "rol": rol, "usuario": user.to_dict()}
    if rol == "alumno":
        body["alumno"] = user.to_dict()  # compatibilidad con clientes anteriores
    return body


def _current_user():
    if is_admin():
        admin = db.session.get(Administrador, current_admin_id())
        if not admin or not admin.activo:
            raise ApiError("sesion_invalida", "La cuenta de administrador no está disponible.", 401)
        return admin, "admin"
    alumno = db.session.get(Alumno, get_jwt_identity())
    if not alumno:
        raise ApiError("sesion_invalida", "El alumno de esta sesión ya no existe.", 401)
    return alumno, "alumno"


@bp.post("/auth/login")
def login():
    """Acepta como usuario: código de alumno, correo institucional o usuario de administrador."""
    data = request.get_json(silent=True) or {}
    raw_user = str(data.get("usuario") or data.get("email") or "").strip()
    password = str(data.get("password") or "")
    if not raw_user or not password:
        raise ApiError("credenciales_invalidas", "Usuario y contraseña son obligatorios.", 400)

    admin = Administrador.query.filter(db.func.lower(Administrador.usuario) == raw_user.lower()).first()
    if admin and check_password_hash(admin.password_hash, password):
        if not admin.activo:
            raise ApiError("usuario_inactivo", "La cuenta de administrador está desactivada.", 403)
        return jsonify(_session_payload(admin, token_for_admin(admin), "admin"))

    lookup = raw_user.lower()
    alumno = db.session.get(Alumno, raw_user) or Alumno.query.filter(db.func.lower(Alumno.email) == lookup).first()
    if not alumno or not check_password_hash(alumno.password_hash, password):
        raise ApiError("credenciales_invalidas", "Usuario o contraseña incorrectos.", 401)
    if alumno.estado != "activo":
        raise ApiError("alumno_no_activo", "Tu cuenta está inactiva. Comunícate con la Oficina de Matrícula.", 403)
    return jsonify(_session_payload(alumno, token_for_alumno(alumno), "alumno"))


@bp.get("/auth/me")
@jwt_required()
def me():
    user, rol = _current_user()
    body = {"rol": rol, "usuario": user.to_dict()}
    if rol == "alumno":
        body["alumno"] = user.to_dict()
    return jsonify(body)


@bp.post("/auth/cambiar-password")
@jwt_required()
def change_password():
    user, rol = _current_user()
    data = request.get_json(silent=True) or {}
    actual = str(data.get("password_actual") or "")
    nueva = str(data.get("password_nueva") or "")
    if not check_password_hash(user.password_hash, actual):
        raise ApiError("password_incorrecta", "La contraseña actual no es correcta.", 400)
    forbidden = {actual}
    if rol == "alumno":
        forbidden.add(user.cod_alumno)
    validate_new_password(nueva, forbidden=forbidden)
    user.password_hash = generate_password_hash(nueva)
    user.debe_cambiar_password = False
    db.session.commit()
    return jsonify(message="Contraseña actualizada correctamente.", usuario=user.to_dict(), rol=rol)


@bp.patch("/auth/perfil")
@jwt_required()
def update_profile():
    """Datos de contacto que el propio usuario puede editar (no afectan su situación académica)."""
    user, rol = _current_user()
    data = request.get_json(silent=True) or {}
    if rol == "alumno":
        if "email_personal" in data:
            value = str(data.get("email_personal") or "").strip().lower() or None
            if value and not EMAIL_RE.match(value):
                raise ApiError("datos_invalidos", "El correo personal no tiene un formato válido.", 400)
            user.email_personal = value
        if "telefono" in data:
            value = str(data.get("telefono") or "").strip() or None
            if value and not PHONE_RE.match(value):
                raise ApiError("datos_invalidos", "El teléfono solo puede contener números, espacios, + o -.", 400)
            user.telefono = value
    else:
        if "nombres" in data:
            value = str(data.get("nombres") or "").strip()
            if not value:
                raise ApiError("datos_invalidos", "El nombre no puede quedar vacío.", 400)
            user.nombres = value
        if "email" in data:
            value = str(data.get("email") or "").strip().lower() or None
            if value and not EMAIL_RE.match(value):
                raise ApiError("datos_invalidos", "El correo no tiene un formato válido.", 400)
            user.email = value
    db.session.commit()
    return jsonify(usuario=user.to_dict(), rol=rol)
