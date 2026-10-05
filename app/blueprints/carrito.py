"""Carrito de matrícula: el alumno reúne secciones de cualquier ciclo (p. ej. cursos que repite)
y las matricula en un solo paso. Cada ítem reserva la vacante durante CARRITO_MINUTOS."""
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select
from flask_jwt_extended import jwt_required

from ..academico import creditos, ocupacion, purgar_carritos_vencidos, validar_secciones
from ..errors import ApiError
from ..extensions import db
from ..models import Alumno, CarritoItem, HorarioDCSeccion, Matricula, PeriodoAcademico
from ..security import require_self_or_admin
from .matriculas import matricular, secciones_activas, serialize_enrollment

bp = Blueprint("carrito", __name__)


def _contexto(cod_alumno, id_periodo):
    require_self_or_admin(cod_alumno, "Solo puede operar sobre su propia selección de cursos.")
    alumno = db.get_or_404(Alumno, cod_alumno)
    periodo = db.get_or_404(PeriodoAcademico, id_periodo)
    purgar_carritos_vencidos()
    return alumno, periodo


def _items(alumno, periodo):
    return (
        CarritoItem.query.filter_by(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id)
        .order_by(CarritoItem.creado_en)
        .all()
    )


def _respuesta(alumno, periodo, extra=None):
    items = _items(alumno, periodo)
    matricula = Matricula.query.filter_by(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id).first()
    matriculadas = secciones_activas(matricula)
    secciones = [i.seccion for i in items]
    occ = ocupacion(secciones, alumno)
    expira = min((i.expira_en for i in items), default=None)
    body = {
        "items": [
            {"id": i.id, "agregado_en": i.creado_en.isoformat() + "Z", "seccion": i.seccion.to_dict(ocupacion=occ.get(i.id_seccion))}
            for i in items
        ],
        "expira_en": expira.isoformat() + "Z" if expira else None,
        "segundos_restantes": max(0, int((expira - datetime.utcnow()).total_seconds())) if expira else None,
        "minutos_reserva": current_app.config["CARRITO_MINUTOS"],
        "creditos_carrito": sum(creditos(s) for s in secciones),
        "creditos_matriculados": sum(creditos(s) for s in matriculadas),
        "max_creditos": current_app.config["MAX_CREDITS"],
        "hora_servidor": datetime.utcnow().isoformat() + "Z",
    }
    if extra:
        body.update(extra)
    return jsonify(body)


@bp.get("/carrito/<cod_alumno>")
@jwt_required()
def ver_carrito(cod_alumno):
    id_periodo = request.args.get("periodo", type=int)
    if not id_periodo:
        raise ApiError("periodo_requerido", "El parámetro periodo es obligatorio.", 400)
    alumno, periodo = _contexto(cod_alumno, id_periodo)
    db.session.commit()
    return _respuesta(alumno, periodo)


@bp.post("/carrito/<cod_alumno>")
@jwt_required()
def agregar(cod_alumno):
    """Agrega una o varias secciones. Si el curso ya estaba en el carrito, se cambia de sección."""
    data = request.get_json(silent=True) or {}
    id_periodo = data.get("id_periodo")
    ids = data.get("secciones") or ([data["id_seccion"]] if data.get("id_seccion") else [])
    if not isinstance(id_periodo, int) or not ids or not all(isinstance(i, int) for i in ids):
        raise ApiError("datos_invalidos", "Se requieren id_periodo y al menos una sección.", 400)
    alumno, periodo = _contexto(cod_alumno, id_periodo)

    # Mismo orden de bloqueo que en la matrícula: alumno y luego secciones (la vacante se cuenta sin carreras)
    db.session.execute(select(Alumno.cod_alumno).where(Alumno.cod_alumno == alumno.cod_alumno).with_for_update())
    nuevas = (
        db.session.execute(
            select(HorarioDCSeccion).where(HorarioDCSeccion.id_seccion.in_(ids)).order_by(HorarioDCSeccion.id_seccion).with_for_update()
        )
        .scalars()
        .all()
    )
    if len(nuevas) != len(set(ids)):
        raise ApiError("seccion_no_encontrada", "Una o más secciones no existen.", 404)
    cursos_nuevos = {s.cod_curso for s in nuevas}
    if len(cursos_nuevos) != len(nuevas):
        raise ApiError("curso_duplicado", "Elegiste dos secciones del mismo curso.", 400)

    items = _items(alumno, periodo)
    # Cambio de sección: el ítem anterior del mismo curso se reemplaza
    reemplazados = [i for i in items if i.seccion.cod_curso in cursos_nuevos]
    conservados = [i for i in items if i not in reemplazados]
    matricula = Matricula.query.filter_by(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id).first()
    matriculadas = secciones_activas(matricula)
    ya = {s.cod_curso for s in matriculadas} & cursos_nuevos
    if ya:
        raise ApiError("curso_duplicado", "Ese curso ya está en tu matrícula de este período.", 409)

    validar_secciones(alumno, periodo, nuevas, matriculadas + [i.seccion for i in conservados])

    ahora = datetime.utcnow()
    # La reserva corre desde el primer curso agregado (como en una tienda: no se renueva sola)
    expira = min((i.expira_en for i in conservados), default=ahora + timedelta(minutes=current_app.config["CARRITO_MINUTOS"]))
    for i in reemplazados:
        db.session.delete(i)
    db.session.flush()
    for s in nuevas:
        db.session.add(CarritoItem(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id, id_seccion=s.id_seccion, creado_en=ahora, expira_en=expira))
    db.session.commit()
    return _respuesta(alumno, periodo, {"mensaje": f"{len(nuevas)} curso(s) agregado(s) a tu selección." if len(nuevas) != 1 else "Curso agregado a tu selección."})


@bp.delete("/carrito/<cod_alumno>/<int:id_seccion>")
@jwt_required()
def quitar(cod_alumno, id_seccion):
    id_periodo = request.args.get("periodo", type=int)
    alumno, periodo = _contexto(cod_alumno, id_periodo)
    CarritoItem.query.filter_by(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id, id_seccion=id_seccion).delete()
    db.session.commit()
    return _respuesta(alumno, periodo)


@bp.delete("/carrito/<cod_alumno>")
@jwt_required()
def vaciar(cod_alumno):
    id_periodo = request.args.get("periodo", type=int)
    alumno, periodo = _contexto(cod_alumno, id_periodo)
    CarritoItem.query.filter_by(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id).delete()
    db.session.commit()
    return _respuesta(alumno, periodo)


@bp.post("/carrito/<cod_alumno>/confirmar")
@jwt_required()
def confirmar(cod_alumno):
    data = request.get_json(silent=True) or {}
    alumno, periodo = _contexto(cod_alumno, data.get("id_periodo"))
    items = _items(alumno, periodo)
    if not items:
        db.session.commit()
        raise ApiError("carrito_vacio", "No tienes cursos seleccionados o la reserva expiró. Vuelve a seleccionar los cursos.", 409)
    matricula = matricular(alumno, periodo, [i.id_seccion for i in items])
    return jsonify(matricula=serialize_enrollment(matricula), mensaje="Matrícula registrada."), 201
