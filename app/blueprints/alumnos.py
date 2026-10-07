import re
from datetime import date, time

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from ..academico import calcular_notas, ciclo_actual, course_sets, notas_detalle, ocupacion, prerequisitos, purgar_carritos_vencidos, redondear
from ..errors import ApiError, entero
from ..extensions import db
from ..fechas import hoy
from ..models import (
    ActaNotas,
    Alumno,
    CarritoItem,
    Curso,
    HorarioCab,
    HorarioDCSeccion,
    HorarioDCurso,
    HorarioDet,
    Matricula,
    MatriculaDetalle,
    MezclaCurso,
    PeriodoAcademico,
    PlanEstudio,
    SolicitudPassword,
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
        fecha_ingreso=hoy(),
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


@bp.delete("/alumnos/<cod_alumno>")
@admin_required
def delete_alumno(cod_alumno):
    """Elimina al alumno con todo su registro: matrículas, notas, cursos seleccionados y solicitudes de contraseña.
    Sus vacantes quedan libres (la ocupación se calcula con las matrículas)."""
    import json as _json

    alumno = _get_alumno(cod_alumno)
    if alumno.cuenta_prueba:
        raise ApiError("cuenta_prueba", "Es la cuenta de prueba compartida: se vuelve a crear en cada arranque, así que no se elimina.", 409)
    nombre = f"{alumno.apellidos}, {alumno.nombres}"
    matriculas = [m.nro_matricula for m in Matricula.query.filter_by(cod_alumno=alumno.cod_alumno).all()]
    if matriculas:
        MatriculaDetalle.query.filter(MatriculaDetalle.nro_matricula.in_(matriculas)).delete(synchronize_session=False)
        Matricula.query.filter(Matricula.nro_matricula.in_(matriculas)).delete(synchronize_session=False)
    CarritoItem.query.filter_by(cod_alumno=alumno.cod_alumno).delete(synchronize_session=False)
    SolicitudPassword.query.filter_by(rol="alumno", usuario=alumno.cod_alumno).delete(synchronize_session=False)
    # Borradores de notas que el docente tenga de este alumno en sus actas
    for acta in ActaNotas.query.all():
        notas = _json.loads(acta.notas or "{}")
        if alumno.cod_alumno in notas:
            notas.pop(alumno.cod_alumno)
            acta.notas = _json.dumps(notas)
    db.session.delete(alumno)
    db.session.commit()
    return jsonify(message=f"Alumno {alumno.cod_alumno} ({nombre}) eliminado.")


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
@bp.get("/alumnos/<cod_alumno>/malla")
@jwt_required()
def malla(cod_alumno):
    require_self_or_admin(cod_alumno)
    alumno = _get_alumno(cod_alumno)
    passing_grade = current_app.config["PASSING_GRADE"]
    approved, in_progress, failed = course_sets(alumno)

    courses = (
        Curso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe)
        .order_by(Curso.semestre, Curso.cod_curso)
        .all()
    )
    prereqs_by_curso = prerequisitos(alumno)

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

    return jsonify(alumno=alumno.to_dict(), cursos=result, nota_minima=passing_grade, ciclo_actual=ciclo_actual(alumno, approved))


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
        notas = notas_detalle(detail)
        if detail.estado == "matriculado":
            if notas["nota_final"] is None:
                academic_status = "en_curso"
            else:
                academic_status = "aprobado" if notas["nota_final"] >= passing_grade else "desaprobado"
        historial_list.append({
            **notas,
            "turno": row.HorarioDCSeccion.turno,
            "seccion": row.HorarioDCSeccion.cod_seccion,
            "id_detalle": detail.id,
            "nro_matricula": detail.nro_matricula,
            "id_seccion": detail.id_seccion,
            "periodo": row.PeriodoAcademico.to_dict(),
            "estado": detail.estado,
            "estado_academico": academic_status,
            "curso": row.Curso.to_dict(),
        })
    alumno = db.session.get(Alumno, cod_alumno)
    return jsonify(historial=historial_list, nota_minima=passing_grade, alumno=alumno.to_dict(), ciclo_actual=ciclo_actual(alumno))


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


HISTORICO = "HISTORICO"


def _seccion_historica(alumno, curso):
    """Período y sección 'H' (registro histórico) para notas de cursos llevados fuera del sistema."""
    periodo = PeriodoAcademico.query.filter_by(cod_per_acad=HISTORICO).first()
    if not periodo:
        nuevo_id = (db.session.query(db.func.max(PeriodoAcademico.unique_id)).scalar() or 0) + 1
        periodo = PeriodoAcademico(unique_id=nuevo_id, cod_per_acad=HISTORICO, fec_inicio=date(2000, 1, 1), fec_fin=date(2025, 12, 31), estado="historico")
        db.session.add(periodo)
        db.session.flush()
    cab = HorarioCab.query.filter_by(cod_per_acad=HISTORICO, cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe).first()
    if not cab:
        nuevo_id = (db.session.query(db.func.max(HorarioCab.id_horario)).scalar() or 0) + 1
        cab = HorarioCab(id_horario=nuevo_id, cod_per_acad=HISTORICO, cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe, fec_inicio=periodo.fec_inicio)
        db.session.add(cab)
        db.session.flush()
        for sem in range(1, 11):
            db.session.add(HorarioDet(id_horario=cab.id_horario, semestre_corr=sem, semestre_desc=f"Ciclo {sem}"))
        db.session.flush()
    seccion = HorarioDCSeccion.query.filter_by(id_horario=cab.id_horario, cod_curso=curso.cod_curso).first()
    if not seccion:
        if not db.session.get(HorarioDCurso, (cab.id_horario, curso.semestre, curso.cod_curso)):
            db.session.add(HorarioDCurso(id_horario=cab.id_horario, semestre_corr=curso.semestre, cod_curso=curso.cod_curso, nro_secc=1))
            db.session.flush()
        nuevo_id = (db.session.query(db.func.max(HorarioDCSeccion.id_seccion)).scalar() or 0) + 1
        seccion = HorarioDCSeccion(
            id_seccion=nuevo_id, id_horario=cab.id_horario, semestre_corr=curso.semestre, cod_curso=curso.cod_curso,
            cod_seccion="H", turno="M", dia_teoria=1, hora_inicio=time(0, 0), hora_fin=time(0, 0),
            aula="-", docente="REGISTRO HISTORICO", cupo_maximo=999, cupo_disponible=999,
        )
        db.session.add(seccion)
        db.session.flush()
    return periodo, seccion


ACTA_REQUERIDA = (
    "nota_por_acta",
    "Las notas de los cursos llevados en el sistema las registra el docente en su acta y las aprueba el Director de Escuela. "
    "Aquí solo se registran notas de cursos llevados antes del sistema.",
)


@bp.post("/alumnos/<cod_alumno>/calificar")
@admin_required
def calificar_curso(cod_alumno):
    """Registra o corrige las notas de un curso del plan del alumno.

    Acepta N1, N2, N3 (con sustitutorio y aplazado opcionales) o una nota final directa.
    El resultado se redondea como en la UNFV: desde x.5 sube (10.5 -> 11), si no, baja (10.2 -> 10).
    Si el alumno ya está matriculado en el curso se califica esa matrícula; si no,
    se registra la nota en una sección del curso del período indicado (o el primero con oferta).
    """
    alumno = _get_alumno(cod_alumno)
    data = request.get_json(silent=True) or {}
    try:
        cod_curso = int(data.get("cod_curso"))
    except (TypeError, ValueError):
        raise ApiError("datos_invalidos", "Se requiere cod_curso.", 400)
    notas = calcular_notas(data)
    nota = notas["nota_final"]

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

    # Las notas de los cursos llevados en el sistema las registra el docente y las aprueba el Director de Escuela
    # (actas de notas). El administrador solo registra notas de cursos llevados antes del sistema (histórico).
    if existing is not None and existing.matricula.periodo.estado != "historico":
        raise ApiError(ACTA_REQUERIDA[0], ACTA_REQUERIDA[1], 403)
    detalle = existing
    if detalle is None:
        if data.get("id_periodo"):
            raise ApiError(ACTA_REQUERIDA[0], ACTA_REQUERIDA[1], 403)
        else:
            # Nota de un curso llevado antes del sistema: se guarda como registro histórico
            # (período cerrado aparte) para no ocupar créditos ni vacantes del semestre actual.
            periodo, seccion = _seccion_historica(alumno, curso)

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

    for campo in ("n1", "n2", "n3", "sustitutorio", "aplazado", "nota_final"):
        setattr(detalle, campo, notas[campo])
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
    nota_txt = f"{nota:02d}"
    mensaje = (
        f"'{curso.den_curso}' APROBADO con {nota_txt}. Cursos que dependen de él: {nombres_sucesores}."
        if is_approved
        else f"'{curso.den_curso}' DESAPROBADO con {nota_txt}. Siguen bloqueados: {nombres_sucesores}."
    )
    return jsonify(
        success=True,
        curso=curso.to_dict(),
        **notas_detalle(detalle),
        estado_academico="aprobado" if is_approved else "desaprobado",
        es_aprobado=is_approved,
        nota_minima=passing_grade,
        sucesores=[{"cod_curso": c.cod_curso, "den_curso": c.den_curso, "semestre": c.semestre} for c in sucesores],
        mensaje=mensaje,
    )


# ---------------------------------------------------------------------------
# Oferta de cursos del período para el alumno (vista de matrícula y carrito)
# ---------------------------------------------------------------------------
@bp.get("/alumnos/<cod_alumno>/oferta")
@jwt_required()
def oferta(cod_alumno):
    """Cursos del plan del alumno programados en el período, con su estado, secciones y vacantes."""
    from ..blueprints.secciones import query_secciones

    require_self_or_admin(cod_alumno)
    alumno = _get_alumno(cod_alumno)
    periodo = db.get_or_404(PeriodoAcademico, request.args.get("periodo", type=int))
    purgar_carritos_vencidos()
    db.session.commit()

    aprobados, en_curso, desaprobados = course_sets(alumno)
    reqs = prerequisitos(alumno)
    # Mientras el proceso de horarios no termina (fases 1-4), los alumnos no ven la programación
    rows = [] if periodo.estado == "programacion" else query_secciones(periodo, plan=alumno.corr_pe)
    occ = ocupacion([s for s, _ in rows], alumno)
    nombres = {
        c.corr_pe * 1000 + c.cod_curso: c.den_curso
        for c in Curso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe).all()
    }

    cursos = {}
    for seccion, curso in rows:
        clave = curso.corr_pe * 1000 + curso.cod_curso
        if clave not in cursos:
            faltan = reqs.get(curso.cod_curso, set()) - aprobados
            if clave in aprobados:
                estado = "aprobado"
            elif clave in en_curso:
                estado = "en_curso"
            elif faltan:
                estado = "bloqueado_por_prerrequisito"
            elif clave in desaprobados:
                estado = "desaprobado"
            else:
                estado = "disponible"
            cursos[clave] = {
                **curso.to_dict(),
                "estado": estado,
                "repitente": clave in desaprobados,
                "prerrequisitos_pendientes": [nombres.get(f, "") for f in sorted(faltan)],
                "secciones": [],
            }
        cursos[clave]["secciones"].append(seccion.to_dict(curso_dict=curso.to_dict(), ocupacion=occ.get(seccion.id_seccion)))

    return jsonify(
        periodo=periodo.to_dict(),
        ciclo_actual=ciclo_actual(alumno, aprobados),
        max_creditos=current_app.config["MAX_CREDITS"],
        minutos_reserva=current_app.config["CARRITO_MINUTOS"],
        cursos=sorted(cursos.values(), key=lambda c: (c["ciclo"], c["codigo_curso"])),
    )
