"""Proceso de creación de horarios por período (6 fases) y solicitudes de cambio entre roles.

Fase 1  Jefe de Departamento arma los horarios por curso (secciones, turnos, días y horas).
Fase 2  Director de Escuela asigna un docente a cada sección (puede devolver al jefe).
Fase 3  Jefe y Director confirman; el Asistente de Escuela asigna aulas y laboratorios.
Fase 4  Cada docente confirma su horario o reporta un problema (solicitud de cambio).
Fase 5  Horarios establecidos: se abre la matrícula de los alumnos.
Fase 6  Ajustes de horario hasta DIAS_AJUSTE_HORARIO días después del inicio de clases.
Fase 7  Proceso y matrícula cerrados.

Cada rol solo puede editar en su fase. Después, cualquier cambio se pide con una solicitud
que el otro rol responsable debe aceptar; las solicitudes tienen un hilo de mensajes.
"""
import json
import re
from datetime import date, datetime, time, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.orm import selectinload

from ..errors import ApiError, entero
from ..extensions import db
from ..fechas import hoy
from ..models import (
    DIAS,
    FASES,
    ROLES_PERSONAL,
    Administrador,
    Curso,
    HorarioCab,
    HorarioDCSeccion,
    HorarioDCurso,
    HorarioDet,
    PeriodoAcademico,
    ProcesoHorario,
    SeccionSesion,
    SolicitudCambio,
    SolicitudMensaje,
    ubicacion_aula,
)
from ..security import current_admin_id, current_role, roles_required

bp = Blueprint("proceso", __name__)

PERSONAL = ("jefe", "director", "asistente", "docente")
GESTORES = ("jefe", "director", "asistente")
SIN_ASIGNAR = "POR ASIGNAR"
RESPONSABLE = {"horario": "jefe", "docente": "director", "aula": "asistente"}
CONTRAPARTE = {"jefe": "director", "director": "jefe", "asistente": "director"}
TIPO_POR_ROL = {"jefe": "horario", "director": "docente", "asistente": "aula"}
FASE_EDICION = {"jefe": 1, "director": 2, "asistente": 3}
HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# Hora académica UNFV: 50 minutos. Las clases se programan en bloques desde las 08:00 hasta las 22:10.
MINUTOS_HORA_ACADEMICA = 50
BLOQUES = [f"{(480 + 50 * i) // 60:02d}:{(480 + 50 * i) % 60:02d}" for i in range(18)]


def minutos_semana(sesiones):
    return sum((int(f[:2]) * 60 + int(f[3:])) - (int(i[:2]) * 60 + int(i[3:])) for _d, i, f in sesiones)


def horas_plan(curso):
    """Horas semanales del plan de estudios (HT + HP): el total del semestre es (HT+HP) × 16."""
    return (curso.ht or 0) + (curso.hp or 0) if curso else 0


def verificar_horas_plan(curso, sesiones):
    """Una sección debe dictar al menos las horas semanales del plan (puede tener horas extra de práctica)."""
    requeridas = horas_plan(curso)
    if requeridas and minutos_semana(sesiones) < requeridas * MINUTOS_HORA_ACADEMICA:
        tiene = minutos_semana(sesiones) // MINUTOS_HORA_ACADEMICA
        raise ApiError(
            "horas_insuficientes",
            f"{curso.den_curso} tiene {curso.ht} h de teoría y {curso.hp} h de práctica por semana en el plan: programa al menos "
            f"{requeridas} bloques de 50 min (ahora hay {tiene}).",
            400,
        )
AULAS_CATALOGO = [
    "B-503", "B-504", "B-505", "D-203", "D-204", "D-308",
    "LAB 1", "LAB 2", "LAB 3", "LAB 4", "LAB 5", "LAB 6", "LAB ELEC", "LAB FISICA",
]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def yo():
    user = db.session.get(Administrador, current_admin_id())
    if not user or not user.activo:
        raise ApiError("sesion_invalida", "Tu cuenta no está disponible.", 401)
    if user.rol != current_role():
        raise ApiError("sesion_invalida", "Tu rol cambió. Vuelve a iniciar sesión.", 401)
    return user


def obtener_proceso(periodo):
    proceso = db.session.get(ProcesoHorario, periodo.unique_id)
    if not proceso:
        fase = 5 if periodo.estado == "en_curso" else 7 if periodo.estado == "cerrado" else 1
        proceso = ProcesoHorario(id_periodo=periodo.unique_id, fase=fase, confirmado_jefe=fase >= 4, confirmado_director=fase >= 4, historial="[]")
        db.session.add(proceso)
        db.session.flush()
    return proceso


def registrar(proceso, user, accion):
    hist = json.loads(proceso.historial or "[]")
    hist.append({"fecha": datetime.utcnow().isoformat() + "Z", "fase": proceso.fase, "rol": user.rol, "usuario": user.to_dict()["nombre_completo"], "accion": accion})
    proceso.historial = json.dumps(hist[-60:], ensure_ascii=False)
    proceso.actualizado_en = datetime.utcnow()


def cambiar_fase(proceso, nueva, user, accion):
    proceso.fase = nueva
    periodo = proceso.periodo
    if nueva in (5, 6):
        periodo.estado = "en_curso"
    elif nueva == 7:
        periodo.estado = "cerrado"
    else:
        periodo.estado = "programacion"
    registrar(proceso, user, accion)


def avanzar_si_todos_confirmaron(proceso, periodo, user):
    """Fase 4 -> 5 automática: cuando todos los docentes confirmaron y no quedan solicitudes abiertas,
    los horarios quedan establecidos y se abre la matrícula de los alumnos."""
    if proceso.fase != 4:
        return False
    secciones = secciones_periodo(periodo)
    if not secciones or any(x.estado_docente != "confirmado" for x in secciones):
        return False
    if SolicitudCambio.query.filter_by(id_periodo=periodo.unique_id, estado="pendiente").first():
        return False
    cambiar_fase(proceso, 5, user, "Todos los docentes confirmaron: horarios establecidos y matrícula abierta automáticamente")
    return True


def periodo_o_404(id_periodo):
    periodo = db.session.get(PeriodoAcademico, id_periodo) if id_periodo else None
    if not periodo or periodo.estado == "historico":
        raise ApiError("periodo_no_encontrado", "El período no existe.", 404)
    return periodo


def cabecera(periodo):
    cab = HorarioCab.query.filter_by(cod_per_acad=periodo.cod_per_acad, cod_fac=1, cod_esc=1, corr_pe=1).first()
    if not cab:
        nuevo = (db.session.query(db.func.max(HorarioCab.id_horario)).scalar() or 0) + 1
        cab = HorarioCab(id_horario=nuevo, cod_per_acad=periodo.cod_per_acad, cod_fac=1, cod_esc=1, corr_pe=1, fec_inicio=periodo.fec_inicio)
        db.session.add(cab)
        db.session.flush()
        for sem in range(1, 11):
            db.session.add(HorarioDet(id_horario=nuevo, semestre_corr=sem, semestre_desc=f"Ciclo {sem}"))
        db.session.flush()
    return cab


def secciones_periodo(periodo):
    cab = HorarioCab.query.filter_by(cod_per_acad=periodo.cod_per_acad, cod_fac=1, cod_esc=1, corr_pe=1).first()
    if not cab:
        return []
    return (
        HorarioDCSeccion.query.filter_by(id_horario=cab.id_horario)
        .options(selectinload(HorarioDCSeccion.sesiones))
        .order_by(HorarioDCSeccion.semestre_corr, HorarioDCSeccion.cod_curso, HorarioDCSeccion.cod_seccion)
        .all()
    )


def ciclos_del_periodo(periodo):
    impar = periodo.cod_per_acad.endswith("-1")
    return [c for c in range(1, 11) if (c % 2 == 1) == impar]


def fechas(periodo):
    limite = periodo.fec_inicio + timedelta(days=current_app.config["DIAS_AJUSTE_HORARIO"])
    return {
        "inicio_clases": periodo.fec_inicio.isoformat(),
        "limite_ajustes": limite.isoformat(),
        "clases_iniciadas": hoy() >= periodo.fec_inicio,
        "ajustes_vencidos": hoy() > limite,
    }


def seccion_dict(s, curso=None):
    curso = curso or s.curso
    return {
        **s.to_dict(curso_dict=curso.to_dict() if curso else None),
        "sin_docente": s.id_docente is None and (s.docente or SIN_ASIGNAR) == SIN_ASIGNAR,
        "sin_aula": (s.aula or SIN_ASIGNAR) == SIN_ASIGNAR,
    }


def serializar_proceso(proceso, user=None):
    periodo = proceso.periodo
    secciones = secciones_periodo(periodo)
    pendientes = 0
    if user is not None:
        q = SolicitudCambio.query.filter_by(id_periodo=periodo.unique_id, estado="pendiente")
        pendientes = q.filter(SolicitudCambio.rol_destino == user.rol).count() if user.rol in GESTORES else 0
    conteo = {
        "secciones": len(secciones),
        "cursos": len({s.cod_curso for s in secciones}),
        "sin_docente": sum(1 for s in secciones if s.id_docente is None and s.docente == SIN_ASIGNAR),
        "sin_aula": sum(1 for s in secciones if (s.aula or SIN_ASIGNAR) == SIN_ASIGNAR),
        "docentes_pendientes": sum(1 for s in secciones if s.estado_docente == "pendiente" and s.id_docente),
        "docentes_observados": sum(1 for s in secciones if s.estado_docente == "observado"),
        "docentes_confirmados": sum(1 for s in secciones if s.estado_docente == "confirmado" and s.id_docente),
    }
    return {
        "id_periodo": periodo.unique_id,
        "periodo": periodo.to_dict(),
        "fase": proceso.fase,
        "fase_nombre": FASES.get(proceso.fase),
        "fases": [{"numero": n, "nombre": FASES[n]} for n in range(1, 8)],
        "confirmado_jefe": proceso.confirmado_jefe,
        "confirmado_director": proceso.confirmado_director,
        "observacion": proceso.observacion,
        "matricula_abierta": proceso.fase in (5, 6),
        "historial": list(reversed(json.loads(proceso.historial or "[]")))[:20],
        "conteo": conteo,
        "solicitudes_pendientes": pendientes,
        **fechas(periodo),
    }


def validar_sesiones(sesiones):
    if not isinstance(sesiones, list) or not sesiones:
        raise ApiError("datos_invalidos", "Indica al menos un día con hora de inicio y fin.", 400)
    limpias = []
    for s in sesiones:
        try:
            dia = int(s.get("dia"))
        except (TypeError, ValueError):
            raise ApiError("datos_invalidos", "Día inválido.", 400)
        ini, fin = str(s.get("hora_inicio") or s.get("inicio") or ""), str(s.get("hora_fin") or s.get("fin") or "")
        if not (1 <= dia <= 6) or not HORA_RE.match(ini) or not HORA_RE.match(fin):
            raise ApiError("datos_invalidos", "Usa días de lunes a sábado y horas en formato HH:MM.", 400)
        if ini not in BLOQUES or fin not in BLOQUES or not ini < fin:
            raise ApiError(
                "hora_fuera_de_bloque",
                f"Las horas van en bloques de 50 minutos desde las 08:00 (08:00, 08:50, 09:40, …, {BLOQUES[-1]}) y el fin debe ser mayor al inicio.",
                400,
            )
        limpias.append((dia, ini, fin))
    for i, a in enumerate(limpias):
        for b in limpias[i + 1:]:
            if a[0] == b[0] and a[1] < b[2] and b[1] < a[2]:
                raise ApiError("datos_invalidos", "Dos sesiones de la misma sección se superponen.", 400)
    return limpias


def _hora(t):
    h, m = t.split(":")
    return time(int(h), int(m))


def _solapan(a, b):
    return any(x.dia == y.dia and x.hora_inicio < y.hora_fin and y.hora_inicio < x.hora_fin for x in a.bloques() for y in b.bloques())


def cruces_de_seccion(s, todas):
    """Advertencias del jefe: la misma sección (letra) de un ciclo no debe cruzarse entre cursos."""
    avisos = []
    for o in todas:
        if o.id_seccion == s.id_seccion or o.cod_curso == s.cod_curso or o.cod_seccion == "E":
            continue
        if o.semestre_corr == s.semestre_corr and o.cod_seccion == s.cod_seccion and _solapan(s, o):
            avisos.append(f"Se cruza con {o.curso.den_curso if o.curso else o.cod_curso} ({o.cod_seccion})")
    return avisos


def verificar_docente(s, id_docente, todas):
    for o in todas:
        if o.id_seccion != s.id_seccion and o.id_docente == id_docente and _solapan(s, o):
            nombre = o.curso.den_curso if o.curso else o.cod_curso
            raise ApiError("cruce_docente", f"El docente ya dicta {nombre} ({o.cod_seccion}) en el mismo horario.", 409)


def verificar_aula(s, aula, todas, bloques=None):
    """Comprueba sesión por sesión que el aula no esté ocupada por otra sección a la misma hora."""
    if aula == SIN_ASIGNAR:
        return
    mias = bloques if bloques is not None else s.bloques()
    for o in todas:
        if o.id_seccion == s.id_seccion:
            continue
        for ob in o.bloques():
            if (ob.aula or o.aula or "").upper() != aula.upper():
                continue
            if any(b.dia == ob.dia and b.hora_inicio < ob.hora_fin and ob.hora_inicio < b.hora_fin for b in mias):
                nombre = o.curso.den_curso if o.curso else o.cod_curso
                raise ApiError("cruce_aula", f"{aula} ya está ocupada por {nombre} ({o.cod_seccion}) en ese horario.", 409)


def aplicar_sesiones(s, limpias):
    for ses in list(s.sesiones):
        db.session.delete(ses)
    db.session.flush()
    s.dia_teoria, s.hora_inicio, s.hora_fin = limpias[0][0], _hora(limpias[0][1]), _hora(limpias[0][2])
    for dia, ini, fin in limpias:
        db.session.add(SeccionSesion(id_seccion=s.id_seccion, dia=dia, hora_inicio=_hora(ini), hora_fin=_hora(fin), aula=s.aula or SIN_ASIGNAR))
    db.session.flush()
    db.session.refresh(s)


def aplicar_docente(s, docente):
    s.id_docente = docente.id_admin if docente else None
    s.docente = docente.nombre_docente if docente else SIN_ASIGNAR


def aplicar_aula(s, aula, sesion=None):
    """Asigna el aula a toda la sección o solo a una sesión (índice)."""
    if sesion is None or not s.sesiones:
        s.aula = aula
        for ses in s.sesiones:
            ses.aula = aula
        return
    s.sesiones[sesion].aula = aula
    aulas = [x.aula or SIN_ASIGNAR for x in s.sesiones]
    # La sección queda "con aula" solo cuando todas sus sesiones la tienen
    s.aula = SIN_ASIGNAR if SIN_ASIGNAR in aulas else aulas[0]


def exigir_fase_edicion(proceso, rol):
    if proceso.fase != FASE_EDICION[rol]:
        raise ApiError(
            "fase_incorrecta",
            f"Solo puedes editar directamente en la fase {FASE_EDICION[rol]}. Ahora estamos en la fase {proceso.fase}: usa una solicitud de cambio.",
            409,
        )


def seccion_del_periodo(id_seccion):
    s = db.session.get(HorarioDCSeccion, id_seccion)
    if not s or not s.curso_programado:
        raise ApiError("seccion_no_encontrada", "La sección no existe.", 404)
    periodo = PeriodoAcademico.query.filter_by(cod_per_acad=s.curso_programado.horario_det.cabecera.cod_per_acad).first()
    if not periodo or periodo.estado == "historico":
        raise ApiError("seccion_no_encontrada", "La sección no existe.", 404)
    return s, periodo, obtener_proceso(periodo)


def aula_valida(aula):
    aula = " ".join(str(aula or "").upper().split())
    if not aula or len(aula) > 30:
        raise ApiError("datos_invalidos", "Indica el aula o laboratorio.", 400)
    return aula


# ---------------------------------------------------------------------------
# Consulta del proceso (personal)
# ---------------------------------------------------------------------------
@bp.get("/proceso/periodos")
@roles_required(*PERSONAL, "admin")
def listar_procesos():
    user = yo()
    periodos = PeriodoAcademico.query.filter(PeriodoAcademico.estado != "historico").order_by(PeriodoAcademico.fec_inicio.desc()).all()
    data = [serializar_proceso(obtener_proceso(p), user) for p in periodos]
    db.session.commit()
    return jsonify(procesos=data, aulas=AULAS_CATALOGO, roles=ROLES_PERSONAL)


@bp.get("/proceso/<int:id_periodo>")
@roles_required(*GESTORES, "admin")
def detalle(id_periodo):
    user = yo()
    periodo = periodo_o_404(id_periodo)
    proceso = obtener_proceso(periodo)
    secciones = secciones_periodo(periodo)
    cursos = Curso.query.filter(Curso.cod_fac == 1, Curso.cod_esc == 1, Curso.corr_pe == 1, Curso.semestre.in_(ciclos_del_periodo(periodo))).order_by(Curso.semestre, Curso.cod_curso).all()
    por_curso = {}
    for s in secciones:
        por_curso.setdefault(s.cod_curso, []).append(s)
    lista = []
    for c in cursos:
        secs = por_curso.get(c.cod_curso, [])
        lista.append({
            **c.to_dict(),
            "secciones": [{**seccion_dict(s, c), "avisos": cruces_de_seccion(s, secciones)} for s in secs],
        })
    db.session.commit()
    return jsonify(proceso=serializar_proceso(proceso, user), cursos=lista, aulas=AULAS_CATALOGO)


@bp.get("/proceso/docentes")
@roles_required("director", "jefe", "asistente")
def docentes():
    id_periodo = request.args.get("periodo", type=int)
    carga = {}
    if id_periodo:
        for s in secciones_periodo(periodo_o_404(id_periodo)):
            if s.id_docente:
                c = carga.setdefault(s.id_docente, {"secciones": 0, "horas": 0.0})
                c["secciones"] += 1
                c["horas"] += sum((b.hora_fin.hour * 60 + b.hora_fin.minute - b.hora_inicio.hour * 60 - b.hora_inicio.minute) / 60 for b in s.bloques())
    lista = Administrador.query.filter_by(rol="docente", activo=True).order_by(Administrador.apellidos, Administrador.nombres).all()
    return jsonify(docentes=[{**d.to_dict(), "nombre_docente": d.nombre_docente, **carga.get(d.id_admin, {"secciones": 0, "horas": 0})} for d in lista])


# ---------------------------------------------------------------------------
# Fase 1 · Jefe de Departamento: secciones y horarios
# ---------------------------------------------------------------------------
@bp.post("/proceso/<int:id_periodo>/secciones")
@roles_required("jefe")
def crear_seccion(id_periodo):
    user = yo()
    periodo = periodo_o_404(id_periodo)
    proceso = obtener_proceso(periodo)
    exigir_fase_edicion(proceso, "jefe")
    data = request.get_json(silent=True) or {}
    curso = Curso.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=1, cod_curso=data.get("cod_curso")).first()
    if not curso:
        raise ApiError("curso_no_encontrado", "El curso no existe en el plan.", 404)
    letra = str(data.get("cod_seccion") or "").strip().upper()
    if letra not in ("A", "B", "C", "D", "E"):
        raise ApiError("datos_invalidos", "La sección debe ser A, B, C, D o E (electivos).", 400)
    turno = str(data.get("turno") or "").upper()
    if turno not in ("M", "T", "N"):
        raise ApiError("datos_invalidos", "El turno debe ser M, T o N.", 400)
    cupo = entero(data.get("cupo"), "cupo", por_defecto=30)
    if not 5 <= cupo <= 80:
        raise ApiError("datos_invalidos", "La capacidad debe estar entre 5 y 80.", 400)
    limpias = validar_sesiones(data.get("sesiones"))
    verificar_horas_plan(curso, limpias)

    cab = cabecera(periodo)
    hc = db.session.get(HorarioDCurso, (cab.id_horario, curso.semestre, curso.cod_curso))
    if not hc:
        hc = HorarioDCurso(id_horario=cab.id_horario, semestre_corr=curso.semestre, cod_curso=curso.cod_curso, nro_secc=0)
        db.session.add(hc)
        db.session.flush()
    if HorarioDCSeccion.query.filter_by(id_horario=cab.id_horario, cod_curso=curso.cod_curso, cod_seccion=letra).first():
        raise ApiError("seccion_duplicada", f"{curso.den_curso} ya tiene la sección {letra}.", 409)
    nuevo = (db.session.query(db.func.max(HorarioDCSeccion.id_seccion)).scalar() or 0) + 1
    s = HorarioDCSeccion(
        id_seccion=nuevo, id_horario=cab.id_horario, semestre_corr=curso.semestre, cod_curso=curso.cod_curso, cod_seccion=letra,
        turno=turno, dia_teoria=limpias[0][0], hora_inicio=_hora(limpias[0][1]), hora_fin=_hora(limpias[0][2]),
        aula=SIN_ASIGNAR, docente=SIN_ASIGNAR, cupo_maximo=cupo, cupo_disponible=cupo, estado_docente="pendiente",
    )
    db.session.add(s)
    db.session.flush()
    aplicar_sesiones(s, limpias)
    hc.nro_secc = (hc.nro_secc or 0) + 1
    registrar(proceso, user, f"Creó la sección {letra} de {curso.den_curso}")
    db.session.commit()
    return jsonify(seccion={**seccion_dict(s, curso), "avisos": cruces_de_seccion(s, secciones_periodo(periodo))}), 201


@bp.put("/proceso/secciones/<int:id_seccion>")
@roles_required("jefe")
def editar_seccion(id_seccion):
    user = yo()
    s, periodo, proceso = seccion_del_periodo(id_seccion)
    exigir_fase_edicion(proceso, "jefe")
    data = request.get_json(silent=True) or {}
    if "turno" in data:
        if data["turno"] not in ("M", "T", "N"):
            raise ApiError("datos_invalidos", "El turno debe ser M, T o N.", 400)
        s.turno = data["turno"]
    if "cupo" in data:
        s.cupo_maximo = s.cupo_disponible = max(5, min(80, entero(data["cupo"], "cupo")))
    if "sesiones" in data:
        limpias = validar_sesiones(data["sesiones"])
        verificar_horas_plan(s.curso, limpias)
        aplicar_sesiones(s, limpias)
    registrar(proceso, user, f"Editó la sección {s.cod_seccion} de {s.curso.den_curso if s.curso else s.cod_curso}")
    db.session.commit()
    return jsonify(seccion={**seccion_dict(s), "avisos": cruces_de_seccion(s, secciones_periodo(periodo))})


@bp.delete("/proceso/secciones/<int:id_seccion>")
@roles_required("jefe")
def eliminar_seccion(id_seccion):
    user = yo()
    s, periodo, proceso = seccion_del_periodo(id_seccion)
    exigir_fase_edicion(proceso, "jefe")
    nombre = s.curso.den_curso if s.curso else s.cod_curso
    registrar(proceso, user, f"Eliminó la sección {s.cod_seccion} de {nombre}")
    db.session.delete(s)
    db.session.commit()
    return jsonify(message="Sección eliminada.")


@bp.post("/proceso/<int:id_periodo>/copiar")
@roles_required("jefe")
def copiar_base(id_periodo):
    """Copia secciones, turnos y horas de otro período como punto de partida (sin docentes ni aulas)."""
    user = yo()
    periodo = periodo_o_404(id_periodo)
    proceso = obtener_proceso(periodo)
    exigir_fase_edicion(proceso, "jefe")
    origen = periodo_o_404((request.get_json(silent=True) or {}).get("desde_periodo"))
    if secciones_periodo(periodo):
        raise ApiError("ya_tiene_secciones", "Este período ya tiene secciones. Elimínalas antes de copiar otra base.", 409)
    cab = cabecera(periodo)
    ciclos = set(ciclos_del_periodo(periodo))
    nuevo = (db.session.query(db.func.max(HorarioDCSeccion.id_seccion)).scalar() or 0) + 1
    creadas = 0
    for o in secciones_periodo(origen):
        if o.semestre_corr not in ciclos:
            continue
        if not db.session.get(HorarioDCurso, (cab.id_horario, o.semestre_corr, o.cod_curso)):
            db.session.add(HorarioDCurso(id_horario=cab.id_horario, semestre_corr=o.semestre_corr, cod_curso=o.cod_curso, nro_secc=0))
            db.session.flush()
        hc = db.session.get(HorarioDCurso, (cab.id_horario, o.semestre_corr, o.cod_curso))
        hc.nro_secc += 1
        s = HorarioDCSeccion(
            id_seccion=nuevo, id_horario=cab.id_horario, semestre_corr=o.semestre_corr, cod_curso=o.cod_curso, cod_seccion=o.cod_seccion,
            turno=o.turno, dia_teoria=o.dia_teoria, hora_inicio=o.hora_inicio, hora_fin=o.hora_fin,
            aula=SIN_ASIGNAR, docente=SIN_ASIGNAR, cupo_maximo=o.cupo_maximo, cupo_disponible=o.cupo_maximo, estado_docente="pendiente",
        )
        db.session.add(s)
        for b in o.bloques():
            db.session.add(SeccionSesion(id_seccion=nuevo, dia=b.dia, hora_inicio=b.hora_inicio, hora_fin=b.hora_fin, aula=SIN_ASIGNAR))
        nuevo += 1
        creadas += 1
    if not creadas:
        raise ApiError(
            "sin_secciones_compatibles",
            f"{origen.cod_per_acad} no tiene secciones de los ciclos que se dictan en {periodo.cod_per_acad}. Elige un período del mismo semestre (-1 o -2).",
        )
    registrar(proceso, user, f"Copió {creadas} secciones de {origen.cod_per_acad} como base")
    db.session.commit()
    return jsonify(message=f"Se copiaron {creadas} secciones de {origen.cod_per_acad}. Revisa y ajusta los horarios.")


# ---------------------------------------------------------------------------
# Fase 2 · Director: docentes   |   Fase 3 · Asistente: aulas
# ---------------------------------------------------------------------------
@bp.put("/proceso/secciones/<int:id_seccion>/docente")
@roles_required("director")
def asignar_docente(id_seccion):
    user = yo()
    s, periodo, proceso = seccion_del_periodo(id_seccion)
    exigir_fase_edicion(proceso, "director")
    id_docente = (request.get_json(silent=True) or {}).get("id_docente")
    docente = None
    if id_docente:
        docente = Administrador.query.filter_by(id_admin=entero(id_docente, "id_docente"), rol="docente", activo=True).first()
        if not docente:
            raise ApiError("docente_no_encontrado", "El docente no existe o está inactivo.", 404)
        verificar_docente(s, docente.id_admin, secciones_periodo(periodo))
    aplicar_docente(s, docente)
    registrar(proceso, user, f"Asignó {s.docente} a {s.curso.den_curso if s.curso else s.cod_curso} ({s.cod_seccion})")
    db.session.commit()
    return jsonify(seccion=seccion_dict(s))


@bp.put("/proceso/secciones/<int:id_seccion>/aula")
@roles_required("asistente")
def asignar_aula(id_seccion):
    user = yo()
    s, periodo, proceso = seccion_del_periodo(id_seccion)
    exigir_fase_edicion(proceso, "asistente")
    data = request.get_json(silent=True) or {}
    aula = aula_valida(data.get("aula"))
    sesion = data.get("sesion")
    bloques = None
    if sesion is not None:
        try:
            sesion = int(sesion)
            bloques = [s.sesiones[sesion]]
        except (TypeError, ValueError, IndexError):
            raise ApiError("datos_invalidos", "Sesión inválida.", 400)
    verificar_aula(s, aula, secciones_periodo(periodo), bloques)
    aplicar_aula(s, aula, sesion)
    dia = f" ({DIAS.get(bloques[0].dia, '')})" if bloques else ""
    registrar(proceso, user, f"Asignó {aula} a {s.curso.den_curso if s.curso else s.cod_curso} ({s.cod_seccion}){dia}")
    db.session.commit()
    return jsonify(seccion=seccion_dict(s), ubicacion=ubicacion_aula(aula))


# ---------------------------------------------------------------------------
# Avance de fases
# ---------------------------------------------------------------------------
@bp.post("/proceso/<int:id_periodo>/accion")
@roles_required(*GESTORES)
def accion(id_periodo):
    user = yo()
    periodo = periodo_o_404(id_periodo)
    proceso = obtener_proceso(periodo)
    data = request.get_json(silent=True) or {}
    acc = data.get("accion")
    secciones = secciones_periodo(periodo)
    rol, fase = user.rol, proceso.fase

    def exigir(rol_ok, fases_ok):
        if rol != rol_ok or fase not in fases_ok:
            raise ApiError("accion_no_permitida", "Esta acción no corresponde a tu rol o a la fase actual del proceso.", 409)

    if acc == "enviar_director":
        exigir("jefe", (1,))
        if not secciones:
            raise ApiError("sin_secciones", "Crea los horarios de los cursos antes de enviarlos.", 409)
        proceso.observacion = None
        cambiar_fase(proceso, 2, user, "Envió los horarios al Director de Escuela")
    elif acc == "devolver_jefe":
        exigir("director", (2,))
        motivo = str(data.get("motivo") or "").strip()
        if len(motivo) < 5:
            raise ApiError("datos_invalidos", "Explica al jefe qué debe corregir.", 400)
        proceso.observacion = motivo[:500]
        cambiar_fase(proceso, 1, user, f"Devolvió los horarios al jefe: {motivo[:200]}")
    elif acc == "enviar_confirmacion":
        exigir("director", (2,))
        faltan = [s for s in secciones if s.id_docente is None and s.docente == SIN_ASIGNAR]
        if faltan:
            raise ApiError("faltan_docentes", f"Faltan asignar docentes en {len(faltan)} secciones.", 409)
        proceso.confirmado_jefe = proceso.confirmado_director = False
        cambiar_fase(proceso, 3, user, "Envió la asignación de docentes a confirmación")
    elif acc == "confirmar":
        if fase != 3 or rol not in ("jefe", "director"):
            raise ApiError("accion_no_permitida", "Solo el jefe y el director confirman en la fase 3.", 409)
        setattr(proceso, "confirmado_jefe" if rol == "jefe" else "confirmado_director", True)
        registrar(proceso, user, "Confirmó horarios y docentes")
    elif acc == "enviar_docentes":
        exigir("asistente", (3,))
        if not (proceso.confirmado_jefe and proceso.confirmado_director):
            raise ApiError("falta_confirmacion", "Espera la confirmación del jefe de departamento y del director.", 409)
        sin_aula = [s for s in secciones if (s.aula or SIN_ASIGNAR) == SIN_ASIGNAR]
        if sin_aula:
            raise ApiError("faltan_aulas", f"Faltan asignar aulas en {len(sin_aula)} secciones.", 409)
        for s in secciones:
            s.estado_docente = "pendiente" if s.id_docente else "confirmado"
        cambiar_fase(proceso, 4, user, "Publicó los horarios para la confirmación de los docentes")
        db.session.flush()
        avanzar_si_todos_confirmaron(proceso, periodo, user)
    elif acc == "establecer":
        exigir("director", (4,))
        pendientes = [s for s in secciones if s.estado_docente != "confirmado"]
        abiertas = SolicitudCambio.query.filter_by(id_periodo=periodo.unique_id, estado="pendiente").count()
        if pendientes or abiertas:
            raise ApiError(
                "faltan_confirmaciones",
                f"Aún hay {len(pendientes)} secciones sin confirmar por su docente y {abiertas} solicitudes de cambio abiertas.",
                409,
            )
        cambiar_fase(proceso, 5, user, "Estableció los horarios y abrió la matrícula de alumnos")
    elif acc == "iniciar_ajustes":
        exigir("director", (5,))
        cambiar_fase(proceso, 6, user, "Inició el período de ajustes de horario")
    elif acc == "cerrar":
        exigir("director", (5, 6))
        # Las solicitudes que quedaron abiertas ya no se pueden aplicar
        SolicitudCambio.query.filter_by(id_periodo=periodo.unique_id, estado="pendiente").update(
            {"estado": "rechazada", "respuesta": "Se cerró el proceso de horarios.", "resuelto_en": datetime.utcnow()}, synchronize_session=False
        )
        cambiar_fase(proceso, 7, user, "Cerró el proceso y la matrícula")
    else:
        raise ApiError("accion_desconocida", "Acción no reconocida.", 400)
    db.session.commit()
    return jsonify(proceso=serializar_proceso(proceso, user))


# ---------------------------------------------------------------------------
# Solicitudes de cambio (comunicación entre roles)
# ---------------------------------------------------------------------------
def estado_actual(tipo, s):
    """Texto de cómo está hoy la sección en el aspecto que se quiere cambiar."""
    if tipo == "docente":
        return s.docente or SIN_ASIGNAR
    if tipo == "aula":
        return " · ".join(dict.fromkeys(ubicacion_aula(b.aula or s.aula or SIN_ASIGNAR)["texto"] for b in s.bloques()))[:300]
    return " · ".join(f"{DIAS.get(b.dia, '')[:3]} {b.hora_inicio.strftime('%H:%M')}-{b.hora_fin.strftime('%H:%M')}" for b in s.bloques())[:300]


def solicitud_dict(sol):
    s = sol.seccion
    return {
        "id": sol.id,
        "tipo": sol.tipo,
        "estado": sol.estado,
        "descripcion": sol.descripcion,
        "respuesta": sol.respuesta,
        "propuesta": json.loads(sol.propuesta) if sol.propuesta else None,
        "anterior": sol.anterior,
        "rol_autor": sol.rol_autor,
        "rol_destino": sol.rol_destino,
        "autor": sol.autor.to_dict()["nombre_completo"] if sol.autor else "",
        "creado_en": sol.creado_en.isoformat() + "Z",
        "resuelto_en": sol.resuelto_en.isoformat() + "Z" if sol.resuelto_en else None,
        "seccion": seccion_dict(s) if s else None,
        "mensajes": [
            {"id": m.id, "rol": m.rol, "autor": m.autor.to_dict()["nombre_completo"] if m.autor else "", "texto": m.texto, "creado_en": m.creado_en.isoformat() + "Z"}
            for m in sol.mensajes
        ],
    }


def validar_propuesta(tipo, propuesta, s, periodo):
    if not propuesta:
        return None
    if tipo == "horario":
        limpias = validar_sesiones(propuesta.get("sesiones"))
        verificar_horas_plan(s.curso, limpias)
        return {"sesiones": [{"dia": d, "hora_inicio": i, "hora_fin": f} for d, i, f in limpias]}
    if tipo == "docente":
        d = Administrador.query.filter_by(id_admin=entero(propuesta.get("id_docente"), "id_docente", por_defecto=0), rol="docente", activo=True).first()
        if not d:
            raise ApiError("docente_no_encontrado", "Elige un docente válido.", 400)
        return {"id_docente": d.id_admin, "docente": d.nombre_docente}
    if tipo == "aula":
        return {"aula": aula_valida(propuesta.get("aula"))}
    return None


def propuesta_sin_cambios(tipo, propuesta, s):
    if tipo == "horario":
        actual = sorted((b.dia, b.hora_inicio.strftime("%H:%M"), b.hora_fin.strftime("%H:%M")) for b in s.bloques())
        nueva = sorted((x["dia"], x["hora_inicio"], x["hora_fin"]) for x in propuesta["sesiones"])
        return actual == nueva
    if tipo == "docente":
        return propuesta["id_docente"] == s.id_docente
    if tipo == "aula":
        return propuesta["aula"] == (s.aula or SIN_ASIGNAR) and all((b.aula or SIN_ASIGNAR) == propuesta["aula"] for b in s.bloques())
    return False


@bp.get("/proceso/<int:id_periodo>/solicitudes")
@roles_required(*PERSONAL)
def listar_solicitudes(id_periodo):
    user = yo()
    periodo = periodo_o_404(id_periodo)
    q = SolicitudCambio.query.filter_by(id_periodo=periodo.unique_id)
    if user.rol == "docente":
        q = q.filter(SolicitudCambio.id_autor == user.id_admin)
    else:
        q = q.filter((SolicitudCambio.rol_destino == user.rol) | (SolicitudCambio.id_autor == user.id_admin) | (SolicitudCambio.rol_autor == user.rol))
    lista = q.order_by(SolicitudCambio.estado.desc(), SolicitudCambio.creado_en.desc()).all()
    return jsonify(solicitudes=[{**solicitud_dict(x), "puedo_resolver": x.estado == "pendiente" and x.rol_destino == user.rol} for x in lista])


@bp.post("/proceso/<int:id_periodo>/solicitudes")
@roles_required(*PERSONAL)
def crear_solicitud(id_periodo):
    user = yo()
    periodo = periodo_o_404(id_periodo)
    proceso = obtener_proceso(periodo)
    data = request.get_json(silent=True) or {}
    try:
        s = db.session.get(HorarioDCSeccion, int(data.get("id_seccion")))
    except (TypeError, ValueError):
        s = None
    if not s:
        raise ApiError("seccion_no_encontrada", "La sección no existe.", 404)
    _s, periodo_seccion, _p = seccion_del_periodo(s.id_seccion)
    if periodo_seccion.unique_id != periodo.unique_id:
        raise ApiError("seccion_periodo_invalido", f"La sección no pertenece al período {periodo.cod_per_acad}.", 400)
    tipo = data.get("tipo")
    if tipo not in RESPONSABLE:
        raise ApiError("datos_invalidos", "El tipo debe ser horario, docente o aula.", 400)
    descripcion = str(data.get("descripcion") or "").strip()
    if len(descripcion) < 8:
        raise ApiError("datos_invalidos", "Describe el problema o el cambio con más detalle.", 400)

    if user.rol == "docente":
        if s.id_docente != user.id_admin:
            raise ApiError("acceso_denegado", "Solo puedes reportar problemas de tus propias secciones.", 403)
        if proceso.fase not in (4, 5, 6):
            raise ApiError("fase_incorrecta", "Los docentes reportan problemas desde la fase 4 hasta los ajustes.", 409)
        destino = RESPONSABLE[tipo]
        s.estado_docente = "observado"
    else:
        if TIPO_POR_ROL[user.rol] != tipo:
            raise ApiError("accion_no_permitida", "Solo puedes proponer cambios de tu competencia.", 403)
        if not (FASE_EDICION[user.rol] < proceso.fase <= 6):
            raise ApiError("fase_incorrecta", "En tu fase edita directamente; las solicitudes son para cambios posteriores.", 409)
        destino = CONTRAPARTE[user.rol]
    if proceso.fase == 7:
        raise ApiError("proceso_cerrado", "El proceso de horarios está cerrado.", 409)
    if proceso.fase == 6 and fechas(periodo)["ajustes_vencidos"]:
        raise ApiError("ajustes_vencidos", "Venció el plazo de 2 semanas para ajustes de horario.", 409)

    propuesta = validar_propuesta(tipo, data.get("propuesta"), s, periodo)
    if user.rol != "docente" and not propuesta:
        raise ApiError("datos_invalidos", "Indica el cambio propuesto.", 400)
    if propuesta and propuesta_sin_cambios(tipo, propuesta, s):
        raise ApiError("sin_cambios", "La propuesta es igual a lo que ya tiene la sección. Modifica el cambio que necesitas.", 400)
    sol = SolicitudCambio(
        id_periodo=periodo.unique_id, id_seccion=s.id_seccion, tipo=tipo, id_autor=user.id_admin, rol_autor=user.rol,
        rol_destino=destino, descripcion=descripcion[:1000], propuesta=json.dumps(propuesta, ensure_ascii=False) if propuesta else None,
        anterior=estado_actual(tipo, s),
    )
    db.session.add(sol)
    registrar(proceso, user, f"Solicitó cambio de {tipo} en {s.curso.den_curso if s.curso else s.cod_curso} ({s.cod_seccion}) a {ROLES_PERSONAL[destino]}")
    db.session.commit()
    return jsonify(solicitud=solicitud_dict(sol)), 201


@bp.post("/proceso/solicitudes/<int:id_sol>/mensajes")
@roles_required(*PERSONAL)
def mensaje(id_sol):
    user = yo()
    sol = db.get_or_404(SolicitudCambio, id_sol)
    participa = user.id_admin == sol.id_autor or user.rol == sol.rol_destino or (user.rol == sol.rol_autor and user.rol != "docente")
    if not participa:
        raise ApiError("acceso_denegado", "No participas en esta solicitud.", 403)
    if sol.estado != "pendiente":
        raise ApiError("solicitud_cerrada", "La solicitud ya fue resuelta.", 409)
    texto = str((request.get_json(silent=True) or {}).get("texto") or "").strip()
    if not texto:
        raise ApiError("datos_invalidos", "Escribe un mensaje.", 400)
    db.session.add(SolicitudMensaje(id_solicitud=sol.id, id_autor=user.id_admin, rol=user.rol, texto=texto[:1000]))
    db.session.commit()
    db.session.refresh(sol)
    return jsonify(solicitud=solicitud_dict(sol))


@bp.post("/proceso/solicitudes/<int:id_sol>/resolver")
@roles_required(*GESTORES)
def resolver(id_sol):
    """El rol destinatario aprueba (se aplica el cambio) o rechaza con una respuesta."""
    user = yo()
    sol = db.get_or_404(SolicitudCambio, id_sol)
    if sol.estado != "pendiente":
        raise ApiError("solicitud_cerrada", "La solicitud ya fue resuelta.", 409)
    if sol.rol_destino != user.rol:
        raise ApiError("acceso_denegado", "Esta solicitud la debe responder otro rol.", 403)
    data = request.get_json(silent=True) or {}
    acc = data.get("accion")
    respuesta = str(data.get("respuesta") or "").strip()
    s = sol.seccion
    periodo = db.session.get(PeriodoAcademico, sol.id_periodo)
    proceso = obtener_proceso(periodo)
    nombre = s.curso.den_curso if s.curso else s.cod_curso
    if acc == "aprobar" and proceso.fase == 7:
        raise ApiError("proceso_cerrado", "El proceso de horarios está cerrado: ya no se aplican cambios.", 409)
    if acc == "aprobar" and proceso.fase == 6 and fechas(periodo)["ajustes_vencidos"]:
        raise ApiError("ajustes_vencidos", "Venció el plazo de ajustes de horario.", 409)

    if acc == "rechazar":
        if len(respuesta) < 5:
            raise ApiError("datos_invalidos", "Explica el motivo del rechazo.", 400)
        sol.estado = "rechazada"
        if sol.rol_autor == "docente" and s.estado_docente == "observado":
            s.estado_docente = "pendiente"
    elif acc == "aprobar":
        # El destinatario puede completar o corregir la propuesta (p. ej. el jefe define el nuevo horario que pidió el docente)
        propuesta = validar_propuesta(sol.tipo, data.get("propuesta"), s, periodo) or (json.loads(sol.propuesta) if sol.propuesta else None)
        if not propuesta:
            raise ApiError("datos_invalidos", "Indica el cambio que se aplicará para aprobar la solicitud.", 400)
        todas = secciones_periodo(periodo)
        if sol.tipo == "horario":
            aplicar_sesiones(s, validar_sesiones(propuesta["sesiones"]))
            if s.id_docente:
                verificar_docente(s, s.id_docente, todas)
            verificar_aula(s, s.aula or SIN_ASIGNAR, todas)
        elif sol.tipo == "docente":
            d = Administrador.query.filter_by(id_admin=propuesta.get("id_docente"), rol="docente", activo=True).first()
            if not d:
                raise ApiError("docente_no_encontrado", "El docente propuesto ya no está disponible.", 409)
            verificar_docente(s, d.id_admin, todas)
            aplicar_docente(s, d)
        elif sol.tipo == "aula":
            verificar_aula(s, propuesta["aula"], todas)
            aplicar_aula(s, propuesta["aula"])
        sol.propuesta = json.dumps(propuesta, ensure_ascii=False)
        sol.estado = "aprobada"
        if proceso.fase >= 4 and s.id_docente:
            # El docente vuelve a confirmar, salvo que el cambio haya sido lo que él mismo propuso
            propio = sol.rol_autor == "docente" and sol.id_autor == s.id_docente and sol.tipo != "docente" and not data.get("propuesta")
            s.estado_docente = "confirmado" if propio else "pendiente"
    else:
        raise ApiError("accion_desconocida", "Usa aprobar o rechazar.", 400)
    sol.respuesta = respuesta[:1000] or None
    sol.id_resuelto_por = user.id_admin
    sol.resuelto_en = datetime.utcnow()
    registrar(proceso, user, f"{'Aprobó' if sol.estado == 'aprobada' else 'Rechazó'} el cambio de {sol.tipo} en {nombre} ({s.cod_seccion})")
    db.session.flush()
    avanzar_si_todos_confirmaron(proceso, periodo, user)
    db.session.commit()
    db.session.refresh(sol)
    return jsonify(solicitud=solicitud_dict(sol))


# ---------------------------------------------------------------------------
# Docente: su horario y confirmación
# ---------------------------------------------------------------------------
@bp.get("/docente/horario")
@roles_required("docente")
def horario_docente():
    user = yo()
    periodos = PeriodoAcademico.query.filter(PeriodoAcademico.estado != "historico").order_by(PeriodoAcademico.fec_inicio.desc()).all()
    procesos = [serializar_proceso(obtener_proceso(p), user) for p in periodos]
    id_periodo = request.args.get("periodo", type=int) or next((p["id_periodo"] for p in procesos if 4 <= p["fase"] <= 6), procesos[0]["id_periodo"] if procesos else None)
    secciones, proceso = [], None
    if id_periodo:
        periodo = periodo_o_404(id_periodo)
        proceso = obtener_proceso(periodo)
        if proceso.fase >= 4:
            secciones = [seccion_dict(s) for s in secciones_periodo(periodo) if s.id_docente == user.id_admin]
    db.session.commit()
    return jsonify(
        procesos=procesos,
        proceso=serializar_proceso(proceso, user) if proceso else None,
        secciones=secciones,
        publicado=bool(proceso and proceso.fase >= 4),
    )


@bp.post("/docente/secciones/<int:id_seccion>/confirmar")
@roles_required("docente")
def confirmar_seccion(id_seccion):
    user = yo()
    s, periodo, proceso = seccion_del_periodo(id_seccion)
    if s.id_docente != user.id_admin:
        raise ApiError("acceso_denegado", "La sección no está asignada a ti.", 403)
    if proceso.fase not in (4, 5, 6):
        raise ApiError("fase_incorrecta", "La confirmación de docentes se hace desde la fase 4.", 409)
    abierta = SolicitudCambio.query.filter_by(id_seccion=s.id_seccion, id_autor=user.id_admin, estado="pendiente").first()
    if abierta:
        raise ApiError("solicitud_abierta", "Tienes un reporte pendiente en esta sección; espera su respuesta.", 409)
    s.estado_docente = "confirmado"
    registrar(proceso, user, f"Confirmó su horario de {s.curso.den_curso if s.curso else s.cod_curso} ({s.cod_seccion})")
    db.session.flush()
    avanzo = avanzar_si_todos_confirmaron(proceso, periodo, user)
    db.session.commit()
    return jsonify(seccion=seccion_dict(s), fase=proceso.fase, matricula_abierta=avanzo or proceso.fase in (5, 6))
