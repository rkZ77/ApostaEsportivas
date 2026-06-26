import os
from urllib.parse import urlparse
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


def _env(*keys: str, default: str = "") -> str:
    """Retorna o primeiro valor não-vazio dentre as chaves fornecidas."""
    for k in keys:
        v = os.getenv(k, "")
        if v:
            return v
    return default


def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        return psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port,
            dbname=parsed.path.lstrip("/"),
            user=parsed.username,
            password=parsed.password,
            sslmode=_env("DB_SSLMODE", "DB_SSLMODE_PROD", default="require"),
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=10,
        )
    return psycopg2.connect(
        host=_env("DB_HOST", "DB_HOST_PROD"),
        port=_env("DB_PORT", "DB_PORT_PROD", default="5432"),
        dbname=_env("DB_NAME", "DB_NAME_PROD", default="postgres"),
        user=_env("DB_USER", "DB_USER_PROD", default="postgres"),
        password=_env("DB_PASS", "DB_PASS_PROD"),
        sslmode=_env("DB_SSLMODE", "DB_SSLMODE_PROD", default="require"),
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )
