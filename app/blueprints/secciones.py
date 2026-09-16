from flask import Blueprint, jsonify, request
from ..errors import ApiError
from ..models import Curso, PeriodoAcademico, Seccion

bp = Blueprint("secciones", __name__)


@bp.get("/periodos/<int:id_periodo>/secciones")
def available_sections(id_periodo):
    PeriodoAcademico.query.get_or_404(id_periodo)
    id_curso = request.args.get("curso", type=int)
    if not id_curso:
        raise ApiError("curso_requerido", "El parámetro de consulta curso es obligatorio.", 400)
    Curso.query.get_or_404(id_curso)
    sections = Seccion.query.filter_by(id_periodo=id_periodo, id_curso=id_curso).order_by(Seccion.nro_seccion).all()
    return jsonify(secciones=[section.to_dict() for section in sections])
