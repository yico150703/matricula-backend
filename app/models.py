from datetime import datetime
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import relationship
from .extensions import db

BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")


# 1. FACULTAD (Imagen 1)
class Facultad(db.Model):
    __tablename__ = "facultad"
    cod_fac = db.Column(db.SmallInteger, primary_key=True)
    den_fac = db.Column(db.String(100), nullable=False, unique=True)
    escuelas = relationship("Escuela", back_populates="facultad", cascade="all, delete-orphan")

    def to_dict(self):
        return {"cod_fac": self.cod_fac, "den_fac": self.den_fac}


# 2. ESCUELA (Imagen 1)
class Escuela(db.Model):
    __tablename__ = "escuela"
    cod_fac = db.Column(db.SmallInteger, ForeignKey("facultad.cod_fac", ondelete="CASCADE"), primary_key=True)
    cod_esc = db.Column(db.SmallInteger, primary_key=True)
    den_escuela = db.Column(db.String(120), nullable=False)
    facultad = relationship("Facultad", back_populates="escuelas")
    planes = relationship("PlanEstudio", back_populates="escuela", cascade="all, delete-orphan")

    def to_dict(self):
        return {"cod_fac": self.cod_fac, "cod_esc": self.cod_esc, "den_escuela": self.den_escuela}


# 3. PLAN DE ESTUDIO (Imagen 2)
class PlanEstudio(db.Model):
    __tablename__ = "plan_estudio"
    __table_args__ = (
        ForeignKeyConstraint(["cod_fac", "cod_esc"], ["escuela.cod_fac", "escuela.cod_esc"], ondelete="CASCADE"),
    )
    cod_fac = db.Column(db.SmallInteger, primary_key=True)
    cod_esc = db.Column(db.SmallInteger, primary_key=True)
    corr_pe = db.Column(db.SmallInteger, primary_key=True)  # 1 = Plan 2019, 2 = Plan 2010
    anio_pe = db.Column(db.String(50), nullable=False)       # 'Plan 2019', 'Plan 2010'
    vigente = db.Column(db.Boolean, nullable=False, default=False)
    escuela = relationship("Escuela", back_populates="planes")
    cursos = relationship("Curso", back_populates="plan_estudio", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id_plan": self.corr_pe,
            "cod_fac": self.cod_fac,
            "cod_esc": self.cod_esc,
            "corr_pe": self.corr_pe,
            "nombre": self.anio_pe,
            "anio_pe": self.anio_pe,
            "anio_resolucion": 2019 if self.corr_pe == 1 else 2010,
            "vigente": self.vigente,
        }


# 4. CURSO (Imagen 2)
class Curso(db.Model):
    __tablename__ = "curso"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cod_fac", "cod_esc", "corr_pe"],
            ["plan_estudio.cod_fac", "plan_estudio.cod_esc", "plan_estudio.corr_pe"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("cod_fac", "cod_esc", "corr_pe", "codigo_asignatura"),
    )
    cod_fac = db.Column(db.SmallInteger, primary_key=True)
    cod_esc = db.Column(db.SmallInteger, primary_key=True)
    corr_pe = db.Column(db.SmallInteger, primary_key=True)
    cod_curso = db.Column(db.Integer, primary_key=True)      # Correlativo: 1, 2, 3...
    codigo_asignatura = db.Column(db.String(20), nullable=False) # Código oficial: EGE005, 10001, etc.
    den_curso = db.Column(db.String(200), nullable=False)    # Denominación: Mate. Discreta, etc.
    semestre = db.Column(db.SmallInteger, nullable=False)    # Ciclo del 1 al 10
    ht = db.Column(db.SmallInteger, nullable=False, default=2) # Horas Teoría
    hp = db.Column(db.SmallInteger, nullable=False, default=2) # Horas Práctica
    cred = db.Column(db.Numeric(4, 2), nullable=False)       # Créditos
    prereq = db.Column(db.String(1), nullable=False, default="N") # 'S' o 'N'
    area_curricular = db.Column(db.String(100))
    mencion_electiva = db.Column(db.String(150))

    plan_estudio = relationship("PlanEstudio", back_populates="cursos")

    def to_dict(self, include_prerequisites=False):
        # Mantiene compatibilidad con la API consumida por el frontend
        id_unico = self.corr_pe * 1000 + self.cod_curso
        return {
            "id_curso": id_unico,
            "cod_curso": self.cod_curso,
            "codigo_curso": self.codigo_asignatura,
            "codigo_asignatura": self.codigo_asignatura,
            "nombre_curso": self.den_curso,
            "den_curso": self.den_curso,
            "ciclo": self.semestre,
            "semestre": self.semestre,
            "ht": self.ht,
            "hp": self.hp,
            "creditos": float(self.cred),
            "cred": float(self.cred),
            "prereq": self.prereq,
            "area_curricular": self.area_curricular,
            "mencion_electiva": self.mencion_electiva,
            "id_plan": self.corr_pe,
        }


# 5. MEZCLA CURSO (Prerrequisitos - Imagen 3)
class MezclaCurso(db.Model):
    __tablename__ = "mezcla_curso"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cod_fac", "cod_esc", "corr_pe", "cod_curso"],
            ["curso.cod_fac", "curso.cod_esc", "curso.corr_pe", "curso.cod_curso"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["cod_fac", "cod_esc", "corr_pe", "cod_curso_prerequisito"],
            ["curso.cod_fac", "curso.cod_esc", "curso.corr_pe", "curso.cod_curso"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("cod_curso <> cod_curso_prerequisito"),
    )
    cod_fac = db.Column(db.SmallInteger, primary_key=True)
    cod_esc = db.Column(db.SmallInteger, primary_key=True)
    corr_pe = db.Column(db.SmallInteger, primary_key=True)
    cod_curso = db.Column(db.Integer, primary_key=True)
    cod_curso_prerequisito = db.Column(db.Integer, primary_key=True)


# 6. PERIODO ACADÉMICO (Imagen 4 ER)
class PeriodoAcademico(db.Model):
    __tablename__ = "periodo_academico"
    unique_id = db.Column(BIGINT, primary_key=True)
    cod_per_acad = db.Column(db.String(20), nullable=False, unique=True) # '2026-1', '2026-2'
    fec_inicio = db.Column(db.Date, nullable=False)
    fec_fin = db.Column(db.Date, nullable=False)
    estado = db.Column(db.String(12), nullable=False, default="en_curso") # 'en_curso', 'cerrado'

    def to_dict(self):
        return {
            "id_periodo": self.unique_id,
            "unique_id": self.unique_id,
            "cod_per_acad": self.cod_per_acad,
            "fecha_inicio": self.fec_inicio.isoformat(),
            "fecha_fin": self.fec_fin.isoformat(),
            "estado": self.estado,
        }


# 7. HORARIO CABECERA (Imagen 4 ER)
class HorarioCab(db.Model):
    __tablename__ = "horario_cab"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cod_fac", "cod_esc", "corr_pe"],
            ["plan_estudio.cod_fac", "plan_estudio.cod_esc", "plan_estudio.corr_pe"],
            ondelete="CASCADE",
        ),
    )
    id_horario = db.Column(BIGINT, primary_key=True)
    cod_per_acad = db.Column(db.String(20), ForeignKey("periodo_academico.cod_per_acad", ondelete="CASCADE"), nullable=False)
    cod_fac = db.Column(db.SmallInteger, nullable=False)
    cod_esc = db.Column(db.SmallInteger, nullable=False)
    corr_pe = db.Column(db.SmallInteger, nullable=False)
    fec_inicio = db.Column(db.Date, nullable=False)

    detalles = relationship("HorarioDet", back_populates="cabecera", cascade="all, delete-orphan")


# 8. HORARIO DETALLE POR SEMESTRE (Imagen 4 ER)
class HorarioDet(db.Model):
    __tablename__ = "horario_det"
    id_horario = db.Column(BIGINT, ForeignKey("horario_cab.id_horario", ondelete="CASCADE"), primary_key=True)
    semestre_corr = db.Column(db.SmallInteger, primary_key=True) # 1..10
    semestre_desc = db.Column(db.String(50), nullable=False)     # 'Ciclo I', 'Ciclo II', etc.

    cabecera = relationship("HorarioCab", back_populates="detalles")
    cursos_programados = relationship("HorarioDCurso", back_populates="horario_det", cascade="all, delete-orphan")


# 9. HORARIO DETALLE POR CURSO (Imagen 4 ER)
class HorarioDCurso(db.Model):
    __tablename__ = "horario_d_curso"
    __table_args__ = (
        ForeignKeyConstraint(["id_horario", "semestre_corr"], ["horario_det.id_horario", "horario_det.semestre_corr"], ondelete="CASCADE"),
    )
    id_horario = db.Column(BIGINT, primary_key=True)
    semestre_corr = db.Column(db.SmallInteger, primary_key=True)
    cod_curso = db.Column(db.Integer, primary_key=True)
    nro_secc = db.Column(db.SmallInteger, nullable=False, default=1)

    horario_det = relationship("HorarioDet", back_populates="cursos_programados")
    secciones = relationship("HorarioDCSeccion", back_populates="curso_programado", cascade="all, delete-orphan")


# 10. HORARIO DETALLE POR SECCIÓN (Imagen 4 ER)
class HorarioDCSeccion(db.Model):
    __tablename__ = "horario_d_c_seccion"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id_horario", "semestre_corr", "cod_curso"],
            ["horario_d_curso.id_horario", "horario_d_curso.semestre_corr", "horario_d_curso.cod_curso"],
            ondelete="CASCADE",
        ),
    )
    id_seccion = db.Column(BIGINT, primary_key=True)
    id_horario = db.Column(BIGINT, nullable=False)
    semestre_corr = db.Column(db.SmallInteger, nullable=False)
    cod_curso = db.Column(db.Integer, nullable=False)
    cod_seccion = db.Column(db.String(10), nullable=False)       # '01', '02'
    dia_teoria = db.Column(db.SmallInteger, nullable=False)      # 1=Lun..6=Sáb
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    aula = db.Column(db.String(30), nullable=False, default="FIIS-101")
    docente = db.Column(db.String(150), nullable=False)
    cupo_maximo = db.Column(db.SmallInteger, nullable=False, default=35)
    cupo_disponible = db.Column(db.SmallInteger, nullable=False, default=30)

    curso_programado = relationship("HorarioDCurso", back_populates="secciones")

    @property
    def dia(self):
        return self.dia_teoria

    @property
    def nro_seccion(self):
        return self.cod_seccion

    @property
    def curso(self):
        try:
            if self.curso_programado and self.curso_programado.horario_det and self.curso_programado.horario_det.cabecera:
                cab = self.curso_programado.horario_det.cabecera
                return Curso.query.filter_by(
                    cod_fac=cab.cod_fac,
                    cod_esc=cab.cod_esc,
                    corr_pe=cab.corr_pe,
                    cod_curso=self.cod_curso,
                ).first()
        except Exception:
            pass
        return None

    def to_dict(self, curso_dict=None):
        if curso_dict is None:
            c = self.curso
            if c:
                curso_dict = c.to_dict()
        return {
            "id_seccion": self.id_seccion,
            "id_horario": self.id_horario,
            "id_curso": (curso_dict.get("id_curso") if curso_dict else self.cod_curso),
            "semestre_corr": self.semestre_corr,
            "cod_curso": self.cod_curso,
            "nro_seccion": self.cod_seccion,
            "cod_seccion": self.cod_seccion,
            "dia": self.dia_teoria,
            "hora_inicio": self.hora_inicio.isoformat(timespec="minutes"),
            "hora_fin": self.hora_fin.isoformat(timespec="minutes"),
            "aula": self.aula,
            "docente": self.docente,
            "cupo_maximo": self.cupo_maximo,
            "cupo_disponible": self.cupo_disponible,
            "curso": curso_dict,
        }


# 11. ALUMNO (Ingeniería de Sistemas)
class Alumno(db.Model):
    __tablename__ = "alumno"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cod_fac", "cod_esc", "corr_pe"],
            ["plan_estudio.cod_fac", "plan_estudio.cod_esc", "plan_estudio.corr_pe"],
            ondelete="RESTRICT",
        ),
    )
    cod_alumno = db.Column(db.String(20), primary_key=True)
    nombres = db.Column(db.String(120), nullable=False)
    apellidos = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    cod_fac = db.Column(db.SmallInteger, nullable=False, default=1)  # FIIS
    cod_esc = db.Column(db.SmallInteger, nullable=False, default=1)  # Sistemas
    corr_pe = db.Column(db.SmallInteger, nullable=False, default=1)  # Plan 2019
    estado = db.Column(db.String(12), nullable=False, default="activo")
    fecha_ingreso = db.Column(db.Date, nullable=False)

    plan = relationship("PlanEstudio")

    @property
    def id_plan(self):
        return self.corr_pe

    @id_plan.setter
    def id_plan(self, val):
        self.corr_pe = val

    def to_dict(self):
        return {
            "cod_alumno": self.cod_alumno,
            "nombres": self.nombres,
            "apellidos": self.apellidos,
            "email": self.email,
            "estado": self.estado,
            "fecha_ingreso": self.fecha_ingreso.isoformat(),
            "cod_fac": self.cod_fac,
            "cod_esc": self.cod_esc,
            "corr_pe": self.corr_pe,
            "id_plan": self.corr_pe,
            "facultad": "FIIS - FACULTAD DE INGENIERÍA INDUSTRIAL Y DE SISTEMAS",
            "escuela": "E.P. DE INGENIERÍA DE SISTEMAS",
            "plan": self.plan.to_dict() if self.plan else {
                "id_plan": self.corr_pe,
                "nombre": "Malla Curricular Vigente 2019" if self.corr_pe == 1 else "Plan Curricular 2010",
            },
        }


# 12. MATRÍCULA Y DETALLE
class Matricula(db.Model):
    __tablename__ = "matricula"
    __table_args__ = (UniqueConstraint("cod_alumno", "id_periodo"),)
    nro_matricula = db.Column(BIGINT, primary_key=True, autoincrement=True)
    cod_alumno = db.Column(db.String(20), ForeignKey("alumno.cod_alumno", ondelete="RESTRICT"), nullable=False)
    id_periodo = db.Column(BIGINT, ForeignKey("periodo_academico.unique_id", ondelete="RESTRICT"), nullable=False)
    fecha_matricula = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    estado = db.Column(db.String(12), nullable=False, default="confirmada")
    monto_pagado = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    alumno = relationship("Alumno")
    periodo = relationship("PeriodoAcademico")
    detalles = relationship("MatriculaDetalle", back_populates="matricula", cascade="all, delete-orphan")


class MatriculaDetalle(db.Model):
    __tablename__ = "matricula_detalle"
    __table_args__ = (UniqueConstraint("nro_matricula", "id_seccion"),)
    id = db.Column(BIGINT, primary_key=True, autoincrement=True)
    nro_matricula = db.Column(BIGINT, ForeignKey("matricula.nro_matricula", ondelete="CASCADE"), nullable=False)
    id_seccion = db.Column(BIGINT, ForeignKey("horario_d_c_seccion.id_seccion", ondelete="RESTRICT"), nullable=False)
    estado = db.Column(db.String(12), nullable=False, default="matriculado")
    nota_final = db.Column(db.Numeric(4, 2))

    matricula = relationship("Matricula", back_populates="detalles")
    seccion = relationship("HorarioDCSeccion")


# Aliases para compatibilidad
Plan = PlanEstudio
Seccion = HorarioDCSeccion
Prerrequisito = MezclaCurso
