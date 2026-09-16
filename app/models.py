from datetime import datetime
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import relationship
from .extensions import db

BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")


class Plan(db.Model):
    __tablename__ = "plan"
    id_plan = db.Column(db.SmallInteger, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    anio_resolucion = db.Column(db.SmallInteger)
    vigente = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {"id_plan": self.id_plan, "nombre": self.nombre, "anio_resolucion": self.anio_resolucion, "vigente": self.vigente}


class Ciclo(db.Model):
    __tablename__ = "ciclo"
    __table_args__ = (UniqueConstraint("id_plan", "numero_ciclo"), UniqueConstraint("id_ciclo", "id_plan"))
    id_ciclo = db.Column(BIGINT, primary_key=True)
    id_plan = db.Column(db.SmallInteger, ForeignKey("plan.id_plan", ondelete="RESTRICT"), nullable=False)
    numero_ciclo = db.Column(db.SmallInteger, nullable=False)
    nombre_ciclo = db.Column(db.String(50), nullable=False)
    anio = db.Column(db.SmallInteger)
    total_creditos_declarado = db.Column(db.Numeric(5, 2))
    total_asignaturas_declarado = db.Column(db.SmallInteger)


class AreaCurricular(db.Model):
    __tablename__ = "area_curricular"
    id_area = db.Column(db.SmallInteger, primary_key=True)
    nombre_area = db.Column(db.String(100), nullable=False, unique=True)


class Curso(db.Model):
    __tablename__ = "curso"
    __table_args__ = (
        UniqueConstraint("id_plan", "codigo_curso"),
        UniqueConstraint("id_curso", "id_plan"),
        ForeignKeyConstraint(["id_ciclo", "id_plan"], ["ciclo.id_ciclo", "ciclo.id_plan"], ondelete="RESTRICT"),
    )
    id_curso = db.Column(BIGINT, primary_key=True)
    id_plan = db.Column(db.SmallInteger, ForeignKey("plan.id_plan", ondelete="RESTRICT"), nullable=False)
    codigo_curso = db.Column(db.String(20), nullable=False)
    nombre_curso = db.Column(db.String(200), nullable=False)
    id_ciclo = db.Column(BIGINT, nullable=False)
    creditos = db.Column(db.Numeric(4, 2), nullable=False)
    id_area = db.Column(db.SmallInteger, ForeignKey("area_curricular.id_area", ondelete="SET NULL"))
    codigo_certificacion = db.Column(db.String(50))
    mencion_electiva = db.Column(db.String(150))
    ciclo = relationship("Ciclo")
    area = relationship("AreaCurricular")

    def to_dict(self, include_prerequisites=False):
        data = {"id_curso": self.id_curso, "id_plan": self.id_plan, "codigo_curso": self.codigo_curso,
                "nombre_curso": self.nombre_curso, "ciclo": self.ciclo.numero_ciclo, "nombre_ciclo": self.ciclo.nombre_ciclo,
                "creditos": float(self.creditos), "area_curricular": self.area.nombre_area if self.area else None,
                "codigo_certificacion": self.codigo_certificacion, "mencion_electiva": self.mencion_electiva}
        if include_prerequisites:
            data["prerrequisitos"] = [p.prerrequisito.to_dict() for p in self.prerrequisitos]
        return data


class Prerrequisito(db.Model):
    __tablename__ = "prerrequisito"
    __table_args__ = (
        ForeignKeyConstraint(["id_curso", "id_plan"], ["curso.id_curso", "curso.id_plan"], ondelete="CASCADE"),
        ForeignKeyConstraint(["id_prerrequisito", "id_plan"], ["curso.id_curso", "curso.id_plan"], ondelete="RESTRICT"),
        CheckConstraint("id_curso <> id_prerrequisito"),
    )
    id_plan = db.Column(db.SmallInteger, ForeignKey("plan.id_plan", ondelete="CASCADE"), primary_key=True)
    id_curso = db.Column(BIGINT, primary_key=True)
    id_prerrequisito = db.Column(BIGINT, primary_key=True)
    curso = relationship("Curso", foreign_keys=[id_curso], backref="prerrequisitos")
    prerrequisito = relationship("Curso", foreign_keys=[id_prerrequisito])


class Alumno(db.Model):
    __tablename__ = "alumno"
    cod_alumno = db.Column(db.String(20), primary_key=True)
    nombres = db.Column(db.String(120), nullable=False)
    apellidos = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    id_plan = db.Column(db.SmallInteger, ForeignKey("plan.id_plan", ondelete="RESTRICT"), nullable=False)
    estado = db.Column(db.String(12), nullable=False)
    fecha_ingreso = db.Column(db.Date, nullable=False)
    plan = relationship("Plan")

    def to_dict(self):
        return {"cod_alumno": self.cod_alumno, "nombres": self.nombres, "apellidos": self.apellidos, "email": self.email, "estado": self.estado, "fecha_ingreso": self.fecha_ingreso.isoformat(), "plan": self.plan.to_dict()}


class PeriodoAcademico(db.Model):
    __tablename__ = "periodo_academico"
    id_periodo = db.Column(BIGINT, primary_key=True)
    cod_per_acad = db.Column(db.String(20), nullable=False, unique=True)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    estado = db.Column(db.String(12), nullable=False)

    def to_dict(self):
        return {"id_periodo": self.id_periodo, "cod_per_acad": self.cod_per_acad, "fecha_inicio": self.fecha_inicio.isoformat(), "fecha_fin": self.fecha_fin.isoformat(), "estado": self.estado}


class Docente(db.Model):
    __tablename__ = "docente"
    cod_docente = db.Column(db.String(20), primary_key=True)
    nombres = db.Column(db.String(120), nullable=False)
    apellidos = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True)


class Aula(db.Model):
    __tablename__ = "aula"
    cod_aula = db.Column(db.String(20), primary_key=True)
    pabellon = db.Column(db.String(60), nullable=False)
    capacidad = db.Column(db.SmallInteger, nullable=False)
    tipo = db.Column(db.String(15), nullable=False)


class Seccion(db.Model):
    __tablename__ = "seccion"
    __table_args__ = (UniqueConstraint("id_curso", "id_periodo", "nro_seccion"),)
    id_seccion = db.Column(BIGINT, primary_key=True)
    id_curso = db.Column(BIGINT, ForeignKey("curso.id_curso", ondelete="RESTRICT"), nullable=False)
    id_periodo = db.Column(BIGINT, ForeignKey("periodo_academico.id_periodo", ondelete="RESTRICT"), nullable=False)
    cod_docente = db.Column(db.String(20), ForeignKey("docente.cod_docente", ondelete="RESTRICT"), nullable=False)
    cod_aula = db.Column(db.String(20), ForeignKey("aula.cod_aula", ondelete="RESTRICT"), nullable=False)
    nro_seccion = db.Column(db.String(10), nullable=False)
    cupo_maximo = db.Column(db.SmallInteger, nullable=False)
    cupo_disponible = db.Column(db.SmallInteger, nullable=False)
    dia = db.Column(db.SmallInteger, nullable=False)
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    curso = relationship("Curso")
    docente = relationship("Docente")
    aula = relationship("Aula")

    def to_dict(self):
        return {"id_seccion": self.id_seccion, "curso": self.curso.to_dict(), "nro_seccion": self.nro_seccion, "cupo_maximo": self.cupo_maximo, "cupo_disponible": self.cupo_disponible, "dia": self.dia, "hora_inicio": self.hora_inicio.isoformat(timespec="minutes"), "hora_fin": self.hora_fin.isoformat(timespec="minutes"), "docente": f"{self.docente.nombres} {self.docente.apellidos}", "aula": self.aula.cod_aula}


class Matricula(db.Model):
    __tablename__ = "matricula"
    __table_args__ = (UniqueConstraint("cod_alumno", "id_periodo"),)
    nro_matricula = db.Column(BIGINT, primary_key=True)
    cod_alumno = db.Column(db.String(20), ForeignKey("alumno.cod_alumno", ondelete="RESTRICT"), nullable=False)
    id_periodo = db.Column(BIGINT, ForeignKey("periodo_academico.id_periodo", ondelete="RESTRICT"), nullable=False)
    fecha_matricula = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    estado = db.Column(db.String(12), nullable=False, default="confirmada")
    monto_pagado = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    alumno = relationship("Alumno")
    periodo = relationship("PeriodoAcademico")
    detalles = relationship("MatriculaDetalle", back_populates="matricula", cascade="all, delete-orphan")


class MatriculaDetalle(db.Model):
    __tablename__ = "matricula_detalle"
    __table_args__ = (UniqueConstraint("nro_matricula", "id_seccion"),)
    id = db.Column(BIGINT, primary_key=True)
    nro_matricula = db.Column(BIGINT, ForeignKey("matricula.nro_matricula", ondelete="CASCADE"), nullable=False)
    id_seccion = db.Column(BIGINT, ForeignKey("seccion.id_seccion", ondelete="RESTRICT"), nullable=False)
    estado = db.Column(db.String(12), nullable=False, default="matriculado")
    nota_final = db.Column(db.Numeric(4, 2))
    matricula = relationship("Matricula", back_populates="detalles")
    seccion = relationship("Seccion")
