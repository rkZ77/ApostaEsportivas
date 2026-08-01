"""Testes do modelo de faltas.

Como o de defesas, trava numeros MEDIDOS contra a base real (946 jogos,
2026-08-01). Quebrou? Perguntar se o modelo mudou de proposito, nao ajustar
a constante ate passar.
"""
import math

import pytest

from services.pick_engine.fouls_model import (
    MEDIA_FALTAS_JOGO,
    MIN_JOGOS_ARBITRO,
    MIN_JOGOS_TIME,
    PESO_ARBITRO,
    PESO_TIMES,
    analyze_fouls_market,
    expected_fouls,
    prob_over_225,
)


def test_pesos_somam_um():
    assert PESO_TIMES + PESO_ARBITRO == pytest.approx(1.0)


def test_sem_amostra_nenhuma_nao_inventa_previsao():
    assert expected_fouls(None, None, None) is None


def test_amostra_insuficiente_dos_dois_lados_nao_preve():
    assert expected_fouls(12.0, 11.0, None,
                          n_casa=MIN_JOGOS_TIME - 1, n_fora=MIN_JOGOS_TIME - 1) is None


def test_so_times_soma_as_duas_medias():
    assert expected_fouls(13.5, 13.0, None, 8, 8, 0) == pytest.approx(26.5)


def test_so_arbitro_usa_a_media_dele():
    """Arbitro sozinho ja e' previsao valida: a amplitude medida entre
    arbitros vai de 21.1 a 32.5 faltas/jogo, quase metade da media."""
    assert expected_fouls(None, None, 29.0, 0, 0, 6) == pytest.approx(29.0)


def test_combinado_fica_entre_os_dois_sinais():
    times, arbitro = 26.5, 29.0
    combinado = expected_fouls(13.5, 13.0, arbitro, 8, 8, 6)
    assert times < combinado < arbitro
    assert combinado == pytest.approx(times * PESO_TIMES + arbitro * PESO_ARBITRO, abs=0.01)


def test_arbitro_sem_amostra_suficiente_e_ignorado():
    com = expected_fouls(13.5, 13.0, 29.0, 8, 8, MIN_JOGOS_ARBITRO - 1)
    sem = expected_fouls(13.5, 13.0, None, 8, 8, 0)
    assert com == sem


def test_faixas_reproduzem_o_backtest():
    """Taxas medidas por faixa de previsao, sem lookahead."""
    assert prob_over_225(19.0)[0] == pytest.approx(0.434)
    assert prob_over_225(21.0)[0] == pytest.approx(0.353)
    assert prob_over_225(23.0)[0] == pytest.approx(0.567)
    assert prob_over_225(27.0)[0] == pytest.approx(0.734)


def test_faixa_devolve_o_tamanho_da_amostra():
    """Faixa de 51 jogos nao merece a mesma confianca que uma de 301."""
    assert prob_over_225(21.0)[1] == 51
    assert prob_over_225(27.0)[1] == 301


def test_previsao_ausente_nao_vira_probabilidade():
    assert prob_over_225(None) is None


def test_faixa_alta_e_a_unica_com_odd_justa_dentro_da_faixa_do_produto():
    """Regra do usuario: odd entre 1.35 e 2.00.

    So' a faixa de previsao 24+ produz odd justa dentro dela -- e' o unico
    recorte onde o mercado pode pagar acima do justo sem ser aposta ruim.
    """
    justas = {faixa: 1 / prob_over_225(p)[0] for faixa, p in
              (("<20", 19.0), ("20-22", 21.0), ("22-24", 23.0), ("24+", 27.0))}
    assert 1.35 <= justas["24+"] <= 2.00
    assert justas["<20"] > 2.00 and justas["20-22"] > 2.00


def test_edge_e_ev_batem_com_a_definicao():
    r = analyze_fouls_market(13.5, 13.0, 29.0, 8, 8, 6, odd=1.55)
    p = r["probability"]
    assert r["edge"] == pytest.approx(p - 1 / 1.55, abs=1e-4)
    assert r["ev"] == pytest.approx(p * 0.55 - (1 - p), abs=1e-4)


def test_jogo_de_times_pouco_faltosos_da_ev_negativo():
    """O motor tem que recusar: previsao baixa, odd de mercado normal."""
    r = analyze_fouls_market(9.0, 9.5, None, 8, 8, 0, odd=1.60)
    assert r["ev"] < 0


def test_sinaliza_se_usou_arbitro():
    com = analyze_fouls_market(13.5, 13.0, 29.0, 8, 8, 6, odd=1.5)
    sem = analyze_fouls_market(13.5, 13.0, None, 8, 8, 0, odd=1.5)
    assert com["usou_arbitro"] is True
    assert sem["usou_arbitro"] is False


def test_sem_dado_devolve_none_em_vez_de_candidato_vazio():
    assert analyze_fouls_market(None, None, None, odd=1.5) is None


def test_binomial_negativa_seria_pior_que_poisson_aqui():
    """Guarda de regressao contra copiar o modelo de defesas pra ca.

    Medido: real 57.9%, Poisson 51.0%, BinNegativa 45.6% na Over 22.5.
    """
    mu, var = MEDIA_FALTAS_JOGO, 109.78
    real = 0.579
    poisson = 1 - sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(23))
    r = mu * mu / (var - mu)
    negbin = 1 - sum(
        math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                 + r * math.log(r / (r + mu)) + k * math.log(mu / (r + mu)))
        for k in range(23)
    )
    assert abs(negbin - real) > abs(poisson - real)
