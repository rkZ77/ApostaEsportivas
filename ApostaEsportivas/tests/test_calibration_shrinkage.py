"""Calibracao por mercado: a correcao de confidence tem que ser proporcional
a evidencia, nao tudo-ou-nada.

Antes o corte era seco em n>=10: n=9 nao recebia correcao nenhuma e n=10
recebia a correcao inteira. Medido em prod em 2026-08-03, isso deixava 5 dos 6
market_types sem correcao -- inclusive `cards`, o pior calibrado de todos
(declarava 82% de confidence e acertava 50%), impune por ter so' n=2.
"""
import pytest

from services.pick_engine import calibration
from services.pick_engine.calibration import (
    _CONSERVATIVE_BONUS,
    _EVIDENCE_STRENGTH,
    _HIT_FLOOR_PENALTY,
    _evidence_weight,
)


def _cal(market_type, n, hit, conf, league_id=None):
    stats = {"n": n, "hit": hit, "conf": conf, "gap": round(conf - hit, 3)}
    dados = {"by_market": {market_type: stats}, "by_market_league": {}}
    if league_id is not None:
        dados["by_market_league"][(market_type, league_id)] = stats
    return dados


def test_peso_cresce_com_a_amostra():
    assert _evidence_weight(0) == 0.0
    assert _evidence_weight(2) == pytest.approx(2 / 12, abs=1e-4)
    assert _evidence_weight(_EVIDENCE_STRENGTH) == pytest.approx(0.5, abs=1e-4)
    assert _evidence_weight(90) == pytest.approx(0.9, abs=1e-4)
    # nunca chega a 1.0, mas converge
    assert _evidence_weight(10_000) > 0.99


def test_mercado_superconfiante_com_amostra_curta_agora_e_corrigido():
    """Caso real de `cards` em 2026-08-03: n=2, conf 0.823, hit 0.500.
    Antes recebia 0.0. Agora recebe uma fracao do gap."""
    dados = _cal("cards", n=2, hit=0.500, conf=0.823)

    ajuste = calibration.calibration_adjustment("cards", dados)

    assert ajuste < 0, "mercado que declara 82% e acerta 50% tem que perder confidence"
    assert ajuste == pytest.approx(-0.323 * (2 / 12), abs=1e-3)


def test_correcao_cresce_conforme_o_historico_acumula():
    """Mesmo gap, amostras diferentes: quanto mais evidencia, mais correcao."""
    ajustes = [
        calibration.calibration_adjustment("cards", _cal("cards", n=n, hit=0.50, conf=0.82))
        for n in (2, 10, 30, 90)
    ]

    assert ajustes == sorted(ajustes, reverse=True), "correcao tem que ficar mais negativa com mais n"
    assert all(a < 0 for a in ajustes)
    # e nunca ultrapassa o gap medido
    assert min(ajustes) > -0.32


def test_sem_historico_nenhum_nao_corrige():
    """Sem dado nao se inventa correcao -- isso nao mudou."""
    assert calibration.calibration_adjustment("corners", {"by_market": {}, "by_market_league": {}}) == 0.0


def test_gap_dentro_da_faixa_neutra_continua_zero():
    """Caso real de `goals`: gap +0.008, dentro da tolerancia. Nao e' pra
    corrigir mercado que ja' esta calibrado."""
    dados = _cal("goals", n=5, hit=0.800, conf=0.808)

    assert calibration.calibration_adjustment("goals", dados) == 0.0


def test_mercado_conservador_ganha_bonus_encolhido():
    """Caso real de `handicap_cards`: gap -0.164 (declara menos do que acerta)."""
    dados = _cal("handicap_cards", n=4, hit=1.000, conf=0.836)

    ajuste = calibration.calibration_adjustment("handicap_cards", dados)

    assert ajuste > 0
    assert ajuste == pytest.approx(_CONSERVATIVE_BONUS * (4 / 14), abs=1e-4)


def test_piso_de_hit_rate_ainda_exige_amostra_robusta():
    """A penalidade mais dura do modulo nao pode disparar por 2 REDs seguidos:
    continua exigindo n>=15 pra ser acionada."""
    curto = _cal("corners", n=10, hit=0.30, conf=0.80)
    longo = _cal("corners", n=20, hit=0.30, conf=0.80)

    ajuste_curto = calibration.calibration_adjustment("corners", curto)
    ajuste_longo = calibration.calibration_adjustment("corners", longo)

    # n=10: nao atinge o piso, cai na regra de gap (gap = +0.50)
    assert ajuste_curto == pytest.approx(-0.50 * (10 / 20), abs=1e-3)
    # n=20: atinge o piso, e o piso tambem entra encolhido
    assert ajuste_longo == pytest.approx(_HIT_FLOOR_PENALTY * (20 / 30), abs=1e-3)


def test_prior_bayesiano_mantem_piso_duro_de_amostra():
    """get_prior() SUBSTITUI a taxa empirica em bayesian_model.shrink_taxa --
    ali amostra curta nao pode virar prior, e isso continua valendo."""
    assert calibration.get_prior("cards", _cal("cards", n=2, hit=0.5, conf=0.82)) is None
    assert calibration.get_prior("cards", _cal("cards", n=10, hit=0.5, conf=0.82)) == 0.5


def test_granularidade_fina_por_liga_continua_preferida():
    """Liga com amostra propria suficiente ganha da agregada."""
    dados = {
        "by_market": {"corners": {"n": 50, "hit": 0.80, "conf": 0.82, "gap": 0.02}},
        "by_market_league": {("corners", 71): {"n": 20, "hit": 0.50, "conf": 0.82, "gap": 0.32}},
    }

    agregado = calibration.calibration_adjustment("corners", dados)
    por_liga = calibration.calibration_adjustment("corners", dados, league_id=71)

    assert agregado == 0.0, "gap +0.02 esta dentro da faixa neutra"
    assert por_liga < 0, "a liga 71 esta mal calibrada e tem amostra pra provar"
