from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from ..errors import ApiError
from ..extensions import db
from ..models import Alumno, Matricula, MatriculaDetalle, PeriodoAcademico, SolicitudPassword
from ..security import admin_required

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
        matriculas = db.session.scalar(
            db.select(func.count()).select_from(Matricula).where(Matricula.id_periodo == periodo.unique_id)
        ) or 0
        cursos = db.session.scalar(
            db.select(func.count())
            .select_from(MatriculaDetalle)
            .join(Matricula, Matricula.nro_matricula == MatriculaDetalle.nro_matricula)
            .where(Matricula.id_periodo == periodo.unique_id, MatriculaDetalle.estado == "matriculado")
        ) or 0
        periodos.append({**periodo.to_dict(), "matriculas": matriculas, "cursos_matriculados": cursos})

    return jsonify(
        alumnos={
            "total": total_alumnos,
            "activos": activos,
            "inactivos": total_alumnos - activos,
            "pendientes_cambio_password": pendientes_password,
            "plan_2019": por_plan.get(1, 0),
        },
        periodos=periodos,
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
        alumno = db.session.get(Alumno, s.usuario) if s.rol == "alumno" else None
        data.append({
            "id": s.id,
            "rol": s.rol,
            "usuario": s.usuario,
            "nombre": f"{alumno.apellidos}, {alumno.nombres}" if alumno else s.usuario,
            "email": alumno.email if alumno else None,
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
    if solicitud.rol != "alumno":
        raise ApiError("solo_alumnos", "Las cuentas de administrador se restablecen con el enlace o desde el servidor.", 400)
    alumno = db.get_or_404(Alumno, solicitud.usuario)
    if accion == "enlace":
        from .auth import crear_solicitud, enlace_restablecer

        solicitud.estado = "atendida"
        solicitud.atendido_en = datetime.utcnow()
        _, token = crear_solicitud(alumno, "alumno", "oficina")
        db.session.commit()
        return jsonify(message="Enlace generado. Compártelo solo con el alumno.", enlace=enlace_restablecer(token))
    alumno.password_hash = generate_password_hash(alumno.cod_alumno)
    alumno.debe_cambiar_password = True
    solicitud.estado = "atendida"
    solicitud.atendido_en = datetime.utcnow()
    db.session.commit()
    return jsonify(message=f"Contraseña de {alumno.cod_alumno} restablecida a su código. Deberá cambiarla al ingresar.")
