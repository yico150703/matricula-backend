"""Fechas en la hora de Lima: el servidor (Render) trabaja en UTC y a las 19:00 de Lima ya sería 'mañana'."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo(os.getenv("ZONA_HORARIA", "America/Lima"))


def hoy() -> date:
    return datetime.now(ZONA).date()
