from flask import Blueprint, jsonify, request
from ..models import Curso, HorarioCab, HorarioDCSeccion, PeriodoAcademico

bp = Blueprint("secciones", __name__)


@bp.get("/periodos/<int:id_periodo>/secciones")
def available_sections(id_periodo):
    periodo = PeriodoAcademico.query.filter_by(unique_id=id_periodo).first_or_404()
    query = (
        HorarioDCSeccion.query
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .join(
            Curso,
            (Curso.cod_fac == HorarioCab.cod_fac)
            & (Curso.cod_esc == HorarioCab.cod_esc)
            & (Curso.corr_pe == HorarioCab.corr_pe)
            & (Curso.cod_curso == HorarioDCSeccion.cod_curso),
        )
        .filter(
            HorarioCab.cod_per_acad == periodo.cod_per_acad,
            HorarioCab.cod_fac == 1,
            HorarioCab.cod_esc == 1,
        )
        .add_columns(Curso)
    )

    plan_filter = request.args.get("plan", type=int)
    if plan_filter:
        query = query.filter(HorarioCab.corr_pe == plan_filter)

    ciclo_filter = request.args.get("ciclo", type=int)
    if ciclo_filter:
        query = query.filter(HorarioDCSeccion.semestre_corr == ciclo_filter)

    curso_filter = request.args.get("curso", type=int)
    if curso_filter:
        if curso_filter >= 1000:
            c_plan = curso_filter // 1000
            c_cod = curso_filter % 1000
            query = query.filter(HorarioCab.corr_pe == c_plan, HorarioDCSeccion.cod_curso == c_cod)
        else:
            query = query.filter(HorarioDCSeccion.cod_curso == curso_filter)

    results = query.order_by(HorarioDCSeccion.semestre_corr, HorarioDCSeccion.cod_curso, HorarioDCSeccion.cod_seccion).all()
    secciones_list = [sec.to_dict(curso_dict=cur.to_dict()) for sec, cur in results]
    return jsonify(secciones=secciones_list)
