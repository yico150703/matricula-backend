"""Crea un período académico activo ('2024-2') y secciones de ejemplo para los cursos."""
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
        # 1. Periodo académico
        periodo = PeriodoAcademico.query.filter_by(cod_per_acad="2024-2").first()
        if not periodo:
            periodo = PeriodoAcademico(
                id_periodo=1,
                cod_per_acad="2024-2",
                fecha_inicio=date(2024, 8, 1),
                fecha_fin=date(2024, 12, 31),
                estado="en_curso",
            )
            db.session.add(periodo)
            db.session.commit()
            print("Período '2024-2' creado.")

        # 2. Aulas
        aulas_data = [
            ("A-101", "Pabellón A", 35, "teoria"),
            ("A-102", "Pabellón A", 35, "teoria"),
            ("A-201", "Pabellón B", 40, "teoria"),
            ("LAB-01", "Pabellón Sistemas", 30, "laboratorio"),
            ("LAB-02", "Pabellón Sistemas", 30, "laboratorio"),
        ]
        for cod, pab, cap, tipo in aulas_data:
            if not Aula.query.get(cod):
                db.session.add(Aula(cod_aula=cod, pabellon=pab, capacidad=cap, tipo=tipo))
        db.session.commit()

        # 3. Docentes
        docentes_data = [
            ("D001", "Carlos", "Mendoza Ramos", "cmendoza@unfv.edu.pe"),
            ("D002", "Rosa", "Huamán Prado", "rhuaman@unfv.edu.pe"),
            ("D003", "Jorge", "Quispe Castro", "jquispe@unfv.edu.pe"),
            ("D004", "Elena", "Vargas Silva", "evargas@unfv.edu.pe"),
            ("D005", "Manuel", "Ríos Cusiquispe", "mrios@unfv.edu.pe"),
        ]
        for cod, nom, ape, em in docentes_data:
            if not Docente.query.get(cod):
                db.session.add(Docente(cod_docente=cod, nombres=nom, apellidos=ape, email=em))
        db.session.commit()

        # 4. Secciones para todos los cursos de ambos planes
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
        ]

        for i, curso in enumerate(cursos):
            # Sección 01
            sec = Seccion.query.filter_by(id_curso=curso.id_curso, id_periodo=periodo.id_periodo, nro_seccion="01").first()
            if not sec:
                dia, h_ini, h_fin = horarios[i % len(horarios)]
                doc = docentes[i % len(docentes)]
                aula = aulas[i % len(aulas)]
                db.session.add(Seccion(
                    id_curso=curso.id_curso,
                    id_periodo=periodo.id_periodo,
                    cod_docente=doc.cod_docente,
                    cod_aula=aula.cod_aula,
                    nro_seccion="01",
                    cupo_maximo=30,
                    cupo_disponible=26,
                    dia=dia,
                    hora_inicio=h_ini,
                    hora_fin=h_fin,
                ))
                secciones_creadas += 1

            # Sección 02 para cursos de ciclo 1 al 4
            if curso.ciclo and curso.ciclo.numero_ciclo <= 4:
                sec2 = Seccion.query.filter_by(id_curso=curso.id_curso, id_periodo=periodo.id_periodo, nro_seccion="02").first()
                if not sec2:
                    dia2, h_ini2, h_fin2 = horarios[(i + 2) % len(horarios)]
                    doc2 = docentes[(i + 1) % len(docentes)]
                    aula2 = aulas[(i + 1) % len(aulas)]
                    db.session.add(Seccion(
                        id_curso=curso.id_curso,
                        id_periodo=periodo.id_periodo,
                        cod_docente=doc2.cod_docente,
                        cod_aula=aula2.cod_aula,
                        nro_seccion="02",
                        cupo_maximo=30,
                        cupo_disponible=28,
                        dia=dia2,
                        hora_inicio=h_ini2,
                        hora_fin=h_fin2,
                    ))
                    secciones_creadas += 1

        db.session.commit()
        print(f"Período, aulas, docentes y {secciones_creadas} secciones generadas exitosamente.")


if __name__ == "__main__":
    main()
