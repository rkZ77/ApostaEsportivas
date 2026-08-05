"""Mercados que o motor classifica mas NAO pode transformar em pick.

Handicap (gols/escanteios/cartoes) saiu do pool por decisao de produto
(2026-08-05) -- classify_market() continua reconhecendo o mercado (a
resolucao de picks ja publicados depende disso), entao o unico ponto que
garante que nenhum pipeline gera handicap e' o descarte na entrada do pool
em orchestrator.analyze_fixture_markets. Este teste trava esse ponto.
"""
from datetime import date

from services.pick_engine import analyze_fixture_markets

HOJE = date(2026, 8, 5)
CASA, FORA = 100, 200

CALIBRACAO_VAZIA = {"by_market_league": {}, "by_market": {}}


def _jogo(dia):
    """Jogo com muito gol, muito escanteio e muito cartao -- historico
    generoso de proposito: se o handicap aparecer no resultado, foi o
    filtro que falhou, nao a falta de amostra."""
    return {
        "match_date": date(2026, 7, dia),
        "home_team_id": CASA, "away_team_id": FORA,
        "home_goals": 3, "away_goals": 1, "total_goals": 4,
        "home_corners": 7, "away_corners": 4, "total_corners": 11,
        "home_yellow_cards": 2, "away_yellow_cards": 2, "total_yellow_cards": 4,
        "home_red_cards": 0, "away_red_cards": 0,
    }


HISTORICO = [_jogo(dia) for dia in range(20, 30)]


def _odd(market_name, value, line, market_id):
    return {
        "market_id": market_id, "market_name": market_name,
        "value": value, "line": line,
        "best_odd": 1.80, "bookmakers_count": 6,
    }


ODDS = [
    # Controle: over/under de gols, que DEVE continuar virando candidato.
    _odd("Goals Over/Under", "Over", "2.5", 5),
    _odd("Goals Over/Under", "Under", "2.5", 5),
    # As tres familias de handicap, uma de cada.
    _odd("Asian Handicap", "Home -1", "-1", 4),
    _odd("Corners Asian Handicap", "Home -1", "-1", 55),
    _odd("Cards Asian Handicap", "Away +1.5", "1.5", 80),
]


def _analisa(debug=False):
    return analyze_fixture_markets(
        ODDS, HISTORICO, HISTORICO,
        reference_date=HOJE,
        calibration_data=CALIBRACAO_VAZIA,
        home_team_id=CASA, away_team_id=FORA,
        debug=debug,
    )


def test_nenhum_candidato_de_handicap():
    candidatos = _analisa()

    assert not [c for c in candidatos if str(c["market_type"]).startswith("handicap")]


def test_o_controle_over_under_continua_passando():
    """Garante que o teste acima nao passa por acidente (historico ruim,
    odd invalida) -- com o MESMO cenario, gols vira candidato."""
    candidatos = _analisa()

    assert [c for c in candidatos if c["market_type"] == "goals"]


def test_debug_registra_o_motivo_da_eliminacao():
    saida = _analisa(debug=True)

    eliminados = {
        e["family"]: e["reason"] for e in saida["eliminated_markets"]
    }
    for familia in ("handicap_goals", "handicap_corners", "handicap_cards"):
        assert "decisao de produto" in eliminados[familia]
