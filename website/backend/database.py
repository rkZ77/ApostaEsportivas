import os
from contextlib import contextmanager
from urllib.parse import urlparse
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv, find_dotenv

# DB_*_PROD (e DB_*_DEV, usada por routers/admin.py pros steps dev_*) vivem
# em .env.dev/.env.prod, separadas do .env principal, pra reduzir o raio de
# explosão caso um dos arquivos vaze.
_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)


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


# Chave do pipeline diario. Numero arbitrario, so precisa ser estavel e nao
# colidir com outra trava do mesmo banco.
LOCK_DAILY_PIPELINE = 810_010


@contextmanager
def advisory_lock(key: int):
    """Trava cooperativa no Postgres, escopo de sessao.

    Serve pra quando mais de um processo aponta pro mesmo banco -- producao e
    noprod (staging com dados de prod), ou duas replicas do mesmo servico.
    Os dois acordam no mesmo minuto e disparam o mesmo job; quem nao pegar a
    trava desiste. Diferente da flag SIDE_EFFECTS, isso protege mesmo se
    ninguem configurar variavel nenhuma.

    Cede True se a trava foi obtida, False se outro processo ja a tem. Nunca
    bloqueia esperando (pg_TRY_advisory_lock).
    """
    conn = get_connection()
    # Sem autocommit a sessao ficaria "idle in transaction" durante todo o
    # pipeline (pode passar de meia hora), segurando recursos no servidor.
    conn.autocommit = True
    got = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (key,))
            got = bool(cur.fetchone()["locked"])
        yield got
    finally:
        if got:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
            except Exception:
                pass  # fechar a conexao ja libera a trava de qualquer jeito
        conn.close()
