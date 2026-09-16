"""Load the two curricular catalogues directly from the repository Excel sources.

Run after `flask db upgrade`:
    python scripts/seed_curricula.py
"""
from decimal import Decimal
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import AreaCurricular, Ciclo, Curso, Plan, Prerrequisito  # noqa: E402


def clean(value):
    return None if pd.isna(value) or str(value).strip() == "" else str(value).strip()


def integer(value):
    value = clean(value)
    return None if value is None else int(float(value))


def decimal(value):
    value = clean(value)
    return None if value is None else Decimal(value)


def require(condition, message):
    if not condition:
        raise ValueError(f"Excel source validation failed: {message}")


def get_or_create_plan(id_plan, nombre, anio, vigente):
    plan = db.session.get(Plan, id_plan)
    if plan is None:
        plan = Plan(id_plan=id_plan)
        db.session.add(plan)
    plan.nombre, plan.anio_resolucion, plan.vigente = nombre, anio, vigente
    return plan


def seed_2010(path):
    courses = pd.read_excel(path, sheet_name="CURSO", dtype=object)
    prereqs = pd.read_excel(path, sheet_name="PRERREQUISITO", dtype=object)
    cycles = pd.read_excel(path, sheet_name="CICLO", dtype=object)
    require(len(courses) == 62, "Plan 2010 must contain 62 courses")
    require(len(prereqs) == 57, "Plan 2010 must contain 57 prerequisite relations")
    require(len(cycles) == 10, "Plan 2010 must contain 10 cycles")
    require(prereqs.duplicated().sum() == 0, "Plan 2010 prerequisite relation duplicates")
    plan = get_or_create_plan(1, "Plan Curricular 2010", 2010, False)
    db.session.flush()
    cycle_by_number = {}
    for row in cycles.to_dict("records"):
        number = integer(row["id_ciclo"])
        cycle = Ciclo.query.filter_by(id_plan=plan.id_plan, numero_ciclo=number).first()
        if cycle is None:
            cycle = Ciclo(id_plan=plan.id_plan, numero_ciclo=number)
            db.session.add(cycle)
        cycle.nombre_ciclo = clean(row["nombre_ciclo"])
        cycle.anio = integer(row["anio"])
        cycle.total_creditos_declarado = decimal(row["total_creditos"])
        cycle.total_asignaturas_declarado = integer(row["total_asignaturas"])
        db.session.flush()
        cycle_by_number[number] = cycle
    course_by_code = {}
    for row in courses.to_dict("records"):
        code = clean(row["id_curso"])
        course = Curso.query.filter_by(id_plan=plan.id_plan, codigo_curso=code).first()
        if course is None:
            course = Curso(id_plan=plan.id_plan, codigo_curso=code)
            db.session.add(course)
        course.nombre_curso = clean(row["nombre_curso"])
        course.id_ciclo = cycle_by_number[integer(row["id_ciclo"])].id_ciclo
        course.creditos = decimal(row["creditos"])
        course.id_area = None
        course.codigo_certificacion = None
        course.mencion_electiva = None
        course_by_code[code] = course
    db.session.flush()
    Prerrequisito.query.filter_by(id_plan=plan.id_plan).delete()
    for row in prereqs.to_dict("records"):
        code, requisite = clean(row["id_curso"]), clean(row["id_prerrequisito"])
        require(code in course_by_code and requisite in course_by_code, f"unknown Plan 2010 code in prerequisite: {code}/{requisite}")
        db.session.add(Prerrequisito(id_plan=plan.id_plan, id_curso=course_by_code[code].id_curso, id_prerrequisito=course_by_code[requisite].id_curso))


def seed_2019(path):
    courses = pd.read_excel(path, sheet_name="CURSO", dtype=object)
    prereqs = pd.read_excel(path, sheet_name="PRERREQUISITO", dtype=object)
    semesters = pd.read_excel(path, sheet_name="SEMESTRE", dtype=object)
    areas = pd.read_excel(path, sheet_name="AREA_CURRICULAR", dtype=object)
    require(len(courses) == 82, "Malla 2019 must contain 82 source courses")
    require(len(prereqs) == 69, "Malla 2019 must contain 69 prerequisite relations")
    require(len(semesters) == 10 and len(areas) == 4, "Malla 2019 catalogue counts do not match source")
    require({38, 45, 53}.isdisjoint({integer(row["id_curso"]) for row in courses.to_dict("records")}), "Missing IDs 38, 45 and 53 must not be invented")
    plan = get_or_create_plan(2, "Malla Curricular Vigente 2019", 2019, True)
    db.session.flush()
    area_by_name = {}
    for row in areas.to_dict("records"):
        name = clean(row["nombre_area"])
        area = AreaCurricular.query.filter_by(nombre_area=name).first()
        if area is None:
            area = AreaCurricular(id_area=integer(row["id_area"]), nombre_area=name)
            db.session.add(area)
        area_by_name[name] = area
    db.session.flush()
    cycle_by_number = {}
    for row in semesters.to_dict("records"):
        number = integer(row["id_semestre"])
        cycle = Ciclo.query.filter_by(id_plan=plan.id_plan, numero_ciclo=number).first()
        if cycle is None:
            cycle = Ciclo(id_plan=plan.id_plan, numero_ciclo=number)
            db.session.add(cycle)
        cycle.nombre_ciclo = clean(row["nombre_semestre"])
        cycle.anio = None
        cycle.total_creditos_declarado = decimal(row["total_creditos"])
        cycle.total_asignaturas_declarado = None
        db.session.flush()
        cycle_by_number[number] = cycle
    course_by_code = {}
    for row in courses.to_dict("records"):
        code = clean(row["id_curso"])
        course = Curso.query.filter_by(id_plan=plan.id_plan, codigo_curso=code).first()
        if course is None:
            course = Curso(id_plan=plan.id_plan, codigo_curso=code)
            db.session.add(course)
        course.nombre_curso = clean(row["nombre_curso"])
        course.id_ciclo = cycle_by_number[integer(row["id_semestre"])].id_ciclo
        course.creditos = decimal(row["creditos"])
        course.id_area = area_by_name[clean(row["area_curricular"])].id_area
        course.codigo_certificacion = clean(row["codigo_certificacion"])
        course.mencion_electiva = clean(row["mencion_electiva"])
        course_by_code[code] = course
    db.session.flush()
    Prerrequisito.query.filter_by(id_plan=plan.id_plan).delete()
    for row in prereqs.to_dict("records"):
        code, requisite = clean(row["id_curso"]), clean(row["id_prerrequisito"])
        require(code in course_by_code and requisite in course_by_code, f"unknown Malla 2019 code in prerequisite: {code}/{requisite}")
        db.session.add(Prerrequisito(id_plan=plan.id_plan, id_curso=course_by_code[code].id_curso, id_prerrequisito=course_by_code[requisite].id_curso))


def main():
    app = create_app()
    with app.app_context():
        try:
            seed_2010(ROOT / "docs" / "plan_curricular_2010_bd.xlsx")
            seed_2019(ROOT / "docs" / "malla_curricular_bd_2019.xlsx")
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    print("Curricular catalogues seeded successfully: Plan 2010 (62/57) and Malla 2019 (82/69).")


if __name__ == "__main__":
    main()
