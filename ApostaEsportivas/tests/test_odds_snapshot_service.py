"""Leitura de odd de jogo passado (services/odds_snapshot_service.py).

`odds_values` e' upsert e guarda so' a cotacao de agora: medido em producao em
2026-08-13, a tabela inteira tinha 1 fixture distinto e nenhum jogo encerrado.
Por isso o backtest cruzava match_statistics com ela e achava ZERO partida, em
DEV e em PROD -- nao era banco desatualizado, era a tabela nao guardar passado.
`odds_snapshots` guardava 311 mil linhas sem ninguem ler.

Nenhum teste toca banco: a consulta e' substituida.
"""
import os

import pytest

os.environ.setdefault("API_FOOTBALL_KEY", "chave-de-teste")

from services.odds_snapshot_service import SnapshotOddsService


def linha(**kw):
    base = {
        "bookmaker_id": 8, "market_id": 5, "value_name": "Over 2.5",
        "line_value": "2.5", "odd_value": 1.85, "minutes_to_kickoff": 30,
        "bookmaker_name": "Bet365", "market_en": "Goals Over/Under",
        "market_pt": "Gols Mais/Menos",
    }
    base.update(kw)
    return base


class _Cursor:
    def __init__(self, linhas):
        self.linhas = linhas
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.linhas

    def close(self):
        pass


class _Conn:
    def __init__(self, linhas):
        self.cur = _Cursor(linhas)

    def cursor(self, **kw):
        return self.cur

    def close(self):
        pass


@pytest.fixture
def conectar(monkeypatch):
    from services import odds_snapshot_service as mod

    def _fabricar(linhas):
        conn = _Conn(linhas)
        monkeypatch.setattr(mod, "get_connection", lambda: conn)
        return conn

    return _fabricar


# ── Reconstrucao do mercado ───────────────────────────────────────────────
def test_market_type_sai_do_catalogo_pela_mesma_funcao_da_producao(conectar):
    """O snapshot guarda so' o market_id. Nome vem de bet_markets_map e o tipo
    de stats_model.classify_market -- a MESMA funcao que classifica em
    producao. Reimplementar aquilo faria o backtest medir outro motor."""
    conectar([linha()])

    saida = SnapshotOddsService().load_odds_by_fixture(1)

    assert saida[0]["market_type"] == "goals"
    assert saida[0]["market_name"] == "Goals Over/Under"
    assert saida[0]["market_pt"] == "Gols Mais/Menos"


def test_mercado_fora_do_catalogo_e_pulado(conectar):
    """Sem o nome em ingles nao ha como classificar familia/escopo, e chutar
    produziria pick de um mercado que o motor nao entende."""
    conectar([linha(market_en=None, market_pt=None)])

    assert SnapshotOddsService().load_odds_by_fixture(1) == []


def test_odd_invalida_e_descartada(conectar):
    conectar([linha(odd_value=1.0), linha(odd_value=0)])

    assert SnapshotOddsService().load_odds_by_fixture(1) == []


def test_casa_sem_nome_nao_vira_none(conectar):
    """bookmaker_name alimenta a contagem de casas e a escolha da melhor odd;
    None ali viraria chave de agrupamento invisivel."""
    conectar([linha(bookmaker_name=None)])

    saida = SnapshotOddsService().load_odds_by_fixture(1)
    assert saida[0]["bookmaker"] == "casa 8"
    assert saida[0]["bookmaker_name"] == "casa 8"


# ── Qual foto e' escolhida ────────────────────────────────────────────────
def test_consulta_pega_a_foto_mais_proxima_do_apito(conectar):
    """DISTINCT ON + ORDER BY crescente = o ultimo preco pre-jogo, que e' o que
    o apostador teria pego."""
    conn = conectar([linha()])
    SnapshotOddsService().load_odds_by_fixture(1)

    sql = conn.cur.sql
    assert "DISTINCT ON (s.bookmaker_id, s.market_id, s.value_name, s.line_value)" in sql
    assert "s.minutes_to_kickoff ASC" in sql


def test_corte_de_minutos_vai_pra_consulta(conectar):
    """`minutes_to_kickoff >= corte` e' o que separa pre-jogo de ao vivo: a
    coluna guarda os dois, com negativo depois do apito."""
    conn = conectar([linha()])
    SnapshotOddsService(minutos_antes=120).load_odds_by_fixture(1)

    assert conn.cur.params == (1, 120)


def test_fixtures_com_snapshot_exige_jogo_encerrado_e_foto_pre_jogo(conectar):
    conn = conectar([])
    SnapshotOddsService().fixtures_com_snapshot()

    sql = conn.cur.sql
    assert "ms.status = 'FT'" in sql
    assert "s.minutes_to_kickoff >= %s" in sql


# ── Reuso da camada de producao ───────────────────────────────────────────
def test_herda_a_agregacao_de_producao(conectar):
    """load_odds_structured (par corrompido, melhor odd, minimo de 2 casas) NAO
    e' reimplementado: e' herdado de OddsService. Um backtest com regra propria
    de agregacao estaria medindo outro motor."""
    from services.odds_service import OddsService

    assert SnapshotOddsService.load_odds_structured is OddsService.load_odds_structured


def test_par_over_under_com_uma_casa_so_e_descartado(conectar):
    """Regra herdada, exercitada de ponta a ponta pela leitura de snapshot."""
    conectar([linha(value_name="Over 2.5", bookmaker_id=8)])

    assert SnapshotOddsService().load_odds_structured(1) == []


def test_par_com_duas_casas_sobrevive_e_pega_a_melhor_odd(conectar):
    conectar([
        linha(value_name="Over 2.5", bookmaker_id=8, odd_value=1.85, bookmaker_name="Bet365"),
        linha(value_name="Over 2.5", bookmaker_id=32, odd_value=1.92, bookmaker_name="Betano"),
    ])

    saida = SnapshotOddsService().load_odds_structured(1)

    assert len(saida) == 1
    assert saida[0]["best_odd"] == 1.92
    assert saida[0]["best_bookmaker"] == "Betano"
    assert saida[0]["bookmakers_count"] == 2
