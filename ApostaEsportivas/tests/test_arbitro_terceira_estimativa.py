"""O arbitro decide parte do cartao, entao ele decide parte da probabilidade.

Ate' 2026-08-10 o arbitro so' existia como porteira (cards_market_eligible) e
como -0.15..+0.15 num score de intensidade que nao chegava na conta. O caso que
mostrou o custo: pick VIP #1579 (RB Bragantino x Corinthians, "Cartoes Over 4.5"
a 71.8%, RED com 4 cartoes). Raphael Claus estava em 3.60 pontos de cartao por
jogo, ABAIXO da linha, e esse numero movia o pick em -0.025 de intensidade.

Medido nos 31 picks de cartao resolvidos com media de arbitro (2026-08-10):
quando a media dele CONTRADIZ a linha, 54.5% de acerto (n=11, -0.64u); quando
concorda, 75.0% (n=20, +5.40u).
"""
import pytest

from services.pick_engine import orchestrator, probability_model, referee_model
from services.pick_engine.config import DEFAULT_CONFIG


def _arbitro(avg_yellow, avg_red=0.0, games=5, fallback=False):
    return {"reliable": True, "games": games, "avg_yellow": avg_yellow,
            "avg_red": avg_red, "avg_fouls": 24.0, "is_league_fallback": fallback}


# ─────────────────────── o lambda do arbitro ───────────────────────


def test_vermelho_pesa_dois_no_lambda():
    """Mesma convencao de _cards_points: amarelo 1, vermelho 2."""
    so_amarelo = referee_model.cards_lambda(_arbitro(4.0, 0.0, games=100))
    com_vermelho = referee_model.cards_lambda(_arbitro(4.0, 0.5, games=100))
    assert com_vermelho == pytest.approx(so_amarelo + 1.0, abs=0.05)


def test_amostra_curta_e_puxada_pro_baseline():
    """3 jogos apitados nao sustentam a media crua, mas tambem nao valem zero."""
    cru = 2.0
    curto = referee_model.cards_lambda(_arbitro(cru, games=3))
    longo = referee_model.cards_lambda(_arbitro(cru, games=100))
    assert cru < curto < referee_model._REFEREE_CARD_POINTS_BASELINE
    assert abs(longo - cru) < abs(curto - cru), "amostra grande encolhe menos"


def test_fallback_de_liga_nao_vira_estimativa_do_arbitro():
    """Ali o numero e' a media da COMPETICAO, que ja esta embutida em todo o
    resto da conta -- usar como terceira leitura seria contar duas vezes."""
    assert referee_model.cards_lambda(_arbitro(5.0, fallback=True)) is None
    assert referee_model.cards_probability(_arbitro(5.0, fallback=True), 4.5, "over") is None


def test_sem_arbitro_confiavel_nao_ha_estimativa():
    assert referee_model.cards_lambda({"reliable": False, "games": 1}) is None


# ─────────────────────── a probabilidade ───────────────────────


def test_o_caso_1579_em_numeros():
    """Claus em 3.60 pontos com 5 jogos, contra Over 4.5."""
    lam = referee_model.cards_lambda(_arbitro(3.60, 0.0, games=5))
    assert lam == pytest.approx(3.82, abs=0.01)
    p = referee_model.cards_probability(_arbitro(3.60, 0.0, games=5), 4.5, "over")
    assert p == pytest.approx(probability_model.poisson_prob_for_line(lam, 4.5, "over"), abs=1e-6)
    assert p < 0.40, "o motor publicou 71.8% neste mercado"


def test_arbitro_rigoroso_sustenta_over():
    """A regra nao e' 'sempre desconfiar': arbitro acima da linha concorda."""
    p = referee_model.cards_probability(_arbitro(6.5, 0.3, games=12), 4.5, "over")
    assert p > 0.70


# ─────────────────── dentro do motor ───────────────────


def _jogo(i, amarelos_casa, amarelos_fora):
    return {
        "match_date": f"2026-07-{i + 1:02d}",
        "home_team_id": 1, "away_team_id": 2,
        "home_yellow_cards": amarelos_casa, "away_yellow_cards": amarelos_fora,
        "home_red_cards": 0, "away_red_cards": 0,
        "opponent_rank": None,
    }


def _odds(linha="4.5"):
    base = {"market_id": 9, "market_name": "Cards Over/Under",
            "line": linha, "bookmakers_count": 3}
    return [{**base, "value": "Over", "best_odd": 2.00},
            {**base, "value": "Under", "best_odd": 2.00}]


def _rodar(referee_stats, linha="4.5"):
    """Times que dao MUITO cartao (7 por jogo) -- a taxa empirica e o Poisson
    dos times concordam em Over 4.5. So' o arbitro discorda."""
    hist = [_jogo(i, 4, 3) for i in range(10)]
    return orchestrator.analyze_fixture_markets(
        _odds(linha), hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
        referee_stats=referee_stats,
        league_stats={"games": 200, "avg_yellow": 4.0, "avg_red": 0.1},
    )


def test_arbitro_muito_permissivo_ja_era_barrado_pela_porteira():
    """Antes da terceira estimativa existir, o unico efeito do arbitro era este:
    media MUITO baixa derruba o score de intensidade abaixo do corte e o mercado
    de cartoes nem e' analisado. Continua valendo -- o que faltava era o meio do
    caminho, o arbitro que passa na porteira e mesmo assim contradiz a linha."""
    assert not [x for x in _rodar({"games": 8, "avg_yellow": 2.0, "avg_red": 0.0})
                if x["market_type"] == "cards"]


def test_arbitro_permissivo_rebaixa_o_over_dos_times():
    """Times de 7 cartoes por jogo (taxa 83%, Poisson 83%) com um arbitro de 3.4
    pontos: as duas leituras dos times concordam entre si e o arbitro discorda
    das duas. E' a forma exata do #1579."""
    permissivo = {"games": 8, "avg_yellow": 3.0, "avg_red": 0.0}
    c = next(x for x in _rodar(permissivo) if x["market_type"] == "cards")
    assert c["value"] == "Over"
    assert c["referee_probability"] is not None
    assert c["referee_fit_diff"] > DEFAULT_CONFIG.model_disagreement_threshold
    # a probabilidade publicada vira a do arbitro, a menor das tres
    assert c["taxa_real"] == c["referee_probability"]
    assert c["taxa_real"] < c["taxa_real_pre_desacordo"]
    # e edge/EV/confidence saem da nova, nunca da anterior
    assert c["ev"] == pytest.approx(c["taxa_real"] * c["odd"] - 1, abs=1e-4)
    assert c["edge"] == pytest.approx(c["taxa_real"] - c["prob_baseline_value"], abs=1e-4)


def test_arbitro_de_acordo_nao_mexe_em_nada():
    """Arbitro rigoroso (8 amarelos, lambda 6.7) num jogo de times rigorosos:
    as tres leituras se sustentam e a probabilidade fica onde estava."""
    rigoroso = {"games": 8, "avg_yellow": 8.0, "avg_red": 0.0}
    c = next(x for x in _rodar(rigoroso) if x["market_type"] == "cards")
    assert c["referee_probability"] is not None
    assert "taxa_real_pre_desacordo" not in c
    assert c["taxa_real"] == pytest.approx(0.8333, abs=1e-3)


def test_o_rastro_guarda_a_leitura_do_arbitro_mesmo_sem_rebaixar():
    """Sem o numero gravado nao da' pra medir depois se o sinal esta ajudando --
    foi essa falta que atrasou a descoberta do #1579."""
    rigoroso = {"games": 8, "avg_yellow": 8.0, "avg_red": 0.0}
    c = next(x for x in _rodar(rigoroso) if x["market_type"] == "cards")
    assert c["referee_lambda"] is not None
    assert c["referee_probability"] is not None


def test_fora_de_cartoes_o_arbitro_nao_entra():
    """Em escanteio ou gol o arbitro nao e' causa; uma terceira estimativa ali
    seria inventar relacao."""
    hist = [{**_jogo(i, 4, 3), "total_corners": 9, "home_corners": 5,
             "away_corners": 4} for i in range(10)]
    odds = [{"market_id": 3, "market_name": "Corners Over/Under", "line": "8.5",
             "bookmakers_count": 3, "value": v, "best_odd": 2.00}
            for v in ("Over", "Under")]
    candidatos = orchestrator.analyze_fixture_markets(
        odds, hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
        referee_stats={"games": 8, "avg_yellow": 2.0, "avg_red": 0.0},
    )
    c = next(x for x in candidatos if x["market_type"] == "corners")
    assert c["referee_probability"] is None
    assert c["referee_lambda"] is None
