"""O motor ao vivo jogava fora quase metade do historico, e sempre a mesma metade.

O CASO QUE ABRIU (Vila Nova x Goias, 10/09/2026)
-----------------------------------------------
Pick publicado: Gols Under 1.5 aos 36', com o jogo em 0x0, odd 1.57,
probabilidade anunciada de 71% contra 60% do mercado. O painel "Como esse
mercado vem se comportando" mostrava, na MESMA tela, Vila Nova com 2 GREEN em
10 (media 3.0 gols em casa) e Goias com 3 GREEN em 10 (media 2.3 fora).

A conta que produzia os 71%:

    baseline do confronto   (3.0 + 2.3) / 2 = 2.65 gols por 90
    taxa observada          0 / 36 = 0.000 por minuto
    peso do observado       36 / (36 + 45) = 0.444
    taxa estimada           0.0164 por minuto  ->  1.47 gols por 90
    lambda residual         0.88  (0.7 com o fator de ritmo baixo)
    prob do modelo          84%
    encolhida contra o mercado (60%)  ->  71%

Ou seja: 36 minutos sem gol derrubavam o baseline em 44%, e o motor passava a
tratar um confronto de 2.65 gols como um confronto de 1.47. O condicional
honesto, com o baseline de pe', e' 53%.

A CAUSA
-------
`peso = minuto / (minuto + 45)` e' `f / (f + 0.5)`: o historico dos dois times
entrava valendo MEIO JOGO, pra toda familia igual. Gol e' quase Poisson
(phi 1.07), o que quer dizer que a variacao de gols entre partidas e' quase
toda sorte -- 36 minutos sem gol e' o estado mais comum do futebol, nao a
descricao de um jogo truncado. Falta e' superdispersa (phi 3.12) e ali os 45
minutos estavam certos por acidente.

Estes testes prendem o peso na dispersao medida, que e' de onde ele sai na
Gama-Poisson (beta = 1/(phi-1) jogos de prior), e prendem o caso da tela.
"""
import pytest

from services.pick_engine import probability_model as pm
from services.pick_engine_live import residual_model as rm


# ── a forca do prior sai da dispersao, nao do relogio ────────────────────

def test_forca_do_prior_e_o_inverso_da_dispersao():
    """beta = 1/(phi-1). Nada escolhido a mao."""
    for familia in ("goals", "corners", "cards", "fouls"):
        phi = pm.dispersao(familia, "total")
        esperado = 1.0 / (phi - 1.0)
        assert rm.forca_do_prior(familia) == pytest.approx(esperado, abs=0.01), familia


def test_gol_tem_prior_muito_mais_forte_que_falta():
    """A ordem importa mais que o numero: quanto menos disperso, mais o
    historico manda. Se esta ordem inverter, o modelo virou outra coisa."""
    gols = rm.forca_do_prior("goals")
    escanteios = rm.forca_do_prior("corners")
    faltas = rm.forca_do_prior("fouls")
    assert gols > escanteios > faltas
    assert gols > 10          # gol: o historico vale mais de 10 jogos
    assert faltas < 0.6       # falta: pouco mais de meio jogo


def test_o_peso_e_a_mesma_gama_poisson_que_a_dispersao_residual_ja_usava():
    """`dispersao_residual` descreve a partida com r = lambda/(phi-1), em
    unidade de EVENTO. `forca_do_prior` e' o mesmo numero em unidade de JOGO
    (r = lambda x beta). Antes desta mudanca o modulo usava esse prior pra
    variancia do residual e um peso sem relacao nenhuma pra media dele."""
    for familia, baseline in (("corners", 10.2), ("cards", 4.0), ("fouls", 24.82)):
        phi_total = pm.dispersao(familia, "total")
        r = baseline / (phi_total - 1.0)          # o que dispersao_residual usa
        beta = rm.forca_do_prior(familia)
        assert r == pytest.approx(baseline * beta, rel=0.01), familia


def test_familia_sem_dispersao_medida_cai_no_prior_maximo():
    """`dispersao` devolve 1.0 (Poisson) pra familia nao medida, e 1/(phi-1)
    estouraria. Na duvida o historico manda, que e' o lado conservador."""
    assert rm.forca_do_prior("familia_que_nao_existe") == rm.FORCA_MAXIMA_DO_PRIOR
    assert rm.forca_do_prior(None) == rm.FORCA_MAXIMA_DO_PRIOR


# ── o peso do proprio jogo ───────────────────────────────────────────────

def test_o_peso_do_jogo_nao_e_mais_o_mesmo_pra_toda_familia():
    """O defeito em uma linha: aos 45' todas as familias pesavam 0.50."""
    pesos = {
        familia: rm.taxa_por_minuto(0, 45, 10.0, familia)["peso_observado"]
        for familia in ("goals", "corners", "cards", "fouls")
    }
    assert len(set(pesos.values())) == len(pesos)
    assert pesos["goals"] < 0.10
    assert pesos["fouls"] > 0.45
    # Falta e' a familia que a formula antiga acertava por acidente: phi 3.12
    # da' beta 0.47, e o 45 do relogio era beta 0.50.
    assert pesos["fouls"] == pytest.approx(45 / (45 + 45), abs=0.06)


def test_zero_gol_no_primeiro_tempo_quase_nao_move_o_baseline():
    """O caso da tela, isolado: 0x0 aos 36' num confronto de 2.65 gols."""
    taxa = rm.taxa_por_minuto(0, 36, 2.65, "goals")
    projetado_por_90 = taxa["taxa_estimada_min"] * 90
    assert projetado_por_90 == pytest.approx(2.65, abs=0.10)
    # Antes: 1.47 por 90, um corte de 44%.
    assert projetado_por_90 > 2.0


def test_o_rastro_grava_phi_e_a_forca_do_prior():
    """Sem isto no engine_debug nao da' pra auditar por que o peso foi aquele."""
    taxa = rm.taxa_por_minuto(3, 40, 10.2, "corners")
    assert taxa["dispersao_phi"] == pytest.approx(1.82, abs=0.01)
    assert taxa["forca_do_prior_jogos"] == pytest.approx(1.22, abs=0.02)


def test_escanteio_continua_ouvindo_o_proprio_jogo():
    """A correcao NAO pode cegar a familia que calibra dos dois lados
    (Over 72.4%, Under 73.1%). Escanteio sai de estilo de jogo, e estilo
    aparece no placar parcial."""
    parado = rm.taxa_por_minuto(1, 45, 10.2, "corners")["taxa_estimada_min"]
    normal = rm.taxa_por_minuto(5, 45, 10.2, "corners")["taxa_estimada_min"]
    aberto = rm.taxa_por_minuto(9, 45, 10.2, "corners")["taxa_estimada_min"]
    assert parado < normal < aberto
    assert (aberto - parado) * 90 > 2.0   # o jogo ainda desloca 2+ escanteios


# ── a ponta de saida ─────────────────────────────────────────────────────

def test_o_pick_da_tela_nao_nasce_mais():
    """Gols Under 1.5, 0x0 aos 36', confronto de 2.65: a probabilidade cai
    abaixo do piso da familia (0.65) e o pick nao chega a existir."""
    lam = rm.lambda_residual("goals", observado=0, minuto=36, status="1H",
                             baseline_por_partida=2.65)
    phi = rm.dispersao_residual("goals", 2.65, lam["lambda_residual"],
                                lam["minutos_restantes"])
    prob_modelo = pm.prob_under(1.5, lam["lambda_residual"], phi)
    publicada = rm.encolher_contra_mercado(prob_modelo, 0.60, 36)["prob"]
    assert publicada < 0.65
    # E continua acima do condicional de um jogo qualquer: nao virou zero,
    # virou honesto.
    assert publicada > 0.50


def test_a_projecao_ainda_conta_o_que_ja_aconteceu():
    """O que a partida mostrou nao foi desligado: ele entra pelo total, que e'
    `observado + residual`, e pelos fatores de ritmo e estado."""
    zerado = rm.lambda_residual("goals", observado=0, minuto=60, status="2H",
                                baseline_por_partida=2.65)
    goleada = rm.lambda_residual("goals", observado=4, minuto=60, status="2H",
                                 baseline_por_partida=2.65)
    assert goleada["projecao_total"] > zerado["projecao_total"] + 3.5
