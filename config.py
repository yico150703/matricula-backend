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
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
    PASSING_GRADE = float(os.getenv("PASSING_GRADE", "11"))
    MAX_CREDITS = float(os.getenv("MAX_CREDITS", "26"))
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    JSON_SORT_KEYS = False
