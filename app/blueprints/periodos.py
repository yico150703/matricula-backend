from flask import Blueprint, jsonify
from ..models import PeriodoAcademico

bp = Blueprint("periodos", __name__)


@bp.get("/periodos")
def list_periodos():
    return jsonify(periodos=[periodo.to_dict() for periodo in PeriodoAcademico.query.order_by(PeriodoAcademico.fecha_inicio.desc()).all()])
