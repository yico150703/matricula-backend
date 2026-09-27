"""Reglas académicas compartidas: redondeo de notas, vacantes, cruces de horario y elegibilidad."""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from flask import current_app
from sqlalchemy import func

from .errors import ApiError
from .extensions import db
from .models import (
    Alumno,
    CarritoItem,
    Curso,
    HorarioCab,
    HorarioDCSeccion,
    Matricula,
    MatriculaDetalle,
    MezclaCurso,
)


# ---------------------------------------------------------------------------
# Notas
# ---------------------------------------------------------------------------
def redondear(valor):
    """Redondeo vigesimal UNFV: desde x.5 sube a x+1, por debajo queda en x (10.5 -> 11, 10.2 -> 10)."""
    if valor is None:
        return None
    return int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _nota(valor, campo):
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise ApiError("nota_invalida", f"{campo} debe ser un número entre 0 y 20.", 400)
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ApiError("nota_invalida", f"{campo} debe ser un número entre 0 y 20.", 400)
    if not 0 <= numero <= 20:
        raise ApiError("nota_fuera_de_rango", f"{campo} debe estar entre 0 y 20.", 400)
    return numero


def calcular_notas(data):
    """Calcula la nota final a partir de N1, N2, N3, sustitutorio y aplazado, o de una nota directa.

    - Promedio = media de las notas parciales registradas, redondeada (desde .5 sube).
    - El sustitutorio reemplaza a la nota parcial más baja si es mayor.
    - Si existe aplazado, la nota final es el aplazado redondeado.
    - La nota directa (`nota` o `nota_final`) se redondea igual.
    """
    parciales = {k: _nota(data.get(k), k.upper()) for k in ("n1", "n2", "n3")}
    sustitutorio = _nota(data.get("sustitutorio"), "Sustitutorio")
    aplazado = _nota(data.get("aplazado"), "Aplazado")
    directa = _nota(data.get("nota", data.get("nota_final")), "Nota")

    registradas = [v for v in parciales.values() if v is not None]
    promedio = None
    if registradas:
        valores = list(registradas)
        if sustitutorio is not None:
            menor = min(range(len(valores)), key=lambda i: valores[i])
            if sustitutorio > valores[menor]:
                valores[menor] = sustitutorio
        promedio = redondear(sum(valores) / len(valores))

    if aplazado is not None:
        final = redondear(aplazado)
    elif promedio is not None:
        final = promedio
    elif directa is not None:
        final = redondear(directa)
    else:
        raise ApiError("datos_invalidos", "Registra al menos una nota (N1, N2, N3) o la nota final.", 400)

    return {**parciales, "sustitutorio": sustitutorio, "aplazado": aplazado, "promedio": promedio, "nota_final": final}


def notas_detalle(detalle):
    def num(v):
        return float(v) if v is not None else None

    promedio = None
    parciales = [num(x) for x in (detalle.n1, detalle.n2, detalle.n3) if x is not None]
    if parciales:
        valores = list(parciales)
        su = num(detalle.sustitutorio)
        if su is not None:
            i = min(range(len(valores)), key=lambda k: valores[k])
            valores[i] = max(valores[i], su)
        promedio = redondear(sum(valores) / len(valores))
    return {
        "n1": num(detalle.n1),
        "n2": num(detalle.n2),
        "n3": num(detalle.n3),
        "sustitutorio": num(detalle.sustitutorio),
        "aplazado": num(detalle.aplazado),
        "promedio": promedio,
        "nota_final": redondear(detalle.nota_final) if detalle.nota_final is not None else None,
    }


# ---------------------------------------------------------------------------
# Estado académico del alumno
# ---------------------------------------------------------------------------
def course_sets(alumno):
    """Conjuntos de id_curso (plan*1000+cod) aprobados, en curso y desaprobados."""
    passing = current_app.config["PASSING_GRADE"]
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
    aprobados, en_curso, desaprobados = set(), set(), set()
    for corr, cod, nota in rows:
        key = corr * 1000 + cod
        if nota is None:
            en_curso.add(key)
        elif redondear(nota) >= passing:
            aprobados.add(key)
        else:
            desaprobados.add(key)
    return aprobados, en_curso, desaprobados - aprobados


def prerequisitos(alumno):
    mezclas = MezclaCurso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe).all()
    req = {}
    for m in mezclas:
        req.setdefault(m.cod_curso, set()).add(alumno.corr_pe * 1000 + m.cod_curso_prerequisito)
    return req


def ciclo_actual(alumno, aprobados=None):
    """Nivel del alumno: el menor ciclo que aún tiene cursos obligatorios sin aprobar."""
    if aprobados is None:
        aprobados = course_sets(alumno)[0]
    cursos = Curso.query.filter_by(cod_fac=alumno.cod_fac, cod_esc=alumno.cod_esc, corr_pe=alumno.corr_pe).all()
    pendientes = [c.semestre for c in cursos if not c.mencion_electiva and (c.corr_pe * 1000 + c.cod_curso) not in aprobados]
    return min(pendientes) if pendientes else 10


# ---------------------------------------------------------------------------
# Vacantes
# ---------------------------------------------------------------------------
def purgar_carritos_vencidos():
    CarritoItem.query.filter(CarritoItem.expira_en <= datetime.utcnow()).delete(synchronize_session=False)


def ocupacion(secciones, alumno=None):
    """Matriculados, reservas activas en carritos y límite efectivo por sección.

    El límite base es la capacidad del aula (cupo del horario oficial). A los alumnos que repiten
    el curso se les permite un sobrecupo, proporcional a cuántos repitentes aptos hay
    (máximo SOBRECUPO_REPITENTES por sección), para que no se queden sin poder llevarlo.
    """
    if not secciones:
        return {}
    ids = [s.id_seccion for s in secciones]
    ahora = datetime.utcnow()
    matriculados = dict(
        db.session.query(MatriculaDetalle.id_seccion, func.count())
        .join(Matricula, Matricula.nro_matricula == MatriculaDetalle.nro_matricula)
        .filter(MatriculaDetalle.id_seccion.in_(ids), MatriculaDetalle.estado == "matriculado", Matricula.estado == "confirmada")
        .group_by(MatriculaDetalle.id_seccion)
        .all()
    )
    reservas_q = db.session.query(CarritoItem.id_seccion, func.count()).filter(
        CarritoItem.id_seccion.in_(ids), CarritoItem.expira_en > ahora
    )
    if alumno is not None:
        reservas_q = reservas_q.filter(CarritoItem.cod_alumno != alumno.cod_alumno)
    reservados = dict(reservas_q.group_by(CarritoItem.id_seccion).all())

    # Repitentes aptos por curso: alumnos activos con el curso desaprobado y aún no aprobado
    passing = current_app.config["PASSING_GRADE"]
    cursos = {(s.curso_programado.horario_det.cabecera.corr_pe, s.cod_curso) for s in secciones if s.curso_programado}
    repitentes = {}
    if cursos:
        filas = (
            db.session.query(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso, Matricula.cod_alumno, func.max(MatriculaDetalle.nota_final))
            .select_from(MatriculaDetalle)
            .join(Matricula, Matricula.nro_matricula == MatriculaDetalle.nro_matricula)
            .join(HorarioDCSeccion, HorarioDCSeccion.id_seccion == MatriculaDetalle.id_seccion)
            .join(HorarioCab, HorarioCab.id_horario == HorarioDCSeccion.id_horario)
            .join(Alumno, Alumno.cod_alumno == Matricula.cod_alumno)
            .filter(
                MatriculaDetalle.estado == "matriculado",
                MatriculaDetalle.nota_final.is_not(None),
                Alumno.estado == "activo",
                HorarioDCSeccion.cod_curso.in_([c for _, c in cursos]),
            )
            .group_by(HorarioCab.corr_pe, HorarioDCSeccion.cod_curso, Matricula.cod_alumno)
            .all()
        )
        for corr, cod, _alumno, mejor in filas:
            if redondear(mejor) < passing:
                repitentes[(corr, cod)] = repitentes.get((corr, cod), 0) + 1

    es_repitente = set()
    if alumno is not None:
        _, _, desaprobados = course_sets(alumno)
        es_repitente = desaprobados

    max_extra = current_app.config["SOBRECUPO_REPITENTES"]
    resultado = {}
    for s in secciones:
        corr = s.curso_programado.horario_det.cabecera.corr_pe if s.curso_programado else 1
        clave = (corr, s.cod_curso)
        num_secciones = max(1, len(s.curso_programado.secciones)) if s.curso_programado else 1
        aptos = repitentes.get(clave, 0)
        sobrecupo = min(max_extra, -(-aptos // num_secciones)) if aptos else 0
        repite = (corr * 1000 + s.cod_curso) in es_repitente
        limite = s.cupo_maximo + (sobrecupo if repite else 0)
        resultado[s.id_seccion] = {
            "matriculados": matriculados.get(s.id_seccion, 0),
            "reservados": reservados.get(s.id_seccion, 0),
            "capacidad": s.cupo_maximo,
            "sobrecupo_repitentes": sobrecupo,
            "repitentes_aptos": aptos,
            "limite": limite,
            "es_repitente": repite,
        }
    return resultado


# ---------------------------------------------------------------------------
# Horarios
# ---------------------------------------------------------------------------
def cruzan(a, b):
    for x in a.bloques():
        for y in b.bloques():
            if x.dia == y.dia and x.hora_inicio < y.hora_fin and y.hora_inicio < x.hora_fin:
                return True
    return False


def creditos(seccion):
    return float(seccion.curso.cred) if seccion.curso else 0.0


def validar_secciones(alumno, periodo, nuevas, ocupadas, *, verificar_cupo=True):
    """Valida que el alumno pueda llevar las secciones `nuevas`, sumadas a las `ocupadas`
    (ya matriculadas o en el carrito). Lanza ApiError con un mensaje claro si algo falla."""
    if periodo.estado != "en_curso":
        raise ApiError("periodo_no_disponible", f"El período {periodo.cod_per_acad} no está abierto para matrícula.", 409)

    aprobados, en_curso, _ = course_sets(alumno)
    reqs = prerequisitos(alumno)
    cursos_ocupados = {o.cod_curso: o for o in ocupadas}

    for s in nuevas:
        nombre = s.curso.den_curso if s.curso else "la asignatura"
        cab = s.curso_programado.horario_det.cabecera if s.curso_programado else None
        if not cab or cab.cod_per_acad != periodo.cod_per_acad:
            raise ApiError("seccion_periodo_invalido", f"La sección de {nombre} no pertenece al período {periodo.cod_per_acad}.", 400)
        if cab.corr_pe != alumno.corr_pe:
            raise ApiError("plan_incompatible", f"{nombre} no pertenece a tu plan curricular.", 409)
        clave = alumno.corr_pe * 1000 + s.cod_curso
        if clave in aprobados:
            raise ApiError("curso_ya_aprobado", f"Ya aprobaste {nombre}.", 409)
        faltan = reqs.get(s.cod_curso, set()) - aprobados
        if faltan:
            raise ApiError("prerrequisito_pendiente", f"Para llevar {nombre} primero debes aprobar sus prerrequisitos.", 409)
        if s.cod_curso in cursos_ocupados and cursos_ocupados[s.cod_curso].id_seccion != s.id_seccion:
            raise ApiError("curso_duplicado", f"Ya tienes {nombre} en otra sección ({cursos_ocupados[s.cod_curso].cod_seccion}).", 409)
        if clave in en_curso and s.cod_curso not in cursos_ocupados:
            raise ApiError("curso_en_curso", f"{nombre} ya lo estás llevando en otro período.", 409)

    todas = [o for o in ocupadas if o.id_seccion not in {n.id_seccion for n in nuevas}] + list(nuevas)
    for i, a in enumerate(todas):
        for b in todas[i + 1:]:
            if a.cod_curso != b.cod_curso and cruzan(a, b):
                na = a.curso.den_curso if a.curso else "un curso"
                nb = b.curso.den_curso if b.curso else "otro curso"
                raise ApiError("cruce_horario", f"Cruce de horario: {na} ({a.cod_seccion}) con {nb} ({b.cod_seccion}).", 409)

    tope = current_app.config["MAX_CREDITS"]
    total = sum(creditos(x) for x in todas)
    if total > tope:
        raise ApiError("tope_creditos", f"Superas el máximo de {tope:g} créditos (tendrías {total:g}).", 409)

    if verificar_cupo:
        occ = ocupacion(nuevas, alumno)
        for s in nuevas:
            o = occ[s.id_seccion]
            if o["matriculados"] + o["reservados"] >= o["limite"]:
                nombre = s.curso.den_curso if s.curso else "la asignatura"
                raise ApiError(
                    "cupo_agotado",
                    f"No hay vacantes en {nombre} sección {s.cod_seccion} ({o['matriculados']}/{o['limite']}).",
                    409,
                )
    return total
