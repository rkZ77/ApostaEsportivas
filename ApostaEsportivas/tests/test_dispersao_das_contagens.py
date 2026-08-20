# -*- coding: utf-8 -*-
"""Poisson so' vale pra gols. Em todo o resto ele infla a probabilidade.

O DEFEITO
---------
`probability_model` assumia Poisson pra toda contagem. Poisson impoe
variancia = media, e isso e' uma AFIRMACAO sobre o dado -- nunca tinha sido
testada. Medida em 2026-08-20 sobre os ~1.690 jogos FT de PROD, ajustando a
MESMA estrutura que o motor usa (lambda_ij = mu x ataque_i x defesa_j) e
lendo a dispersao de Pearson que sobra:

    gols (mandante/visitante/total)   1.05 / 0.98 / 1.07
    cartoes (mandante)                1.24
    chutes no gol (total)             1.61
    escanteios (mandante/visitante)   1.82 / 1.86
    faltas (mandante)                 2.15
    cartoes (total)                   2.28
    faltas (total)                    3.12
    chutes (total)                    3.20

O phi e' RESIDUAL: a variacao entre times ja' foi removida, entao o que sobra
e' superdispersao que o lambda do motor nao explica.

POR QUE ISSO EXPLICA O DESEMPENHO POR MERCADO
----------------------------------------------
Gols e' a UNICA familia em que a distribuicao assumida estava certa, e e' a
unica em que o motor bate o mercado. Escanteios anunciava 71,9% e realizava
50,0% em agosto de 2026.

Backtest fora da amostra (lambda so' de jogos anteriores), restrito a faixa
em que o motor publica (probabilidade >= 60%):

    familia            Poisson          Binomial Negativa
    gols               +0.6pp erro      -0.0pp erro
    escanteios         +3.6pp           -1.2pp
    cartoes            +4.3pp           -2.4pp
    faltas             +5.6pp           +0.5pp
    chutes no gol      +3.5pp           -0.4pp

Brier melhorou nas CINCO familias, e o lucro por aposta tambem. Volume cai
(faltas perde 41% das previsoes acima de 60%), que e' o resultado certo: eram
previsoes que so' passavam do corte porque a conta exagerava.
"""
import math

import pytest

from services.pick_engine import probability_model as pm


# ─────────────────────── a tabela e' medida, nao escolhida ─────────────────
def test_gols_fica_em_poisson():
    """O controle da medicao. phi ~ 1 quer dizer que o mercado que funciona
    nao pode ser tocado por esta mudanca."""
    for escopo in ("home", "away", "total"):
        assert pm.dispersao("goals", escopo) <= 1.07


def test_familia_sem_medicao_continua_poisson():
    """O default protege quem nao foi medido: sem evidencia, o comportamento
    e' exatamente o de antes de 2026-08-20."""
    assert pm.dispersao("saves", "home") == 1.0
    assert pm.dispersao("btts", "total") == 1.0
    assert pm.dispersao(None, "total") == 1.0
    assert pm.dispersao("familia_que_nao_existe", "home") == 1.0


def test_escopo_desconhecido_cai_no_total():
    """Escopo novo nao pode virar Poisson silenciosamente numa familia que se
    sabe superdispersa -- cai no total, que e' o valor mais conservador."""
    assert pm.dispersao("corners", "escopo_novo") == pm.dispersao("corners", "total")


def test_total_e_mais_disperso_que_o_lado_em_cartoes_faltas_e_chutes():
    """Nao e' erro de digitacao: cartao dos dois times anda junto (jogo pegado
    castiga os dois), e correlacao positiva infla a variancia da soma."""
    for familia in ("cards", "fouls", "shots"):
        assert pm.dispersao(familia, "total") > pm.dispersao(familia, "home")


# ─────────────────────── a matematica ──────────────────────────────────────
def test_nb_com_phi_1_e_poisson():
    """A Binomial Negativa precisa CONTER o Poisson: senao ligar a dispersao
    mudaria gols tambem, e gols e' o mercado que funciona."""
    for k in range(0, 12):
        assert pm.nb_pmf(k, 2.5, 1.0) == pytest.approx(pm.poisson_pmf(k, 2.5), abs=1e-12)


def test_nb_soma_um():
    for phi in (1.0, 1.5, 2.28, 3.2):
        total = sum(pm.nb_pmf(k, 6.0, phi) for k in range(0, 200))
        assert total == pytest.approx(1.0, abs=1e-6)


def test_nb_tem_a_variancia_pedida():
    """A parametrizacao (media, phi) tem que devolver variancia = phi x media,
    senao o numero medido nao chega na conta."""
    mu, phi = 5.0, 1.82
    ks = range(0, 300)
    p = [pm.nb_pmf(k, mu, phi) for k in ks]
    media = sum(k * pk for k, pk in zip(ks, p))
    var = sum((k - media) ** 2 * pk for k, pk in zip(ks, p))
    assert media == pytest.approx(mu, abs=1e-4)
    assert var == pytest.approx(phi * mu, rel=1e-3)


def test_contagem_alta_nao_estoura():
    """Faltas passa de 30 por jogo; a versao ingenua com factorial/gamma
    direto estoura antes disso."""
    assert 0.0 < pm.nb_pmf(45, 23.0, 3.12) < 1.0
    assert not math.isnan(pm.nb_pmf(120, 23.0, 3.12))


# ─────────────────────── o efeito na probabilidade ─────────────────────────
@pytest.mark.parametrize("familia,escopo,lam,linha", [
    ("corners", "home", 5.05, 3.5),
    ("corners", "away", 3.74, 2.5),
    ("corners", "total", 8.79, 7.5),
    ("fouls", "home", 12.25, 9.5),
    ("cards", "total", 4.47, 3.5),
])
def test_superdispersao_derruba_o_over_perto_da_media(familia, escopo, lam, linha):
    """A direcao e' sempre a mesma: massa vai pras caudas, e a linha de aposta
    fica perto da media -- entao o Poisson exagerava."""
    poisson = pm.poisson_prob_for_line(lam, linha, "over")
    negbin = pm.poisson_prob_for_line(lam, linha, "over", familia, escopo)
    assert negbin < poisson


def test_derruba_o_under_tambem_nao_e_so_o_over():
    """Superdispersao nao e' 'o jogo tem menos evento', e' 'o jogo e' menos
    previsivel'. Tratar como vies de direcao levaria a inverter o pick em vez
    de descontar a confianca dele."""
    poisson = pm.poisson_prob_for_line(8.79, 11.5, "under")
    negbin = pm.poisson_prob_for_line(8.79, 11.5, "under", "corners", "total")
    assert negbin < poisson


def test_gols_quase_nao_se_move():
    """O numero que prova que o mercado bom nao foi sacrificado pra corrigir
    os ruins."""
    poisson = pm.poisson_prob_for_line(2.54, 1.5, "over")
    negbin = pm.poisson_prob_for_line(2.54, 1.5, "over", "goals", "total")
    assert abs(negbin - poisson) < 0.015


def test_sem_familia_a_conta_e_identica_a_de_antes():
    """Trava a compatibilidade: todo chamador que ainda nao passa family
    continua vendo Poisson exato, entao a mudanca nunca age onde nao foi
    ligada de proposito (residual_model do motor ao vivo, por exemplo)."""
    for lam, linha, direcao in ((5.05, 4.5, "over"), (8.79, 10, "under"),
                                (2.54, 2.5, "over")):
        com = pm.poisson_prob_for_line(lam, linha, direcao)
        sem = pm.poisson_prob_for_line(lam, linha, direcao, None, None)
        assert com == sem


def test_push_de_linha_redonda_continua_normalizado():
    """Linha redonda devolve stake no empate exato, e a renormalizacao tem que
    usar a MESMA distribuicao -- misturar as duas somaria massa de Poisson
    numa probabilidade de Binomial Negativa."""
    p = pm.poisson_prob_for_line(8.79, 10, "under", "corners", "total")
    phi = pm.dispersao("corners", "total")
    push = pm.nb_pmf(10, 8.79, phi)
    esperado = (pm.nb_cdf(10, 8.79, phi) - push) / (1 - push)
    assert p == pytest.approx(round(esperado, 4), abs=1e-4)


# ─────────────────────── quem consome ──────────────────────────────────────
def test_o_arbitro_usa_a_dispersao_do_total():
    """cards_lambda e' a media do arbitro na PARTIDA INTEIRA. Usar a dispersao
    de um lado so' (1.24 contra 2.28) subestimaria quase pela metade."""
    import inspect
    from services.pick_engine import referee_model
    fonte = inspect.getsource(referee_model.cards_probability)
    assert 'family="cards"' in fonte and 'scope="total"' in fonte


def test_o_orquestrador_passa_familia_e_escopo():
    """Sem isso a tabela existe e nao e' consultada -- o defeito silencioso
    mais provavel desta mudanca."""
    import inspect
    from services.pick_engine import orchestrator
    fonte = inspect.getsource(orchestrator)
    assert "family=family, scope=scope" in fonte


def test_o_efeito_de_mata_mata_usa_a_mesma_distribuicao_dos_dois_lados():
    """tie_effect mede a DIFERENCA entre duas probabilidades. Distribuicoes
    diferentes nas duas pontas mediriam a troca de modelo, nao o agregado."""
    import inspect
    from services.pick_engine import tie_effect
    fonte = inspect.getsource(tie_effect)
    assert fonte.count("family=familia, scope=escopo") >= 2
