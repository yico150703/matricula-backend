from datetime import date
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import generate_password_hash
from ..errors import ApiError
from ..extensions import db
from ..models import (
    Alumno,
    Curso,
    HorarioCab,
    HorarioDet,
    HorarioDCurso,
    HorarioDCSeccion,
    Matricula,
    MatriculaDetalle,
    MezclaCurso,
    PeriodoAcademico,
    PlanEstudio,
)

bp = Blueprint("alumnos", __name__)


@bp.get("/alumnos")
def list_alumnos():
    alumnos = Alumno.query.order_by(Alumno.cod_alumno.asc()).all()
    return jsonify(alumnos=[a.to_dict() for a in alumnos])


@bp.post("/alumnos")
def create_alumno():
    data = request.get_json(silent=True) or {}
    cod_alumno = str(data.get("cod_alumno") or "").strip()
    nombres = str(data.get("nombres") or "").strip()
    apellidos = str(data.get("apellidos") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "").strip()
    id_plan = data.get("id_plan", 1)

    if not cod_alumno or not nombres or not apellidos or not email or not password:
        raise ApiError("datos_invalidos", "Código, nombres, apellidos, correo y contraseña son obligatorios.", 400)

    if Alumno.query.filter_by(cod_alumno=cod_alumno).first():
        raise ApiError("alumno_duplicado", f"El código de alumno {cod_alumno} ya está registrado.", 409)

    if Alumno.query.filter_by(email=email).first():
        raise ApiError("email_duplicado", f"El correo institucional {email} ya se encuentra registrado.", 409)

    plan = PlanEstudio.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=id_plan).first()
    if not plan:
        id_plan = 1

    nuevo_alumno = Alumno(
        cod_alumno=cod_alumno,
        nombres=nombres,
        apellidos=apellidos,
        email=email,
        password_hash=generate_password_hash(password),
        cod_fac=1,
        cod_esc=1,
        corr_pe=id_plan,
        estado="activo",
        fecha_ingreso=date.today(),
    )
    db.session.add(nuevo_alumno)
    db.session.commit()

    token = create_access_token(identity=nuevo_alumno.cod_alumno)
    return jsonify(alumno=nuevo_alumno.to_dict(), access_token=token), 201


def require_owner(cod_alumno):
    if get_jwt_identity() != cod_alumno:
        raise ApiError("acceso_denegado", "Solo puede consultar su propia información académica.", 403)


@bp.get("/alumnos/<cod_alumno>/malla")
@jwt_required()
def malla(cod_alumno):
    require_owner(cod_alumno)
    alumno = Alumno.query.get_or_404(cod_alumno)
    passing_grade = current_app.config["PASSING_GRADE"]

    approved_rows = (
        db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
            MatriculaDetalle.nota_final >= passing_grade,
        )
        .all()
    )
    approved = {corr * 1000 + cod for corr, cod in approved_rows}

    active_rows = (
        db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(PeriodoAcademico, Matricula.id_periodo == PeriodoAcademico.unique_id)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
            MatriculaDetalle.nota_final.is_(None),
        )
        .all()
    )
    in_progress = {corr * 1000 + cod for corr, cod in active_rows}

    failed_rows = (
        db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso)
        .select_from(MatriculaDetalle)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(HorarioDCSeccion, MatriculaDetalle.id_seccion == HorarioDCSeccion.id_seccion)
        .join(HorarioCab, HorarioDCSeccion.id_horario == HorarioCab.id_horario)
        .filter(
            Matricula.cod_alumno == cod_alumno,
            Matricula.estado == "confirmada",
            MatriculaDetalle.estado == "matriculado",
            MatriculaDetalle.nota_final.is_not(None),
            MatriculaDetalle.nota_final < passing_grade,
        )
        .all()
    )
    failed = {corr * 1000 + cod for corr, cod in failed_rows}

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
        elif id_c in failed:
            status = "desaprobado"
        elif required <= approved:
            status = "disponible"
        else:
            status = "bloqueado_por_prerrequisito"

        item = course.to_dict(include_prerequisites=True)
        item["estado"] = status
        item["prerrequisitos"] = list(required)
        result.append(item)

    return jsonify(alumno=alumno.to_dict(), cursos=result, nota_minima=passing_grade)


@bp.get("/alumnos/<cod_alumno>/historial")
@jwt_required()
def historial(cod_alumno):
    require_owner(cod_alumno)
    Alumno.query.get_or_404(cod_alumno)
    passing_grade = current_app.config["PASSING_GRADE"]

    query = (
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
        .filter(
            Matricula.cod_alumno == cod_alumno,
            MatriculaDetalle.estado.in_(["matriculado", "retirado"]),
        )
        .order_by(PeriodoAcademico.fec_inicio.desc(), Curso.semestre, Curso.cod_curso)
    )

    rows = query.all()
    historial_list = []
    for row in rows:
        detail = row.MatriculaDetalle
        academic_status = detail.estado
        if detail.estado == "matriculado" and detail.nota_final is not None:
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


@bp.patch("/alumnos/<cod_alumno>/plan")
@jwt_required()
def update_plan(cod_alumno):
    require_owner(cod_alumno)
    alumno = Alumno.query.get_or_404(cod_alumno)
    data = request.get_json(silent=True) or {}
    id_plan = data.get("id_plan")
    if not id_plan or not isinstance(id_plan, int):
        raise ApiError("datos_invalidos", "Se requiere el id_plan numérico.", 400)
    PlanEstudio.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=id_plan).first_or_404()
    alumno.corr_pe = id_plan
    db.session.commit()
    return jsonify(alumno=alumno.to_dict())


@bp.post("/alumnos/<cod_alumno>/calificar")
@jwt_required()
def calificar_curso(cod_alumno):
    """Permite registrar o modificar la calificación final (0 a 20) de cualquier curso de la malla.
    Nota >= 11 aprueba la asignatura y habilita sus prerrequisitos dependientes.
    Nota <= 10 desaprueba y mantiene bloqueados sus cursos dependientes."""
    alumno = Alumno.query.get_or_404(cod_alumno)
    data = request.get_json(silent=True) or {}
    cod_curso = data.get("cod_curso")
    nota = data.get("nota")

    if cod_curso is None or nota is None:
        raise ApiError("datos_invalidos", "Se requieren cod_curso y nota.", 400)

    try:
        nota = float(nota)
    except (ValueError, TypeError):
        raise ApiError("nota_invalida", "La nota debe ser un número válido entre 0 y 20.", 400)

    if not (0 <= nota <= 20):
        raise ApiError("nota_fuera_de_rango", "La nota debe estar en el rango de 0 a 20.", 400)

    # 1. Buscar el curso en la malla curricular del alumno
    curso = Curso.query.filter_by(
        cod_fac=alumno.cod_fac,
        cod_esc=alumno.cod_esc,
        corr_pe=alumno.corr_pe,
        cod_curso=int(cod_curso),
    ).first()

    if not curso:
        raise ApiError("curso_no_encontrado", f"No se encontró el curso {cod_curso} en el Plan del estudiante.", 404)

    # 2. Obtener o crear una sección para este curso
    seccion = HorarioDCSeccion.query.filter_by(cod_curso=curso.cod_curso).first()
    if not seccion:
        horario_cab = HorarioCab.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe).first()
        if not horario_cab:
            per = PeriodoAcademico.query.first()
            horario_cab = HorarioCab(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe, id_periodo=per.unique_id)
            db.session.add(horario_cab)
            db.session.flush()

        horario_det = HorarioDet.query.filter_by(id_horario=horario_cab.id_horario, semestre_corr=curso.semestre).first()
        if not horario_det:
            horario_det = HorarioDet(id_horario=horario_cab.id_horario, semestre_corr=curso.semestre)
            db.session.add(horario_det)
            db.session.flush()

        h_curso = HorarioDCurso.query.filter_by(id_horario=horario_cab.id_horario, semestre_corr=curso.semestre, cod_curso=curso.cod_curso).first()
        if not h_curso:
            h_curso = HorarioDCurso(id_horario=horario_cab.id_horario, semestre_corr=curso.semestre, cod_curso=curso.cod_curso, num_secciones=1)
            db.session.add(h_curso)
            db.session.flush()

        seccion = HorarioDCSeccion(
            id_horario=horario_cab.id_horario,
            semestre_corr=curso.semestre,
            cod_curso=curso.cod_curso,
            num_seccion=1,
            cod_docente=1,
            num_aula=101,
            num_vacantes=35,
            num_matriculados=1,
        )
        db.session.add(seccion)
        db.session.flush()

    # 3. Buscar o crear matrícula para registrar la nota
    periodo = PeriodoAcademico.query.filter_by(cod_per_acad="2026-1").first() or PeriodoAcademico.query.first()
    matricula = Matricula.query.filter_by(cod_alumno=cod_alumno, id_periodo=periodo.unique_id, estado="confirmada").first()
    if not matricula:
        matricula = Matricula(
            cod_alumno=cod_alumno,
            id_periodo=periodo.unique_id,
            estado="confirmada",
        )
        db.session.add(matricula)
        db.session.flush()

    # 4. Asignar nota_final
    detalle = (
        MatriculaDetalle.query.filter_by(nro_matricula=matricula.nro_matricula, id_seccion=seccion.id_seccion)
        .first()
    )
    if not detalle:
        detalle = MatriculaDetalle(
            nro_matricula=matricula.nro_matricula,
            id_seccion=seccion.id_seccion,
            estado="matriculado",
            nota_final=round(nota, 2),
        )
        db.session.add(detalle)
    else:
        detalle.nota_final = round(nota, 2)
        detalle.estado = "matriculado"

    db.session.commit()

    passing_grade = current_app.config.get("PASSING_GRADE", 11)
    is_approved = float(detalle.nota_final) >= passing_grade
    academic_status = "aprobado" if is_approved else "desaprobado"

    # 5. Obtener los cursos sucesores que exigen esta asignatura como prerrequisito
    sucesores_mezcla = MezclaCurso.query.filter_by(
        cod_fac=alumno.cod_fac,
        cod_esc=alumno.cod_esc,
        corr_pe=alumno.corr_pe,
        cod_curso_prerequisito=curso.cod_curso,
    ).all()

    sucesores_cods = [s.cod_curso for s in sucesores_mezcla]
    cursos_sucesores = (
        Curso.query.filter(
            Curso.cod_fac == alumno.cod_fac,
            Curso.cod_esc == alumno.cod_esc,
            Curso.corr_pe == alumno.corr_pe,
            Curso.cod_curso.in_(sucesores_cods),
        ).all()
        if sucesores_cods
        else []
    )

    sucesores_list = [
        {"cod_curso": c.cod_curso, "den_curso": c.den_curso, "semestre": c.semestre}
        for c in cursos_sucesores
    ]

    return jsonify({
        "success": True,
        "curso": curso.to_dict(),
        "nota_final": float(detalle.nota_final),
        "estado_academico": academic_status,
        "es_aprobado": is_approved,
        "nota_minima": passing_grade,
        "sucesores": sucesores_list,
        "mensaje": (
            f"Asignatura '{curso.den_curso}' APROBADA con nota {float(detalle.nota_final)} (>= 11). "
            f"Se han habilitado para matrícula sus cursos sucesores: {', '.join([c.den_curso for c in cursos_sucesores]) if cursos_sucesores else 'Ninguno'}."
            if is_approved
            else f"Asignatura '{curso.den_curso}' DESAPROBADA con nota {float(detalle.nota_final)} (<= 10). "
            f"Permanecen bloqueados sus cursos sucesores: {', '.join([c.den_curso for c in cursos_sucesores]) if cursos_sucesores else 'Ninguno'}."
        ),
    })

