import hashlib
import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from ..buzon import aviso_seguridad
from ..errors import ApiError
from ..extensions import db
from ..mailer import mail_configured, send_mail
from ..models import Administrador, Alumno, SolicitudPassword
from ..security import current_admin_id, is_staff, token_for_admin, token_for_alumno, usuario_de_sesion, validate_new_password

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\-\s]{6,20}$")


def _session_payload(user, token, rol):
    body = {"access_token": token, "rol": rol, "usuario": user.to_dict()}
    if rol == "alumno":
        body["alumno"] = user.to_dict()  # compatibilidad con clientes anteriores
    return body


def _current_user():
    return usuario_de_sesion()


def correo_en_uso(email, excepto_admin=None):
    """Un correo identifica a una sola cuenta (personal o alumno)."""
    email = (email or "").strip().lower()
    q = Administrador.query.filter(db.func.lower(Administrador.email) == email)
    if excepto_admin:
        q = q.filter(Administrador.id_admin != excepto_admin)
    return q.first() is not None or Alumno.query.filter(db.func.lower(Alumno.email) == email).first() is not None


def _no_cuenta_prueba(user):
    if getattr(user, "cuenta_prueba", False):
        raise ApiError(
            "cuenta_prueba",
            "Esta es una cuenta de prueba compartida: sus datos y contraseña no se pueden cambiar para que todos puedan seguir entrando.",
            403,
        )


@bp.post("/auth/login")
def login():
    """Acepta como usuario: código de alumno, correo institucional o usuario de administrador."""
    data = request.get_json(silent=True) or {}
    raw_user = str(data.get("usuario") or data.get("email") or "").strip()
    password = str(data.get("password") or "")
    if not raw_user or not password:
        raise ApiError("credenciales_invalidas", "Usuario y contraseña son obligatorios.", 400)

    candidatos = Administrador.query.filter(
        (db.func.lower(Administrador.usuario) == raw_user.lower()) | (db.func.lower(Administrador.email) == raw_user.lower())
    ).all()
    admin = next((a for a in candidatos if check_password_hash(a.password_hash, password)), None)
    if admin:
        if not admin.activo:
            raise ApiError("usuario_inactivo", "Tu cuenta está desactivada. Comunícate con el administrador del sistema.", 403)
        return jsonify(_session_payload(admin, token_for_admin(admin), admin.rol))

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
    _no_cuenta_prueba(user)
    data = request.get_json(silent=True) or {}
    actual = str(data.get("password_actual") or "")
    nueva = str(data.get("password_nueva") or "")
    if not check_password_hash(user.password_hash, actual):
        raise ApiError("password_incorrecta", "La contraseña actual no es correcta.", 400)
    forbidden = {actual}
    if rol == "alumno":
        forbidden.add(user.cod_alumno)
    validate_new_password(nueva, forbidden=forbidden)
    inicial = user.debe_cambiar_password
    user.password_hash = generate_password_hash(nueva)
    user.debe_cambiar_password = False
    if rol == "alumno":
        aviso_seguridad(
            user.cod_alumno,
            "Creaste tu contraseña" if inicial else "Cambiaste tu contraseña",
            "Tu cuenta ya tiene una contraseña personal: desde ahora ingresa con ella." if inicial else "La contraseña de tu cuenta se cambió desde Configuración.",
        )
    db.session.commit()
    return jsonify(message="Contraseña actualizada correctamente.", usuario=user.to_dict(), rol=rol)


@bp.patch("/auth/perfil")
@jwt_required()
def update_profile():
    """Datos de contacto que el propio usuario puede editar (no afectan su situación académica)."""
    user, rol = _current_user()
    _no_cuenta_prueba(user)
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
            if value and correo_en_uso(value, excepto_admin=user.id_admin):
                raise ApiError("correo_en_uso", "Ese correo ya pertenece a otra cuenta.", 409)
            user.email = value
    db.session.commit()
    return jsonify(usuario=user.to_dict(), rol=rol)


# ---------------------------------------------------------------------------
# Recuperación de contraseña
# ---------------------------------------------------------------------------
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _buscar_usuario(raw):
    raw = (raw or "").strip()
    if not raw:
        return None, None
    admin = Administrador.query.filter(
        (db.func.lower(Administrador.usuario) == raw.lower()) | (db.func.lower(Administrador.email) == raw.lower())
    ).first()
    if admin:
        return admin, "admin"
    alumno = db.session.get(Alumno, raw) or Alumno.query.filter(db.func.lower(Alumno.email) == raw.lower()).first()
    return (alumno, "alumno") if alumno else (None, None)


def crear_solicitud(user, rol, canal):
    """Crea un token de un solo uso (se guarda solo su hash) y anula los anteriores del usuario."""
    rol = "alumno" if rol == "alumno" else "admin"  # todo el personal comparte la tabla 'administrador'
    usuario = user.cod_alumno if rol == "alumno" else user.usuario
    SolicitudPassword.query.filter_by(rol=rol, usuario=usuario, estado="pendiente").update({"estado": "anulada"})
    token = secrets.token_urlsafe(32)
    solicitud = SolicitudPassword(
        rol=rol,
        usuario=usuario,
        token_hash=_hash(token),
        expira_en=datetime.utcnow() + timedelta(minutes=current_app.config["RESET_MINUTOS"]),
        canal=canal,
    )
    db.session.add(solicitud)
    return solicitud, token


def enlace_restablecer(token):
    base = current_app.config.get("FRONTEND_URL") or request.headers.get("Origin", "")
    return f"{base}/restablecer?token={token}"


def _mascara(email):
    if not email or "@" not in email:
        return None
    nombre, dominio = email.split("@", 1)
    return f"{nombre[:2]}{'*' * max(1, len(nombre) - 2)}@{dominio}"


@bp.post("/auth/recuperar")
def solicitar_recuperacion():
    """Siempre responde lo mismo para no revelar qué usuarios existen."""
    data = request.get_json(silent=True) or {}
    user, rol = _buscar_usuario(str(data.get("usuario") or ""))
    respuesta = {
        "message": "Si el usuario existe, recibirás un enlace en tu correo o la Oficina de Matrícula atenderá tu solicitud.",
        "canal": "oficina",
    }
    if not user:
        return jsonify(respuesta)
    if getattr(user, "cuenta_prueba", False):
        # Las cuentas de prueba tienen contraseña fija (se muestra en el inicio de sesión)
        return jsonify(message="Es una cuenta de prueba: su contraseña es la que aparece en el inicio de sesión.", canal="prueba")

    usuario = user.cod_alumno if rol == "alumno" else user.usuario
    reciente = SolicitudPassword.query.filter(
        SolicitudPassword.rol == rol,
        SolicitudPassword.usuario == usuario,
        SolicitudPassword.creado_en > datetime.utcnow() - timedelta(minutes=2),
    ).first()
    if reciente:
        return jsonify(respuesta)

    destinos = [e for e in {getattr(user, "email", None), getattr(user, "email_personal", None)} if e]
    canal = "correo" if (mail_configured() and destinos) else "oficina"
    solicitud, token = crear_solicitud(user, rol, canal)
    if rol == "alumno":
        aviso_seguridad(
            user.cod_alumno,
            "Se solicitó recuperar tu contraseña",
            "Alguien pidió recuperar la contraseña de tu cuenta desde «¿Olvidaste tu contraseña?». "
            + ("Se envió un enlace a tu correo." if canal == "correo" else "La solicitud pasó a la Oficina de Matrícula."),
        )
    db.session.commit()

    if canal == "correo":
        link = enlace_restablecer(token)
        minutos = current_app.config["RESET_MINUTOS"]
        enviado = send_mail(
            destinos,
            "Restablecer tu contraseña - Matrícula UNFV",
            f"Hola {user.nombres}:\n\nPara crear una nueva contraseña abre este enlace (vence en {minutos} minutos):\n{link}\n\n"
            "Si no lo solicitaste, ignora este mensaje.\n\nOficina de Matrícula FIIS - UNFV",
        )
        if enviado:
            respuesta.update(canal="correo", destino=", ".join(filter(None, (_mascara(d) for d in destinos))))
        else:
            solicitud.canal = "oficina"
            db.session.commit()
    return jsonify(respuesta)


@bp.get("/auth/restablecer/<token>")
def validar_token(token):
    solicitud = SolicitudPassword.query.filter_by(token_hash=_hash(token), estado="pendiente").first()
    if not solicitud or solicitud.expira_en < datetime.utcnow():
        raise ApiError("enlace_invalido", "El enlace no es válido o ya venció. Solicita uno nuevo.", 400)
    return jsonify(usuario=solicitud.usuario, rol=solicitud.rol, expira_en=solicitud.expira_en.isoformat() + "Z")


@bp.post("/auth/restablecer")
def restablecer():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "")
    solicitud = SolicitudPassword.query.filter_by(token_hash=_hash(token), estado="pendiente").first()
    if not solicitud or solicitud.expira_en < datetime.utcnow():
        raise ApiError("enlace_invalido", "El enlace no es válido o ya venció. Solicita uno nuevo.", 400)
    if solicitud.rol == "alumno":
        user = db.session.get(Alumno, solicitud.usuario)
        prohibidas = {solicitud.usuario}
    else:
        user = Administrador.query.filter_by(usuario=solicitud.usuario).first()
        prohibidas = set()
    if not user:
        raise ApiError("enlace_invalido", "El usuario ya no existe.", 400)
    nueva = validate_new_password(str(data.get("password_nueva") or ""), forbidden=prohibidas)
    user.password_hash = generate_password_hash(nueva)
    user.debe_cambiar_password = False
    solicitud.estado = "usada"
    solicitud.atendido_en = datetime.utcnow()
    if solicitud.rol == "alumno":
        aviso_seguridad(user.cod_alumno, "Recuperaste tu contraseña", "Creaste una nueva contraseña con el enlace de recuperación.")
    db.session.commit()
    return jsonify(message="Tu contraseña fue actualizada. Ya puedes iniciar sesión.")
