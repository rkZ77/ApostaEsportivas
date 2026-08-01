"""Testes do modelo de defesas de goleiro.

Varios testes aqui travam NUMEROS MEDIDOS contra a base real (946 jogos,
1892 atuacoes, 2026-08-01), nao valores arbitrarios. Se um deles quebrar,
a pergunta certa e' "o modelo mudou de proposito?" -- nao "qual constante
eu ajusto pra passar?".
"""
import math

import pytest

from services.pick_engine.goalkeeper_model import (
    BASE_RATE_OVER_15,
    DISPERSION_R,
    LEAGUE_MEAN_SAVES,
    MIN_OPPONENT_SAMPLE,
    SAVE_RATE_PER_SHOT_ON,
    _nb_pmf,
    analyze_saves_market,
    expected_saves,
    prob_over,
)


def test_pmf_e_uma_distribuicao_de_probabilidade():
    total = sum(_nb_pmf(k, LEAGUE_MEAN_SAVES, DISPERSION_R) for k in range(60))
    assert total == pytest.approx(1.0, abs=1e-6)


def test_pmf_nunca_negativo():
    assert all(_nb_pmf(k, 2.5, DISPERSION_R) >= 0 for k in range(30))


def test_reproduz_a_taxa_base_medida_na_producao():
    """Na media da liga, Over 1.5 tem que bater os 63.4% reais.

    Este e' o teste central do modelo: e' o que justifica ter trocado
    Poisson por Binomial Negativa.
    """
    p = prob_over(1.5, LEAGUE_MEAN_SAVES)
    assert p == pytest.approx(BASE_RATE_OVER_15, abs=0.02)


def test_erra_para_baixo_e_nao_para_cima():
    """Subestimar nunca cria edge falso; superestimar sim.

    O modelo tem que ficar do lado conservador da taxa real.
    """
    assert prob_over(1.5, LEAGUE_MEAN_SAVES) <= BASE_RATE_OVER_15


def test_poisson_seria_otimista_demais():
    """Guarda de regressao: impede alguem 'simplificar' pra Poisson.

    Poisson diz 72% onde o real e' 63.4% -- odd justa 1.39 em vez de 1.58,
    o que faria o motor comprar odd 1.45 achando que e' valor.
    """
    mu = LEAGUE_MEAN_SAVES
    poisson_over_15 = 1 - math.exp(-mu) * (1 + mu)
    assert poisson_over_15 - BASE_RATE_OVER_15 > 0.05
    assert abs(prob_over(1.5, mu) - BASE_RATE_OVER_15) < abs(poisson_over_15 - BASE_RATE_OVER_15)


def test_probabilidade_cresce_com_defesas_esperadas():
    anterior = 0.0
    for mu in (1.0, 2.0, 3.0, 4.0, 5.0):
        atual = prob_over(1.5, mu)
        assert atual > anterior
        anterior = atual


def test_linha_mais_alta_e_menos_provavel():
    mu = 3.0
    assert prob_over(0.5, mu) > prob_over(1.5, mu) > prob_over(2.5, mu)


def test_sem_sinal_nenhum_nao_inventa_numero():
    assert expected_saves(None, None) is None
    assert expected_saves(0, 0) is None


def test_usa_chutes_no_alvo_do_adversario_quando_e_o_unico_sinal():
    # Sem amostra, shrink_taxa devolve None e cai no mu bruto.
    esperado = 6.0 * SAVE_RATE_PER_SHOT_ON
    assert expected_saves(6.0, None, None) == pytest.approx(esperado, abs=0.01)


def test_amostra_pequena_encolhe_para_a_media_da_liga():
    """Amostra de 1 jogo nao pode sustentar estimativa extrema."""
    bruto = 10.0 * SAVE_RATE_PER_SHOT_ON
    encolhido = expected_saves(10.0, None, sample_size=1)
    assert LEAGUE_MEAN_SAVES < encolhido < bruto


def test_encolhimento_diminui_conforme_a_amostra_cresce():
    """Quanto mais jogos, menos o prior manda.

    Com prior_strength=10 (padrao de bayesian_model), n=100 ainda deixa
    ~9% de peso no prior -- encolhimento pequeno, nao nulo. O que o modelo
    garante e' a monotonicidade, nao convergencia exata pro bruto.
    """
    bruto = 10.0 * SAVE_RATE_PER_SHOT_ON
    pequena = expected_saves(10.0, None, sample_size=1)
    media = expected_saves(10.0, None, sample_size=10)
    grande = expected_saves(10.0, None, sample_size=100)

    # Todas abaixo do bruto (o prior puxa pra baixo) e cada vez mais perto.
    assert pequena < media < grande < bruto
    assert abs(grande - bruto) < abs(media - bruto) < abs(pequena - bruto)
    assert grande / bruto > 0.90


def test_rejeita_amostra_abaixo_do_minimo():
    assert analyze_saves_market(6.0, 3.0, MIN_OPPONENT_SAMPLE - 1, odd=1.5) is None
    assert analyze_saves_market(6.0, 3.0, MIN_OPPONENT_SAMPLE, odd=1.5) is not None


def test_edge_e_ev_batem_com_a_definicao():
    r = analyze_saves_market(6.0, 3.0, 10, odd=2.0)
    p = r["probability"]
    assert r["edge"] == pytest.approx(p - 0.5, abs=1e-4)
    assert r["ev"] == pytest.approx(p * 1.0 - (1 - p), abs=1e-4)


def test_odd_justa_e_o_inverso_da_probabilidade():
    r = analyze_saves_market(6.0, 3.0, 10, odd=None)
    assert r["fair_odd"] == pytest.approx(1 / r["probability"], abs=0.01)
    assert "edge" not in r and "ev" not in r      # sem odd, nao ha o que comparar


def test_ev_negativo_quando_a_odd_nao_paga_o_risco():
    r = analyze_saves_market(3.0, 2.0, 10, odd=1.05)
    assert r["ev"] < 0
