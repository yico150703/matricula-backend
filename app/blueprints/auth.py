from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash
from ..errors import ApiError
from ..models import Alumno

bp = Blueprint("auth", __name__)


@bp.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email, password = data.get("email", "").strip().lower(), data.get("password", "")
    if not email or not password:
        raise ApiError("credenciales_invalidas", "Email y contraseña son obligatorios.", 400)
    alumno = Alumno.query.filter_by(email=email).first()
    if not alumno or not check_password_hash(alumno.password_hash, password):
        raise ApiError("credenciales_invalidas", "Email o contraseña incorrectos.", 401)
    if alumno.estado != "activo":
        raise ApiError("alumno_no_activo", "El alumno no está habilitado para iniciar sesión.", 403)
    return jsonify(access_token=create_access_token(identity=alumno.cod_alumno), alumno=alumno.to_dict())


@bp.get("/auth/me")
@jwt_required()
def me():
    alumno = Alumno.query.get_or_404(get_jwt_identity())
    return jsonify(alumno=alumno.to_dict())
