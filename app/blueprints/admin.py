from flask import Blueprint, jsonify
from sqlalchemy import func

from ..extensions import db
from ..models import Alumno, Matricula, MatriculaDetalle, PeriodoAcademico
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
    for periodo in PeriodoAcademico.query.order_by(PeriodoAcademico.fec_inicio).all():
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
            "plan_2010": por_plan.get(2, 0),
        },
        periodos=periodos,
    )
