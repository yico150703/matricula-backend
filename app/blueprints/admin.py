import re
from datetime import date, datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from ..errors import ApiError
from ..extensions import db
from ..models import ROLES_PERSONAL, Administrador, Alumno, Matricula, MatriculaDetalle, PeriodoAcademico, ProcesoHorario, SolicitudPassword
from ..usuarios import base_usuario, correo_personal, usuario_disponible
from .proceso import cabecera
from ..security import admin_required, current_admin_id

bp = Blueprint("admin", __name__)


@bp.get("/admin/resumen")
@admin_required
def resumen():
    """Indicadores para el panel del administrador."""
    total_alumnos = db.session.scalar(db.select(func.count()).select_from(Alumno)) or 0
    activos = db.session.scalar(db.select(func.count()).select_from(Alumno).where(Alumno.estado == "activo")) or 0
    pendientes_password = db.session.scalar(
        db.select(func.count()).select_from(Alumno).where(Alumno.debe_cambiar_password.is_(True))
    ) or 0
    por_plan = dict(db.session.execute(db.select(Alumno.corr_pe, func.count()).group_by(Alumno.corr_pe)).all())

    periodos = []
    for periodo in PeriodoAcademico.query.filter(PeriodoAcademico.estado != "historico").order_by(PeriodoAcademico.fec_inicio).all():
        proceso = db.session.get(ProcesoHorario, periodo.unique_id)
        matriculas = db.session.scalar(
            db.select(func.count()).select_from(Matricula).where(Matricula.id_periodo == periodo.unique_id)
        ) or 0
        cursos = db.session.scalar(
            db.select(func.count())
            .select_from(MatriculaDetalle)
            .join(Matricula, Matricula.nro_matricula == MatriculaDetalle.nro_matricula)
            .where(Matricula.id_periodo == periodo.unique_id, MatriculaDetalle.estado == "matriculado")
        ) or 0
        periodos.append({**periodo.to_dict(), "matriculas": matriculas, "cursos_matriculados": cursos, "fase": proceso.fase if proceso else None})

    return jsonify(
        alumnos={
            "total": total_alumnos,
            "activos": activos,
            "inactivos": total_alumnos - activos,
            "pendientes_cambio_password": pendientes_password,
            "plan_2019": por_plan.get(1, 0),
        },
        periodos=periodos,
        personal={r: Administrador.query.filter_by(rol=r, activo=True).count() for r in ROLES_PERSONAL},
        solicitudes_password=SolicitudPassword.query.filter_by(estado="pendiente", canal="oficina").count(),
    )


@bp.get("/admin/solicitudes-password")
@admin_required
def solicitudes_password():
    """Pedidos de recuperación que la Oficina debe atender (los que no pudieron resolverse por correo)."""
    ahora = datetime.utcnow()
    pendientes = (
        SolicitudPassword.query.filter_by(estado="pendiente", canal="oficina")
        .order_by(SolicitudPassword.creado_en.desc())
        .all()
    )
    data = []
    for s in pendientes:
        persona = db.session.get(Alumno, s.usuario) if s.rol == "alumno" else Administrador.query.filter_by(usuario=s.usuario).first()
        data.append({
            "id": s.id,
            "rol": s.rol if s.rol == "alumno" else (persona.rol if persona else s.rol),
            "usuario": s.usuario,
            "nombre": f"{persona.apellidos}, {persona.nombres}" if persona else s.usuario,
            "email": persona.email if persona else None,
            "creado_en": s.creado_en.isoformat() + "Z",
            "vencida": s.expira_en < ahora,
        })
    return jsonify(solicitudes=data)


@bp.post("/admin/solicitudes-password/<int:id_solicitud>/atender")
@admin_required
def atender_solicitud(id_solicitud):
    """accion = 'restablecer' (contraseña = código) | 'enlace' (genera un enlace de un solo uso) | 'descartar'."""
    solicitud = db.get_or_404(SolicitudPassword, id_solicitud)
    accion = (request.get_json(silent=True) or {}).get("accion", "restablecer")
    if solicitud.estado != "pendiente":
        raise ApiError("solicitud_cerrada", "La solicitud ya fue atendida.", 409)
    if accion == "descartar":
        solicitud.estado = "anulada"
        db.session.commit()
        return jsonify(message="Solicitud descartada.")
    if solicitud.rol == "alumno":
        persona = db.get_or_404(Alumno, solicitud.usuario)
        clave_inicial = persona.cod_alumno
    else:
        persona = Administrador.query.filter_by(usuario=solicitud.usuario).first_or_404()
        clave_inicial = persona.usuario
    if accion == "enlace":
        from .auth import crear_solicitud, enlace_restablecer

        solicitud.estado = "atendida"
        solicitud.atendido_en = datetime.utcnow()
        _, token = crear_solicitud(persona, solicitud.rol, "oficina")
        db.session.commit()
        return jsonify(message="Enlace generado. Compártelo solo con la persona que lo solicitó.", enlace=enlace_restablecer(token))
    persona.password_hash = generate_password_hash(clave_inicial)
    persona.debe_cambiar_password = True
    solicitud.estado = "atendida"
    solicitud.atendido_en = datetime.utcnow()
    db.session.commit()
    return jsonify(message=f"Contraseña de {solicitud.usuario} restablecida a '{clave_inicial}'. Deberá cambiarla al ingresar.")


# ---------------------------------------------------------------------------
# Personal (jefe, director, asistente, docente, admin): alta con usuario y correo automáticos
# ---------------------------------------------------------------------------
def _nombre(valor, campo):
    valor = " ".join(str(valor or "").split())
    if not valor:
        raise ApiError("datos_invalidos", f"El campo {campo} es obligatorio.", 400)
    return valor.title()


@bp.get("/admin/usuarios")
@admin_required
def listar_personal():
    rol = request.args.get("rol")
    q = Administrador.query
    if rol:
        q = q.filter_by(rol=rol)
    lista = q.order_by(Administrador.rol, Administrador.apellidos, Administrador.nombres).all()
    return jsonify(usuarios=[u.to_dict() for u in lista], roles=ROLES_PERSONAL)


@bp.post("/admin/usuarios")
@admin_required
def crear_personal():
    """Nombres + apellidos + rol. Usuario: inicial del nombre + apellidos (jalvaradotorres);
    correo: usuario@STAFF_EMAIL_DOMAIN; contraseña inicial = usuario (se cambia al ingresar)."""
    data = request.get_json(silent=True) or {}
    nombres = _nombre(data.get("nombres"), "nombres")
    apellidos = _nombre(data.get("apellidos"), "apellidos")
    rol = data.get("rol")
    if rol not in ROLES_PERSONAL:
        raise ApiError("datos_invalidos", "Elige un rol válido.", 400)
    usuario = usuario_disponible(base_usuario(nombres, apellidos))
    email = correo_personal(usuario)
    user = Administrador(
        usuario=usuario, nombres=nombres, apellidos=apellidos, email=email, rol=rol,
        password_hash=generate_password_hash(usuario), activo=True, debe_cambiar_password=True,
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(usuario=user.to_dict(), credenciales={"usuario": usuario, "email": email, "password_inicial": usuario}), 201


@bp.patch("/admin/usuarios/<int:id_usuario>")
@admin_required
def editar_personal(id_usuario):
    user = db.get_or_404(Administrador, id_usuario)
    data = request.get_json(silent=True) or {}
    if "nombres" in data:
        user.nombres = _nombre(data["nombres"], "nombres")
    if "apellidos" in data:
        user.apellidos = _nombre(data["apellidos"], "apellidos")
    if "rol" in data:
        if data["rol"] not in ROLES_PERSONAL:
            raise ApiError("datos_invalidos", "Elige un rol válido.", 400)
        if user.id_admin == current_admin_id() and data["rol"] != "admin":
            raise ApiError("accion_no_permitida", "No puedes quitarte el rol de administrador.", 409)
        user.rol = data["rol"]
    if "activo" in data:
        if user.id_admin == current_admin_id() and not data["activo"]:
            raise ApiError("accion_no_permitida", "No puedes desactivar tu propia cuenta.", 409)
        user.activo = bool(data["activo"])
    db.session.commit()
    return jsonify(usuario=user.to_dict())


@bp.post("/admin/usuarios/<int:id_usuario>/reset-password")
@admin_required
def reset_personal(id_usuario):
    user = db.get_or_404(Administrador, id_usuario)
    user.password_hash = generate_password_hash(user.usuario)
    user.debe_cambiar_password = True
    db.session.commit()
    return jsonify(message=f"Contraseña restablecida: {user.usuario} ingresará con su usuario como contraseña y deberá cambiarla.")


@bp.post("/admin/periodos")
@admin_required
def crear_periodo():
    """Crea un período en planificación: el Jefe de Departamento inicia la fase 1."""
    data = request.get_json(silent=True) or {}
    cod = str(data.get("cod_per_acad") or "").strip()
    if not re.fullmatch(r"20\d{2}-[12]", cod):
        raise ApiError("datos_invalidos", "El código debe tener el formato 2027-1 o 2027-2.", 400)
    if PeriodoAcademico.query.filter_by(cod_per_acad=cod).first():
        raise ApiError("periodo_duplicado", f"El período {cod} ya existe.", 409)
    try:
        inicio = date.fromisoformat(data.get("fecha_inicio"))
        fin = date.fromisoformat(data.get("fecha_fin"))
    except (TypeError, ValueError):
        raise ApiError("datos_invalidos", "Indica las fechas de inicio y fin de clases.", 400)
    if fin <= inicio:
        raise ApiError("datos_invalidos", "La fecha de fin debe ser posterior al inicio.", 400)
    nuevo = (db.session.query(func.max(PeriodoAcademico.unique_id)).scalar() or 0) + 1
    periodo = PeriodoAcademico(unique_id=nuevo, cod_per_acad=cod, fec_inicio=inicio, fec_fin=fin, estado="programacion")
    db.session.add(periodo)
    db.session.flush()
    cabecera(periodo)
    db.session.add(ProcesoHorario(id_periodo=nuevo, fase=1, historial="[]"))
    db.session.commit()
    return jsonify(periodo=periodo.to_dict()), 201
