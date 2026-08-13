"""Coleta de odds respeita a tela "Casas de aposta" do /admin.

A REGRESSAO QUE ESTE ARQUIVO FECHA
----------------------------------
A tabela `bookmakers` nasceu em migracao com o proposito escrito de "desativar
uma casa pela tela, sem deploy". O /admin passou a escrever `ativo` nela e a
responder ao usuario que "so' a coleta futura ignora esta casa". O consumidor
nunca foi escrito: o coletor seguia lendo a constante BR_BOOKMAKERS, entao
ativar, desativar ou cadastrar casa pelo site nao mudava nada.

Nao dava erro em lugar nenhum. A tela simplesmente prometia uma coisa e o
coletor fazia outra, e so' quem fosse ler os dois arquivos lado a lado
descobriria.

Nenhum teste aqui toca banco nem API: get_connection e' substituido.
"""
import os

import pytest

os.environ.setdefault("API_FOOTBALL_KEY", "chave-de-teste")

from collectors import odds_collector_service as coletor
from collectors.odds_collector_service import OddsCollectorService, BR_BOOKMAKERS


class _CursorFake:
    def __init__(self, retorno):
        self.retorno = retorno

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.retorno

    def close(self):
        pass


class _ConnFake:
    def __init__(self, retorno):
        self.retorno = retorno
        self.fechada = False

    def cursor(self):
        return _CursorFake(self.retorno)

    def close(self):
        self.fechada = True


def _com_tabela(monkeypatch, ids, contador=None):
    """Substitui get_connection por uma que devolve `ids` como casas ativas."""
    conexoes = []

    def _fake():
        if contador is not None:
            contador.append(1)
        conn = _ConnFake([(i,) for i in ids])
        conexoes.append(conn)
        return conn

    monkeypatch.setattr(coletor, "get_connection", _fake)
    return conexoes


# ── A tela passa a valer ──────────────────────────────────────────────────
def test_casa_desativada_no_admin_sai_da_coleta(monkeypatch):
    """O ponto inteiro: desativar a Betano no /admin tem que parar de coletar
    a Betano."""
    _com_tabela(monkeypatch, [8])

    assert coletor.casas_ativas() == {8}


def test_casa_nova_cadastrada_no_admin_entra_na_coleta(monkeypatch):
    """Cadastrar uma casa pelo site nao pode exigir deploy -- e' o que a
    migration prometeu quando criou a tabela."""
    _com_tabela(monkeypatch, [8, 32, 44])

    assert coletor.casas_ativas() == {8, 32, 44}


# ── Os dois modos de falha que o fallback existe pra evitar ───────────────
def test_tabela_ausente_cai_no_padrao(monkeypatch):
    """Banco anterior a migracao (ou DEV recem-criado): sem fallback a coleta
    do dia inteiro sairia vazia, e o motor ficaria sem odd nenhuma sem nenhum
    erro obvio."""
    def _explode():
        raise RuntimeError('relation "bookmakers" does not exist')

    monkeypatch.setattr(coletor, "get_connection", _explode)

    assert coletor.casas_ativas() == BR_BOOKMAKERS


def test_tabela_vazia_cai_no_padrao(monkeypatch):
    """"Nenhuma casa cadastrada" quase sempre e' "ninguem cadastrou ainda", nao
    "o usuario quis desligar tudo"."""
    _com_tabela(monkeypatch, [])

    assert coletor.casas_ativas() == BR_BOOKMAKERS


def test_conexao_e_fechada_mesmo_quando_a_tabela_esta_vazia(monkeypatch):
    conexoes = _com_tabela(monkeypatch, [])
    coletor.casas_ativas()

    assert all(c.fechada for c in conexoes)


# ── Resolucao unica por execucao ──────────────────────────────────────────
def test_casas_resolvidas_uma_vez_por_rodada(monkeypatch):
    """Uma consulta por fixture seriam centenas de idas ao banco pra ler a
    mesma linha; e a lista mudando no meio faria o mesmo dia ter jogo coletado
    com um conjunto e jogo com outro."""
    chamadas = []
    _com_tabela(monkeypatch, [8, 32], contador=chamadas)

    svc = OddsCollectorService()
    for _ in range(5):
        _ = svc.casas

    assert len(chamadas) == 1


# ── O filtro chega ate' a gravacao ────────────────────────────────────────
def test_save_odds_recebe_so_as_casas_ativas(monkeypatch):
    """Ate 2026-08-13 o filtro era calculado, usado no aviso e na contagem, e
    o `bookmakers` CRU e' que ia pro save_odds. Nao gravou casa proibida
    porque a busca ja e' feita uma casa por vez, mas o filtro estava
    desconectado da gravacao."""
    _com_tabela(monkeypatch, [8])

    svc = OddsCollectorService()
    monkeypatch.setattr(svc, "fetch_odds_by_fixture", lambda fid: {
        "bookmakers": [{"id": 8, "name": "Bet365"}, {"id": 32, "name": "Betano"}]
    })
    recebidos = []
    monkeypatch.setattr(svc, "save_odds", lambda fid, bks: recebidos.append(bks))

    svc.process_fixture_odds(123)

    assert [bk["id"] for bk in recebidos[0]] == [8]


def test_fixture_sem_nenhuma_casa_ativa_nao_grava(monkeypatch):
    _com_tabela(monkeypatch, [8])

    svc = OddsCollectorService()
    monkeypatch.setattr(svc, "fetch_odds_by_fixture", lambda fid: {
        "bookmakers": [{"id": 32, "name": "Betano"}]
    })
    recebidos = []
    monkeypatch.setattr(svc, "save_odds", lambda fid, bks: recebidos.append(bks))

    svc.process_fixture_odds(123)

    assert recebidos == []


def test_busca_na_api_usa_as_casas_ativas(monkeypatch):
    """A busca e' uma requisicao POR CASA. Casa desativada nao pode nem custar
    a requisicao."""
    _com_tabela(monkeypatch, [8])

    pedidos = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": []}

    class _RequestsFake:
        def get(self, url, headers=None, params=None, timeout=None):
            pedidos.append(params["bookmaker"])
            return _Resp()

    monkeypatch.setattr(coletor, "requests", _RequestsFake())

    OddsCollectorService().fetch_odds_by_fixture(123)

    assert pedidos == [8]


# ── O padrao continua sendo o que estava em producao ──────────────────────
def test_padrao_nao_mudou():
    """Banco com a tabela intacta (todas ativas, populadas pela migration a
    partir das odds ja coletadas) tem que produzir a MESMA coleta de antes
    desta mudanca. Se este numero mudar sem decisao, a coleta muda junto."""
    assert BR_BOOKMAKERS == {8, 32}
