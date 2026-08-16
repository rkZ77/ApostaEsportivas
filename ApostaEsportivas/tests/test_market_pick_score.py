"""Score de selecao de faltas e goleiros (services/pick_engine/market_pick_score).

O que estes testes travam e' o DESENHO da formula, nao os numeros exatos: que a
probabilidade pesa mais que o edge, que dentro da faixa a odd mais barata pontua
mais, e que edge grande nao escala pra sempre. Se os pesos mudarem por medicao,
estes testes devem continuar passando -- se algum quebrar, a mudanca inverteu o
criterio, que e' exatamente o que se quer perceber.
"""
from services.pick_engine.market_pick_score import (
    EDGE_TETO, amostra_bonus, faixa_config, pick_score,
)

CONFIG = faixa_config(1.10, 2.00)


def _score(prob, odd, amostra=10, edge=None):
    """Candidato com edge coerente com a odd, que e' como o pipeline monta."""
    if edge is None:
        edge = prob - 1 / odd
    return pick_score(probability=prob, odd=odd, edge=edge,
                      amostra=amostra, amostra_saturacao=10, config=CONFIG)


def test_mesma_probabilidade_prefere_a_odd_mais_barata():
    """O pedido do usuario de 2026-08-14 virado em teste: quando da' pra descer
    um degrau e ficar mais seguro sem sair da faixa, desce.

    Com a MESMA probabilidade, a odd mais alta tem edge maior por construcao --
    era assim que o criterio antigo (maior edge) subia a linha sozinho."""
    barato = _score(prob=0.85, odd=1.30)
    caro = _score(prob=0.85, odd=1.90)

    assert barato > caro


def test_probabilidade_vence_edge():
    """Candidato estatisticamente melhor ganha de candidato com margem melhor.
    E' a razao de o modulo existir: edge de 10-20% acertou 57,1% em producao e
    edge abaixo de 10% acertou 71,4%."""
    forte_e_barato = _score(prob=0.80, odd=1.40)
    fraco_e_generoso = _score(prob=0.62, odd=1.90)

    assert forte_e_barato > fraco_e_generoso
    # E o de margem maior e' mesmo o segundo, senao o teste passaria por acaso.
    assert (0.62 - 1 / 1.90) > (0.80 - 1 / 1.40)


def test_amostra_maior_pontua_mais():
    """Tudo igual, mais evidencia sustentando o numero vale mais."""
    assert _score(prob=0.80, odd=1.50, amostra=10) > _score(prob=0.80, odd=1.50, amostra=5)


def test_edge_absurdo_nao_escala_pra_sempre():
    """Edge gigante quase sempre significa probabilidade otimista, nao casa
    errada. Sem teto, o outlier voltaria a vencer pela porta dos fundos."""
    no_teto = _score(prob=0.80, odd=1.50, edge=EDGE_TETO)
    muito_acima = _score(prob=0.80, odd=1.50, edge=EDGE_TETO * 20)

    assert no_teto == muito_acima


def test_edge_negativo_nao_vira_bonus():
    """Edge negativo e' descartado pelo EDGE_MIN antes de chegar aqui, mas se
    chegasse nao pode somar pontos por ser negativo (nem virar score negativo)."""
    assert _score(prob=0.80, odd=1.50, edge=-0.30) == _score(prob=0.80, odd=1.50, edge=0.0)


def test_amostra_ausente_vale_zero():
    """Ausencia e' informacao aqui, nao neutralidade: os dois modelos ja' exigem
    amostra minima, entao o que chega vazio e' caso de borda."""
    assert amostra_bonus(None, 10) == 0.0
    assert amostra_bonus(0, 10) == 0.0
    assert amostra_bonus(5, 10) == 0.5
    assert amostra_bonus(50, 10) == 1.0  # satura, nao passa de 1


def test_faixa_do_pipeline_e_respeitada():
    """A faixa destes pipelines e' [1.10, 2.00], nao a 1.50-1.90 do VIP. Uma odd
    de 1.20 esta' DENTRO da faixa aqui e tem que pontuar bem no termo de
    seguranca -- com a config do VIP ela cairia na regiao de despenque."""
    dentro = _score(prob=0.90, odd=1.20)
    fora_do_teto = _score(prob=0.90, odd=2.60)

    assert dentro > fora_do_teto
