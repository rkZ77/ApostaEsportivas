import os
import psycopg2
from dotenv import load_dotenv, find_dotenv

# Credenciais de banco vivem em .env.dev/.env.prod (separadas do .env
# principal) pra reduzir o raio de explosão caso um dos arquivos vaze --
# ambas continuam carregadas aqui porque scripts como
# copy_prod_history_to_dev.py precisam de PROD e DEV no mesmo processo.
_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)

_logged_envs: set = set()


def get_connection(env: str = None):
    """
    env = 'prod' → usa DB_HOST_PROD, DB_PASS_PROD, etc.
    env = 'dev'  → usa DB_HOST_DEV, DB_PASS_DEV, etc.
    env = None   → usa DB_HOST (legado / Railway)
    Também respeita a variável de ambiente DB_ENV se 'env' não for passado.
    """
    if env is None:
        env = os.getenv("DB_ENV", "").lower()  # "prod", "dev" ou ""

    if env == "prod":
        suffix = "_PROD"
    elif env == "dev":
        suffix = "_DEV"
    else:
        suffix = ""  # compatibilidade com Railway (DB_HOST direto)

    DB_HOST   = os.getenv(f"DB_HOST{suffix}")
    DB_PORT   = os.getenv(f"DB_PORT{suffix}")
    DB_NAME   = os.getenv(f"DB_NAME{suffix}")
    DB_USER   = os.getenv(f"DB_USER{suffix}")
    DB_PASS   = os.getenv(f"DB_PASS{suffix}")
    DB_SSLMODE = os.getenv(f"DB_SSLMODE{suffix}", "require")

    if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS]):
        raise RuntimeError(
            f"Variáveis de banco não definidas para env='{env or 'default'}' no .env")

    label = env.upper() if env else "RAILWAY"
    if label not in _logged_envs:
        print(f"[DB] Conectando ao banco {label}: {DB_HOST}")
        _logged_envs.add(label)

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        sslmode=DB_SSLMODE,
    )
