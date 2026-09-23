"""Inicializa la base de datos de matrícula de forma SEGURA (idempotente).

- Crea las tablas que falten y agrega columnas nuevas sin borrar datos.
- Carga el catálogo (facultades, planes, cursos, prerrequisitos, períodos y horarios)
  solo si la base está vacía.
- Garantiza que exista el usuario administrador y el alumno de demostración.

Uso:
    python scripts/seed_database_completa.py           # seguro, se ejecuta en cada arranque
    python scripts/seed_database_completa.py --reset   # BORRA TODO y vuelve a poblar
"""
import argparse
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
import sys
import pandas as pd
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from app import create_app
from app.extensions import db
from app.models import (
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


NEW_COLUMNS = {
    # tabla: {columna: DDL}
    "alumno": {
        "debe_cambiar_password": "BOOLEAN NOT NULL DEFAULT FALSE",
        "email_personal": "VARCHAR(254)",
        "telefono": "VARCHAR(20)",
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


def ensure_demo_student():
    if db.session.get(Alumno, "20260001"):
        return
    email = "20260001@unfv.edu.pe"
    if Alumno.query.filter_by(email=email).first():
        return
    db.session.add(Alumno(
        cod_alumno="20260001",
        nombres="Ana",
        apellidos="Pérez",
        email=email,
        password_hash=generate_password_hash("20260001"),
        cod_fac=1,
        cod_esc=1,
        corr_pe=1,  # Plan 2019
        estado="activo",
        fecha_ingreso=date(2026, 3, 1),
        debe_cambiar_password=True,
    ))
    db.session.commit()
    print("✓ Alumno demo 20260001 creado (contraseña inicial = código).")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Borra toda la base y la vuelve a poblar.")
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        if args.reset:
            reset_database()
        ensure_schema()
        if db.session.query(Facultad).first() is None:
            seed_catalog()
        else:
            print("✓ Catálogo ya cargado: se conservan los datos existentes.")
        ensure_admin()
        ensure_demo_student()
        print("✓ Base de datos lista.")


def seed_catalog():
    """Carga el catálogo académico completo desde los Excel de docs/ (solo en base vacía)."""

    # -----------------------------------------------------------------
    # 1. FACULTAD (Imagen 1)
    # -----------------------------------------------------------------
    print("2. Insertando Facultades...")
    f1 = Facultad(cod_fac=1, den_fac="FIIS")
    f2 = Facultad(cod_fac=2, den_fac="Medicina")
    db.session.add_all([f1, f2])
    db.session.commit()
    print("✓ Facultades: FIIS (1), Medicina (2)")

    # -----------------------------------------------------------------
    # 2. ESCUELA (Imagen 1)
    # -----------------------------------------------------------------
    print("3. Insertando Escuelas...")
    escuelas = [
        Escuela(cod_fac=1, cod_esc=1, den_escuela="Esc. Ing Sistemas"),
        Escuela(cod_fac=1, cod_esc=2, den_escuela="Esc. Ing. Industrial"),
        Escuela(cod_fac=1, cod_esc=3, den_escuela="Esc. Ing Tranportes"),
        Escuela(cod_fac=2, cod_esc=1, den_escuela="Esc. Medicina tropical"),
        Escuela(cod_fac=2, cod_esc=2, den_escuela="Esc. Enfermeria"),
    ]
    db.session.add_all(escuelas)
    db.session.commit()
    print("✓ 5 Escuelas insertadas (Sistemas, Industrial, Transportes, Medicina, Enfermería)")

    # -----------------------------------------------------------------
    # 3. PLAN ESTUDIO (Imagen 2)
    # -----------------------------------------------------------------
    print("4. Insertando Planes de Estudio para Ing. de Sistemas...")
    pe1 = PlanEstudio(cod_fac=1, cod_esc=1, corr_pe=1, anio_pe="Plan 2019", vigente=True)
    pe2 = PlanEstudio(cod_fac=1, cod_esc=1, corr_pe=2, anio_pe="Plan 2010", vigente=False)
    db.session.add_all([pe1, pe2])
    db.session.commit()
    print("✓ Planes de Estudio: Plan 2019 (corr 1, vigente) y Plan 2010 (corr 2)")

    # -----------------------------------------------------------------
    # 4 y 5. CURSOS Y MEZCLA CURSO (Prerrequisitos - Imágenes 2 y 3)
    # -----------------------------------------------------------------
    print("5. Cargando cursos y prerrequisitos de Ingeniería de Sistemas desde Excel...")
    docs_dir = ROOT / "docs"

    # A. Cursos Plan 2019 (corr_pe = 1)
    path_2019 = docs_dir / "malla_curricular_bd_2019.xlsx"
    df_c2019 = pd.read_excel(path_2019, sheet_name="CURSO", dtype=object)
    df_p2019 = pd.read_excel(path_2019, sheet_name="PRERREQUISITO", dtype=object)

    prereqs_set_2019 = set(df_p2019["id_curso"].astype(str).str.strip().tolist())

    # Mapa de código oficial a correlativo cod_curso
    map_code_to_codcurso_2019 = {}
    for idx, row in enumerate(df_c2019.to_dict("records"), start=1):
        codigo_asig = clean(row.get("id_curso"))
        nombre = clean(row.get("nombre_curso"))
        semestre = clean_int(row.get("id_semestre"), 1)
        cred = clean_dec(row.get("creditos"), Decimal("3.0"))
        area = clean(row.get("area_curricular"))
        electiva = clean(row.get("mencion_electiva"))
        tiene_prereq = "S" if codigo_asig in prereqs_set_2019 else "N"

        # Calcular HT y HP
        ht = 2 if cred <= 3 else 3
        hp = 2 if cred >= 3 else 0

        c = Curso(
            cod_fac=1,
            cod_esc=1,
            corr_pe=1,
            cod_curso=idx,
            codigo_asignatura=codigo_asig,
            den_curso=nombre,
            semestre=semestre,
            ht=ht,
            hp=hp,
            cred=cred,
            prereq=tiene_prereq,
            area_curricular=area,
            mencion_electiva=electiva,
        )
        db.session.add(c)
        map_code_to_codcurso_2019[codigo_asig] = idx

    db.session.commit()
    print(f"✓ {len(map_code_to_codcurso_2019)} cursos cargados para Plan 2019.")

    # Prerrequisitos MezclaCurso 2019
    mezcla_count_2019 = 0
    for row in df_p2019.to_dict("records"):
        cod_c = clean(row.get("id_curso"))
        cod_req = clean(row.get("id_prerrequisito"))
        if cod_c in map_code_to_codcurso_2019 and cod_req in map_code_to_codcurso_2019:
            num_c = map_code_to_codcurso_2019[cod_c]
            num_req = map_code_to_codcurso_2019[cod_req]
            db.session.add(MezclaCurso(
                cod_fac=1,
                cod_esc=1,
                corr_pe=1,
                cod_curso=num_c,
                cod_curso_prerequisito=num_req,
            ))
            mezcla_count_2019 += 1

    db.session.commit()
    print(f"✓ {mezcla_count_2019} relaciones de prerrequisito en MezclaCurso (Plan 2019).")

    # B. Cursos Plan 2010 (corr_pe = 2)
    path_2010 = docs_dir / "plan_curricular_2010_bd.xlsx"
    df_c2010 = pd.read_excel(path_2010, sheet_name="CURSO", dtype=object)
    df_p2010 = pd.read_excel(path_2010, sheet_name="PRERREQUISITO", dtype=object)

    prereqs_set_2010 = set(df_p2010["id_curso"].astype(str).str.strip().tolist())
    map_code_to_codcurso_2010 = {}

    for idx, row in enumerate(df_c2010.to_dict("records"), start=1):
        codigo_asig = clean(row.get("id_curso"))
        nombre = clean(row.get("nombre_curso"))
        semestre = clean_int(row.get("id_ciclo"), 1)
        cred = clean_dec(row.get("creditos"), Decimal("3.0"))
        tiene_prereq = "S" if codigo_asig in prereqs_set_2010 else "N"

        ht = 2 if cred <= 3 else 3
        hp = 2 if cred >= 3 else 0

        c = Curso(
            cod_fac=1,
            cod_esc=1,
            corr_pe=2,
            cod_curso=idx,
            codigo_asignatura=codigo_asig,
            den_curso=nombre,
            semestre=semestre,
            ht=ht,
            hp=hp,
            cred=cred,
            prereq=tiene_prereq,
            area_curricular=None,
            mencion_electiva=None,
        )
        db.session.add(c)
        map_code_to_codcurso_2010[codigo_asig] = idx

    db.session.commit()
    print(f"✓ {len(map_code_to_codcurso_2010)} cursos cargados para Plan 2010.")

    # Prerrequisitos MezclaCurso 2010
    mezcla_count_2010 = 0
    for row in df_p2010.to_dict("records"):
        cod_c = clean(row.get("id_curso"))
        cod_req = clean(row.get("id_prerrequisito"))
        if cod_c in map_code_to_codcurso_2010 and cod_req in map_code_to_codcurso_2010:
            num_c = map_code_to_codcurso_2010[cod_c]
            num_req = map_code_to_codcurso_2010[cod_req]
            db.session.add(MezclaCurso(
                cod_fac=1,
                cod_esc=1,
                corr_pe=2,
                cod_curso=num_c,
                cod_curso_prerequisito=num_req,
            ))
            mezcla_count_2010 += 1

    db.session.commit()
    print(f"✓ {mezcla_count_2010} relaciones de prerrequisito en MezclaCurso (Plan 2010).")

    # -----------------------------------------------------------------
    # 6. PERIODO ACADÉMICO (Imagen 4 ER)
    # -----------------------------------------------------------------
    print("6. Insertando Períodos Académicos 2026-1 y 2026-2...")
    per1 = PeriodoAcademico(unique_id=1, cod_per_acad="2026-1", fec_inicio=date(2026, 3, 16), fec_fin=date(2026, 7, 31), estado="en_curso")
    per2 = PeriodoAcademico(unique_id=2, cod_per_acad="2026-2", fec_inicio=date(2026, 8, 17), fec_fin=date(2026, 12, 31), estado="en_curso")
    db.session.add_all([per1, per2])
    db.session.commit()
    print("✓ Períodos 2026-1 (Impar) y 2026-2 (Par) configurados.")

    # -----------------------------------------------------------------
    # 7, 8, 9, 10. HORARIOS: HorarioCab, HorarioDet, HorarioDCurso, HorarioDCSeccion
    # -----------------------------------------------------------------
    print("7. Generando estructura de Horarios según Diagrama ER...")
    docentes = [
        "Dr. Carlos Mendoza Ramos",
        "Mg. Rosa Huamán Prado",
        "Ing. Jorge Quispe Castro",
        "Dra. Elena Vargas Silva",
        "Ing. Manuel Ríos Cusiquispe",
        "Mg. Alberto Chumpitaz Vega",
        "Dra. Patricia Benavides Salas",
        "Ing. Fernando Alarcón Díaz",
    ]
    aulas = ["FIIS-101", "FIIS-102", "FIIS-201", "LAB-SIS-01", "LAB-IA"]
    horarios_slots = [
        (1, time(8, 0), time(10, 0)),
        (2, time(10, 0), time(12, 0)),
        (3, time(14, 0), time(16, 0)),
        (4, time(16, 0), time(18, 0)),
        (5, time(18, 0), time(20, 0)),
        (6, time(8, 0), time(12, 0)),
    ]

    id_horario_counter = 1
    id_seccion_counter = 1

    # Para cada período (2026-1 y 2026-2) y cada plan (1 y 2)
    for cod_per, p_obj in [("2026-1", per1), ("2026-2", per2)]:
        for corr in [1, 2]:
            h_cab = HorarioCab(
                id_horario=id_horario_counter,
                cod_per_acad=cod_per,
                cod_fac=1,
                cod_esc=1,
                corr_pe=corr,
                fec_inicio=p_obj.fec_inicio,
            )
            db.session.add(h_cab)

            # HorarioDet para los semestres 1 al 10
            for sem in range(1, 11):
                h_det = HorarioDet(
                    id_horario=id_horario_counter,
                    semestre_corr=sem,
                    semestre_desc=f"Ciclo {sem}",
                )
                db.session.add(h_det)

            db.session.flush()

            # Cursos de este plan
            cursos_plan = Curso.query.filter_by(cod_fac=1, cod_esc=1, corr_pe=corr).all()
            for c in cursos_plan:
                # HorarioDCurso
                h_curso = HorarioDCurso(
                    id_horario=id_horario_counter,
                    semestre_corr=c.semestre,
                    cod_curso=c.cod_curso,
                    nro_secc=1,
                )
                db.session.add(h_curso)
                db.session.flush()

                # HorarioDCSeccion 01
                slot = horarios_slots[(c.cod_curso + c.semestre) % len(horarios_slots)]
                doc = docentes[(c.cod_curso + c.semestre) % len(docentes)]
                aula = aulas[(c.cod_curso + c.semestre) % len(aulas)]

                sec1 = HorarioDCSeccion(
                    id_seccion=id_seccion_counter,
                    id_horario=id_horario_counter,
                    semestre_corr=c.semestre,
                    cod_curso=c.cod_curso,
                    cod_seccion="01",
                    dia_teoria=slot[0],
                    hora_inicio=slot[1],
                    hora_fin=slot[2],
                    aula=aula,
                    docente=doc,
                    cupo_maximo=35,
                    cupo_disponible=30,
                )
                db.session.add(sec1)
                id_seccion_counter += 1

                # Sección 02 para los ciclos correspondientes al período
                es_impar = (c.semestre % 2 == 1)
                if (cod_per == "2026-1" and es_impar) or (cod_per == "2026-2" and not es_impar):
                    slot2 = horarios_slots[(c.cod_curso + c.semestre + 2) % len(horarios_slots)]
                    doc2 = docentes[(c.cod_curso + c.semestre + 3) % len(docentes)]
                    aula2 = aulas[(c.cod_curso + c.semestre + 1) % len(aulas)]

                    sec2 = HorarioDCSeccion(
                        id_seccion=id_seccion_counter,
                        id_horario=id_horario_counter,
                        semestre_corr=c.semestre,
                        cod_curso=c.cod_curso,
                        cod_seccion="02",
                        dia_teoria=slot2[0],
                        hora_inicio=slot2[1],
                        hora_fin=slot2[2],
                        aula=aula2,
                        docente=doc2,
                        cupo_maximo=35,
                        cupo_disponible=32,
                    )
                    db.session.add(sec2)
                    id_seccion_counter += 1

            id_horario_counter += 1
            db.session.commit()

    print(f"✓ HorarioCab, HorarioDet, HorarioDCurso y {id_seccion_counter - 1} secciones creadas.")

    print("✓ Catálogo académico cargado.")


if __name__ == "__main__":
    main()
