from flask import Blueprint, jsonify, request
from ..errors import ApiError
from ..models import Curso, PeriodoAcademico, Seccion

bp = Blueprint("secciones", __name__)


@bp.get("/periodos/<int:id_periodo>/secciones")
def available_sections(id_periodo):
    PeriodoAcademico.query.get_or_404(id_periodo)
    id_curso = request.args.get("curso", type=int)
    query = Seccion.query.filter_by(id_periodo=id_periodo)
    if id_curso:
        Curso.query.get_or_404(id_curso)
        query = query.filter_by(id_curso=id_curso)
    sections = query.order_by(Seccion.id_curso, Seccion.nro_seccion).all()
    return jsonify(secciones=[section.to_dict() for section in sections])
