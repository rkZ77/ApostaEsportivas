"""Mercado de 1º tempo liquidava contra o jogo inteiro no site.

`_enrich_leg` lia o placar e a folha do JOGO INTEIRO pra qualquer mercado:
"Escanteios 1º Tempo Menos de 4.5" com 3 no intervalo e 10 no fim saía RED.
Desde 27/09/2026 a folha por tempo vem na mesma requisição (`half=true`), e do
intervalo em diante o mercado de 1º tempo lê o placar do intervalo e a folha
`statistics_1h`.

Nenhum teste toca rede nem banco.
"""
import pytest

import market_form
from routers import live


RESPOSTA_DA_API = [
    {"team": {"id": 20},
     "statistics": [{"type": "Corner Kicks", "value": 4}],
     "statistics_1h": [{"type": "Corner Kicks", "value": 1}]},
    {"team": {"id": 10},
     "statistics": [{"type": "Corner Kicks", "value": 6}],
     "statistics_1h": [{"type": "Corner Kicks", "value": 2}]},
]


def _fixture(status="FT", halftime=(0, 1)):
    ht = {"home": halftime[0], "away": halftime[1]} if halftime else {}
    return {
        "fixture": {"status": {"short": status}, "timestamp": 1_700_000_000},
        "goals": {"home": 3, "away": 2},
        "score": {"halftime": ht},
        "teams": {"home": {"id": 10}, "away": {"id": 20}},
        "league": {"id": 71},
    }


@pytest.fixture
def api(monkeypatch):
    def _instalar(**kw):
        monkeypatch.setattr(live, "_fetch_fixture", lambda fid: _fixture(**kw))
        monkeypatch.setattr(live, "_fetch_stats", lambda fid, status: RESPOSTA_DA_API)
    return _instalar


def _perna(market, line, market_type=None):
    return live._enrich_leg(1492380, market, line, "Athletico", "Outro", 10, 20, 1.8,
                            market_type=market_type)


def test_escanteio_do_1o_tempo_liquida_pela_folha_do_1o_tempo(api):
    """3 no intervalo, 10 no jogo: GREEN, e nao o RED do jogo inteiro."""
    api()
    perna = _perna("Total de Escanteios (1º Tempo)", "Under 4.5", "corners_1h")
    assert perna["current_val"] == 3
    assert live._locked_leg_result(perna) == "GREEN"


def test_gol_do_1o_tempo_usa_o_placar_do_intervalo(api):
    api()
    perna = _perna("Gols Mais/Menos - 1º Tempo", "Over 1.5", "goals_1h")
    assert perna["current_val"] == 1
    assert live._locked_leg_result(perna) == "RED"


def test_ambas_marcam_do_1o_tempo(api):
    api()
    perna = _perna("Ambas Marcam - 1º Tempo", "Sim", "btts_1h")
    assert live._locked_leg_result(perna) == "RED"


def test_durante_o_1o_tempo_o_numero_de_agora_e_o_do_1o_tempo(api):
    """Com a bola rolando no 1º tempo a folha cheia AINDA é a do 1º tempo."""
    api(status="1H", halftime=None)
    perna = _perna("Total de Escanteios (1º Tempo)", "Over 8.5", "corners_1h")
    assert perna["current_val"] == 10


def test_sem_placar_do_intervalo_nao_liquida(api):
    api(halftime=None)
    perna = _perna("Gols Mais/Menos - 1º Tempo", "Over 0.5", "goals_1h")
    assert perna["is_ft"] is False
    assert live._locked_leg_result(perna) is None


def test_jogo_inteiro_nao_mudou(api):
    api()
    perna = _perna("Escanteios Mais/Menos", "Under 12.5", "corners")
    assert perna["current_val"] == 10


def test_prorrogacao_nao_prende_o_1o_tempo(api):
    api(status="AET")
    perna = _perna("Total de Escanteios (1º Tempo)", "Under 4.5", "corners_1h")
    assert perna["went_to_extra_time"] is False
    assert live._locked_leg_result(perna) == "GREEN"


def test_serie_do_card_le_as_colunas_do_1o_tempo():
    ms = {"home_corners": 6, "away_corners": 4,
          "home_corners_1h": 2, "away_corners_1h": 1}
    casa, fora = market_form.folha_do_jogo(ms, primeiro_tempo=True)
    assert (casa["Corner Kicks"], fora["Corner Kicks"]) == (2, 1)


@pytest.mark.parametrize("market, market_type", [
    ("Total de Escanteios (1º Tempo)", None),
    ("Gols Mais/Menos - 1º Tempo", None),
    ("Escanteios Mais/Menos", "corners_1h"),
    ("Under 2.5 HT", "goals_ht"),
])
def test_reconhece_o_1o_tempo(market, market_type):
    assert market_form.e_mercado_de_primeiro_tempo(market, market_type)


def test_jogo_inteiro_nao_e_1o_tempo():
    assert not market_form.e_mercado_de_primeiro_tempo("Escanteios Mais/Menos", "corners")


def test_gol_do_2o_tempo_no_site(api):
    """3x2 no fim, 0x1 no intervalo: 4 gols no 2o tempo."""
    api()
    perna = _perna("Gols Mais/Menos - 2º Tempo", "Over 3.5")
    assert perna["current_val"] == 4
    assert live._locked_leg_result(perna) == "GREEN"


def test_escanteio_do_2o_tempo_le_a_folha_do_2o_tempo(api, monkeypatch):
    api()  # sem o duble, `_fetch_fixture` iria a API de verdade
    resposta = [dict(t, statistics_2h=[{"type": "Corner Kicks", "value": v}])
                for t, v in zip(RESPOSTA_DA_API, (3, 4))]
    monkeypatch.setattr(live, "_fetch_stats", lambda fid, status: resposta)
    perna = _perna("Total de Escanteios (2º Tempo)", "Under 7.5")
    assert perna["current_val"] == 7
