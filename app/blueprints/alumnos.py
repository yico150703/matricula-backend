from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from ..errors import ApiError
from ..models import Alumno, Curso, Matricula, MatriculaDetalle, PeriodoAcademico, Seccion

bp = Blueprint("alumnos", __name__)


def require_owner(cod_alumno):
    if get_jwt_identity() != cod_alumno:
        raise ApiError("acceso_denegado", "Solo puede consultar su propia información académica.", 403)


@bp.get("/alumnos/<cod_alumno>/malla")
@jwt_required()
def malla(cod_alumno):
    require_owner(cod_alumno)
    alumno = Alumno.query.get_or_404(cod_alumno)
    passing_grade = current_app.config["PASSING_GRADE"]
    approved_rows = (
        MatriculaDetalle.query.join(Matricula).join(PeriodoAcademico).join(Seccion)
        .filter(Matricula.cod_alumno == cod_alumno, Matricula.estado == "confirmada", MatriculaDetalle.estado == "matriculado",
                PeriodoAcademico.estado == "cerrado", MatriculaDetalle.nota_final >= passing_grade)
        .with_entities(Seccion.id_curso).all()
    )
    approved = {row[0] for row in approved_rows}
    active_rows = (
        MatriculaDetalle.query.join(Matricula).join(PeriodoAcademico).join(Seccion)
        .filter(Matricula.cod_alumno == cod_alumno, Matricula.estado == "confirmada", MatriculaDetalle.estado == "matriculado",
                PeriodoAcademico.estado == "en_curso")
        .with_entities(Seccion.id_curso).all()
    )
    in_progress = {row[0] for row in active_rows}
    courses = Curso.query.filter_by(id_plan=alumno.id_plan).order_by(Curso.id_ciclo, Curso.codigo_curso).all()
    result = []
    for course in courses:
        required = {edge.id_prerrequisito for edge in course.prerrequisitos}
        status = "aprobado" if course.id_curso in approved else "en_curso" if course.id_curso in in_progress else "disponible" if required <= approved else "bloqueado_por_prerrequisito"
        item = course.to_dict(include_prerequisites=True)
        item["estado"] = status
        result.append(item)
    return jsonify(alumno=alumno.to_dict(), cursos=result)


@bp.get("/alumnos/<cod_alumno>/historial")
@jwt_required()
def historial(cod_alumno):
    require_owner(cod_alumno)
    Alumno.query.get_or_404(cod_alumno)
    details = (MatriculaDetalle.query.join(Matricula).join(PeriodoAcademico).join(Seccion).join(Curso)
               .filter(Matricula.cod_alumno == cod_alumno, MatriculaDetalle.estado.in_(["matriculado", "retirado"]))
               .order_by(PeriodoAcademico.fecha_inicio.desc(), Curso.id_ciclo, Curso.codigo_curso).all())
    return jsonify(historial=[{
        "periodo": detail.matricula.periodo.to_dict(), "estado": detail.estado,
        "nota_final": float(detail.nota_final) if detail.nota_final is not None else None,
        "curso": detail.seccion.curso.to_dict()
    } for detail in details])
