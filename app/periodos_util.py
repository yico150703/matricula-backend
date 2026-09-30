"""Eliminación segura de un período que aún se está programando (sin matrículas ni notas)."""
from .errors import ApiError
from .extensions import db
from .models import (
    ActaNotas,
    CarritoItem,
    HorarioCab,
    HorarioDCSeccion,
    HorarioDCurso,
    HorarioDet,
    Matricula,
    ProcesoHorario,
    SeccionSesion,
    SolicitudCambio,
    SolicitudMensaje,
)


def puede_eliminarse(periodo):
    if periodo.estado not in ("programacion",):
        return False, "Solo se eliminan períodos que aún están en programación (antes de abrir la matrícula)."
    if Matricula.query.filter_by(id_periodo=periodo.unique_id).first():
        return False, "El período ya tiene matrículas."
    if ActaNotas.query.filter_by(id_periodo=periodo.unique_id).first():
        return False, "El período ya tiene actas de notas."
    return True, ""


def eliminar_periodo(periodo):
    ok, motivo = puede_eliminarse(periodo)
    if not ok:
        raise ApiError("periodo_no_eliminable", motivo, 409)
    cabs = HorarioCab.query.filter_by(cod_per_acad=periodo.cod_per_acad).all()
    ids_h = [c.id_horario for c in cabs]
    secciones = [s.id_seccion for s in HorarioDCSeccion.query.filter(HorarioDCSeccion.id_horario.in_(ids_h)).all()] if ids_h else []
    sols = [s.id for s in SolicitudCambio.query.filter_by(id_periodo=periodo.unique_id).all()]
    if sols:
        SolicitudMensaje.query.filter(SolicitudMensaje.id_solicitud.in_(sols)).delete(synchronize_session=False)
        SolicitudCambio.query.filter(SolicitudCambio.id.in_(sols)).delete(synchronize_session=False)
    CarritoItem.query.filter_by(id_periodo=periodo.unique_id).delete(synchronize_session=False)
    if secciones:
        SeccionSesion.query.filter(SeccionSesion.id_seccion.in_(secciones)).delete(synchronize_session=False)
        HorarioDCSeccion.query.filter(HorarioDCSeccion.id_seccion.in_(secciones)).delete(synchronize_session=False)
    if ids_h:
        HorarioDCurso.query.filter(HorarioDCurso.id_horario.in_(ids_h)).delete(synchronize_session=False)
        HorarioDet.query.filter(HorarioDet.id_horario.in_(ids_h)).delete(synchronize_session=False)
        HorarioCab.query.filter(HorarioCab.id_horario.in_(ids_h)).delete(synchronize_session=False)
    ProcesoHorario.query.filter_by(id_periodo=periodo.unique_id).delete(synchronize_session=False)
    db.session.delete(periodo)
