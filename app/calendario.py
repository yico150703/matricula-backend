"""Calendario académico UNFV: cada período dura 16 semanas de clases (lunes a sábado), sigue 1 semana de
vacaciones y el lunes siguiente empieza el período 2. El período 1 empieza un lunes de marzo, abril o mayo."""
from datetime import date, timedelta

from .errors import ApiError

SEMANAS_CLASES = 16
SEMANAS_VACACIONES = 1
MESES_INICIO_PRIMERO = (3, 4, 5)
MESES = {3: "marzo", 4: "abril", 5: "mayo"}


def fin_de_clases(inicio: date) -> date:
    """Sábado de la semana 16."""
    return inicio + timedelta(weeks=SEMANAS_CLASES) - timedelta(days=2)


def inicio_segundo(inicio_primero: date) -> date:
    """Lunes siguiente a la semana de vacaciones."""
    return inicio_primero + timedelta(weeks=SEMANAS_CLASES + SEMANAS_VACACIONES)


def validar_inicio_primero(inicio: date, anio: int):
    if inicio.weekday() != 0:
        raise ApiError("fecha_invalida", "El inicio de clases debe ser un lunes.", 400)
    if inicio.year != anio or inicio.month not in MESES_INICIO_PRIMERO:
        raise ApiError("fecha_invalida", f"El período {anio}-1 debe empezar un lunes de marzo, abril o mayo de {anio}.", 400)


def fechas_para(cod: str, inicio: date | None, inicio_primero: date | None):
    """Devuelve (inicio, fin) del período según su código (AAAA-1 / AAAA-2)."""
    anio, numero = int(cod[:4]), cod[-1]
    if numero == "1":
        if inicio is None:
            raise ApiError("datos_invalidos", "Indica la fecha de inicio de clases.", 400)
        validar_inicio_primero(inicio, anio)
        return inicio, fin_de_clases(inicio)
    if inicio_primero is None:
        raise ApiError("falta_primer_periodo", f"Primero crea el período {anio}-1: el {anio}-2 empieza la semana siguiente a sus vacaciones.", 409)
    ini = inicio_segundo(inicio_primero)
    return ini, fin_de_clases(ini)
