from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from ..errors import ApiError
from ..extensions import db
from ..models import (
    Alumno,
    Curso,
    HorarioCab,
    HorarioDCSeccion,
    Matricula,
    MatriculaDetalle,
    MezclaCurso,
    PeriodoAcademico,
    PlanEstudio,
)

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
        db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(PeriodoAcademico, Matricula.id_periodo == PeriodoAcademico.unique_id)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
            PeriodoAcademico.estado == "cerrado",
            MatriculaDetalle.nota_final >= passing_grade,
        )
        .all()
    )
    approved = {corr * 1000 + cod for corr, cod in approved_rows}

    active_rows = (
        db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(PeriodoAcademico, Matricula.id_periodo == PeriodoAcademico.unique_id)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
            PeriodoAcademico.estado == "en_curso",
        )
        .all()
    )
    in_progress = {corr * 1000 + cod for corr, cod in active_rows}

    courses = (
        Curso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe)
        .order_by(Curso.semestre, Curso.cod_curso)
        .all()
    )

    mezclas = MezclaCurso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe).all()
    prereqs_by_curso = {}
    for m in mezclas:
        prereqs_by_curso.setdefault(m.cod_curso, set()).add(alumno.corr_pe * 1000 + m.cod_curso_prerequisito)

    result = []
    for course in courses:
        id_c = course.corr_pe * 1000 + course.cod_curso
        required = prereqs_by_curso.get(course.cod_curso, set())
        if id_c in approved:
            status = "aprobado"
        elif id_c in in_progress:
            status = "en_curso"
        elif required <= approved:
            status = "disponible"
        else:
            status = "bloqueado_por_prerrequisito"

        item = course.to_dict(include_prerequisites=True)
        item["estado"] = status
        item["prerrequisitos"] = list(required)
        result.append(item)

    return jsonify(alumno=alumno.to_dict(), cursos=result)


@bp.get("/alumnos/<cod_alumno>/historial")
@jwt_required()
def historial(cod_alumno):
    require_owner(cod_alumno)
    Alumno.query.get_or_404(cod_alumno)

    query = (
        db.session.query(MatriculaDetalle, Matricula, PeriodoAcademico, HorarioDCSeccion, Curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(PeriodoAcademico, Matricula.id_periodo == PeriodoAcademico.unique_id)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .join(
            Curso,
            (Curso.cod_fac == HorarioCab.cod_fac)
            & (Curso.cod_esc == HorarioCab.cod_esc)
            & (Curso.corr_pe == HorarioCab.corr_pe)
            & (Curso.cod_curso == HorarioDCSeccion.cod_curso),
        )
        .filter(
            Matricula.cod_alumno == cod_alumno,
            MatriculaDetalle.estado.in_(["matriculado", "retirado"]),
        )
        .order_by(PeriodoAcademico.fec_inicio.desc(), Curso.semestre, Curso.cod_curso)
    )

    rows = query.all()
    historial_list = [
        {
            "periodo": row.PeriodoAcademico.to_dict(),
            "estado": row.MatriculaDetalle.estado,
            "nota_final": float(row.MatriculaDetalle.nota_final) if row.MatriculaDetalle.nota_final is not None else None,
            "curso": row.Curso.to_dict(),
        }
        for row in rows
    ]
    return jsonify(historial=historial_list)


@bp.patch("/alumnos/<cod_alumno>/plan")
@jwt_required()
def update_plan(cod_alumno):
    require_owner(cod_alumno)
    alumno = Alumno.query.get_or_404(cod_alumno)
    data = request.get_json(silent=True) or {}
    id_plan = data.get("id_plan")
    if not id_plan or not isinstance(id_plan, int):
        raise ApiError("datos_invalidos", "Se requiere el id_plan numérico.", 400)
    PlanEstudio.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=id_plan).first_or_404()
    alumno.corr_pe = id_plan
    db.session.commit()
    return jsonify(alumno=alumno.to_dict())
