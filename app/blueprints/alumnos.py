import re
from datetime import date

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

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
    PlanEstudio,
)
from ..security import admin_required, institutional_email, require_self_or_admin

bp = Blueprint("alumnos", __name__)

CODE_RE = re.compile(r"^\d{6,12}$")
ESTADOS_ALUMNO = {"activo", "inactivo"}


def _get_alumno(cod_alumno):
    alumno = db.session.get(Alumno, cod_alumno)
    if not alumno:
        raise ApiError("alumno_no_encontrado", f"No existe el alumno con código {cod_alumno}.", 404)
    return alumno


def _get_plan(id_plan):
    try:
        id_plan = int(id_plan)
    except (TypeError, ValueError):
        raise ApiError("datos_invalidos", "El plan curricular debe ser un número.", 400)
    plan = PlanEstudio.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=id_plan).first()
    if not plan:
        raise ApiError("plan_no_encontrado", "El plan curricular indicado no existe.", 404)
    return plan


def _clean_name(value, field):
    value = " ".join(str(value or "").split())
    if not value:
        raise ApiError("datos_invalidos", f"El campo {field} es obligatorio.", 400)
    if len(value) > 120:
        raise ApiError("datos_invalidos", f"El campo {field} es demasiado largo.", 400)
    return value


# ---------------------------------------------------------------------------
# Gestión de alumnos (solo administrador)
# ---------------------------------------------------------------------------
@bp.get("/alumnos")
@admin_required
def list_alumnos():
    query = Alumno.query
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                db.func.lower(Alumno.cod_alumno).like(like),
                db.func.lower(Alumno.nombres).like(like),
                db.func.lower(Alumno.apellidos).like(like),
                db.func.lower(Alumno.email).like(like),
            )
        )
    alumnos = query.order_by(Alumno.cod_alumno.asc()).all()
    return jsonify(alumnos=[a.to_dict() for a in alumnos])


@bp.post("/alumnos")
@admin_required
def create_alumno():
    """Registra un alumno con solo código, nombres, apellidos y plan.

    - El correo institucional se genera automáticamente: <código>@unfv.edu.pe
    - La contraseña inicial es el propio código y se exige cambiarla en el primer ingreso.
    """
    data = request.get_json(silent=True) or {}
    cod_alumno = str(data.get("cod_alumno") or "").strip()
    if not CODE_RE.match(cod_alumno):
        raise ApiError("codigo_invalido", "El código de alumno debe tener solo números (entre 6 y 12 dígitos).", 400)
    nombres = _clean_name(data.get("nombres"), "nombres")
    apellidos = _clean_name(data.get("apellidos"), "apellidos")
    plan = _get_plan(data.get("id_plan", 1))

    email = institutional_email(cod_alumno)
    if db.session.get(Alumno, cod_alumno):
        raise ApiError("alumno_duplicado", f"El código de alumno {cod_alumno} ya está registrado.", 409)
    if Alumno.query.filter(db.func.lower(Alumno.email) == email).first():
        raise ApiError("email_duplicado", f"El correo {email} ya está en uso.", 409)

    alumno = Alumno(
        cod_alumno=cod_alumno,
        nombres=nombres,
        apellidos=apellidos,
        email=email,
        password_hash=generate_password_hash(cod_alumno),
        cod_fac=plan.cod_fac,
        cod_esc=plan.cod_esc,
        corr_pe=plan.corr_pe,
        estado="activo",
        fecha_ingreso=date.today(),
        debe_cambiar_password=True,
    )
    db.session.add(alumno)
    db.session.commit()
    return jsonify(
        alumno=alumno.to_dict(),
        credenciales={"usuario": cod_alumno, "email": email, "password_inicial": cod_alumno},
    ), 201


@bp.patch("/alumnos/<cod_alumno>")
@admin_required
def update_alumno(cod_alumno):
    alumno = _get_alumno(cod_alumno)
    data = request.get_json(silent=True) or {}
    if "nombres" in data:
        alumno.nombres = _clean_name(data.get("nombres"), "nombres")
    if "apellidos" in data:
        alumno.apellidos = _clean_name(data.get("apellidos"), "apellidos")
    if "id_plan" in data:
        plan = _get_plan(data.get("id_plan"))
        alumno.corr_pe = plan.corr_pe
    if "estado" in data:
        estado = str(data.get("estado") or "").strip().lower()
        if estado not in ESTADOS_ALUMNO:
            raise ApiError("datos_invalidos", "El estado debe ser 'activo' o 'inactivo'.", 400)
        alumno.estado = estado
    db.session.commit()
    return jsonify(alumno=alumno.to_dict())


@bp.post("/alumnos/<cod_alumno>/reset-password")
@admin_required
def reset_password(cod_alumno):
    """Restablece la contraseña al código del alumno y obliga a cambiarla."""
    alumno = _get_alumno(cod_alumno)
    alumno.password_hash = generate_password_hash(alumno.cod_alumno)
    alumno.debe_cambiar_password = True
    db.session.commit()
    return jsonify(
        message=f"Contraseña restablecida. El alumno ingresará con su código ({alumno.cod_alumno}) y deberá cambiarla.",
        alumno=alumno.to_dict(),
    )


@bp.patch("/alumnos/<cod_alumno>/plan")
@admin_required
def update_plan(cod_alumno):
    alumno = _get_alumno(cod_alumno)
    data = request.get_json(silent=True) or {}
    plan = _get_plan(data.get("id_plan"))
    alumno.corr_pe = plan.corr_pe
    db.session.commit()
    return jsonify(alumno=alumno.to_dict())


# ---------------------------------------------------------------------------
# Consulta académica (el propio alumno o el administrador)
# ---------------------------------------------------------------------------
def _course_sets(alumno, passing_grade):
    rows = (
        db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso, MatriculaDetalle.nota_final)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == alumno.cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
        )
        .all()
    )
    approved, in_progress, failed = set(), set(), set()
    for corr, cod, nota in rows:
        key = corr * 1000 + cod
        if nota is None:
            in_progress.add(key)
        elif float(nota) >= passing_grade:
            approved.add(key)
        else:
            failed.add(key)
    return approved, in_progress, failed


@bp.get("/alumnos/<cod_alumno>/malla")
@jwt_required()
def malla(cod_alumno):
    require_self_or_admin(cod_alumno)
    alumno = _get_alumno(cod_alumno)
    passing_grade = current_app.config["PASSING_GRADE"]
    approved, in_progress, failed = _course_sets(alumno, passing_grade)

    courses = (
        Curso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe)
        .order_by(Curso.semestre, Curso.cod_curso)
        .all()
    )
    mezclas = MezclaCurso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe).all()
    prereqs_by_curso = {}
    for m in mezclas:
        prereqs_by_curso.setdefault(m.cod_curso, set()).add(alumno.corr_pe * 1000 + m.cod_curso_prerequisito)

    result = []
    for course in courses:
        id_c = course.corr_pe * 1000 + course.cod_curso
        required = prereqs_by_curso.get(course.cod_curso, set())
        if id_c in approved:
            status = "aprobado"
        elif id_c in in_progress:
            status = "en_curso"
        elif not required <= approved:
            status = "bloqueado_por_prerrequisito"
        elif id_c in failed:
            status = "desaprobado"
        else:
            status = "disponible"
        item = course.to_dict()
        item["estado"] = status
        item["prerrequisitos"] = sorted(required)
        result.append(item)

    return jsonify(alumno=alumno.to_dict(), cursos=result, nota_minima=passing_grade)


@bp.get("/alumnos/<cod_alumno>/historial")
@jwt_required()
def historial(cod_alumno):
    require_self_or_admin(cod_alumno)
    _get_alumno(cod_alumno)
    passing_grade = current_app.config["PASSING_GRADE"]

    rows = (
        db.session.query(MatriculaDetalle, Matricula, PeriodoAcademico, HorarioDCSeccion, Curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(PeriodoAcademico, Matricula.id_periodo == PeriodoAcademico.unique_id)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .join(
            Curso,
            (Curso.cod_fac == HorarioCab.cod_fac)
            & (Curso.cod_esc == HorarioCab.cod_esc)
            & (Curso.corr_pe == HorarioCab.corr_pe)
            & (Curso.cod_curso == HorarioDCSeccion.cod_curso),
        )
        .filter(Matricula.cod_alumno == cod_alumno, MatriculaDetalle.estado.in_(["matriculado", "retirado"]))
        .order_by(PeriodoAcademico.fec_inicio.desc(), Curso.semestre, Curso.cod_curso)
        .all()
    )
    historial_list = []
    for row in rows:
        detail = row.MatriculaDetalle
        academic_status = detail.estado
        if detail.estado == "matriculado":
            if detail.nota_final is None:
                academic_status = "en_curso"
            else:
                academic_status = "aprobado" if float(detail.nota_final) >= passing_grade else "desaprobado"
        historial_list.append({
            "id_detalle": detail.id,
            "nro_matricula": detail.nro_matricula,
            "id_seccion": detail.id_seccion,
            "periodo": row.PeriodoAcademico.to_dict(),
            "estado": detail.estado,
            "estado_academico": academic_status,
            "nota_final": float(detail.nota_final) if detail.nota_final is not None else None,
            "curso": row.Curso.to_dict(),
        })
    return jsonify(historial=historial_list, nota_minima=passing_grade)


# ---------------------------------------------------------------------------
# Calificaciones (solo administrador)
# ---------------------------------------------------------------------------
def _section_for_course(alumno, curso, periodo):
    return (
        HorarioDCSeccion.query.join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            HorarioCab.cod_per_acad == periodo.cod_per_acad,
            HorarioCab.cod_fac == alumno.cod_fac,
            HorarioCab.cod_esc == alumno.cod_esc,
            HorarioCab.corr_pe == alumno.corr_pe,
            HorarioDCSeccion.cod_curso == curso.cod_curso,
        )
        .order_by(HorarioDCSeccion.cod_seccion)
        .first()
    )


@bp.post("/alumnos/<cod_alumno>/calificar")
@admin_required
def calificar_curso(cod_alumno):
    """Registra o corrige la nota final (0 a 20) de un curso del plan del alumno.

    Si el alumno ya está matriculado en el curso se califica esa matrícula; si no,
    se registra la nota en una sección del curso del período indicado (o el primero).
    Nota >= PASSING_GRADE aprueba y habilita los cursos que lo tienen como prerrequisito.
    """
    alumno = _get_alumno(cod_alumno)
    data = request.get_json(silent=True) or {}
    cod_curso, nota = data.get("cod_curso"), data.get("nota")
    if cod_curso is None or nota is None or isinstance(nota, bool):
        raise ApiError("datos_invalidos", "Se requieren cod_curso y nota.", 400)
    try:
        nota = round(float(nota), 2)
        cod_curso = int(cod_curso)
    except (ValueError, TypeError):
        raise ApiError("nota_invalida", "La nota debe ser un número válido entre 0 y 20.", 400)
    if not 0 <= nota <= 20:
        raise ApiError("nota_fuera_de_rango", "La nota debe estar en el rango de 0 a 20.", 400)

    curso = Curso.query.filter_by(
        cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe, cod_curso=cod_curso
    ).first()
    if not curso:
        raise ApiError("curso_no_encontrado", f"El curso {cod_curso} no pertenece al plan del alumno.", 404)

    # 1. ¿Ya está matriculado en este curso (mismo plan)? Se prioriza la matrícula sin nota.
    existing = (
        db.session.query(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(PeriodoAcademico, Matricula.id_periodo == PeriodoAcademico.unique_id)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == alumno.cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
            HorarioCab.corr_pe == alumno.corr_pe,
            HorarioDCSeccion.cod_curso == curso.cod_curso,
        )
        .order_by(MatriculaDetalle.nota_final.is_(None).desc(), PeriodoAcademico.fec_inicio.desc())
        .first()
    )

    detalle = existing
    if detalle is None:
        periodos = PeriodoAcademico.query.order_by(PeriodoAcademico.fec_inicio.asc()).all()
        id_periodo = data.get("id_periodo")
        if id_periodo:
            periodos = [p for p in periodos if p.unique_id == int(id_periodo)] or periodos
        seccion = periodo = None
        for candidate in periodos:
            seccion = _section_for_course(alumno, curso, candidate)
            if seccion:
                periodo = candidate
                break
        if not seccion:
            raise ApiError("sin_seccion", "El curso no tiene secciones programadas en ningún período.", 409)

        matricula = Matricula.query.filter_by(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id).first()
        if not matricula:
            matricula = Matricula(cod_alumno=alumno.cod_alumno, id_periodo=periodo.unique_id, estado="confirmada", monto_pagado=0)
            db.session.add(matricula)
            db.session.flush()
        elif matricula.estado != "confirmada":
            raise ApiError("matricula_anulada", "La matrícula del alumno en ese período está anulada.", 409)

        detalle = MatriculaDetalle.query.filter_by(nro_matricula=matricula.nro_matricula, id_seccion=seccion.id_seccion).first()
        if not detalle:
            detalle = MatriculaDetalle(nro_matricula=matricula.nro_matricula, id_seccion=seccion.id_seccion)
            db.session.add(detalle)
        detalle.estado = "matriculado"

    detalle.nota_final = nota
    db.session.commit()

    passing_grade = current_app.config["PASSING_GRADE"]
    is_approved = nota >= passing_grade
    sucesores_cods = [
        m.cod_curso
        for m in MezclaCurso.query.filter_by(
            cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe, cod_curso_prerequisito=curso.cod_curso
        ).all()
    ]
    sucesores = (
        Curso.query.filter(
            Curso.cod_fac == alumno.cod_fac,
            Curso.cod_esc == alumno.cod_esc,
            Curso.corr_pe == alumno.corr_pe,
            Curso.cod_curso.in_(sucesores_cods),
        ).all()
        if sucesores_cods
        else []
    )
    nombres_sucesores = ", ".join(c.den_curso for c in sucesores) or "ninguno"
    nota_txt = f"{nota:g}"
    mensaje = (
        f"'{curso.den_curso}' APROBADO con {nota_txt}. Cursos que dependen de él: {nombres_sucesores}."
        if is_approved
        else f"'{curso.den_curso}' DESAPROBADO con {nota_txt}. Siguen bloqueados: {nombres_sucesores}."
    )
    return jsonify(
        success=True,
        curso=curso.to_dict(),
        nota_final=nota,
        estado_academico="aprobado" if is_approved else "desaprobado",
        es_aprobado=is_approved,
        nota_minima=passing_grade,
        sucesores=[{"cod_curso": c.cod_curso, "den_curso": c.den_curso, "semestre": c.semestre} for c in sucesores],
        mensaje=mensaje,
    )
