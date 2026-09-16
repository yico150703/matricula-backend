from flask import Blueprint, jsonify, request
from ..models import Curso, Plan

bp = Blueprint("planes", __name__)


@bp.get("/planes")
def list_planes():
    return jsonify(planes=[plan.to_dict() for plan in Plan.query.order_by(Plan.id_plan).all()])


@bp.get("/planes/<int:id_plan>/cursos")
def list_cursos_plan(id_plan):
    Plan.query.get_or_404(id_plan)
    query = Curso.query.filter_by(id_plan=id_plan)
    ciclo = request.args.get("ciclo", type=int)
    if ciclo:
        query = query.join(Curso.ciclo).filter_by(numero_ciclo=ciclo)
    return jsonify(cursos=[curso.to_dict() for curso in query.order_by(Curso.id_ciclo, Curso.codigo_curso).all()])
