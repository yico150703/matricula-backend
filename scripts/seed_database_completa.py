"""Inicializa la base de datos de matrícula de forma SEGURA (idempotente).

- Crea las tablas que falten y agrega columnas nuevas sin borrar datos.
- Carga el catálogo oficial: malla 2019 de Ing. de Sistemas (docs/malla_curricular_bd_2019.xlsx)
  y los horarios reales 2026-1 / 2026-2 con secciones A, B, C, turnos, docentes y aulas
  (docs/horarios_2026.json, generado con scripts/fuentes/extraer_horarios.py).
- Cuando cambia la versión del catálogo, lo reemplaza conservando alumnos y administradores
  (las matrículas y notas de prueba anteriores se eliminan porque apuntan a horarios que ya no existen).
- Garantiza que exista el usuario administrador y el alumno de demostración.

Uso:
    python scripts/seed_database_completa.py           # seguro, se ejecuta en cada arranque
    python scripts/seed_database_completa.py --reset   # BORRA TODO y vuelve a poblar
"""
import argparse
import json
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
import sys
import pandas as pd
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app import create_app
from app.extensions import db
from app.models import (
    ActaNotas,
    ProcesoHorario,
    SolicitudCambio,
    SolicitudMensaje,
    AppMeta,
    CarritoItem,
    SeccionSesion,
    SolicitudPassword,
    Administrador,
    Alumno,
    Curso,
    Escuela,
    Facultad,
    HorarioCab,
    HorarioDCSeccion,
    HorarioDCurso,
    HorarioDet,
    Matricula,
    MatriculaDetalle,
    MezclaCurso,
    PeriodoAcademico,
    PlanEstudio,
)


def clean(val):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s if s != "" else None


def clean_int(val, default=0):
    c = clean(val)
    if c is None:
        return default
    try:
        return int(float(c))
    except Exception:
        return default


def clean_dec(val, default=Decimal("3.0")):
    c = clean(val)
    if c is None:
        return default
    try:
        return Decimal(str(c))
    except Exception:
        return default


CATALOGO_VERSION = "2026-horario-oficial-v2"  # v2: solo secciones A, B y C
HORARIOS_JSON = ROOT / "docs" / "horarios_2026.json"
MALLA_XLSX = ROOT / "docs" / "malla_curricular_bd_2019.xlsx"
PERIODOS = [
    (1, "2026-1", date(2026, 3, 16), date(2026, 7, 31)),
    (2, "2026-2", date(2026, 8, 17), date(2026, 12, 31)),
]

NEW_COLUMNS = {
    # tabla: {columna: DDL}
    "alumno": {
        "debe_cambiar_password": "BOOLEAN NOT NULL DEFAULT FALSE",
        "email_personal": "VARCHAR(254)",
        "telefono": "VARCHAR(20)",
        "cuenta_prueba": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
    "solicitud_cambio": {
        "anterior": "VARCHAR(300)",
    },
    "horario_d_c_seccion": {
        "turno": "VARCHAR(1) NOT NULL DEFAULT 'M'",
        "id_docente": "INTEGER",
        "estado_docente": "VARCHAR(12) NOT NULL DEFAULT 'confirmado'",
    },
    "administrador": {
        "rol": "VARCHAR(20) NOT NULL DEFAULT 'admin'",
        "apellidos": "VARCHAR(150)",
        "cuenta_prueba": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
    "matricula_detalle": {
        "n1": "NUMERIC(4,2)",
        "n2": "NUMERIC(4,2)",
        "n3": "NUMERIC(4,2)",
        "sustitutorio": "NUMERIC(4,2)",
        "aplazado": "NUMERIC(4,2)",
    },
}


def reset_database():
    print("! Borrando TODAS las tablas (--reset)...")
    if db.engine.dialect.name == "postgresql":
        db.session.execute(db.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        db.session.commit()
    else:
        db.drop_all()


def ensure_schema():
    """Crea tablas faltantes y agrega columnas nuevas a tablas existentes (sin perder datos)."""
    db.create_all()
    inspector = db.inspect(db.engine)
    for table, columns in NEW_COLUMNS.items():
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                print(f"✓ Columna agregada: {table}.{name}")
    db.session.commit()


def ensure_admin():
    usuario = os.getenv("ADMIN_USER", "admin").strip().lower()
    if Administrador.query.filter(db.func.lower(Administrador.usuario) == usuario).first():
        return
    password = os.getenv("ADMIN_PASSWORD", "Admin2026!")
    db.session.add(Administrador(
        usuario=usuario,
        nombres=os.getenv("ADMIN_NAME", "Oficina de Matrícula FIIS"),
        email=os.getenv("ADMIN_EMAIL", "matricula.fiis@unfv.edu.pe"),
        password_hash=generate_password_hash(password),
        activo=True,
        debe_cambiar_password=True,
    ))
    db.session.commit()
    print(f"✓ Administrador '{usuario}' creado (debe cambiar la contraseña al ingresar).")


# Cuentas de prueba compartidas (se muestran en el inicio de sesión). En cada arranque se crean o se
# reparan (contraseña conocida, activas, sin cambio obligatorio) para que nadie deje a los demás sin acceso.
# Su contraseña no se puede cambiar desde el sistema. Con CUENTAS_PRUEBA=false se desactivan.
PERSONAL_DEMO = [
    ("adminprueba", "adminprueba@unfv.edu.pe", "Administrador", "de Prueba", "admin", "Admin2026!"),
    ("jefedepartamentoescuelasistemas", "jefedepartamentoescuelasistemas@unfv.edu.pe", "Jefe de Departamento", "E.P. Ingeniería de Sistemas", "jefe", "Jefe2026!"),
    ("directorescuelasistemas", "directorescuelasistemas@unfv.edu.pe", "Director de Escuela", "E.P. Ingeniería de Sistemas", "director", "Director2026!"),
    ("asistenteescuelasistemas", "asistenteescuelasistemas@unfv.edu.pe", "Asistente de Escuela", "E.P. Ingeniería de Sistemas", "asistente", "Asistente2026!"),
    ("jalvaradot", "jalvaradot@unfv.edu.pe", "Juan Carlos", "Alvarado Torres", "docente", "Docente2026!"),
]
ALUMNO_DEMO = ("20260001", "Ana", "Pérez")


def cuentas_prueba_activas():
    return os.getenv("CUENTAS_PRUEBA", "true").strip().lower() not in ("false", "0", "no")


USUARIOS_FIJOS = {"admin", "adminprueba", "jefedepartamentoescuelasistemas", "directorescuelasistemas", "asistenteescuelasistemas"}


def migrar_usuarios_personal():
    """Una sola vez: usuarios y correos del personal al formato UNFV (jalvaradot@unfv.edu.pe).
    Las cuentas que aún tienen la contraseña inicial (= usuario) reciben como contraseña el usuario nuevo."""
    from app.usuarios import base_usuario, correo_personal

    meta = db.session.get(AppMeta, "usuarios_personal")
    if meta and meta.valor == "v2":
        return
    fijos = USUARIOS_FIJOS | {os.getenv("ADMIN_USER", "admin").strip().lower()}
    cuentas = Administrador.query.order_by(Administrador.id_admin).all()
    ocupados = {a.usuario.lower() for a in cuentas}
    cambios = 0
    for a in cuentas:
        if a.usuario.lower() in fijos:
            if a.email and a.email.lower().endswith("@unfv.pe"):
                a.email = a.email[: -len("unfv.pe")] + "unfv.edu.pe"
            continue
        base = base_usuario(a.nombres if a.nombres != "-" else "", a.apellidos or "")
        if a.usuario == base or (a.usuario.startswith(base) and a.usuario[len(base):].isdigit()):
            nuevo = a.usuario
        else:
            ocupados.discard(a.usuario.lower())
            nuevo, n = base, 1
            while nuevo in ocupados:
                n += 1
                nuevo = f"{base}{n}"
            ocupados.add(nuevo)
        if nuevo != a.usuario:
            if a.debe_cambiar_password and check_password_hash(a.password_hash, a.usuario):
                a.password_hash = generate_password_hash(nuevo)
            a.usuario = nuevo
            cambios += 1
        a.email = correo_personal(a.usuario)
    if meta:
        meta.valor = "v2"
    else:
        db.session.add(AppMeta(clave="usuarios_personal", valor="v2"))
    db.session.commit()
    print(f"✓ Usuarios del personal en formato UNFV ({cambios} actualizados, correos @unfv.edu.pe).")


def ensure_cuentas_prueba():
    activas = cuentas_prueba_activas()
    for usuario, email, nombres, apellidos, rol, clave in PERSONAL_DEMO:
        cuenta = Administrador.query.filter_by(usuario=usuario).first()
        if not cuenta:
            if not activas:
                continue
            cuenta = Administrador(usuario=usuario, email=email, nombres=nombres, apellidos=apellidos, rol=rol)
            db.session.add(cuenta)
            print(f"✓ Cuenta de prueba {rol}: {email}")
        if cuenta.apellidos == "Escuela de Sistemas":  # nombre de prueba anterior
            cuenta.apellidos = apellidos
        cuenta.cuenta_prueba = True
        cuenta.activo = activas
        if activas:
            cuenta.rol = rol
            cuenta.email = email
            cuenta.debe_cambiar_password = False
            if not check_password_hash(cuenta.password_hash or "", clave):
                cuenta.password_hash = generate_password_hash(clave)

    codigo, nombres, apellidos = ALUMNO_DEMO
    alumno = db.session.get(Alumno, codigo)
    if not alumno and activas and not Alumno.query.filter_by(email=f"{codigo}@unfv.edu.pe").first():
        alumno = Alumno(cod_alumno=codigo, nombres=nombres, apellidos=apellidos, email=f"{codigo}@unfv.edu.pe",
                        password_hash="", cod_fac=1, cod_esc=1, corr_pe=1, estado="activo", fecha_ingreso=date(2026, 3, 1))
        db.session.add(alumno)
        print(f"✓ Alumno de prueba {codigo}.")
    if alumno:
        alumno.cuenta_prueba = True
        alumno.estado = "activo" if activas else "inactivo"
        if activas:
            alumno.debe_cambiar_password = False
            if not check_password_hash(alumno.password_hash or "", codigo):
                alumno.password_hash = generate_password_hash(codigo)
    db.session.commit()
    print("✓ Cuentas de prueba " + ("listas (contraseñas restablecidas)." if activas else "desactivadas (CUENTAS_PRUEBA=false)."))


def _sin_tildes(t):
    import unicodedata

    return unicodedata.normalize("NFD", (t or "").lower()).encode("ascii", "ignore").decode().strip()


def _parecidos(a, b):
    """Iguales o con una sola letra distinta (Karin / Karen)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    corto, largo = sorted((a, b), key=len)
    return any(largo[:i] + largo[i + 1:] == corto for i in range(len(largo)))


def misma_persona(nombres, apellidos):
    """Los horarios oficiales a veces escriben distinto al mismo docente (Julio / Julio Elmer, Karin / Karen):
    mismos apellidos y primer nombre igual o casi igual."""
    ape = _sin_tildes(apellidos)
    primero = (_sin_tildes(nombres).split() or [""])[0]
    for d in Administrador.query.filter_by(rol="docente").all():
        if _sin_tildes(d.apellidos) != ape:
            continue
        otro = (_sin_tildes(d.nombres if d.nombres != "-" else "").split() or [""])[0]
        if _parecidos(primero, otro):
            return d
    return None


def ensure_docentes():
    """Crea una cuenta de docente por cada profesor de los horarios oficiales y la vincula a sus secciones."""
    from app.usuarios import base_usuario, correo_personal, separar_nombre_horario, usuario_disponible

    creados = 0
    cache = {}
    for s in HorarioDCSeccion.query.filter(HorarioDCSeccion.id_docente.is_(None)).all():
        nombre = (s.docente or "").strip()
        if not nombre or nombre == "POR ASIGNAR" or nombre.startswith("DPTO.") or nombre == "REGISTRO HISTORICO":
            continue
        nombres, apellidos = separar_nombre_horario(nombre)
        base = base_usuario(nombres, apellidos)
        clave = (nombres.lower(), apellidos.lower())  # se identifica a la persona por su nombre, no por el usuario
        if clave not in cache:
            docente = misma_persona(nombres, apellidos)
            if not docente:
                usuario = usuario_disponible(base)
                docente = Administrador(usuario=usuario, email=correo_personal(usuario), nombres=nombres or "-", apellidos=apellidos, rol="docente",
                                        password_hash=generate_password_hash(usuario), activo=True, debe_cambiar_password=True)
                db.session.add(docente)
                db.session.flush()
                creados += 1
            cache[clave] = docente
        s.id_docente = cache[clave].id_admin
    db.session.commit()
    if creados:
        print(f"✓ {creados} cuentas de docentes creadas desde los horarios (contraseña inicial = usuario).")


def ensure_procesos():
    from app.fechas import hoy

    for p in PeriodoAcademico.query.filter(PeriodoAcademico.estado != "historico").all():
        proceso = db.session.get(ProcesoHorario, p.unique_id)
        if not proceso:
            fase = 5 if p.estado == "en_curso" else 7 if p.estado == "cerrado" else 1
            proceso = ProcesoHorario(id_periodo=p.unique_id, fase=fase, confirmado_jefe=fase >= 4, confirmado_director=fase >= 4, historial="[]")
            db.session.add(proceso)
        # Un período cuyo fin ya pasó queda cerrado (las bases antiguas dejaban 2026-1 "en curso")
        if p.fec_fin and p.fec_fin < hoy() and (proceso.fase < 7 or p.estado != "cerrado"):
            proceso.fase, p.estado = 7, "cerrado"
            print(f"✓ Período {p.cod_per_acad} cerrado: terminó el {p.fec_fin.isoformat()}.")
        # Secciones ya establecidas (fase 5+) no esperan confirmación docente
        if proceso.fase >= 5:
            cab = HorarioCab.query.filter_by(cod_per_acad=p.cod_per_acad).first()
            if cab:
                db.session.query(HorarioDCSeccion).filter(
                    HorarioDCSeccion.id_horario == cab.id_horario, HorarioDCSeccion.estado_docente == "pendiente"
                ).update({HorarioDCSeccion.estado_docente: "confirmado"}, synchronize_session=False)
    db.session.commit()


def limpiar_periodo_automatico():
    """Una sola vez: las versiones anteriores creaban solas el 2027-1 para probar. Ahora lo crea el administrador,
    así que ese período de prueba se elimina si aún no tiene matrículas ni actas."""
    from app.periodos_util import eliminar_periodo, puede_eliminarse

    meta = db.session.get(AppMeta, "limpieza_2027_1")
    if meta:
        return
    periodo = PeriodoAcademico.query.filter_by(cod_per_acad="2027-1").first()
    if periodo:
        ok, motivo = puede_eliminarse(periodo)
        if ok:
            eliminar_periodo(periodo)
            print("✓ Período de prueba 2027-1 eliminado: el administrador lo creará desde su panel.")
        else:
            print(f"! No se eliminó el 2027-1 de prueba: {motivo}")
    db.session.add(AppMeta(clave="limpieza_2027_1", valor="hecho"))
    db.session.commit()


# Reinicio de pruebas: se ejecuta UNA sola vez por cada valor de REINICIO_PRUEBAS. Deja la base así:
#   2026-1  cerrado (fase 7)
#   2026-2  matrícula de alumnos abierta (fase 5) con los horarios oficiales
#   2027-1  en programación (fase 1): el Jefe de Departamento arma los horarios desde cero
# Borra matrículas, notas, actas, carritos y solicitudes de cambio; conserva alumnos y cuentas del personal.
# Para repetirlo más adelante basta con cambiar REINICIO_PRUEBAS y volver a desplegar.
REINICIO_PRUEBAS = "2026-10-05"
PERIODO_PROGRAMACION = ("2027-1", date(2027, 3, 15))


def reinicio_pruebas():
    meta = db.session.get(AppMeta, "reinicio_pruebas")
    if meta and meta.valor == REINICIO_PRUEBAS:
        return False
    print(f"! Reinicio de pruebas {REINICIO_PRUEBAS}: 2026-2 en matrícula (fase 5) y 2027-1 en fase 1.")
    for modelo in (ActaNotas, SolicitudMensaje, SolicitudCambio, CarritoItem, MatriculaDetalle, Matricula, ProcesoHorario):
        db.session.query(modelo).delete(synchronize_session=False)
    db.session.commit()
    if db.session.query(Curso).first() is not None:
        limpiar_catalogo_anterior()
    # Solo quedan los períodos oficiales 2026 (y el histórico de notas anteriores)
    oficiales = {cod for _uid, cod, _ini, _fin in PERIODOS}
    for p in PeriodoAcademico.query.all():
        if p.estado != "historico" and p.cod_per_acad not in oficiales:
            db.session.delete(p)
    hoy_ = date.today()
    for _uid, cod, ini, fin in PERIODOS:
        p = PeriodoAcademico.query.filter_by(cod_per_acad=cod).first()
        if p:
            p.fec_inicio, p.fec_fin = ini, fin
            p.estado = "en_curso" if hoy_ <= fin else "cerrado"
    db.session.commit()
    seed_catalog()
    for meta_clave, valor in (("catalogo", CATALOGO_VERSION), ("reinicio_pruebas", REINICIO_PRUEBAS), ("limpieza_2027_1", "hecho")):
        fila = db.session.get(AppMeta, meta_clave)
        if fila:
            fila.valor = valor
        else:
            db.session.add(AppMeta(clave=meta_clave, valor=valor))
    db.session.commit()
    return True


def crear_periodo_programacion(cod, inicio):
    """Crea un período en programación (fase 1), sin secciones, igual que desde el panel del administrador."""
    from app.blueprints.proceso import cabecera
    from app.calendario import fechas_para

    if PeriodoAcademico.query.filter_by(cod_per_acad=cod).first():
        return
    ini, fin = fechas_para(cod, inicio, None)
    nuevo = (db.session.query(db.func.max(PeriodoAcademico.unique_id)).scalar() or 0) + 1
    periodo = PeriodoAcademico(unique_id=nuevo, cod_per_acad=cod, fec_inicio=ini, fec_fin=fin, estado="programacion")
    db.session.add(periodo)
    db.session.flush()
    cabecera(periodo)
    db.session.add(ProcesoHorario(id_periodo=nuevo, fase=1, historial="[]"))
    db.session.commit()
    print(f"✓ Período {cod} en programación (fase 1): clases del {ini.isoformat()} al {fin.isoformat()}.")


def version_catalogo():
    meta = db.session.get(AppMeta, "catalogo")
    return meta.valor if meta else None


def limpiar_catalogo_anterior():
    """Elimina horarios, cursos y matrículas de prueba del catálogo anterior. Conserva alumnos y administradores."""
    print("! Actualizando catálogo: se reemplazan horarios/cursos y se eliminan matrículas y notas de prueba.")
    for modelo in (SolicitudMensaje, SolicitudCambio, CarritoItem, MatriculaDetalle, Matricula, SeccionSesion, HorarioDCSeccion, HorarioDCurso, HorarioDet, HorarioCab, MezclaCurso, Curso):
        db.session.query(modelo).delete(synchronize_session=False)
    # El Plan 2010 ya no se usa: sus alumnos pasan al Plan 2019 vigente
    db.session.query(Alumno).filter(Alumno.corr_pe != 1).update({Alumno.corr_pe: 1}, synchronize_session=False)
    db.session.query(PlanEstudio).filter(PlanEstudio.corr_pe != 1).delete(synchronize_session=False)
    db.session.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Borra toda la base y la vuelve a poblar.")
    parser.add_argument("--reemplazar-catalogo", action="store_true", help="Reemplaza cursos y horarios si cambió CATALOGO_VERSION (borra matrículas de prueba).")
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        if args.reset:
            reset_database()
        ensure_schema()
        reiniciado = reinicio_pruebas()
        actual = version_catalogo()
        hay_datos = db.session.query(Curso).first() is not None
        permitir = args.reemplazar_catalogo or os.getenv("REEMPLAZAR_CATALOGO", "").strip() == CATALOGO_VERSION
        if actual != CATALOGO_VERSION and hay_datos and not permitir:
            # Nunca se borran matrículas ni notas en un arranque normal
            print(
                f"! El catálogo de la base ({actual or 'sin versión'}) no es {CATALOGO_VERSION}. No se modificó nada: "
                f"para reemplazarlo ejecuta el script con --reemplazar-catalogo o define REEMPLAZAR_CATALOGO={CATALOGO_VERSION}."
            )
        elif actual != CATALOGO_VERSION:
            if hay_datos:
                limpiar_catalogo_anterior()
            seed_catalog()
            meta = db.session.get(AppMeta, "catalogo") or AppMeta(clave="catalogo", valor="")
            meta.valor = CATALOGO_VERSION
            db.session.add(meta)
            db.session.commit()
        else:
            print(f"✓ Catálogo {CATALOGO_VERSION} vigente: se conservan los datos existentes.")
        ensure_admin()
        migrar_usuarios_personal()
        ensure_cuentas_prueba()
        ensure_docentes()
        ensure_procesos()
        limpiar_periodo_automatico()
        if reiniciado:
            crear_periodo_programacion(*PERIODO_PROGRAMACION)
        print("✓ Base de datos lista.")


def _hora(texto):
    h, m = texto.split(":")
    return time(int(h), int(m))


def seed_catalog():
    """Carga facultades, plan 2019, cursos con códigos oficiales, prerrequisitos, períodos y horarios reales."""
    hoy = date.today()
    if not db.session.get(Facultad, 1):
        db.session.add_all([Facultad(cod_fac=1, den_fac="FIIS"), Facultad(cod_fac=2, den_fac="Medicina")])
        db.session.flush()
    if not db.session.get(Escuela, (1, 1)):
        db.session.add_all([
            Escuela(cod_fac=1, cod_esc=1, den_escuela="Esc. Ing. de Sistemas"),
            Escuela(cod_fac=1, cod_esc=2, den_escuela="Esc. Ing. Industrial"),
            Escuela(cod_fac=1, cod_esc=3, den_escuela="Esc. Ing. de Transportes"),
        ])
        db.session.flush()
    if not db.session.get(PlanEstudio, (1, 1, 1)):
        db.session.add(PlanEstudio(cod_fac=1, cod_esc=1, corr_pe=1, anio_pe="Plan 2019", vigente=True))
        db.session.flush()

    fuente = json.loads(HORARIOS_JSON.read_text(encoding="utf-8"))
    codigos = fuente["codigos"]

    # Cursos de la malla 2019 (cod_curso = id de la malla; código oficial del horario UNFV)
    df_c = pd.read_excel(MALLA_XLSX, sheet_name="CURSO", dtype=object)
    df_p = pd.read_excel(MALLA_XLSX, sheet_name="PRERREQUISITO", dtype=object)
    con_prereq = set(df_p["id_curso"].astype(str).str.strip())
    cursos = {}
    for row in df_c.to_dict("records"):
        idm = clean_int(row.get("id_curso"))
        cred = clean_dec(row.get("creditos"), Decimal("3"))
        codigo = codigos.get(str(idm)) or clean(row.get("codigo_certificacion")) or f"SIS{idm:03d}"
        c = Curso(
            cod_fac=1, cod_esc=1, corr_pe=1, cod_curso=idm,
            codigo_asignatura=codigo,
            den_curso=clean(row.get("nombre_curso")),
            semestre=clean_int(row.get("id_semestre"), 1),
            ht=2 if cred <= 3 else 3, hp=2 if cred >= 3 else 0, cred=cred,
            prereq="S" if str(idm) in con_prereq else "N",
            area_curricular=clean(row.get("area_curricular")),
            mencion_electiva=clean(row.get("mencion_electiva")),
        )
        db.session.add(c)
        cursos[idm] = c
    db.session.flush()
    n_pre = 0
    for row in df_p.to_dict("records"):
        a, b = clean_int(row.get("id_curso")), clean_int(row.get("id_prerrequisito"))
        if a in cursos and b in cursos and a != b:
            db.session.add(MezclaCurso(cod_fac=1, cod_esc=1, corr_pe=1, cod_curso=a, cod_curso_prerequisito=b))
            n_pre += 1
    db.session.flush()
    print(f"✓ {len(cursos)} cursos del Plan 2019 y {n_pre} prerrequisitos.")

    # Períodos (se conservan si ya existen)
    periodos = {}
    for uid, cod, ini, fin in PERIODOS:
        p = PeriodoAcademico.query.filter_by(cod_per_acad=cod).first()
        if not p:
            p = PeriodoAcademico(unique_id=uid, cod_per_acad=cod, fec_inicio=ini, fec_fin=fin,
                                 estado="en_curso" if hoy <= fin else "cerrado")
            db.session.add(p)
        periodos[cod] = p
    db.session.flush()

    # Horarios oficiales
    next_horario = (db.session.query(db.func.max(HorarioCab.id_horario)).scalar() or 0) + 1
    next_seccion = (db.session.query(db.func.max(HorarioDCSeccion.id_seccion)).scalar() or 0) + 1
    cabeceras, programados = {}, {}
    total = 0
    for item in fuente["secciones"]:
        cod_per = item["periodo"]
        if cod_per not in periodos or item["id_curso_malla"] not in cursos:
            continue
        if cod_per not in cabeceras:
            cab = HorarioCab(id_horario=next_horario, cod_per_acad=cod_per, cod_fac=1, cod_esc=1, corr_pe=1,
                             fec_inicio=periodos[cod_per].fec_inicio)
            db.session.add(cab)
            db.session.flush()
            for sem in range(1, 11):
                db.session.add(HorarioDet(id_horario=next_horario, semestre_corr=sem, semestre_desc=f"Ciclo {sem}"))
            db.session.flush()
            cabeceras[cod_per] = next_horario
            next_horario += 1
        id_h = cabeceras[cod_per]
        curso = cursos[item["id_curso_malla"]]
        clave = (id_h, curso.cod_curso)
        if clave not in programados:
            hc = HorarioDCurso(id_horario=id_h, semestre_corr=curso.semestre, cod_curso=curso.cod_curso, nro_secc=0)
            db.session.add(hc)
            programados[clave] = hc
        programados[clave].nro_secc += 1
        db.session.flush()

        ses = item["sesiones"]
        aula = item["aula"] or "POR ASIGNAR"
        sec = HorarioDCSeccion(
            id_seccion=next_seccion, id_horario=id_h, semestre_corr=curso.semestre, cod_curso=curso.cod_curso,
            cod_seccion=item["seccion"], turno=item["turno"],
            dia_teoria=ses[0]["dia"], hora_inicio=_hora(ses[0]["inicio"]), hora_fin=_hora(ses[0]["fin"]),
            aula=aula, docente=item["docente"] or "POR ASIGNAR",
            cupo_maximo=item["cupo"], cupo_disponible=item["cupo"],
        )
        db.session.add(sec)
        for b in ses:
            db.session.add(SeccionSesion(id_seccion=next_seccion, dia=b["dia"], hora_inicio=_hora(b["inicio"]),
                                         hora_fin=_hora(b["fin"]), aula=aula))
        next_seccion += 1
        total += 1
    db.session.commit()
    print(f"✓ {total} secciones oficiales (A/B/C) con turnos, docentes y aulas.")


if __name__ == "__main__":
    main()
