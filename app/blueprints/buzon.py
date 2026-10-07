"""Buzón del alumno (solo lectura de sus propios mensajes)."""
from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity

from ..errors import ApiError
from ..extensions import db
from ..models import MensajeBuzon
from ..security import roles_required

bp = Blueprint("buzon", __name__)


def _mios():
    return MensajeBuzon.query.filter_by(cod_alumno=get_jwt_identity())


@bp.get("/buzon")
@roles_required("alumno")
def listar():
    mensajes = _mios().order_by(MensajeBuzon.creado_en.desc(), MensajeBuzon.id.desc()).limit(100).all()
    return jsonify(mensajes=[m.to_dict() for m in mensajes], no_leidos=_mios().filter_by(leido=False).count())


@bp.get("/buzon/no-leidos")
@roles_required("alumno")
def no_leidos():
    return jsonify(no_leidos=_mios().filter_by(leido=False).count())


@bp.post("/buzon/<int:id_mensaje>/leido")
@roles_required("alumno")
def marcar_leido(id_mensaje):
    msg = _mios().filter_by(id=id_mensaje).first()
    if not msg:
        raise ApiError("mensaje_no_encontrado", "El mensaje no existe.", 404)
    msg.leido = True
    db.session.commit()
    return jsonify(mensaje=msg.to_dict(), no_leidos=_mios().filter_by(leido=False).count())


@bp.post("/buzon/leer-todos")
@roles_required("alumno")
def leer_todos():
    _mios().filter_by(leido=False).update({"leido": True}, synchronize_session=False)
    db.session.commit()
    return jsonify(no_leidos=0)
