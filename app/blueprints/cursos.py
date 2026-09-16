from flask import Blueprint, jsonify
from ..models import Curso

bp = Blueprint("cursos", __name__)


@bp.get("/cursos/<int:id_curso>/prerrequisitos")
def prerequisites(id_curso):
    curso = Curso.query.get_or_404(id_curso)
    return jsonify(curso=curso.to_dict(), prerrequisitos=[edge.prerrequisito.to_dict() for edge in curso.prerrequisitos])
