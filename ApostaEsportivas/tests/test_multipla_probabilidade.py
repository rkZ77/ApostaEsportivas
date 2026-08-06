"""Multipla: a probabilidade do BILHETE e' o produto das pernas.

Ate 2026-08-05 o pipeline usava `score_combo` (a MEDIA dos final_score das
pernas) como se fosse a probabilidade do bilhete: alimentava o Kelly em
staking.calculate_stake e era exposta ao usuario como "confidence" em 5 rotas
do backend. Tres pernas de 72/70/68% davam 34,3% de chance real e apareciam
como 86,0%.

alavancagem_pipeline.py ja' tinha encontrado e corrigido exatamente esse erro
(ver o comentario longo em _save_pick la'); a correcao nunca tinha sido
propagada pra multipla.
"""
import pytest

from services.pick_engine.staking import calculate_stake


def _bilhete(pernas):
    odd_total = 1.0
    prob = 1.0
    for p in pernas:
        odd_total *= p["odd"]
        prob *= p["taxa_real"]
    return round(odd_total, 4), round(prob, 4)


PERNAS_FORTES = [
    {"taxa_real": 0.72, "odd": 1.55, "final_score": 0.8720},
    {"taxa_real": 0.70, "odd": 1.62, "final_score": 0.8610},
    {"taxa_real": 0.68, "odd": 1.70, "final_score": 0.8455},
]


def test_probabilidade_do_bilhete_e_o_produto_nao_a_media():
    _, prob = _bilhete(PERNAS_FORTES)
    media_final_score = sum(p["final_score"] for p in PERNAS_FORTES) / len(PERNAS_FORTES)

    assert prob == pytest.approx(0.3427, abs=1e-3)
    # A media que era usada antes fica ~52 pontos percentuais acima da verdade.
    assert media_final_score - prob > 0.50


def test_ev_do_bilhete_sai_do_produto():
    odd_total, prob = _bilhete(PERNAS_FORTES)
    ev = round(prob * odd_total - 1.0, 4)
    assert ev == pytest.approx(0.4632, abs=1e-3)


def test_pernas_com_ev_positivo_garantem_bilhete_com_ev_positivo():
    """Propriedade que o gate de perna ja' garante: EV do bilhete =
    produto de (taxa x odd) menos 1. Se cada fator e' > 1, o produto tambem e'.
    Por isso NAO faz falta um gate de EV separado na multipla -- o que faltava
    era a probabilidade certa, nao o gate."""
    odd_total, prob = _bilhete(PERNAS_FORTES)
    for p in PERNAS_FORTES:
        assert p["taxa_real"] * p["odd"] > 1.0
    assert prob * odd_total > 1.0


def test_kelly_deixa_de_saturar_o_teto_em_bilhete_fraco():
    """Com score_combo o Kelly dava o teto (2,5%) pra qualquer bilhete,
    inclusive um de EV negativo -- dimensionamento constante, Kelly
    decorativo. Com a probabilidade real ele volta a discriminar."""
    fracas = [
        {"taxa_real": 0.66, "odd": 1.50, "final_score": 0.8700},
        {"taxa_real": 0.66, "odd": 1.50, "final_score": 0.8650},
        {"taxa_real": 0.66, "odd": 1.50, "final_score": 0.8600},
    ]
    odd_total, prob = _bilhete(fracas)
    ev = prob * odd_total - 1.0
    assert ev < 0  # bilhete ruim

    score_combo = sum(p["final_score"] for p in fracas) / len(fracas)
    stake_antigo, _ = calculate_stake(confidence=score_combo, odd=odd_total, pick_type="multipla")
    stake_novo, _ = calculate_stake(confidence=prob, odd=odd_total, ev=ev, pick_type="multipla")

    assert stake_antigo == pytest.approx(0.025)   # teto
    assert stake_novo < stake_antigo              # piso


def test_bilhete_forte_continua_recebendo_stake_cheia():
    odd_total, prob = _bilhete(PERNAS_FORTES)
    ev = prob * odd_total - 1.0
    stake, unidades = calculate_stake(
        confidence=prob, odd=odd_total, ev=ev, pick_type="multipla")
    assert stake == pytest.approx(0.025)
    assert unidades >= 2
