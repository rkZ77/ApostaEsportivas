"""O agente do chat cota as MESMAS casas que o site coleta.

Existiam tres listas para a mesma pergunta: {8, 32} no coletor de odds, a tabela
`bookmakers` que o /admin edita, e {8, 32, 34} cravado neste arquivo. O
assinante perguntava do jogo pro agente, recebia uma odd da casa 34, e o card do
pick mostrava outra casa e outro numero -- sem nada errado em lugar nenhum,
porque cada metade obedecia a uma lista diferente.

Desde 2026-08-13 os dois leem a tabela, com a constante servindo so' de padrao
quando o banco nao responde.

O conftest recusa conexao de banco em toda a suite, entao o caminho de falha
e' o padrao aqui -- e testa-lo e' de graca: e' exatamente o cenario "banco fora"
que nao pode deixar o chat mudo.
"""
import database
import pytest

from futebol_agent.tools import odds as tool_odds


@pytest.fixture(autouse=True)
def _limpa_cache():
    tool_odds._cache = None
    yield
    tool_odds._cache = None


class _CursorFake:
    def __init__(self, linhas):
        self.linhas = linhas

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.linhas

    def close(self):
        pass


class _ConnFake:
    def __init__(self, linhas):
        self.linhas = linhas

    def cursor(self):
        return _CursorFake(self.linhas)

    def close(self):
        pass


def test_banco_fora_nao_deixa_o_chat_sem_cotar():
    """O conftest ja recusa conexao: este e' o caminho de falha, e ele tem que
    devolver o padrao em vez de estourar na cara de quem esta conversando."""
    assert tool_odds.casas_ativas() == tool_odds.BR_BOOKMAKERS


def test_casa_desativada_no_admin_some_do_chat(monkeypatch):
    monkeypatch.setattr(database, "get_connection", lambda: _ConnFake([(8,)]))

    assert tool_odds.casas_ativas() == {8}


def test_casa_nova_cadastrada_aparece_no_chat(monkeypatch):
    monkeypatch.setattr(database, "get_connection", lambda: _ConnFake([(8,), (32,), (44,)]))

    assert tool_odds.casas_ativas() == {8, 32, 44}


def test_tabela_vazia_cai_no_padrao(monkeypatch):
    """Mesma regra do coletor: "nenhuma casa cadastrada" e' "ninguem cadastrou
    ainda", nao "desligue tudo"."""
    monkeypatch.setattr(database, "get_connection", lambda: _ConnFake([]))

    assert tool_odds.casas_ativas() == tool_odds.BR_BOOKMAKERS


def test_consulta_uma_vez_e_reusa_dentro_do_ttl(monkeypatch):
    """Este caminho roda por MENSAGEM de chat: consultar o banco a cada
    pergunta e' latencia na frente do usuario pra ler uma linha que muda uma
    vez por mes."""
    chamadas = []

    def _conta():
        chamadas.append(1)
        return _ConnFake([(8,)])

    monkeypatch.setattr(database, "get_connection", _conta)
    for _ in range(5):
        tool_odds.casas_ativas()

    assert len(chamadas) == 1


def test_cache_expira(monkeypatch):
    """TTL e' o que faz uma edicao no /admin valer sem reiniciar o servico."""
    chamadas = []

    def _conta():
        chamadas.append(1)
        return _ConnFake([(8,)])

    monkeypatch.setattr(database, "get_connection", _conta)
    tool_odds.casas_ativas()
    # Envelhece o cache alem do TTL sem esperar de verdade.
    tool_odds._cache = (tool_odds._cache[0] - tool_odds._CACHE_TTL_S - 1, tool_odds._cache[1])
    tool_odds.casas_ativas()

    assert len(chamadas) == 2


def test_padrao_e_o_mesmo_do_coletor():
    """A terceira lista era esta: o agente incluia a casa 34, que o coletor
    nunca coletou e da qual o site nunca publicou pick."""
    assert tool_odds.BR_BOOKMAKERS == {8, 32}


def test_odds_do_chat_consultam_a_tabela_e_nao_a_constante():
    """A constante existe como padrao. Se o fluxo voltar a filtrar por ela
    direto, a tela do /admin volta a nao valer pro chat."""
    import inspect

    fonte = inspect.getsource(tool_odds.get_prematch_odds)
    assert "casas_ativas()" in fonte
    assert "BR_BOOKMAKERS" not in fonte
