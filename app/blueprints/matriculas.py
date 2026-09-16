from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import select
from ..errors import ApiError
from ..extensions import db
from ..models import (
    Alumno,
    Curso,
    HorarioCab,
    HorarioDCSeccion,
    Matricula,
    MatriculaDetalle,
    MezclaCurso,
    PeriodoAcademico,
)

bp = Blueprint("matriculas", __name__)


def _assert_owner(cod_alumno):
    if get_jwt_identity() != cod_alumno:
        raise ApiError("acceso_denegado", "Solo puede operar sobre su propia matrícula.", 403)


def _approved_course_ids(cod_alumno):
    grade = current_app.config["PASSING_GRADE"]
    rows = (
        db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, Matricula.nro_matricula == MatriculaDetalle.nro_matricula)
        .join(PeriodoAcademico, PeriodoAcademico.unique_id == Matricula.id_periodo)
        .join(HorarioDCSeccion, HorarioDCSeccion.id_seccion == MatriculaDetalle.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
            PeriodoAcademico.estado == "cerrado",
            MatriculaDetalle.nota_final >= grade,
        )
        .all()
    )
    return {corr * 1000 + cod for corr, cod in rows}


def _conflicts(first, second):
    return (
        first.dia_teoria == second.dia_teoria
        and first.hora_inicio < second.hora_fin
        and second.hora_inicio < first.hora_fin
    )


def _serialize_enrollment(matricula):
    detalles_list = []
    for detail in matricula.detalles:
        sec = detail.seccion
        curso_dict = sec.curso.to_dict() if (sec and sec.curso) else None
        detalles_list.append({
            "id": detail.id,
            "estado": detail.estado,
            "nota_final": float(detail.nota_final) if detail.nota_final is not None else None,
            "seccion": sec.to_dict(curso_dict=curso_dict) if sec else None,
        })
    return {
        "nro_matricula": matricula.nro_matricula,
        "cod_alumno": matricula.cod_alumno,
        "periodo": matricula.periodo.to_dict(),
        "estado": matricula.estado,
        "monto_pagado": float(matricula.monto_pagado),
        "detalles": detalles_list,
    }


@bp.post("/matriculas")
@jwt_required()
def create_enrollment():
    data = request.get_json(silent=True) or {}
    cod_alumno, id_periodo, raw_ids = data.get("cod_alumno"), data.get("id_periodo"), data.get("secciones")
    if not cod_alumno or not isinstance(id_periodo, int) or not isinstance(raw_ids, list) or not raw_ids:
        raise ApiError("datos_invalidos", "Se requieren cod_alumno, id_periodo y una lista no vacía de secciones.", 400)
    _assert_owner(cod_alumno)
    if len(raw_ids) != len(set(raw_ids)) or not all(isinstance(item, int) for item in raw_ids):
        raise ApiError("secciones_invalidas", "Las secciones deben ser identificadores enteros no repetidos.", 400)

    alumno = Alumno.query.get_or_404(cod_alumno)
    if alumno.estado != "activo":
        raise ApiError("alumno_no_activo", "El alumno no está habilitado para matricularse.", 403)

    periodo = PeriodoAcademico.query.filter_by(unique_id=id_periodo).first_or_404()
    if periodo.estado != "en_curso":
        raise ApiError("periodo_no_disponible", "Solo se permite matrícula en períodos en curso.", 409)

    try:
        locked_sections = (
            db.session.execute(
                select(HorarioDCSeccion).where(HorarioDCSeccion.id_seccion.in_(raw_ids)).with_for_update()
            )
            .scalars()
            .all()
        )
        if len(locked_sections) != len(raw_ids):
            raise ApiError("seccion_no_encontrada", "Una o más secciones no existen.", 404)

        for section in locked_sections:
            cabecera = section.curso_programado.horario_det.cabecera if (section.curso_programado and section.curso_programado.horario_det) else None
            if not cabecera or cabecera.cod_per_acad != periodo.cod_per_acad:
                raise ApiError("seccion_periodo_invalido", "Una sección no pertenece al período indicado.", 400)
            if cabecera.corr_pe != alumno.corr_pe:
                raise ApiError("plan_incompatible", "La asignatura no pertenece al plan curricular del alumno.", 409)
            if section.cupo_disponible <= 0:
                raise ApiError("cupo_agotado", f"No hay vacantes en la sección {section.cod_seccion}.", 409)

        for index, section in enumerate(locked_sections):
            if any(_conflicts(section, other) for other in locked_sections[index + 1 :]):
                raise ApiError("cruce_horario", "Las secciones seleccionadas tienen cruce de horario entre sí.", 409)

        approved = _approved_course_ids(cod_alumno)
        for section in locked_sections:
            prereqs = MezclaCurso.query.filter_by(
                cod_fac=alumno.cod_fac,
                cod_esc=alumno.cod_esc,
                corr_pe=alumno.corr_pe,
                cod_curso=section.cod_curso,
            ).all()
            required_ids = {alumno.corr_pe * 1000 + m.cod_curso_prerequisito for m in prereqs}
            missing = required_ids - approved
            if missing:
                nombre = section.curso.den_curso if section.curso else "la asignatura"
                raise ApiError("prerrequisito_pendiente", f"No aprobó todos los prerrequisitos de {nombre}.", 409)

        matricula = Matricula.query.filter_by(cod_alumno=cod_alumno, id_periodo=id_periodo).with_for_update().first()
        if matricula and matricula.estado == "anulada":
            raise ApiError("matricula_anulada", "La matrícula existente está anulada y no puede modificarse.", 409)

        existing = [] if not matricula else [detail for detail in matricula.detalles if detail.estado == "matriculado"]
        existing_course_codes = {detail.seccion.cod_curso for detail in existing if detail.seccion}
        for section in locked_sections:
            if section.cod_curso in existing_course_codes:
                nombre = section.curso.den_curso if section.curso else "la asignatura"
                raise ApiError("curso_duplicado", f"El curso {nombre} ya está matriculado en este período.", 409)
            if any(_conflicts(section, detail.seccion) for detail in existing if detail.seccion):
                nombre = section.curso.den_curso if section.curso else "la asignatura"
                raise ApiError("cruce_horario", f"{nombre} se cruza con una sección ya matriculada.", 409)

        if not matricula:
            matricula = Matricula(cod_alumno=cod_alumno, id_periodo=id_periodo, estado="confirmada", monto_pagado=0)
            db.session.add(matricula)
            db.session.flush()

        for section in locked_sections:
            section.cupo_disponible -= 1
            db.session.add(
                MatriculaDetalle(nro_matricula=matricula.nro_matricula, id_seccion=section.id_seccion, estado="matriculado")
            )
        db.session.commit()
    except ApiError:
        db.session.rollback()
        raise

    return jsonify(matricula=_serialize_enrollment(matricula)), 201


@bp.get("/matriculas/<cod_alumno>")
@jwt_required()
def current_enrollment(cod_alumno):
    _assert_owner(cod_alumno)
    id_periodo = request.args.get("periodo", type=int)
    if not id_periodo:
        raise ApiError("periodo_requerido", "El parámetro periodo es obligatorio.", 400)
    matricula = Matricula.query.filter_by(cod_alumno=cod_alumno, id_periodo=id_periodo).first()
    if not matricula:
        raise ApiError("matricula_no_encontrada", "El alumno no tiene matrícula en el período solicitado.", 404)
    return jsonify(matricula=_serialize_enrollment(matricula))


@bp.delete("/matriculas/<int:nro_matricula>/detalle/<int:id_seccion>")
@jwt_required()
def withdraw_course(nro_matricula, id_seccion):
    matricula = Matricula.query.get_or_404(nro_matricula)
    _assert_owner(matricula.cod_alumno)
    if matricula.periodo.estado != "en_curso" or matricula.estado != "confirmada":
        raise ApiError("retiro_no_disponible", "Solo puede retirar cursos de una matrícula confirmada en período en curso.", 409)
    detail = (
        MatriculaDetalle.query.filter_by(nro_matricula=nro_matricula, id_seccion=id_seccion, estado="matriculado")
        .with_for_update()
        .first()
    )
    if not detail:
        raise ApiError("detalle_no_encontrado", "No existe una matrícula activa para esa sección.", 404)
    section = HorarioDCSeccion.query.filter_by(id_seccion=id_seccion).with_for_update().one()
    detail.estado = "retirado"
    section.cupo_disponible += 1
    db.session.commit()
    return jsonify(message="Curso retirado correctamente.", matricula=_serialize_enrollment(matricula))
