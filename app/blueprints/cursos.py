from flask import Blueprint, jsonify
from ..models import Curso, MezclaCurso

bp = Blueprint("cursos", __name__)


@bp.get("/cursos/<int:id_curso>/prerrequisitos")
def prerequisites(id_curso):
    if id_curso >= 1000:
        corr_pe = id_curso // 1000
        cod_c = id_curso % 1000
    else:
        corr_pe = 1
        cod_c = id_curso
    curso = Curso.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=corr_pe, cod_curso=cod_c).first_or_404()
    mezclas = MezclaCurso.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=corr_pe, cod_curso=cod_c).all()
    req_cods = [m.cod_curso_prerequisito for m in mezclas]
    req_cursos = (
        Curso.query.filter(Curso.cod_fac == 1, Curso.cod_esc == 1, Curso.corr_pe == corr_pe, Curso.cod_curso.in_(req_cods)).all()
        if req_cods else []
    )
    return jsonify(curso=curso.to_dict(), prerrequisitos=[rc.to_dict() for rc in req_cursos])
