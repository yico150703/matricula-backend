import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

def database_url():
    url = os.getenv("DATABASE_URL", "sqlite:///matricula.db")
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-development-key")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    # Tiempo absoluto de sesión (OWASP: depende del uso; una sesión de matrícula es corta)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=float(os.getenv("SESSION_HOURS", "2")))
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
    PASSING_GRADE = float(os.getenv("PASSING_GRADE", "11"))
    MAX_CREDITS = float(os.getenv("MAX_CREDITS", "26"))
    SOBRECUPO_REPITENTES = int(os.getenv("SOBRECUPO_REPITENTES", "5"))
    CARRITO_MINUTOS = int(os.getenv("CARRITO_MINUTOS", "10"))
    RESET_MINUTOS = int(os.getenv("RESET_MINUTOS", "30"))
    FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = os.getenv("SMTP_PORT", "587")
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "")
    DIAS_AJUSTE_HORARIO = int(os.getenv("DIAS_AJUSTE_HORARIO", "14"))
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # PDF del acta de notas: hasta 5 MB
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    JSON_SORT_KEYS = False
