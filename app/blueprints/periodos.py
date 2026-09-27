from flask import Blueprint, jsonify, request

from ..errors import ApiError
from ..extensions import db
from ..models import PeriodoAcademico, ProcesoHorario
from ..security import admin_required

bp = Blueprint("periodos", __name__)

ESTADOS_PERIODO = {"en_curso", "cerrado"}


@bp.get("/periodos")
def list_periodos():
    periodos = PeriodoAcademico.query.filter(PeriodoAcademico.estado != "historico").order_by(PeriodoAcademico.fec_inicio.asc()).all()
    procesos = {p.id_periodo: p for p in ProcesoHorario.query.all()}
    data = []
    for periodo in periodos:
        proceso = procesos.get(periodo.unique_id)
        fase = proceso.fase if proceso else (5 if periodo.estado == "en_curso" else 7)
        data.append({**periodo.to_dict(), "fase": fase, "matricula_abierta": fase in (5, 6) and periodo.estado == "en_curso"})
    return jsonify(periodos=data)
