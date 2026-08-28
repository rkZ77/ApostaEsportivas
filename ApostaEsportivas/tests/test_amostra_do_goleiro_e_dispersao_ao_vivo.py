# -*- coding: utf-8 -*-
"""Duas lacunas fechadas em 2026-08-20, medidas em vez de estimadas.

1. A AMOSTRA QUE CHEGAVA AO MODELO DE GOLEIRO ERA A DO ADVERSARIO
-------------------------------------------------------------------
`expected_saves` mistura dois sinais -- chutes no alvo do adversario (peso 2)
e a media de defesas do proprio goleiro (peso 1) -- e depois encolhe o blend
pro baseline da liga usando `sample_size`. So' que `sample_size` e' a
quantidade de jogos do ADVERSARIO (e' o que goleiros_pipeline passava, e o
proprio `MIN_OPPONENT_SAMPLE` deixa isso explicito no nome).

Consequencia: a media do goleiro entrava CRUA. Um goleiro com uma unica
aparicao contribuia com o placar de defesas daquele jogo como se fosse a media
dele, porque quem tinha 8 jogos era o time que chuta contra ele.

Medido em PROD: `player_match_stats` tem 240 aparicoes de goleiro na base
inteira, e das 125 com historico previo, 86 vem de goleiro com 1 ou 2 jogos
anteriores. Nao e' caso de borda -- e' o caso comum.

Nao foi criada regra nova: e' o mesmo `shrink_taxa` que o resto do motor ja'
aplica a toda taxa de amostra curta. O que estava errado era a amostra.

2. O MOTOR AO VIVO NAO PODIA EMPRESTAR O phi DO PRE-JOGO
---------------------------------------------------------
O pre-jogo mediu phi 1.82 pra escanteios da partida inteira. Ao vivo a
pergunta e' outra: quanto dessa incerteza ainda vale depois de ver 40 minutos?

A resposta nao foi escolhida, foi derivada -- e' a preditiva posterior do
MESMO modelo Gama-Poisson:

    r = lambda_total / (phi_total - 1)
    phi_restante = 1 + lambda_restante / (r + exposicao_ja_observada)

Com lambda 8.79 e phi 1.82 (r = 10.7) isso da' 1.60 aos 15 minutos e 1.05 aos
80, sozinho. Usar 1.82 aos 80 minutos descontaria duas vezes uma incerteza que
a partida ja' resolveu.
"""
import pytest

from services.pick_engine import goalkeeper_model as gm
from services.pick_engine_live import residual_model as rm


# ─────────────────────────── goleiro ───────────────────────────────────────
def test_amostra_curta_do_goleiro_encolhe_a_media_dele():
    """O caso dos 86: um jogo, e uma media que nao descreve nada."""
    um_jogo = gm.expected_saves(4.0, 5.0, 8, keeper_sample=1)
    muitos = gm.expected_saves(4.0, 5.0, 8, keeper_sample=20)
    so_adversario = gm.expected_saves(4.0, None, 8)
    assert um_jogo < muitos, "amostra curta tem que pesar menos"
    assert abs(um_jogo - so_adversario) < abs(muitos - so_adversario), (
        "com um jogo so', a estimativa tem que ficar perto do sinal do "
        "adversario, que e' o unico com amostra")


def test_goleiro_ruim_com_amostra_curta_tambem_e_puxado_pro_meio():
    """O encolhimento e' pros DOIS lados. Se so' corrigisse pra baixo, seria
    um filtro de otimismo disfarcado de estatistica."""
    poucos = gm.expected_saves(4.0, 0.5, 8, keeper_sample=1)
    muitos = gm.expected_saves(4.0, 0.5, 8, keeper_sample=20)
    assert poucos > muitos


def test_sem_amostra_do_goleiro_o_comportamento_e_o_de_antes():
    """Compatibilidade: chamador que ainda nao informa a amostra do goleiro
    nao pode mudar de resultado silenciosamente."""
    assert (gm.expected_saves(4.0, 5.0, 8)
            == gm.expected_saves(4.0, 5.0, 8, keeper_sample=None))


def test_amostra_grande_do_goleiro_quase_nao_encolhe():
    assert gm.expected_saves(4.0, 5.0, 8, keeper_sample=200) == pytest.approx(
        gm.expected_saves(4.0, 5.0, 8), abs=0.05)


def test_o_pipeline_passa_a_amostra_do_goleiro():
    """Sem esta linha o parametro existe e ninguem usa -- que era exatamente
    o estado anterior, so' que sem o parametro.

    Lia o goleiros_pipeline ate' 28/08, quando ele foi apagado. Quem chama
    `expected_saves` hoje e' `_avaliar_saves` do Player Stats, e a amostra vem
    do tamanho da serie do proprio goleiro em vez de um campo do dicionario ·
    mesma grandeza, outro caminho."""
    import inspect
    from engine_pipelines import player_stats_pipeline
    fonte = inspect.getsource(player_stats_pipeline._avaliar_saves)
    assert "keeper_sample=len(valores)" in fonte


def test_as_duas_amostras_sao_de_coisas_diferentes():
    """Trava o que confundiu os dois: mudar a amostra do ADVERSARIO nao pode
    ter o mesmo efeito que mudar a do GOLEIRO."""
    muda_adversario = gm.expected_saves(4.0, 5.0, 30, keeper_sample=3)
    muda_goleiro = gm.expected_saves(4.0, 5.0, 8, keeper_sample=30)
    base = gm.expected_saves(4.0, 5.0, 8, keeper_sample=3)
    assert muda_adversario != base
    assert muda_goleiro != base
    assert muda_adversario != muda_goleiro


# ─────────────────────────── ao vivo ───────────────────────────────────────
def _phi_no_minuto(minuto, familia="corners", baseline=8.79):
    restantes = 90 - minuto
    return rm.dispersao_residual(familia, baseline,
                                 baseline * restantes / 90, restantes)


def test_dispersao_residual_cai_com_o_relogio():
    """A propriedade central: a partida vai revelando o proprio ritmo."""
    valores = [_phi_no_minuto(m) for m in (15, 30, 45, 60, 80)]
    assert valores == sorted(valores, reverse=True)
    assert valores[0] > 1.5, "aos 15 minutos quase nada foi resolvido"
    assert valores[-1] < 1.10, "aos 80 minutos a partida ja' se explicou"


def test_no_limite_do_apito_inicial_bate_com_o_phi_da_partida():
    """Sem nada observado, a preditiva tem que devolver o phi do pre-jogo --
    se nao devolvesse, as duas contas estariam falando de coisas diferentes."""
    from services.pick_engine import probability_model as pm
    phi_total = pm.dispersao("corners", "total")
    assert rm.dispersao_residual("corners", 8.79, 8.79, 90) == pytest.approx(
        phi_total, abs=0.01)


def test_gols_ao_vivo_continua_poisson():
    """Mesmo controle do pre-jogo: o mercado que funciona nao e' tocado."""
    assert _phi_no_minuto(45, "goals", 2.54) < 1.05


def test_familia_sem_medicao_devolve_poisson():
    assert rm.dispersao_residual("saves", 2.5, 1.2, 45) == 1.0
    assert rm.dispersao_residual("corners", None, 4.0, 45) == 1.0
    assert rm.dispersao_residual("corners", 8.79, 0, 45) == 1.0


def test_a_linha_ao_vivo_fica_mais_baixa_com_dispersao():
    """O efeito pratico: Over perto da media para de ser exagerado."""
    poisson = rm.probabilidade_da_linha(4.39, 9.5, "over", 6)
    negbin = rm.probabilidade_da_linha(4.39, 9.5, "over", 6, _phi_no_minuto(45))
    assert negbin < poisson


def test_o_orquestrador_ao_vivo_consulta_a_dispersao():
    """Sem isto a funcao existe e nao e' chamada."""
    import inspect
    from services.pick_engine_live import orchestrator
    fonte = inspect.getsource(orchestrator)
    assert "rm.dispersao_residual(" in fonte


def test_linha_ja_resolvida_continua_curto_circuitada():
    """A dispersao nao pode reintroduzir incerteza numa linha que o placar ja'
    decidiu -- e' o caso que protege o EV de virar infinito."""
    assert rm.probabilidade_da_linha(2.0, 5.5, "over", 9, 1.6) == 0.9999
    assert rm.probabilidade_da_linha(2.0, 5.5, "under", 9, 1.6) == 0.0001
