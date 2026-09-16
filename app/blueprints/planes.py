from flask import Blueprint, jsonify, request
from ..models import Curso, PlanEstudio

bp = Blueprint("planes", __name__)


@bp.get("/planes")
def list_planes():
    planes = PlanEstudio.query.filter_by(cod_fac=1, cod_esc=1).order_by(PlanEstudio.corr_pe).all()
    return jsonify(planes=[plan.to_dict() for plan in planes])


@bp.get("/planes/<int:id_plan>/cursos")
def list_cursos_plan(id_plan):
    PlanEstudio.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=id_plan).first_or_404()
    query = Curso.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=id_plan)
    ciclo = request.args.get("ciclo", type=int)
    if ciclo:
        query = query.filter_by(semestre=ciclo)
    cursos = query.order_by(Curso.semestre, Curso.cod_curso).all()
    return jsonify(cursos=[curso.to_dict() for curso in cursos])
