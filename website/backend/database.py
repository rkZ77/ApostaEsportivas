import os
import threading
from contextlib import contextmanager
from urllib.parse import urlparse
import psycopg2
import psycopg2.extras
import psycopg2.pool
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


def _parametros() -> dict:
    """Credenciais resolvidas uma vez, num lugar so."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        return dict(
            host=parsed.hostname,
            port=parsed.port,
            dbname=parsed.path.lstrip("/"),
            user=parsed.username,
            password=parsed.password,
            sslmode=_env("DB_SSLMODE", "DB_SSLMODE_PROD", default="require"),
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=10,
        )
    return dict(
        host=_env("DB_HOST", "DB_HOST_PROD"),
        port=_env("DB_PORT", "DB_PORT_PROD", default="5432"),
        dbname=_env("DB_NAME", "DB_NAME_PROD", default="postgres"),
        user=_env("DB_USER", "DB_USER_PROD", default="postgres"),
        password=_env("DB_PASS", "DB_PASS_PROD"),
        sslmode=_env("DB_SSLMODE", "DB_SSLMODE_PROD", default="require"),
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )


def get_direct_connection():
    """Conexao NOVA, fora do pool. Use so' quando a sessao precisa ser sua.

    Dois casos, e os dois sao reais aqui:

      - a sessao carrega estado (autocommit, trava de sessao). Devolver isso ao
        pool entregaria o estado pro proximo request;
      - a conexao fica presa por muito tempo. `advisory_lock` segura enquanto o
        pipeline roda, o que passa de meia hora -- prender um slot do pool esse
        tempo todo e' tirar capacidade do site pra um job de fundo.
    """
    return psycopg2.connect(**_parametros())


# ─── Pool ────────────────────────────────────────────────────────────────────
# POR QUE ISTO EXISTE, com numero medido (2026-08-13)
#
#     abrir conexao:   998ms
#     cada consulta:   154ms
#
# Abrir custava o equivalente a SEIS consultas, e o codigo abria uma por
# requisicao: 122 chamadas de get_connection() no backend, cada uma seguida de
# conn.close(). Ou seja, todo request do site -- login, Picks, Banca, admin --
# pagava um handshake TLS inteiro com o Supabase antes de fazer qualquer coisa.
#
# Era o custo dominante da Home: /public/leaderboard roda UMA consulta que o
# EXPLAIN ANALYZE mede em 1.6ms, e a resposta levava 829ms.
#
# NAO SE TROCOU NENHUM DOS 122 CHAMADORES. get_connection() devolve um proxy
# cujo .close() DEVOLVE ao pool em vez de fechar. E' o retrofit padrao pra isso:
# a alternativa seria reescrever 122 lugares e depender de ninguem esquecer um.
_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
# Teto conservador: o Supabase limita conexoes por projeto, e o pool concorre
# com os scripts do motor, que abrem as proprias. Subir isto sem olhar o limite
# do plano troca lentidao por "too many connections", que e' pior.
_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

_pool = None
_pool_lock = threading.Lock()
_pool_stats = {"reusos": 0, "aberturas": 0, "fallback": 0}


def _obter_pool():
    """Cria o pool na primeira necessidade, nunca no import.

    No import a suite de teste ainda nao substituiu get_connection, e um pool
    criado ali abriria conexao de verdade -- contra PRODUCAO, porque e' o que o
    .env da raiz aponta. Ja aconteceu de teste escrever em prod neste projeto.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    _POOL_MIN, _POOL_MAX, **_parametros())
    return _pool


class _ConexaoDoPool:
    """Proxy de conexao cujo `close()` devolve ao pool.

    Repassa tudo o mais pro objeto real. `__enter__`/`__exit__` sao explicitos
    porque `__getattr__` nao intercepta dunder: sem eles, `with conn:` pegaria
    o comportamento errado silenciosamente.
    """

    __slots__ = ("_conn", "_devolvida")

    def __init__(self, conn):
        self._conn = conn
        self._devolvida = False

    def __getattr__(self, nome):
        return getattr(self._conn, nome)

    def __setattr__(self, nome, valor):
        # SEM ISTO O PROXY QUEBRA CODIGO QUE JA FUNCIONAVA. `__getattr__` so'
        # cobre LEITURA; escrita cairia no proprio proxy, que tem __slots__ e
        # levanta AttributeError. `conn.autocommit = True` -- exatamente o que
        # advisory_lock faz -- deixaria de funcionar. Foi um teste que pegou
        # isto, nao a leitura do codigo.
        if nome in _ConexaoDoPool.__slots__:
            object.__setattr__(self, nome, valor)
        else:
            setattr(self._conn, nome, valor)

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def close(self):
        # Idempotente de proposito: fechar duas vezes e' comum em codigo com
        # try/finally aninhado, e devolver a mesma conexao duas vezes ao pool
        # entregaria a MESMA sessao a dois requests ao mesmo tempo.
        if self._devolvida:
            return
        self._devolvida = True
        _devolver(self._conn)


def _devolver(conn) -> None:
    """Devolve ao pool deixando a sessao limpa.

    O rollback nao e' zelo: request que estourou no meio deixa a transacao
    aberta, e a proxima pessoa a pegar essa conexao herdaria
    "current transaction is aborted" sem ter feito nada.
    """
    quebrada = False
    try:
        if conn.closed:
            quebrada = True
        else:
            if getattr(conn, "autocommit", False):
                conn.autocommit = False
            conn.rollback()
    except Exception:
        quebrada = True
    try:
        _obter_pool().putconn(conn, close=quebrada)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def get_connection():
    """Conexao do pool. Chame `.close()` normalmente -- ela volta pro pool.

    Pool esgotado NAO vira erro 500: abre uma conexao direta e segue, mais
    lenta porem viva. Preferir "site lento" a "site fora" num pico e' a
    escolha obvia, e o contador de fallback deixa o evento visivel em
    /admin/db-pool em vez de silencioso.
    """
    try:
        conn = _obter_pool().getconn()
        _pool_stats["reusos"] += 1
        return _ConexaoDoPool(conn)
    except psycopg2.pool.PoolError:
        _pool_stats["fallback"] += 1
        return get_direct_connection()
    except Exception:
        # Pool indisponivel por qualquer outro motivo (credencial, rede na
        # criacao): nao pode derrubar o request que teria funcionado sozinho.
        _pool_stats["fallback"] += 1
        return get_direct_connection()


def pool_stats() -> dict:
    """Numeros pra confirmar que o pool esta de pe' (ver /admin/db-pool)."""
    pool = _pool
    return {
        "ativo": pool is not None,
        "min": _POOL_MIN,
        "max": _POOL_MAX,
        "conexoes_abertas": len(getattr(pool, "_used", {})) + len(getattr(pool, "_pool", []))
        if pool else 0,
        "em_uso": len(getattr(pool, "_used", {})) if pool else 0,
        **_pool_stats,
    }


def fechar_pool() -> None:
    """Fecha tudo no shutdown do processo."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            finally:
                _pool = None


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

    CONEXAO DIRETA, fora do pool, por dois motivos independentes: a trava e' de
    SESSAO (devolver a conexao ao pool com a trava presa entregaria ela ao
    proximo request), e a sessao fica segura enquanto o pipeline roda, o que
    passa de meia hora -- prender um slot do pool esse tempo seria tirar
    capacidade do site pra um job de fundo.
    """
    conn = get_direct_connection()
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
