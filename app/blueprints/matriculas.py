from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import select

from ..academico import calcular_notas, notas_detalle, purgar_carritos_vencidos, redondear, validar_secciones
from ..errors import ApiError
from ..extensions import db
from ..models import Alumno, CarritoItem, HorarioDCSeccion, Matricula, MatriculaDetalle, PeriodoAcademico
from ..security import admin_required, require_self_or_admin

bp = Blueprint("matriculas", __name__)


def _assert_owner(cod_alumno):
    require_self_or_admin(cod_alumno, "Solo puede operar sobre su propia matrícula.")


def serialize_enrollment(matricula):
    passing = current_app.config["PASSING_GRADE"]
    detalles = []
    for detail in matricula.detalles:
        sec = detail.seccion
        curso_dict = sec.curso.to_dict() if (sec and sec.curso) else None
        notas = notas_detalle(detail)
        academic = detail.estado
        if detail.estado == "matriculado" and notas["nota_final"] is not None:
            academic = "aprobado" if notas["nota_final"] >= passing else "desaprobado"
        detalles.append({
            "id": detail.id,
            "estado": detail.estado,
            "estado_academico": academic,
            **notas,
            "seccion": sec.to_dict(curso_dict=curso_dict) if sec else None,
        })
    return {
        "nro_matricula": matricula.nro_matricula,
        "cod_alumno": matricula.cod_alumno,
        "periodo": matricula.periodo.to_dict(),
        "estado": matricula.estado,
        "fecha_matricula": matricula.fecha_matricula.isoformat() if matricula.fecha_matricula else None,
        "monto_pagado": float(matricula.monto_pagado),
        "detalles": detalles,
    }


def secciones_activas(matricula):
    if not matricula:
        return []
    return [d.seccion for d in matricula.detalles if d.estado == "matriculado" and d.seccion]


def matricular(alumno, periodo, ids):
    """Registra las secciones indicadas (validación completa con bloqueo de filas)."""
    if alumno.estado != "activo":
        raise ApiError("alumno_no_activo", "El alumno no está habilitado para matricularse.", 403)
    if len(ids) != len(set(ids)) or not all(isinstance(i, int) for i in ids) or not ids:
        raise ApiError("secciones_invalidas", "Las secciones deben ser identificadores enteros no repetidos.", 400)
    try:
        # Orden de bloqueo fijo (alumno y luego secciones por id) en matrícula y carrito: evita dobles matrículas
        # simultáneas del mismo alumno y que dos alumnos tomen la última vacante a la vez.
        db.session.execute(select(Alumno.cod_alumno).where(Alumno.cod_alumno == alumno.cod_alumno).with_for_update())
        secciones = (
            db.session.execute(
                select(HorarioDCSeccion).where(HorarioDCSeccion.id_seccion.in_(ids)).order_by(HorarioDCSeccion.id_seccion).with_for_update()
            )
            .scalars()
            .all()
        )
        if len(secciones) != len(ids):
            raise ApiError("seccion_no_encontrada", "Una o más secciones no existen.", 404)

        matricula = Matricula.query.filter_by(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id).with_for_update().first()
        if matricula and matricula.estado == "anulada":
            raise ApiError("matricula_anulada", "La matrícula existente está anulada y no puede modificarse.", 409)
        existentes = secciones_activas(matricula)
        repetidas = {s.id_seccion for s in existentes} & set(ids)
        if repetidas:
            raise ApiError("curso_duplicado", "Una de las secciones ya está en tu matrícula.", 409)

        validar_secciones(alumno, periodo, secciones, existentes)

        if not matricula:
            matricula = Matricula(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id, estado="confirmada", monto_pagado=0)
            db.session.add(matricula)
            db.session.flush()
        for s in secciones:
            previo = MatriculaDetalle.query.filter_by(nro_matricula=matricula.nro_matricula, id_seccion=s.id_seccion).first()
            if previo:  # un retiro previo de la misma sección se reactiva
                previo.estado = "matriculado"
            else:
                db.session.add(MatriculaDetalle(nro_matricula=matricula.nro_matricula, id_seccion=s.id_seccion, estado="matriculado"))
        CarritoItem.query.filter(
            CarritoItem.cod_alumno == alumno.cod_alumno,
            CarritoItem.id_periodo == periodo.unique_id,
            CarritoItem.id_seccion.in_(ids),
        ).delete(synchronize_session=False)
        db.session.commit()
    except ApiError:
        db.session.rollback()
        raise
    db.session.refresh(matricula)
    return matricula


@bp.post("/matriculas")
@jwt_required()
def create_enrollment():
    data = request.get_json(silent=True) or {}
    cod_alumno, id_periodo, ids = data.get("cod_alumno"), data.get("id_periodo"), data.get("secciones")
    if not cod_alumno or not isinstance(id_periodo, int) or not isinstance(ids, list):
        raise ApiError("datos_invalidos", "Se requieren cod_alumno, id_periodo y una lista de secciones.", 400)
    _assert_owner(cod_alumno)
    alumno = db.get_or_404(Alumno, cod_alumno)
    periodo = db.get_or_404(PeriodoAcademico, id_periodo)
    purgar_carritos_vencidos()
    matricula = matricular(alumno, periodo, ids)
    return jsonify(matricula=serialize_enrollment(matricula)), 201


@bp.get("/matriculas/<cod_alumno>")
@jwt_required()
def current_enrollment(cod_alumno):
    _assert_owner(cod_alumno)
    id_periodo = request.args.get("periodo", type=int)
    if not id_periodo:
        raise ApiError("periodo_requerido", "El parámetro periodo es obligatorio.", 400)
    matricula = Matricula.query.filter_by(cod_alumno=cod_alumno, id_periodo=id_periodo).first()
    # 200 con null: "sin matrícula" es un estado normal, no un error
    return jsonify(matricula=serialize_enrollment(matricula) if matricula else None)


@bp.delete("/matriculas/<int:nro_matricula>/detalle/<int:id_seccion>")
@jwt_required()
def withdraw_course(nro_matricula, id_seccion):
    matricula = db.get_or_404(Matricula, nro_matricula)
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
    if detail.nota_final is not None or any(v is not None for v in (detail.n1, detail.n2, detail.n3)):
        raise ApiError("retiro_no_disponible", "No puede retirar un curso que ya tiene notas registradas.", 409)
    detail.estado = "retirado"
    db.session.commit()
    return jsonify(message="Curso retirado correctamente.", matricula=serialize_enrollment(matricula))


@bp.patch("/matriculas/<int:nro_matricula>/detalle/<int:id_seccion>/nota")
@admin_required
def record_grade(nro_matricula, id_seccion):
    """Registra o corrige notas (N1, N2, N3, sustitutorio, aplazado o nota final directa)."""
    matricula = db.get_or_404(Matricula, nro_matricula)
    if matricula.periodo.estado != "historico":
        raise ApiError(
            "nota_por_acta",
            "Las notas de este período las registra el docente en su acta y las aprueba el Director de Escuela.",
            403,
        )
    data = request.get_json(silent=True) or {}
    notas = calcular_notas(data)
    detail = (
        MatriculaDetalle.query.filter_by(nro_matricula=nro_matricula, id_seccion=id_seccion, estado="matriculado")
        .with_for_update()
        .first()
    )
    if not detail:
        raise ApiError("detalle_no_encontrado", "No existe una matrícula activa para esa sección.", 404)
    for campo in ("n1", "n2", "n3", "sustitutorio", "aplazado", "nota_final"):
        setattr(detail, campo, notas[campo])
    db.session.commit()
    passing = current_app.config["PASSING_GRADE"]
    return jsonify(
        detalle={
            "id": detail.id,
            "nro_matricula": detail.nro_matricula,
            "id_seccion": detail.id_seccion,
            **notas_detalle(detail),
            "estado_academico": "aprobado" if redondear(detail.nota_final) >= passing else "desaprobado",
        },
        nota_minima=passing,
    )
