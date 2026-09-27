from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from sqlalchemy.orm import selectinload

from ..academico import ocupacion, purgar_carritos_vencidos
from ..extensions import db
from ..models import Alumno, Curso, HorarioCab, HorarioDCSeccion, HorarioDCurso, HorarioDet, PeriodoAcademico

bp = Blueprint("secciones", __name__)


def query_secciones(periodo, plan=None, ciclo=None, curso=None):
    query = (
        HorarioDCSeccion.query.join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .join(
            Curso,
            (Curso.cod_fac == HorarioCab.cod_fac)
            & (Curso.cod_esc == HorarioCab.cod_esc)
            & (Curso.corr_pe == HorarioCab.corr_pe)
            & (Curso.cod_curso == HorarioDCSeccion.cod_curso),
        )
        .filter(HorarioCab.cod_per_acad == periodo.cod_per_acad, HorarioCab.cod_fac == 1, HorarioCab.cod_esc == 1)
        .add_columns(Curso)
        .options(
            selectinload(HorarioDCSeccion.sesiones),
            selectinload(HorarioDCSeccion.curso_programado).selectinload(HorarioDCurso.secciones),
            selectinload(HorarioDCSeccion.curso_programado).selectinload(HorarioDCurso.horario_det).selectinload(HorarioDet.cabecera),
        )
    )
    if plan:
        query = query.filter(HorarioCab.corr_pe == plan)
    if ciclo:
        query = query.filter(HorarioDCSeccion.semestre_corr == ciclo)
    if curso:
        if curso >= 1000:
            query = query.filter(HorarioCab.corr_pe == curso // 1000, HorarioDCSeccion.cod_curso == curso % 1000)
        else:
            query = query.filter(HorarioDCSeccion.cod_curso == curso)
    return query.order_by(HorarioDCSeccion.semestre_corr, HorarioDCSeccion.cod_curso, HorarioDCSeccion.cod_seccion).all()


@bp.get("/periodos/<int:id_periodo>/secciones")
def available_sections(id_periodo):
    periodo = PeriodoAcademico.query.filter_by(unique_id=id_periodo).first_or_404()
    alumno = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity and not str(identity).startswith(("admin:", "staff:")):
            alumno = db.session.get(Alumno, identity)
    except Exception:  # token inválido: se responde como consulta pública
        alumno = None
    purgar_carritos_vencidos()
    db.session.commit()
    if periodo.estado == "programacion":
        return jsonify(secciones=[], mensaje="Los horarios de este período aún se están programando.")
    rows = query_secciones(
        periodo,
        plan=request.args.get("plan", type=int),
        ciclo=request.args.get("ciclo", type=int),
        curso=request.args.get("curso", type=int),
    )
    occ = ocupacion([s for s, _ in rows], alumno)
    return jsonify(secciones=[s.to_dict(curso_dict=c.to_dict(), ocupacion=occ.get(s.id_seccion)) for s, c in rows])
