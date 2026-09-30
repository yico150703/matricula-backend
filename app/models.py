import re
from datetime import datetime
from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import deferred, relationship
from .extensions import db

BIGINT = db.BigInteger().with_variant(db.Integer, "sqlite")

TURNOS = {"M": "Mañana", "T": "Tarde", "N": "Noche"}
DIAS = {1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves", 5: "Viernes", 6: "Sábado", 7: "Domingo"}
LABORATORIOS = {"ELEC": "Laboratorio de Electrónica", "FISICA": "Laboratorio de Física"}


def ubicacion_aula(codigo):
    """Traduce el código del horario oficial (B-505, LAB 1...) a una ubicación legible."""
    codigo = (codigo or "").strip().upper()
    m = re.match(r"^([A-Z])-?(\d)(\d{2})$", codigo)
    if m:
        pabellon, piso, resto = m.groups()
        return {"codigo": codigo, "tipo": "aula", "pabellon": pabellon, "piso": int(piso),
                "texto": f"Pabellón {pabellon} · Aula {piso}{resto}", "detalle": f"{piso}.º piso"}
    m = re.match(r"^LAB\.?\s*(.+)$", codigo)
    if m:
        nombre = LABORATORIOS.get(m.group(1), f"Laboratorio de Cómputo {m.group(1)}")
        return {"codigo": codigo, "tipo": "laboratorio", "pabellon": None, "piso": None, "texto": nombre, "detalle": "Laboratorio"}
    return {"codigo": codigo or None, "tipo": "otro", "pabellon": None, "piso": None, "texto": codigo or "Por asignar", "detalle": ""}


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

    @property
    def abreviatura(self):
        palabras = [p for p in re.split(r"[^A-ZÁÉÍÓÚÑ0-9/]+", self.den_curso.upper()) if p]
        romanos = [p for p in palabras if re.fullmatch(r"I{1,3}|IV|V|VI{0,3}|IX|X", p)]
        vacias = {"DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "E", "EN", "A", "CON", "WITH"}
        significativas = [p for p in palabras if p not in vacias and p not in romanos]
        letras = significativas[0][:3] if len(significativas) == 1 else "".join(p[0] for p in significativas)[:4]
        return f"{letras} {romanos[-1]}" if romanos else letras

    def to_dict(self, include_prerequisites=False):
        # Mantiene compatibilidad con la API consumida por el frontend
        id_unico = self.corr_pe * 1000 + self.cod_curso
        return {
            "abreviatura": self.abreviatura,
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
    cupo_disponible = db.Column(db.SmallInteger, nullable=False, default=30)  # legado: la ocupación se calcula
    turno = db.Column(db.String(1), nullable=False, default="M", server_default="M")  # M, T, N
    id_docente = db.Column(db.Integer, ForeignKey("administrador.id_admin", ondelete="SET NULL"))
    estado_docente = db.Column(db.String(12), nullable=False, default="pendiente", server_default="confirmado")  # pendiente|confirmado|observado

    curso_programado = relationship("HorarioDCurso", back_populates="secciones")
    sesiones = relationship(
        "SeccionSesion", back_populates="seccion", cascade="all, delete-orphan", order_by="SeccionSesion.dia, SeccionSesion.hora_inicio"
    )

    def bloques(self):
        """Sesiones semanales de la sección (si no hay detalle, usa el horario principal)."""
        if self.sesiones:
            return list(self.sesiones)
        return [SeccionSesion(dia=self.dia_teoria, hora_inicio=self.hora_inicio, hora_fin=self.hora_fin, aula=self.aula)]

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

    def to_dict(self, curso_dict=None, ocupacion=None):
        if curso_dict is None:
            c = self.curso
            if c:
                curso_dict = c.to_dict()
        sesiones = [b.to_dict() for b in self.bloques()]
        data = {
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
            "ubicacion": ubicacion_aula(self.aula),
            "docente": self.docente,
            "id_docente": self.id_docente,
            "estado_docente": self.estado_docente,
            "turno": self.turno,
            "turno_nombre": TURNOS.get(self.turno, self.turno),
            "sesiones": sesiones,
            "cupo_maximo": self.cupo_maximo,
            "cupo_disponible": self.cupo_disponible,
            "curso": curso_dict,
        }
        if ocupacion is not None:
            data.update(ocupacion)
            data["cupo_disponible"] = max(0, ocupacion["limite"] - ocupacion["matriculados"] - ocupacion["reservados"])
        return data


class SeccionSesion(db.Model):
    """Cada bloque semanal de clases de una sección (una sección puede dictarse 1 a 3 días)."""

    __tablename__ = "seccion_sesion"
    id = db.Column(BIGINT, primary_key=True, autoincrement=True)
    id_seccion = db.Column(BIGINT, ForeignKey("horario_d_c_seccion.id_seccion", ondelete="CASCADE"), nullable=False, index=True)
    dia = db.Column(db.SmallInteger, nullable=False)  # 1=Lun .. 6=Sáb
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    aula = db.Column(db.String(30), nullable=False)

    seccion = relationship("HorarioDCSeccion", back_populates="sesiones")

    def to_dict(self):
        return {
            "dia": self.dia,
            "dia_nombre": DIAS.get(self.dia, str(self.dia)),
            "hora_inicio": self.hora_inicio.isoformat(timespec="minutes"),
            "hora_fin": self.hora_fin.isoformat(timespec="minutes"),
            "aula": self.aula,
            "ubicacion": ubicacion_aula(self.aula),
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
    debe_cambiar_password = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    email_personal = db.Column(db.String(254))
    telefono = db.Column(db.String(20))
    # Cuenta de prueba compartida (se muestra en el login): su contraseña no se cambia y se restablece al arrancar
    cuenta_prueba = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

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
            "rol": "alumno",
            "debe_cambiar_password": bool(self.debe_cambiar_password),
            "cuenta_prueba": bool(self.cuenta_prueba),
            "email_personal": self.email_personal,
            "telefono": self.telefono,
            "facultad": "FIIS - FACULTAD DE INGENIERÍA INDUSTRIAL Y DE SISTEMAS",
            "escuela": "E.P. DE INGENIERÍA DE SISTEMAS",
            "plan": self.plan.to_dict() if self.plan else {
                "id_plan": self.corr_pe,
                "nombre": "Plan 2019" if self.corr_pe == 1 else "Plan 2010",
            },
        }


# 11-B. ADMINISTRADOR (usuario con permisos de gestión: notas, alumnos, períodos)
ROLES_PERSONAL = {
    "admin": "Administrador del sistema",
    "jefe": "Jefe de Departamento",
    "director": "Director de Escuela",
    "asistente": "Asistente de Escuela",
    "docente": "Docente",
}


class Administrador(db.Model):
    """Personal de la universidad con acceso al sistema (tabla histórica 'administrador').

    rol: admin (administrador del sistema), jefe (jefe de departamento: arma horarios),
    director (director de escuela: asigna docentes), asistente (asistente de escuela: asigna aulas)
    y docente (confirma su horario o reporta problemas).
    """

    __tablename__ = "administrador"
    id_admin = db.Column(db.Integer, primary_key=True, autoincrement=True)
    usuario = db.Column(db.String(50), nullable=False, unique=True)
    nombres = db.Column(db.String(150), nullable=False)
    apellidos = db.Column(db.String(150))
    email = db.Column(db.String(254))
    password_hash = db.Column(db.String(255), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    debe_cambiar_password = db.Column(db.Boolean, nullable=False, default=False)
    rol = db.Column(db.String(20), nullable=False, default="admin", server_default="admin")
    cuenta_prueba = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    @property
    def nombre_docente(self):
        """Formato de los horarios oficiales: APELLIDOS NOMBRES en mayúsculas."""
        return " ".join(filter(None, [self.apellidos, self.nombres])).upper()

    def to_dict(self):
        return {
            "id_admin": self.id_admin,
            "id_usuario": self.id_admin,
            "usuario": self.usuario,
            "nombres": self.nombres,
            "apellidos": self.apellidos or "",
            "nombre_completo": " ".join(filter(None, [self.nombres, self.apellidos])),
            "email": self.email,
            "rol": self.rol,
            "rol_nombre": ROLES_PERSONAL.get(self.rol, self.rol),
            "activo": self.activo,
            "debe_cambiar_password": bool(self.debe_cambiar_password),
            "cuenta_prueba": bool(self.cuenta_prueba),
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
    nota_final = db.Column(db.Numeric(4, 2))  # siempre entero (redondeo: desde .5 sube)
    n1 = db.Column(db.Numeric(4, 2))
    n2 = db.Column(db.Numeric(4, 2))
    n3 = db.Column(db.Numeric(4, 2))
    sustitutorio = db.Column(db.Numeric(4, 2))
    aplazado = db.Column(db.Numeric(4, 2))

    matricula = relationship("Matricula", back_populates="detalles")
    seccion = relationship("HorarioDCSeccion")


# 13. CARRITO DE MATRÍCULA (reserva temporal de vacantes)
class CarritoItem(db.Model):
    __tablename__ = "carrito_item"
    __table_args__ = (UniqueConstraint("cod_alumno", "id_periodo", "id_seccion"),)
    id = db.Column(BIGINT, primary_key=True, autoincrement=True)
    cod_alumno = db.Column(db.String(20), ForeignKey("alumno.cod_alumno", ondelete="CASCADE"), nullable=False, index=True)
    id_periodo = db.Column(BIGINT, ForeignKey("periodo_academico.unique_id", ondelete="CASCADE"), nullable=False)
    id_seccion = db.Column(BIGINT, ForeignKey("horario_d_c_seccion.id_seccion", ondelete="CASCADE"), nullable=False, index=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expira_en = db.Column(db.DateTime, nullable=False)

    seccion = relationship("HorarioDCSeccion")


# 14. SOLICITUDES DE RECUPERACIÓN DE CONTRASEÑA
class SolicitudPassword(db.Model):
    __tablename__ = "solicitud_password"
    id = db.Column(BIGINT, primary_key=True, autoincrement=True)
    rol = db.Column(db.String(10), nullable=False)  # alumno | admin
    usuario = db.Column(db.String(50), nullable=False, index=True)  # cod_alumno o usuario admin
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expira_en = db.Column(db.DateTime, nullable=False)
    estado = db.Column(db.String(12), nullable=False, default="pendiente")  # pendiente | usada | atendida | anulada
    canal = db.Column(db.String(12), nullable=False, default="oficina")  # correo | oficina
    atendido_en = db.Column(db.DateTime)


# 16. PROCESO DE CREACIÓN DE HORARIOS (una instancia por período)
FASES = {
    1: "Horarios por curso (Jefe de Departamento)",
    2: "Asignación de docentes (Director de Escuela)",
    3: "Confirmación y asignación de aulas (Asistente)",
    4: "Confirmación de docentes",
    5: "Horarios establecidos · Matrícula abierta",
    6: "Ajustes de horario (hasta 2 semanas de clases)",
    7: "Proceso cerrado",
}


class ProcesoHorario(db.Model):
    __tablename__ = "proceso_horario"
    id_periodo = db.Column(BIGINT, ForeignKey("periodo_academico.unique_id", ondelete="CASCADE"), primary_key=True)
    fase = db.Column(db.SmallInteger, nullable=False, default=1)
    confirmado_jefe = db.Column(db.Boolean, nullable=False, default=False)
    confirmado_director = db.Column(db.Boolean, nullable=False, default=False)
    observacion = db.Column(db.String(500))  # p. ej. motivo de devolución al jefe
    actualizado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    historial = db.Column(db.Text, nullable=False, default="[]")  # JSON: [{fase, fecha, usuario, accion}]

    periodo = relationship("PeriodoAcademico")


class SolicitudCambio(db.Model):
    """Pedido de cambio de horario, docente o aula que otro rol debe aceptar."""

    __tablename__ = "solicitud_cambio"
    id = db.Column(BIGINT, primary_key=True, autoincrement=True)
    id_periodo = db.Column(BIGINT, ForeignKey("periodo_academico.unique_id", ondelete="CASCADE"), nullable=False, index=True)
    id_seccion = db.Column(BIGINT, ForeignKey("horario_d_c_seccion.id_seccion", ondelete="CASCADE"), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # horario | docente | aula
    id_autor = db.Column(db.Integer, ForeignKey("administrador.id_admin", ondelete="CASCADE"), nullable=False)
    rol_autor = db.Column(db.String(20), nullable=False)
    rol_destino = db.Column(db.String(20), nullable=False)
    descripcion = db.Column(db.String(1000), nullable=False)
    propuesta = db.Column(db.Text)  # JSON con el cambio propuesto
    anterior = db.Column(db.String(300))  # cómo estaba la sección al crear la solicitud
    estado = db.Column(db.String(12), nullable=False, default="pendiente")  # pendiente | aprobada | rechazada
    respuesta = db.Column(db.String(1000))
    id_resuelto_por = db.Column(db.Integer, ForeignKey("administrador.id_admin", ondelete="SET NULL"))
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resuelto_en = db.Column(db.DateTime)

    seccion = relationship("HorarioDCSeccion")
    autor = relationship("Administrador", foreign_keys=[id_autor])
    mensajes = relationship("SolicitudMensaje", cascade="all, delete-orphan", order_by="SolicitudMensaje.creado_en")


class SolicitudMensaje(db.Model):
    __tablename__ = "solicitud_mensaje"
    id = db.Column(BIGINT, primary_key=True, autoincrement=True)
    id_solicitud = db.Column(BIGINT, ForeignKey("solicitud_cambio.id", ondelete="CASCADE"), nullable=False, index=True)
    id_autor = db.Column(db.Integer, ForeignKey("administrador.id_admin", ondelete="CASCADE"), nullable=False)
    rol = db.Column(db.String(20), nullable=False)
    texto = db.Column(db.String(1000), nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    autor = relationship("Administrador")


# 15. METADATOS DE LA APLICACIÓN (versión del catálogo cargado, etc.)
class AppMeta(db.Model):
    __tablename__ = "app_meta"
    clave = db.Column(db.String(50), primary_key=True)
    valor = db.Column(db.String(200), nullable=False)


# Aliases para compatibilidad
Plan = PlanEstudio
Seccion = HorarioDCSeccion
Prerrequisito = MezclaCurso


# 16. ACTAS DE NOTAS: el docente registra las notas de su salón y sube el acta firmada (PDF);
# el Director de Escuela la aprueba y recién entonces las notas pasan al registro del alumno.
ESTADOS_ACTA = {
    "borrador": "Borrador del docente",
    "enviada": "Enviada al Director",
    "observada": "Observada por el Director",
    "aprobada": "Aprobada",
}


class ActaNotas(db.Model):
    __tablename__ = "acta_notas"
    id = db.Column(BIGINT, primary_key=True, autoincrement=True)
    id_seccion = db.Column(BIGINT, ForeignKey("horario_d_c_seccion.id_seccion", ondelete="CASCADE"), nullable=False, unique=True)
    id_periodo = db.Column(BIGINT, ForeignKey("periodo_academico.unique_id", ondelete="CASCADE"), nullable=False, index=True)
    id_docente = db.Column(db.Integer, ForeignKey("administrador.id_admin", ondelete="SET NULL"))
    estado = db.Column(db.String(12), nullable=False, default="borrador")
    notas = db.Column(db.Text, nullable=False, default="{}")  # {cod_alumno: {n1, n2, n3, sustitutorio, aplazado}}
    archivo = deferred(db.Column(db.LargeBinary))  # PDF del acta firmada (se guarda en la base: el disco de Render es temporal)
    archivo_nombre = db.Column(db.String(200))
    archivo_bytes = db.Column(db.Integer)
    enviado_en = db.Column(db.DateTime)
    revisado_en = db.Column(db.DateTime)
    id_revisor = db.Column(db.Integer, ForeignKey("administrador.id_admin", ondelete="SET NULL"))
    observacion = db.Column(db.String(1000))
    historial = db.Column(db.Text, nullable=False, default="[]")
    actualizado_en = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    seccion = relationship("HorarioDCSeccion")
    docente = relationship("Administrador", foreign_keys=[id_docente])
    revisor = relationship("Administrador", foreign_keys=[id_revisor])
