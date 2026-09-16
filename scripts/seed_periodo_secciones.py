"""Crea los períodos académicos '2026-1' y '2026-2', docentes, aulas y secciones."""
from datetime import date, time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import db
from app.models import Aula, Curso, Docente, PeriodoAcademico, Seccion


def main():
    app = create_app()
    with app.app_context():
        # 1. Periodos académicos 2026-1 y 2026-2
        p1 = db.session.get(PeriodoAcademico, 1)
        if p1:
            p1.cod_per_acad = "2026-1"
            p1.fecha_inicio = date(2026, 3, 16)
            p1.fecha_fin = date(2026, 7, 31)
            p1.estado = "en_curso"
        else:
            p1 = PeriodoAcademico(id_periodo=1, cod_per_acad="2026-1", fecha_inicio=date(2026, 3, 16), fecha_fin=date(2026, 7, 31), estado="en_curso")
            db.session.add(p1)

        p2 = db.session.get(PeriodoAcademico, 2)
        if p2:
            p2.cod_per_acad = "2026-2"
            p2.fecha_inicio = date(2026, 8, 17)
            p2.fecha_fin = date(2026, 12, 31)
            p2.estado = "en_curso"
        else:
            p2 = PeriodoAcademico(id_periodo=2, cod_per_acad="2026-2", fecha_inicio=date(2026, 8, 17), fecha_fin=date(2026, 12, 31), estado="en_curso")
            db.session.add(p2)
        db.session.commit()
        print("Períodos '2026-1' y '2026-2' configurados.")

        periodos_dict = {"2026-1": p1, "2026-2": p2}

        # 2. Aulas
        aulas_data = [
            ("FIIS-101", "Pabellón FIIS - 1er Piso", 35, "teoria"),
            ("FIIS-102", "Pabellón FIIS - 1er Piso", 35, "teoria"),
            ("FIIS-201", "Pabellón FIIS - 2do Piso", 40, "teoria"),
            ("FIIS-202", "Pabellón FIIS - 2do Piso", 40, "teoria"),
            ("LAB-SIS-01", "Pabellón Sistemas - Lab 1", 30, "laboratorio"),
            ("LAB-SIS-02", "Pabellón Sistemas - Lab 2", 30, "laboratorio"),
            ("LAB-IA", "Centro de Cómputo FIIS", 25, "laboratorio"),
        ]
        for cod, pab, cap, tipo in aulas_data:
            if not db.session.get(Aula, cod):
                db.session.add(Aula(cod_aula=cod, pabellon=pab, capacidad=cap, tipo=tipo))
        db.session.commit()

        # 3. Docentes de la FIIS
        docentes_data = [
            ("D001", "Carlos", "Mendoza Ramos", "cmendoza@unfv.edu.pe"),
            ("D002", "Rosa", "Huamán Prado", "rhuaman@unfv.edu.pe"),
            ("D003", "Jorge", "Quispe Castro", "jquispe@unfv.edu.pe"),
            ("D004", "Elena", "Vargas Silva", "evargas@unfv.edu.pe"),
            ("D005", "Manuel", "Ríos Cusiquispe", "mrios@unfv.edu.pe"),
            ("D006", "Alberto", "Chumpitaz Vega", "achumpitaz@unfv.edu.pe"),
            ("D007", "Patricia", "Benavides Salas", "pbenavides@unfv.edu.pe"),
            ("D008", "Fernando", "Alarcón Díaz", "falarcon@unfv.edu.pe"),
        ]
        for cod, nom, ape, em in docentes_data:
            if not db.session.get(Docente, cod):
                db.session.add(Docente(cod_docente=cod, nombres=nom, apellidos=ape, email=em))
        db.session.commit()

        # 4. Secciones para cursos
        # Ciclos impares (1, 3, 5, 7, 9) principalmente en 2026-1
        # Ciclos pares (2, 4, 6, 8, 10) principalmente en 2026-2
        # (Y también secciones disponibles para que todos los cursos tengan programación activa)
        cursos = Curso.query.all()
        docentes = Docente.query.all()
        aulas = Aula.query.all()
        secciones_creadas = 0

        horarios = [
            (1, time(8, 0), time(10, 0)),
            (2, time(10, 0), time(12, 0)),
            (3, time(14, 0), time(16, 0)),
            (4, time(16, 0), time(18, 0)),
            (5, time(18, 0), time(20, 0)),
            (6, time(8, 0), time(12, 0)), # Sábado mañana
        ]

        for p_cod, p_obj in periodos_dict.items():
            es_impar_periodo = (p_cod == "2026-1")
            for i, curso in enumerate(cursos):
                c_num = curso.ciclo.numero_ciclo if curso.ciclo else 1
                es_impar_ciclo = (c_num % 2 == 1)

                # Priorizar cursos correspondientes al período, pero garantizar secciones para todos
                debe_crear = (es_impar_periodo and es_impar_ciclo) or (not es_impar_periodo and not es_impar_ciclo)

                sec = Seccion.query.filter_by(id_curso=curso.id_curso, id_periodo=p_obj.id_periodo, nro_seccion="01").first()
                if not sec:
                    dia, h_ini, h_fin = horarios[(i + c_num) % len(horarios)]
                    doc = docentes[(i + c_num) % len(docentes)]
                    aula = aulas[(i + c_num) % len(aulas)]
                    db.session.add(Seccion(
                        id_curso=curso.id_curso,
                        id_periodo=p_obj.id_periodo,
                        cod_docente=doc.cod_docente,
                        cod_aula=aula.cod_aula,
                        nro_seccion="01",
                        cupo_maximo=35,
                        cupo_disponible=30,
                        dia=dia,
                        hora_inicio=h_ini,
                        hora_fin=h_fin,
                    ))
                    secciones_creadas += 1

                # Sección 02 para los cursos del ciclo correspondiente al periodo
                if debe_crear:
                    sec2 = Seccion.query.filter_by(id_curso=curso.id_curso, id_periodo=p_obj.id_periodo, nro_seccion="02").first()
                    if not sec2:
                        dia2, h_ini2, h_fin2 = horarios[(i + c_num + 2) % len(horarios)]
                        doc2 = docentes[(i + c_num + 3) % len(docentes)]
                        aula2 = aulas[(i + c_num + 1) % len(aulas)]
                        db.session.add(Seccion(
                            id_curso=curso.id_curso,
                            id_periodo=p_obj.id_periodo,
                            cod_docente=doc2.cod_docente,
                            cod_aula=aula2.cod_aula,
                            nro_seccion="02",
                            cupo_maximo=35,
                            cupo_disponible=32,
                            dia=dia2,
                            hora_inicio=h_ini2,
                            hora_fin=h_fin2,
                        ))
                        secciones_creadas += 1

        db.session.commit()
        print(f"Períodos 2026-1 y 2026-2 listos. Se crearon {secciones_creadas} secciones con docentes y aulas FIIS.")


if __name__ == "__main__":
    main()
