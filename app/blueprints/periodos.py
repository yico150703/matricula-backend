from flask import Blueprint, jsonify
from ..models import PeriodoAcademico

bp = Blueprint("periodos", __name__)


@bp.get("/periodos")
def list_periodos():
    periodos = PeriodoAcademico.query.order_by(PeriodoAcademico.fec_inicio.asc()).all()
    return jsonify(periodos=[periodo.to_dict() for periodo in periodos])
