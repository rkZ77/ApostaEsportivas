"""Pool de conexao (database.py).

O NUMERO QUE MOTIVOU (medido contra producao em 2026-08-13):

    abrir conexao:   998ms
    cada consulta:   154ms

Abrir custava seis consultas, e o codigo abria uma POR REQUISICAO -- 122
chamadas de get_connection() no backend, cada uma seguida de conn.close().
/public/leaderboard roda UMA consulta que o EXPLAIN ANALYZE mede em 1.6ms e a
resposta levava 829ms: era handshake, nao SQL.

O retrofit nao trocou os 122 chamadores: get_connection() devolve um proxy cujo
close() DEVOLVE ao pool. Isso cria riscos que nao existiam antes, e sao eles que
estes testes cobrem -- estado de sessao vazando pro proximo request, transacao
abortada herdada, e a mesma conexao entregue duas vezes.

Nenhum teste abre conexao real: o pool e' substituido por dubles.
"""
import os

import pytest

os.environ.setdefault("APP_ENV", "development")

import database

# O conftest substitui database.get_connection por uma funcao que RECUSA, pra
# nenhum teste tocar banco -- e' proteção certa e nao se remove. Aqui a gente
# precisa da implementacao de verdade (o pool embaixo dela e' que vira duble),
# entao guarda-se a referencia no import, que acontece antes da fixture.
_get_connection = database.get_connection


class _ConnFake:
    def __init__(self):
        self.closed = 0
        self.autocommit = False
        self.rollbacks = 0
        self.fechada_de_verdade = False

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.fechada_de_verdade = True
        self.closed = 1

    def cursor(self):
        raise AssertionError("teste nao deve consultar")


class _PoolFake:
    def __init__(self, tamanho=2):
        self.livres = [_ConnFake() for _ in range(tamanho)]
        self.devolvidas = []
        self.fechadas_ao_devolver = []

    def getconn(self):
        if not self.livres:
            raise database.psycopg2.pool.PoolError("pool esgotado")
        return self.livres.pop()

    def putconn(self, conn, close=False):
        self.devolvidas.append(conn)
        if close:
            self.fechadas_ao_devolver.append(conn)
        else:
            self.livres.append(conn)   # volta pra fila, como o pool de verdade

    def closeall(self):
        pass


@pytest.fixture
def pool(monkeypatch):
    p = _PoolFake()
    monkeypatch.setattr(database, "_obter_pool", lambda: p)
    monkeypatch.setattr(database, "_pool", p)
    return p


# ── O ganho ───────────────────────────────────────────────────────────────
def test_close_devolve_ao_pool_em_vez_de_fechar(pool):
    """O ponto inteiro: os 122 chamadores continuam escrevendo conn.close()."""
    conn = _get_connection()
    real = conn._conn
    conn.close()

    assert pool.devolvidas == [real]
    assert real.fechada_de_verdade is False


def test_conexao_volta_a_ser_usada(pool):
    primeira = _get_connection()
    real = primeira._conn
    primeira.close()
    segunda = _get_connection()

    assert segunda._conn is real


# ── Vazamento de estado entre requisicoes ─────────────────────────────────
def test_transacao_aberta_e_desfeita_na_devolucao(pool):
    """Request que estourou no meio deixa transacao aberta. Sem rollback, a
    proxima pessoa a pegar essa conexao herda 'current transaction is aborted'
    sem ter feito nada."""
    conn = _get_connection()
    conn.close()

    assert pool.devolvidas[0].rollbacks == 1


def test_autocommit_nao_vaza_pro_proximo_request(pool):
    """advisory_lock liga autocommit. Se essa conexao voltasse ao pool assim,
    o proximo request escreveria sem transacao sem saber."""
    conn = _get_connection()
    conn.autocommit = True
    conn.close()

    assert pool.devolvidas[0].autocommit is False


def test_conexao_quebrada_nao_volta_pro_pool(pool):
    """Devolver conexao morta faz o proximo request falhar por algo que
    aconteceu no anterior."""
    conn = _get_connection()
    conn._conn.closed = 1
    conn.close()

    assert pool.fechadas_ao_devolver == [conn._conn]


def test_devolver_duas_vezes_e_inofensivo(pool):
    """try/finally aninhado fecha duas vezes com facilidade. Devolver a mesma
    conexao duas vezes entregaria a MESMA sessao a dois requests ao mesmo
    tempo -- duas transacoes se misturando."""
    conn = _get_connection()
    conn.close()
    conn.close()

    assert len(pool.devolvidas) == 1


# ── Degradacao ────────────────────────────────────────────────────────────
def test_pool_cheio_abre_conexao_direta_em_vez_de_estourar(pool, monkeypatch):
    """Pico de trafego nao pode virar 500. Site lento e' melhor que site fora."""
    monkeypatch.setattr(database, "_ESPERA_POR_SLOT", 0.0)
    monkeypatch.setattr(database, "get_direct_connection", _ConnFake)

    a = _get_connection()
    b = _get_connection()
    c = _get_connection()

    assert isinstance(c, database._ConexaoDireta)
    assert database.pool_stats()["fallback"] >= 1
    a.close(); b.close(); c.close()


def test_espera_por_slot_antes_de_abrir_conexao_propria(pool, monkeypatch):
    """Slot que vaga em milissegundos nao justifica conexao nova.

    A consulta mediana do site e' curta: esperar quase sempre termina antes de
    a espera acabar, e cada conexao evitada e' uma a menos nas ~57 do projeto.
    """
    monkeypatch.setattr(database, "get_direct_connection",
                        lambda: pytest.fail("nao devia precisar de conexao direta"))
    a = _get_connection()
    b = _get_connection()

    import threading
    threading.Timer(0.05, a.close).start()

    c = _get_connection()          # espera o slot de `a` vagar
    assert isinstance(c, database._ConexaoDoPool)
    b.close(); c.close()


def test_fallback_tem_teto(pool, monkeypatch):
    """SEM TETO, O MECANISMO ANTI-500 DERRUBA O BANCO.

    O Supabase da' max_connections=60 pro projeto INTEIRO -- site, motor e
    scripts na mesma cota. Fallback ilimitado significa uma conexao nova por
    request excedente: em algumas dezenas de requests simultaneos o banco
    recusa todo mundo com "too many connections", inclusive quem ja estava
    sendo atendido. Fila e' lenta; estouro de conexao e' fora do ar.
    """
    monkeypatch.setattr(database, "_ESPERA_POR_SLOT", 0.0)
    monkeypatch.setattr(database, "_FALLBACK_MAX", 1)
    monkeypatch.setattr(database, "get_direct_connection", _ConnFake)

    a = _get_connection()
    b = _get_connection()
    c = _get_connection()          # consome o unico fallback

    assert isinstance(c, database._ConexaoDireta)

    # o proximo nao pode abrir outra: espera. Libera um slot pra ele sair.
    import threading
    threading.Timer(0.05, a.close).start()
    d = _get_connection()
    assert isinstance(d, database._ConexaoDoPool)

    b.close(); c.close(); d.close()


def test_teto_estourado_nao_pendura_o_request(pool, monkeypatch):
    """O TETO NAO PODE VIRAR LACO INFINITO.

    Com o pool cheio, o orcamento gasto e nenhum slot vagando, a versao
    anterior reiniciava o prazo e esperava pra sempre: o request nunca saia.
    Isso troca "site lento", que degrada e volta sozinho, por "site
    pendurado", que nao volta -- o oposto do motivo deste codigo existir.

    Passado o prazo maximo, abre conexao propria mesmo acima do teto. Teto e'
    politica de capacidade; pendurar quem esta usando o site nao e' politica.
    """
    monkeypatch.setattr(database, "_ESPERA_POR_SLOT", 0.0)
    monkeypatch.setattr(database, "_PRAZO_MAXIMO", 0.2)
    monkeypatch.setattr(database, "_FALLBACK_MAX", 0)      # nenhum orcamento
    monkeypatch.setattr(database, "get_direct_connection", _ConnFake)

    a = _get_connection()
    b = _get_connection()

    import time
    t0 = time.monotonic()
    c = _get_connection()                                   # nao pode pendurar
    decorrido = time.monotonic() - t0

    assert isinstance(c, database._ConexaoDireta)
    assert decorrido < 5, f"demorou {decorrido:.1f}s -- pendurou"
    assert database.pool_stats()["fallback_acima_do_teto"] >= 1
    a.close(); b.close(); c.close()


def test_conexao_direta_devolve_o_orcamento_ao_fechar(pool, monkeypatch):
    """Sem isto o teto vazaria: o fallback pararia de existir depois do
    primeiro pico do dia."""
    monkeypatch.setattr(database, "_ESPERA_POR_SLOT", 0.0)
    monkeypatch.setattr(database, "get_direct_connection", _ConnFake)

    a = _get_connection(); b = _get_connection()
    c = _get_connection()
    assert database.pool_stats()["fallback_em_uso"] == 1
    c.close()
    assert database.pool_stats()["fallback_em_uso"] == 0
    c.close()                                   # idempotente
    assert database.pool_stats()["fallback_em_uso"] == 0
    a.close(); b.close()


def test_advisory_lock_nao_usa_o_pool():
    """A trava e' de SESSAO e fica presa enquanto o pipeline roda (passa de
    meia hora). Devolver essa conexao ao pool entregaria a trava ao proximo
    request; e prender um slot esse tempo tira capacidade do site."""
    import inspect

    fonte = inspect.getsource(database.advisory_lock)
    assert "get_direct_connection()" in fonte
    assert "conn = get_connection()" not in fonte


# ── Ciclo de vida ─────────────────────────────────────────────────────────
def test_pool_nao_e_criado_no_import():
    """No import a suite ainda nao substituiu get_connection, e o .env da raiz
    aponta pra PRODUCAO. Criar pool ali abriria conexao real contra prod --
    ja aconteceu de teste escrever em producao neste projeto."""
    import ast

    arvore = ast.parse(open(database.__file__, encoding="utf-8").read())
    atribuicoes = [n for n in arvore.body if isinstance(n, ast.Assign)]
    for no in atribuicoes:
        if any(isinstance(t, ast.Name) and t.id == "_pool" for t in no.targets):
            assert ast.unparse(no.value) == "None"


def test_shutdown_fecha_o_pool():
    """Sem isto cada redeploy deixa ate DB_POOL_MAX conexoes penduradas, e o
    Supabase limita conexoes por projeto."""
    import inspect
    import main

    assert "fechar_pool" in inspect.getsource(main.fechar_pool_hook)
