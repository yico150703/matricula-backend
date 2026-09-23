from flask import Blueprint, jsonify, request

from ..errors import ApiError
from ..extensions import db
from ..models import PeriodoAcademico
from ..security import admin_required

bp = Blueprint("periodos", __name__)

ESTADOS_PERIODO = {"en_curso", "cerrado"}


@bp.get("/periodos")
def list_periodos():
    periodos = PeriodoAcademico.query.order_by(PeriodoAcademico.fec_inicio.asc()).all()
    return jsonify(periodos=[periodo.to_dict() for periodo in periodos])


@bp.patch("/periodos/<int:id_periodo>")
@admin_required
def update_periodo(id_periodo):
    """Abre o cierra un período para matrícula (solo administrador)."""
    periodo = db.get_or_404(PeriodoAcademico, id_periodo)
    data = request.get_json(silent=True) or {}
    estado = str(data.get("estado") or "").strip()
    if estado not in ESTADOS_PERIODO:
        raise ApiError("datos_invalidos", "El estado debe ser 'en_curso' o 'cerrado'.", 400)
    periodo.estado = estado
    db.session.commit()
    return jsonify(periodo=periodo.to_dict())
