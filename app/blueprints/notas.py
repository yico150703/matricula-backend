"""Actas de notas.

Flujo: el docente registra las notas de cada alumno de su salón (borrador), descarga el acta, la firma y la sube
en PDF; al enviarla pasa al Director de Escuela, que la aprueba (las notas se copian al registro académico del
alumno) o la observa (vuelve al docente con un comentario). El administrador solo supervisa el avance.
"""
import json
from datetime import datetime

from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file

from ..academico import _nota, calcular_notas
from ..errors import ApiError
from ..extensions import db
from ..models import ESTADOS_ACTA, ActaNotas, Alumno, Matricula, MatriculaDetalle
from ..security import roles_required
from .proceso import obtener_proceso, periodo_o_404, secciones_periodo, seccion_del_periodo, yo

bp = Blueprint("notas", __name__)

CAMPOS = ("n1", "n2", "n3", "sustitutorio", "aplazado")
FASE_MINIMA = 5  # las notas se registran cuando los horarios ya están establecidos (fases 5, 6 y 7)
EDITABLE = ("borrador", "observada")
MAX_PDF = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def alumnos_de(seccion):
    """Matrículas vigentes del salón, ordenadas por apellidos."""
    return (
        db.session.query(MatriculaDetalle, Alumno)
        .join(Matricula, MatriculaDetalle.nro_matricula == Matricula.nro_matricula)
        .join(Alumno, Matricula.cod_alumno == Alumno.cod_alumno)
        .filter(MatriculaDetalle.id_seccion == seccion.id_seccion, MatriculaDetalle.estado == "matriculado", Matricula.estado == "confirmada")
        .order_by(Alumno.apellidos, Alumno.nombres)
        .all()
    )


def resultado(notas):
    """Promedio y nota final de un registro, o None si aún está incompleto (sin romper con ApiError)."""
    try:
        r = calcular_notas(notas or {})
    except ApiError:
        return None, None
    return r["promedio"], r["nota_final"]


def registrar(acta, user, accion):
    hist = json.loads(acta.historial or "[]")
    hist.append({"fecha": datetime.utcnow().isoformat() + "Z", "rol": user.rol, "usuario": user.to_dict()["nombre_completo"], "accion": accion})
    acta.historial = json.dumps(hist[-50:], ensure_ascii=False)
    acta.actualizado_en = datetime.utcnow()


def acta_dict(acta, alumnos=None):
    if not acta:
        if alumnos == 0:  # salón sin matriculados: no requiere acta
            return {"estado": "sin_alumnos", "estado_nombre": "Sin alumnos", "tiene_pdf": False}
        return {"estado": "sin_acta", "estado_nombre": "Sin registrar", "tiene_pdf": False}
    return {
        "id": acta.id,
        "estado": acta.estado,
        "estado_nombre": ESTADOS_ACTA.get(acta.estado, acta.estado),
        "tiene_pdf": bool(acta.archivo_nombre),
        "archivo_nombre": acta.archivo_nombre,
        "archivo_bytes": acta.archivo_bytes,
        "enviado_en": acta.enviado_en.isoformat() + "Z" if acta.enviado_en else None,
        "revisado_en": acta.revisado_en.isoformat() + "Z" if acta.revisado_en else None,
        "revisor": acta.revisor.to_dict()["nombre_completo"] if acta.revisor else None,
        "observacion": acta.observacion,
        "historial": json.loads(acta.historial or "[]"),
    }


def seccion_basica(s):
    curso = s.curso
    return {
        "id_seccion": s.id_seccion,
        "cod_seccion": s.cod_seccion,
        "turno": s.turno,
        "docente": s.docente,
        "id_docente": s.id_docente,
        "curso": {
            "cod_curso": s.cod_curso,
            "nombre_curso": curso.den_curso if curso else str(s.cod_curso),
            "codigo_curso": getattr(curso, "codigo_asignatura", None) if curso else None,
            "abreviatura": curso.to_dict().get("abreviatura") if curso else None,
            "creditos": float(curso.cred) if curso else None,
            "ciclo": s.semestre_corr,
        },
    }


def detalle_salon(s, periodo, acta):
    borrador = json.loads(acta.notas) if acta else {}
    filas = []
    for det, al in alumnos_de(s):
        oficiales = {c: float(getattr(det, c)) if getattr(det, c) is not None else None for c in CAMPOS}
        # Borrador del docente mientras el acta no esté aprobada; si no, las notas oficiales del registro
        usar_borrador = acta is not None and acta.estado != "aprobada" and al.cod_alumno in borrador
        notas = {c: borrador[al.cod_alumno].get(c) for c in CAMPOS} if usar_borrador else oficiales
        promedio, final = resultado(notas)
        filas.append(
            {
                "cod_alumno": al.cod_alumno,
                "nombres": al.nombres,
                "apellidos": al.apellidos,
                "notas": notas,
                "promedio": promedio,
                "nota_final": final,
                "aprobado": final is not None and final >= current_app.config["PASSING_GRADE"],
            }
        )
    return {
        "seccion": seccion_basica(s),
        "periodo": periodo.to_dict(),
        "acta": acta_dict(acta),
        "alumnos": filas,
        "nota_minima": current_app.config["PASSING_GRADE"],
        "completas": sum(1 for f in filas if f["nota_final"] is not None),
    }


def acta_de(s, periodo, crear=False):
    acta = ActaNotas.query.filter_by(id_seccion=s.id_seccion).first()
    if not acta and crear:
        acta = ActaNotas(id_seccion=s.id_seccion, id_periodo=periodo.unique_id, id_docente=s.id_docente, estado="borrador", notas="{}", historial="[]")
        db.session.add(acta)
        db.session.flush()
    return acta


def salon_del_docente(id_seccion, user):
    s, periodo, proceso = seccion_del_periodo(id_seccion)
    if s.id_docente != user.id_admin:
        raise ApiError("acceso_denegado", "Este salón no está a tu cargo.", 403)
    if proceso.fase < FASE_MINIMA:
        raise ApiError("fase_incorrecta", "Las notas se registran cuando los horarios del período ya están establecidos (fase 5 en adelante).", 409)
    return s, periodo


def limpiar_notas(notas):
    """Valida cada nota (0 a 20) sin exigir que el registro esté completo: es un borrador."""
    limpio = {}
    for c in CAMPOS:
        v = _nota((notas or {}).get(c), c.upper() if c.startswith("n") else c.capitalize())
        limpio[c] = v
    return limpio


# ---------------------------------------------------------------------------
# Docente: sus salones, notas y envío del acta
# ---------------------------------------------------------------------------
@bp.get("/docente/salones")
@roles_required("docente")
def mis_salones():
    user = yo()
    periodo = periodo_o_404(request.args.get("periodo", type=int))
    proceso = obtener_proceso(periodo)
    secciones = [s for s in secciones_periodo(periodo) if s.id_docente == user.id_admin]
    actas = {a.id_seccion: a for a in ActaNotas.query.filter(ActaNotas.id_seccion.in_([s.id_seccion for s in secciones])).all()} if secciones else {}
    salones = []
    for s in sorted(secciones, key=lambda x: (x.semestre_corr, x.curso.den_curso if x.curso else "", x.cod_seccion)):
        n = len(alumnos_de(s))
        salones.append({**seccion_basica(s), "alumnos": n, "acta": acta_dict(actas.get(s.id_seccion), n)})
    return jsonify(salones=salones, fase=proceso.fase, habilitado=proceso.fase >= FASE_MINIMA)


@bp.get("/docente/salones/<int:id_seccion>")
@roles_required("docente")
def ver_salon(id_seccion):
    user = yo()
    s, periodo = salon_del_docente(id_seccion, user)
    return jsonify(detalle_salon(s, periodo, acta_de(s, periodo)))


@bp.put("/docente/salones/<int:id_seccion>/notas")
@roles_required("docente")
def guardar_notas(id_seccion):
    user = yo()
    s, periodo = salon_del_docente(id_seccion, user)
    acta = acta_de(s, periodo, crear=True)
    if acta.estado not in EDITABLE:
        raise ApiError("acta_bloqueada", f"El acta está {ESTADOS_ACTA[acta.estado].lower()}: ya no se puede modificar.", 409)
    recibidas = (request.get_json(silent=True) or {}).get("notas")
    if not isinstance(recibidas, dict):
        raise ApiError("datos_invalidos", "Envía las notas por alumno.", 400)
    validos = {al.cod_alumno for _det, al in alumnos_de(s)}
    borrador = json.loads(acta.notas or "{}")
    for cod, notas in recibidas.items():
        if cod not in validos:
            raise ApiError("alumno_no_encontrado", f"El alumno {cod} no está matriculado en este salón.", 400)
        if not isinstance(notas, dict):
            raise ApiError("datos_invalidos", "Formato de notas inválido.", 400)
        borrador[cod] = limpiar_notas(notas)
    acta.notas = json.dumps(borrador)
    acta.id_docente = user.id_admin
    registrar(acta, user, "Guardó las notas")
    db.session.commit()
    return jsonify(detalle_salon(s, periodo, acta))


@bp.post("/docente/salones/<int:id_seccion>/acta")
@roles_required("docente")
def enviar_acta(id_seccion):
    """Recibe el PDF del acta firmada (multipart, campo 'archivo') y la envía al Director de Escuela."""
    user = yo()
    s, periodo = salon_del_docente(id_seccion, user)
    acta = acta_de(s, periodo, crear=True)
    if acta.estado not in EDITABLE:
        raise ApiError("acta_bloqueada", f"El acta está {ESTADOS_ACTA[acta.estado].lower()}.", 409)
    archivo = request.files.get("archivo")
    if archivo is None and not acta.archivo_nombre:
        raise ApiError("pdf_requerido", "Adjunta el acta de notas firmada en PDF.", 400)
    if archivo is not None:
        contenido = archivo.read(MAX_PDF + 1)
        if len(contenido) > MAX_PDF:
            raise ApiError("pdf_muy_grande", "El PDF no puede pesar más de 5 MB.", 400)
        if not contenido.startswith(b"%PDF"):
            raise ApiError("pdf_invalido", "El archivo debe ser un PDF.", 400)
        acta.archivo = contenido
        acta.archivo_nombre = (archivo.filename or "acta.pdf")[-200:]
        acta.archivo_bytes = len(contenido)

    detalle = detalle_salon(s, periodo, acta)
    if not detalle["alumnos"]:
        raise ApiError("salon_vacio", "El salón no tiene alumnos matriculados.", 409)
    faltan = [f"{a['apellidos']}, {a['nombres']}" for a in detalle["alumnos"] if a["nota_final"] is None]
    if faltan:
        raise ApiError("notas_incompletas", f"Faltan notas de {len(faltan)} alumno(s): {', '.join(faltan[:3])}{'…' if len(faltan) > 3 else ''}.", 409)
    acta.estado = "enviada"
    acta.enviado_en = datetime.utcnow()
    acta.observacion = None
    registrar(acta, user, "Envió el acta al Director de Escuela")
    db.session.commit()
    return jsonify(detalle_salon(s, periodo, acta))


# ---------------------------------------------------------------------------
# Director (aprueba) y administrador (supervisa)
# ---------------------------------------------------------------------------
@bp.get("/actas")
@roles_required("director", "admin")
def listar_actas():
    """Todas las secciones del período con el estado de su acta (para revisar o supervisar)."""
    periodo = periodo_o_404(request.args.get("periodo", type=int))
    secciones = secciones_periodo(periodo)
    actas = {a.id_seccion: a for a in ActaNotas.query.filter_by(id_periodo=periodo.unique_id).all()}
    filas = []
    for s in secciones:
        n = len(alumnos_de(s))
        filas.append({**seccion_basica(s), "alumnos": n, "acta": acta_dict(actas.get(s.id_seccion), n)})
    orden = {"enviada": 0, "observada": 1, "borrador": 2, "sin_acta": 3, "aprobada": 4, "sin_alumnos": 5}
    filas.sort(key=lambda f: (orden[f["acta"]["estado"]], f["curso"]["ciclo"], f["curso"]["nombre_curso"], f["cod_seccion"]))
    resumen = {e: sum(1 for f in filas if f["acta"]["estado"] == e) for e in orden}
    return jsonify(actas=filas, resumen=resumen, periodo=periodo.to_dict(), fase=obtener_proceso(periodo).fase)


def acta_o_404(id_acta):
    acta = db.session.get(ActaNotas, id_acta)
    if not acta:
        raise ApiError("acta_no_encontrada", "El acta no existe.", 404)
    return acta


@bp.get("/actas/<int:id_acta>")
@roles_required("director", "admin")
def ver_acta(id_acta):
    acta = acta_o_404(id_acta)
    s, periodo, _proceso = seccion_del_periodo(acta.id_seccion)
    return jsonify(detalle_salon(s, periodo, acta))


@bp.get("/actas/<int:id_acta>/pdf")
@roles_required("director", "admin", "docente")
def descargar_pdf(id_acta):
    user = yo()
    acta = acta_o_404(id_acta)
    if user.rol == "docente" and acta.id_docente != user.id_admin:
        raise ApiError("acceso_denegado", "Esta acta no es tuya.", 403)
    if not acta.archivo:
        raise ApiError("sin_pdf", "El acta aún no tiene PDF.", 404)
    return send_file(BytesIO(acta.archivo), mimetype="application/pdf", download_name=acta.archivo_nombre or "acta.pdf", as_attachment=False)


@bp.post("/actas/<int:id_acta>/revisar")
@roles_required("director")
def revisar_acta(id_acta):
    """aprobar: las notas pasan al registro académico · observar: vuelve al docente · reabrir: corrige un acta aprobada."""
    user = yo()
    acta = acta_o_404(id_acta)
    data = request.get_json(silent=True) or {}
    accion = data.get("accion")
    observacion = str(data.get("observacion") or "").strip()[:1000]
    s, periodo, _proceso = seccion_del_periodo(acta.id_seccion)

    if accion == "aprobar":
        if acta.estado != "enviada":
            raise ApiError("estado_invalido", "Solo se aprueban actas enviadas por el docente.", 409)
        borrador = json.loads(acta.notas or "{}")
        for det, al in alumnos_de(s):
            notas = calcular_notas(borrador.get(al.cod_alumno) or {})
            for campo in (*CAMPOS, "nota_final"):
                setattr(det, campo, notas[campo])
        acta.estado = "aprobada"
        registrar(acta, user, "Aprobó el acta: las notas pasaron al registro académico")
    elif accion in ("observar", "reabrir"):
        esperado = "enviada" if accion == "observar" else "aprobada"
        if acta.estado != esperado:
            raise ApiError("estado_invalido", f"Solo se puede {accion} un acta {ESTADOS_ACTA[esperado].lower()}.", 409)
        if len(observacion) < 5:
            raise ApiError("datos_invalidos", "Explica al docente qué debe corregir.", 400)
        if accion == "reabrir":
            # Se parte de las notas oficiales vigentes para que el docente las corrija
            acta.notas = json.dumps(
                {al.cod_alumno: {c: float(getattr(det, c)) if getattr(det, c) is not None else None for c in CAMPOS} for det, al in alumnos_de(s)}
            )
        acta.estado = "observada"
        registrar(acta, user, "Observó el acta" if accion == "observar" else "Reabrió el acta para corregir notas")
    else:
        raise ApiError("accion_desconocida", "Usa aprobar, observar o reabrir.", 400)
    acta.observacion = observacion or None
    acta.id_revisor = user.id_admin
    acta.revisado_en = datetime.utcnow()
    db.session.commit()
    return jsonify(detalle_salon(s, periodo, acta))
