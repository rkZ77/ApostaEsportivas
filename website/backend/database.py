import os
import threading
import time
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


def _da_url(url: str) -> dict:
    """Parametros a partir de uma URL postgres://. O pooler do Supabase e'
    entregue nesse formato, com usuario `postgres.<project-ref>`."""
    parsed = urlparse(url)
    return dict(
        host=parsed.hostname,
        port=parsed.port,
        dbname=parsed.path.lstrip("/") or "postgres",
        user=parsed.username,
        password=parsed.password,
        sslmode=_env("DB_SSLMODE", "DB_SSLMODE_PROD", default="require"),
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )


def _parametros(sessao: bool = False) -> dict:
    """Credenciais resolvidas uma vez, num lugar so.

    `sessao=True` devolve o destino das conexoes que precisam de SESSAO
    propria -- hoje so' `advisory_lock`, via get_direct_connection().

    POR QUE O DESTINO PRECISA PODER SER OUTRO
    -----------------------------------------
    `db.<ref>.supabase.co` (a conexao DIRETA do Supabase) tem duas limitacoes
    que so' aparecem com trafego:

      * resolve SO' em IPv6 -- nao existe registro A. Host sem egress IPv6
        simplesmente nao conecta, e o sintoma e' "o banco caiu";
      * `max_connections` = 60 no plano, 3 reservadas. Esse teto e' do PROJETO
        inteiro: o site, o motor e os scripts dividem as mesmas 57.

    O caminho recomendado pelo proprio Supabase e' o pooler (Supavisor), que
    tem IPv4 e multiplexa milhares de clientes em poucas conexoes reais:

        porta 6543 = transaction mode -> o site (DATABASE_URL)
        porta 5432 = session  mode    -> advisory_lock (DATABASE_URL_SESSION)

    E' por isso que os dois destinos sao separaveis por variavel: em
    transaction mode a sessao e' compartilhada entre requests, e
    `pg_try_advisory_lock` -- que e' de sessao -- deixaria de proteger o
    pipeline sem dar erro nenhum. Sem as variaveis de sessao configuradas,
    tudo cai no destino unico de sempre e nada muda.
    """
    if sessao:
        url_sessao = os.getenv("DATABASE_URL_SESSION")
        if url_sessao:
            return _da_url(url_sessao)
        host_sessao = _env("DB_HOST_SESSION")
        if host_sessao:
            return dict(
                host=host_sessao,
                port=_env("DB_PORT_SESSION", default="5432"),
                dbname=_env("DB_NAME_SESSION", "DB_NAME", "DB_NAME_PROD", default="postgres"),
                user=_env("DB_USER_SESSION", "DB_USER", "DB_USER_PROD", default="postgres"),
                password=_env("DB_PASS_SESSION", "DB_PASS", "DB_PASS_PROD"),
                sslmode=_env("DB_SSLMODE", "DB_SSLMODE_PROD", default="require"),
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=10,
            )

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return _da_url(database_url)
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
    return psycopg2.connect(**_parametros(sessao=True))


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

#: Quanto tempo um request espera por um slot do pool antes de considerar
#: abrir conexao propria. Consulta mediana do site e' curta, entao esta espera
#: quase sempre termina em alguns milissegundos.
_ESPERA_POR_SLOT = float(os.getenv("DB_ESPERA_POR_SLOT", "1.5"))
#: Teto de conexoes ABERTAS FORA DO POOL ao mesmo tempo. Somado a _POOL_MAX,
#: e' o maximo que este processo pode tirar das ~57 conexoes utilizaveis do
#: projeto Supabase. Com WEB_CONCURRENCY > 1, multiplique por worker antes de
#: mexer.
_FALLBACK_MAX = int(os.getenv("DB_FALLBACK_MAX", "5"))
#: Prazo TOTAL que um request pode passar aqui dentro. Depois dele, abre
#: conexao propria mesmo estourando o teto: e' o que garante que esta funcao
#: sempre termina. Sem ele o teto vira laco infinito quando o pool nao vaga.
_PRAZO_MAXIMO = float(os.getenv("DB_PRAZO_MAXIMO", "8"))

_pool = None
_pool_lock = threading.Lock()
_fallback_lock = threading.Lock()
_pool_stats = {"reusos": 0, "aberturas": 0, "fallback": 0,
               "fallback_em_uso": 0, "fallback_negado": 0,
               "fallback_acima_do_teto": 0}


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


class _ConexaoDireta:
    """Conexao FORA do pool cujo `close()` devolve o orcamento de fallback.

    Sem isto o teto vazaria: cada pico consumiria o orcamento pra sempre e o
    fallback pararia de existir depois do primeiro dia de movimento.
    """

    __slots__ = ("_conn", "_fechada")

    def __init__(self, conn):
        self._conn = conn
        self._fechada = False

    def __getattr__(self, nome):
        return getattr(self._conn, nome)

    def __setattr__(self, nome, valor):
        if nome in _ConexaoDireta.__slots__:
            object.__setattr__(self, nome, valor)
        else:
            setattr(self._conn, nome, valor)

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def close(self):
        if self._fechada:
            return
        self._fechada = True
        try:
            self._conn.close()
        finally:
            with _fallback_lock:
                _pool_stats["fallback_em_uso"] = max(
                    0, _pool_stats["fallback_em_uso"] - 1)


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

    Pool esgotado NAO vira erro 500: espera um instante por um slot e, se
    nenhum vagar, abre uma conexao direta e segue -- mais lenta porem viva.
    Preferir "site lento" a "site fora" num pico e' a escolha obvia, e o
    contador de fallback deixa o evento visivel em /admin/db-pool em vez de
    silencioso.

    O FALLBACK TEM TETO DESDE 2026-08-26, E O MOTIVO E' O OPOSTO DO QUE PARECE
    --------------------------------------------------------------------------
    Ilimitado, ele transformava um pico em queda do banco INTEIRO. O Supabase
    da' `max_connections` = 60 pro projeto todo -- site, motor e scripts na
    mesma cota. Com o pool em 10, o 11o request simultaneo abria conexao
    direta, o 12o outra, e assim por diante: em 50 requests concorrentes o
    banco recusa TODO MUNDO com "too many connections", inclusive quem ja
    estava sendo atendido e inclusive o motor. Ou seja, o mecanismo que existe
    pra evitar erro 500 num pico era exatamente o que derrubava tudo.

    Com teto, o excedente ESPERA por um slot do pool (que dura milissegundos:
    a consulta mediana e' curta) em vez de abrir conexao nova. Fila e' lenta;
    estouro de conexao e' fora do ar.

    MAS A ESPERA TEM PRAZO (_PRAZO_MAXIMO), E ISSO NAO E' DETALHE. Estourado o
    prazo, esta funcao abre conexao propria mesmo passando do teto. O teto e'
    politica de capacidade; pendurar quem esta tentando usar o site nao e'
    politica nenhuma. Uma versao anterior reiniciava o prazo e podia esperar
    pra sempre -- trocava "site lento", que degrada e volta, por "site
    pendurado", que nao volta sozinho.
    """
    limite = time.monotonic() + _ESPERA_POR_SLOT
    prazo_maximo = time.monotonic() + _PRAZO_MAXIMO
    while True:
        try:
            conn = _obter_pool().getconn()
            _pool_stats["reusos"] += 1
            return _ConexaoDoPool(conn)
        except psycopg2.pool.PoolError:
            # Pool cheio. Ainda da' tempo de esperar um slot?
            if time.monotonic() < limite:
                time.sleep(0.02)
                continue
            with _fallback_lock:
                if _pool_stats["fallback_em_uso"] < _FALLBACK_MAX:
                    _pool_stats["fallback_em_uso"] += 1
                    _pool_stats["fallback"] += 1
                    tem_orcamento = True
                else:
                    _pool_stats["fallback_negado"] += 1
                    tem_orcamento = False
            if not tem_orcamento:
                # SEM SLOT E SEM ORCAMENTO. Esperar mais um pouco e' melhor que
                # estourar o teto de conexoes do projeto -- mas so' ATE' o
                # prazo maximo. Antes daqui existia um `continue` que reiniciava
                # o prazo, e isso e' um laco infinito: com o pool cheio e o
                # orcamento gasto, o request nunca saia. Trocava um problema
                # que degrada (site lento) por um que nao volta sozinho (site
                # pendurado), que e' exatamente o oposto do motivo deste codigo
                # existir.
                if time.monotonic() < prazo_maximo:
                    time.sleep(0.05)
                    limite = time.monotonic() + _ESPERA_POR_SLOT
                    continue
                # Estourou o prazo: abre conexao propria mesmo passando do
                # teto. O teto e' uma politica de capacidade, nao uma promessa
                # -- e nenhuma politica de capacidade justifica pendurar quem
                # esta tentando usar o site.
                with _fallback_lock:
                    _pool_stats["fallback"] += 1
                    _pool_stats["fallback_em_uso"] += 1
                    _pool_stats["fallback_acima_do_teto"] += 1
                return _ConexaoDireta(get_direct_connection())
            return _ConexaoDireta(get_direct_connection())
        except Exception:
            # Pool indisponivel por qualquer outro motivo (credencial, rede na
            # criacao): nao pode derrubar o request que teria funcionado
            # sozinho. Aqui nao ha' pool pra esperar, entao vai direto -- mas
            # ainda contabilizado.
            with _fallback_lock:
                _pool_stats["fallback"] += 1
                _pool_stats["fallback_em_uso"] += 1
            return _ConexaoDireta(get_direct_connection())


def pool_stats() -> dict:
    """Numeros pra confirmar que o pool esta de pe' (ver /admin/db-pool)."""
    pool = _pool
    return {
        "ativo": pool is not None,
        "min": _POOL_MIN,
        "max": _POOL_MAX,
        "fallback_max": _FALLBACK_MAX,
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
