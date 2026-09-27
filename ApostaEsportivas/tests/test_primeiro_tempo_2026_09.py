# -*- coding: utf-8 -*-
"""Mercados de 1o tempo: coleta, pool do motor e liquidacao (2026-09-27).

O QUE FALTAVA
-------------
O motor so' conhecia o placar do intervalo. Escanteio, cartao e chute do 1o
tempo nao eram gravados, entao todo mercado de 1o tempo saia do pool por
decisao ("o dado nao existe") -- e, pior, o que chegasse a ser liquidado era
comparado contra o JOGO INTEIRO: `_stat_family` so' separava o 1o tempo de gol.

A API devolve a folha por tempo (`statistics_1h`) na mesma requisicao quando se
pede `half=true`. Estes testes travam as tres pontas que dependem disso.
"""
from decimal import Decimal

import pytest

from collectors.match_statistics_sync_service import (
    COLUNAS_1T, MatchStatisticsSyncService, ler_primeiro_tempo,
)
from services.ai_result_checker_service import AIResultCheckerService
from services.pick_engine import orchestrator, ranking, stats_model
from services.pick_engine.stats_model import classify_market


# ---------------------------------------------------------------------------
# Classificacao
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome, esperado", [
    ("Goals Over/Under First Half",       ("goals_1h", "total")),
    ("Home Team Total Goals(1st Half)",   ("goals_1h", "home")),
    ("Away Team Total Goals(1st Half)",   ("goals_1h", "away")),
    ("Goal Line (1st Half)",              ("goals_1h", "total")),
    ("Total Corners (1st Half)",          ("corners_1h", "total")),
    ("Home Total Corners (1st Half)",     ("corners_1h", "home")),
    ("Away Total Corners (1st Half)",     ("corners_1h", "away")),
    ("Yellow Over/Under (1st Half)",      ("cards_1h", "total")),
    ("Both Teams Score - First Half",     ("btts_1h", "total")),
])
def test_mercado_de_1o_tempo_tem_familia_propria(nome, esperado):
    assert classify_market(nome) == esperado


@pytest.mark.parametrize("nome", [
    "Goals Over/Under - Second Half",
    "Total Corners (2nd Half)",
    "Asian Handicap First Half",
    "Corners Asian Handicap (1st Half)",
    "Correct Score - First Half",
    "Exact Goals Number - First Half",
    "Double Chance - First Half",
    "First Half Winner",
    "Odd/Even - First Half",
    "Corners 1x2 (1st Half)",
    "Highest Scoring Half",
])
def test_fora_do_escopo_continua_fora(nome):
    assert classify_market(nome) is None


def test_jogo_inteiro_nao_mudou():
    assert classify_market("Goals Over/Under") == ("goals", "total")
    assert classify_market("Corners Over Under") == ("corners", "total")
    assert classify_market("Both Teams Score") == ("btts", "total")


# ---------------------------------------------------------------------------
# Pool do motor
# ---------------------------------------------------------------------------
CASA, FORA = 10, 20


def jogo(ht_casa=0, ht_fora=0, esc_casa=None, esc_fora=None, status="FT"):
    return {
        "match_date": "2026-09-01", "status": status,
        "home_team_id": CASA, "away_team_id": 99,
        "home_goals": 3, "away_goals": 2,
        "home_goals_ht": ht_casa, "away_goals_ht": ht_fora,
        "home_corners": 9, "away_corners": 7, "total_corners": 16,
        "home_corners_1h": esc_casa, "away_corners_1h": esc_fora,
    }


def test_jogo_sem_folha_do_1o_tempo_nao_vira_zero_escanteio():
    """O caso normal do historico: partida gravada antes de 27/09 nao tem a
    folha por tempo. Se passasse, `_extract_stat` leria `None or 0` e cada uma
    viraria um Under 4.5 ganho."""
    com_folha = [jogo(esc_casa=4, esc_fora=3) for _ in range(3)]      # 7 > 4.5
    sem_folha = [jogo() for _ in range(20)]
    taxa = stats_model.market_taxa(
        "corners_1h", "total", "Under", "4.5", com_folha + sem_folha, [],
        home_team_id=CASA)
    assert taxa["amostra"] == 3
    assert taxa["taxa_bruta"] == 0.0


def test_escanteio_do_1o_tempo_le_a_coluna_do_1o_tempo():
    pool = [jogo(esc_casa=1, esc_fora=1) for _ in range(4)]           # 2 no 1T, 16 no jogo
    taxa = stats_model.market_taxa(
        "corners_1h", "total", "Under", "4.5", pool, [], home_team_id=CASA)
    assert taxa["taxa_bruta"] == 1.0


def test_gol_do_1o_tempo_le_o_placar_do_intervalo_e_mantem_a_prorrogacao():
    """Placar final 3x2 em todos; no intervalo 0x0. E o AET fica: o 1o tempo
    e' tempo regulamentar em qualquer jogo."""
    pool = [jogo(0, 0), jogo(0, 0, status="AET")]
    taxa = stats_model.market_taxa(
        "goals_1h", "total", "Under", "0.5", pool, [], home_team_id=CASA)
    assert taxa["amostra"] == 2
    assert taxa["taxa_bruta"] == 1.0


def test_ambas_marcam_no_1o_tempo():
    pool = [jogo(1, 1), jogo(1, 0), jogo(0, 0), jogo(2, 1)]
    taxa = stats_model.market_taxa(
        "btts_1h", "total", "Yes", "", pool, [], home_team_id=CASA)
    assert taxa["taxa_bruta"] == 0.5


def test_1o_tempo_disputa_o_mesmo_grupo_do_jogo_inteiro():
    assert ranking.correlation_group("goals_1h") == "goals"
    assert ranking.correlation_group("btts_1h") == "goals"
    assert ranking.correlation_group("corners_1h") == "corners"


def test_cartao_do_1o_tempo_e_eliminado_com_motivo():
    """Sem contagem validada por tempo o pick nunca liquidaria."""
    rastro = []
    odds = [{"market_name": "Yellow Over/Under (1st Half)", "value": "Under",
             "line": "2.5", "best_odd": 1.8, "bookmakers_count": 3,
             "market_id": 1}]
    orchestrator.analyze_fixture_markets(
        odds, [], [], calibration_data={}, rastro=rastro)
    assert any(r.get("market_type") == "cards_1h" and r.get("status") == "eliminada"
               for r in rastro)


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def test_leitura_do_1o_tempo_nao_fabrica_zero():
    """A folha do 1o tempo nao traz "Fouls" (medido): a regra da folha robusta,
    aplicada aqui, transformaria qualquer tipo omitido em zero."""
    folha = [
        {"type": "Corner Kicks", "value": 2},
        {"type": "Yellow Cards", "value": 1},
        {"type": "Red Cards", "value": None},
        {"type": "Total Shots", "value": 4},
        {"type": "Ball Possession", "value": "52%"},
        {"type": "Total passes", "value": 273},
    ]
    lida = ler_primeiro_tempo(folha)
    assert lida["corners_1h"] == 2
    assert lida["red_cards_1h"] == 0          # null no vermelho e' zero (regra da API)
    assert lida["shots_on_1h"] is None        # tipo ausente continua ausente


def test_folha_vazia_do_1o_tempo_e_tudo_none():
    assert all(v is None for v in ler_primeiro_tempo([]).values())


class _Cursor:
    def __init__(self):
        self.execucoes = []

    def execute(self, sql, params=None):
        self.execucoes.append((sql, params))


def _servico():
    s = MatchStatisticsSyncService()
    s.cur = _Cursor()
    return s


def test_resposta_sem_a_chave_1h_nao_marca_a_partida():
    """Sem `statistics_1h` na resposta a partida continua na fila do backfill."""
    s = _servico()
    s._gravar_primeiro_tempo(123, None, None)
    assert s.cur.execucoes == []


def test_api_sem_1o_tempo_marca_e_grava_null():
    s = _servico()
    s._gravar_primeiro_tempo(123, [], [])
    sql, params = s.cur.execucoes[0]
    assert "stats_1h_checked_at = NOW()" in sql
    assert params[:-1] == (None,) * len(COLUNAS_1T)
    assert params[-1] == 123


def test_lados_do_1o_tempo_saem_pelo_team_id():
    stats = [
        {"team": {"id": FORA}, "statistics": ["f"], "statistics_1h": ["f1"]},
        {"team": {"id": CASA}, "statistics": ["c"], "statistics_1h": ["c1"]},
    ]
    assert MatchStatisticsSyncService._separar_lados(stats, CASA) == (["c"], ["f"], ["c1"], ["f1"])


# ---------------------------------------------------------------------------
# Liquidacao
# ---------------------------------------------------------------------------
@pytest.fixture
def checker():
    return AIResultCheckerService()


def folha(**extra):
    base = {
        "home_goals": 3, "away_goals": 2, "total_goals": 5,
        "home_goals_ht": 0, "away_goals_ht": 1, "total_goals_ht": 1,
        "home_corners": 6, "away_corners": 4, "total_corners": 10,
        "home_corners_ht": 2, "away_corners_ht": 1, "total_corners_ht": 3,
        "home_cards": 2, "away_cards": 1, "total_cards": 3,
        "status": "FT",
    }
    base.update(extra)
    return base


def test_escanteio_do_1o_tempo_liquida_pelo_1o_tempo(checker):
    """3 no intervalo, 10 no jogo. Pelo jogo inteiro isto era RED."""
    res, _ = checker.evaluate_pick("Total de Escanteios (1º Tempo)", "Under 4.5", 1.8, folha())
    assert res == "GREEN"


def test_market_type_do_motor_basta_pra_saber_o_periodo(checker):
    res, _ = checker.evaluate_pick("Escanteios Mais/Menos", "Under 4.5", 1.8, folha(),
                                   market_type="corners_1h")
    assert res == "GREEN"


def test_sem_folha_do_1o_tempo_fica_pendente_e_nao_cai_no_jogo_inteiro(checker):
    res, fator = checker.evaluate_pick(
        "Total de Escanteios (1º Tempo)", "Over 4.5", 1.8,
        folha(home_corners_ht=None, away_corners_ht=None, total_corners_ht=None))
    assert res is None and fator == Decimal("0")


def test_cartao_do_1o_tempo_nunca_usa_o_jogo_inteiro(checker):
    res, _ = checker.evaluate_pick("Cartões 1º Tempo Mais/Menos", "Over 2.5", 1.8, folha())
    assert res is None


def test_gol_e_ambas_marcam_do_1o_tempo_usam_o_intervalo(checker):
    assert checker.evaluate_pick("Gols Mais/Menos - 1º Tempo", "Over 1.5", 1.8, folha())[0] == "RED"
    assert checker.evaluate_pick("Ambas Marcam - 1º Tempo", "Sim", 1.8, folha())[0] == "RED"


def test_gol_do_2o_tempo_e_o_placar_dos_90_menos_o_intervalo(checker):
    """3x2 no fim, 0x1 no intervalo: 4 gols no 2o tempo."""
    f = folha(home_goals_2t=3, away_goals_2t=1, total_goals_2t=4)
    assert checker.evaluate_pick("Gols Mais/Menos - 2º Tempo", "Over 3.5", 1.8, f)[0] == "GREEN"


def test_escanteio_do_2o_tempo_fica_pendente(checker):
    assert checker.evaluate_pick("Total de Escanteios (2º Tempo)", "Over 4.5", 1.8, folha())[0] is None
