"""Cortes medidos contra PROD em 2026-09-09 (motor ao vivo e Free).

A medicao, em uma linha cada:

  LIVE   146 picks liquidados   68.5% real   +17.62u   ROI +12.1%
  FREE    70 picks liquidados   64.3% real    +1.98u   ROI  +2.8%

Nenhum dos dois estava quebrado no agregado -- os dois estavam carregando
fatias que perdiam dinheiro de forma sistematica, e o agregado escondia isso.
Cada teste aqui protege um corte, e o comentario de config.py guarda o numero
que o justificou. Se um deles comecar a atrapalhar, o caminho e' remedir a
fatia, nao afrouxar o limiar no escuro.
"""
import pytest

from services.pick_engine import ranking
from services.pick_engine.config import DICA_CONFIG, VIP_CONFIG, DEFAULT_CONFIG
from services.pick_engine_live import orchestrator
from services.pick_engine_live.config import LiveEngineConfig, DEFAULT_LIVE_CONFIG


# ───────────────────────────── FREE: cauda alta ──────────────────────────────


def _linha(odd=1.70, taxa=0.70, edge=0.10, ev=0.15, **extra):
    return {"odd": odd, "taxa_real": taxa, "edge": edge, "ev": ev,
            "amostra": 10, "confidence": 0.80, "bookmakers_count": 3,
            "market_type": "corners", **extra}


def test_free_recusa_taxa_acima_do_teto():
    """Taxa prevista >85% acertou 40% em PROD (5 picks, -1.93u). Uma taxa de
    89% num pool de 14 jogos quer dizer "12 de 14", nao "9 em cada 10"."""
    assert ranking.rank_all_candidates([_linha(taxa=0.90)], DICA_CONFIG) == []
    assert len(ranking.rank_all_candidates([_linha(taxa=0.75)], DICA_CONFIG)) == 1


def test_free_recusa_edge_acima_do_teto():
    """Edge >24% acertou 33% (6 picks, -2.52u). Edge grande e' alerta de que a
    amostra nao representa o jogo, nunca nota de qualidade."""
    reject = ranking.evaluate_all_lines([_linha(edge=0.30)], DICA_CONFIG)[0]["reject_reason"]
    assert reject is not None and "teto" in reject
    assert ranking.evaluate_all_lines([_linha(edge=0.15)], DICA_CONFIG)[0]["reject_reason"] is None


def test_o_motivo_aparece_no_debug():
    """A homologacao precisa dizer POR QUE cortou, senao o corte vira sumico."""
    _, descartados = ranking.rank_all_candidates_debug([_linha(taxa=0.90)], DICA_CONFIG)
    assert any("teto" in m for m in descartados[0]["discard_reasons"])


def test_os_tetos_sao_so_da_free():
    """VIP e os pipelines do default nao foram medidos, entao nao herdam o
    limiar -- foi exatamente esse descuido que deixou o min_confidence 0.72 da
    era da IA cortando a Free por anos sem numero nenhum atras."""
    assert DICA_CONFIG.max_taxa is not None and DICA_CONFIG.max_edge is not None
    assert VIP_CONFIG.max_taxa is None and VIP_CONFIG.max_edge is None
    assert DEFAULT_CONFIG.max_taxa is None and DEFAULT_CONFIG.max_edge is None
    assert len(ranking.rank_all_candidates([_linha(taxa=0.90)], VIP_CONFIG)) == 1


# ────────────────────────────── LIVE: os vetos ───────────────────────────────


def _gates(direcao="over", familia="goals", prob=0.75, ritmo=None,
           config=DEFAULT_LIVE_CONFIG):
    entrada = {"odd": 1.70, "tem_par": True}
    valor = {"ev": 0.15, "edge": 0.10}
    conf = {"confidence": 0.70}
    conv = {"a_favor": 4, "contra": 0}
    return orchestrator._gates(
        entrada, prob, valor, conf, conv, observado=2, linha=3.5,
        direcao=direcao, fresh=None, config=config,
        familia=familia, ritmo=ritmo)


def test_live_veta_over_de_gols():
    """Gols Over 42.9% real (-4.06u) contra gols Under 64.0% (+0.60u). Comprar
    Over ao vivo e' comprar a continuacao de um ritmo que o modelo so' leu
    depois que ele apareceu."""
    assert any("UNDER" in m for m in _gates(direcao="over", familia="goals"))
    assert not _gates(direcao="under", familia="goals", prob=0.75)


def test_live_nao_veta_over_de_escanteios():
    """Em escanteios os dois lados calibram (Over 72.4%, Under 73.1%): o vies
    e' de gol, nao do motor."""
    assert not _gates(direcao="over", familia="corners", prob=0.75)


def test_live_veta_ritmo_muito_alto():
    """A pior fatia do motor inteiro: 11 picks, 36.4% real contra 71.2%
    previsto, -5.26u, negativa nos dois mercados ao mesmo tempo."""
    assert any("MUITO_ALTO" in m
               for m in _gates(direcao="under", familia="goals", ritmo={"nivel": "MUITO_ALTO"}))
    assert not _gates(direcao="under", familia="goals", ritmo={"nivel": "ALTO"})


def test_live_piso_de_probabilidade_e_maior_em_gols():
    """0.55 geral, 0.65 em gols · o piso nao conserta a extrapolacao, so'
    exige que ela venha de uma posicao com folga."""
    assert any("probabilidade" in m
               for m in _gates(direcao="under", familia="goals", prob=0.60))
    assert not _gates(direcao="under", familia="corners", prob=0.60)


def test_live_um_pick_por_partida():
    """O segundo pick da mesma partida acertava 63.2% contra 73.1% do unico:
    ele le' o MESMO jogo, entao quando a leitura erra os dois erram juntos."""
    assert LiveEngineConfig().max_picks_por_partida == 1


# ─────────────────── LINHA QUARTER · o bug de conta (10/09) ──────────────────
#
# A casa cota gols ao vivo em quarter (.25/.75) o tempo todo: dos 168 picks ao
# vivo liquidados em PROD, 25 tinham linha quarter e os 25 eram de GOLS.
# `prob_over`/`prob_under` usam floor(linha), entao a quarter virava uma vizinha
# .5 -- e qual vizinha depende do lado, o que faz o erro trocar de sinal.

from services.pick_engine_live import residual_model as rm
from services.pick_engine import probability_model as pm


def test_linha_meia_nao_muda():
    """A correcao e' cirurgica: linha .5 continua exatamente como era. Este e'
    o teste que separa "consertei a quarter" de "mexi na conta de todo mundo"."""
    for linha, direcao in ((3.5, "over"), (2.5, "under"), (9.5, "over")):
        f = pm.prob_over if direcao == "over" else pm.prob_under
        assert rm.probabilidade_da_linha(1.8, linha, direcao, 0) == \
            pytest.approx(f(linha, 1.8, 1.0), abs=1e-4)


def test_over_quarter_deixa_de_ser_lido_como_a_linha_de_baixo():
    """"Over 3.75" contava X=4 como acerto cheio, quando ele paga metade."""
    novo = rm.probabilidade_da_linha(1.8, 3.75, "over", 0)
    assert novo < pm.prob_over(3.5, 1.8, 1.0)
    # e fica entre as duas vizinhas, que e' o que "meia aposta em cada" quer dizer
    assert pm.prob_over(4.0, 1.8, 1.0) < novo < pm.prob_over(3.5, 1.8, 1.0)


def test_under_quarter_erra_para_os_dois_lados():
    """O sinal do erro depende de .25 ou .75, porque floor() escolhe vizinhas
    diferentes -- e' por isso que ele passou tanto tempo sem aparecer."""
    assert rm.probabilidade_da_linha(1.8, 2.25, "under", 0) < pm.prob_under(2.25, 1.8, 1.0)
    assert rm.probabilidade_da_linha(1.8, 1.75, "under", 0) > pm.prob_under(1.75, 1.8, 1.0)


def test_quarter_respeita_o_placar_ja_observado():
    """A quarter se preserva na subtracao (observado e' inteiro), entao o ramo
    tem que valer tambem no meio do jogo, nao so' com o placar zerado."""
    assert rm.probabilidade_da_linha(1.5, 5.75, "over", 2) == \
        pytest.approx(rm.probabilidade_da_linha(1.5, 3.75, "over", 0), abs=1e-6)


def test_quarter_nunca_sai_da_faixa_de_probabilidade():
    for linha in (0.75, 1.25, 2.25, 3.75, 6.25, 10.75):
        for direcao in ("over", "under"):
            p = rm.probabilidade_da_linha(2.0, linha, direcao, 0)
            assert 0.0 <= p <= 1.0


# ──────────────── Ritmo vetado corta antes de gastar requisicao ──────────────


def test_ritmo_vetado_para_na_triagem_e_nao_no_gate():
    """A triagem e' quem decide se vale gastar /odds/live · com teto de 15
    requisicoes por rodada, vetar so no gate final paga a chamada pra recusar
    depois. O ritmo ja esta calculado nesse ponto, e de graca."""
    analise = {
        "estado": {"minuto": 40, "status": "1H"},
        "freshness": {"nivel": "FRESH"},
        "ritmo": {"nivel": "MUITO_ALTO"},
        "familias": {"corners": {"disponivel": True, "observado": 4, "baseline": 9.0,
                                 "projecao_total": 13.0,
                                 "lambda": {"lambda_residual": 5.0}}},
    }
    tri = orchestrator.triagem(analise, DEFAULT_LIVE_CONFIG)
    assert tri["vale"] is False and "MUITO_ALTO" in tri["motivo"]
    # e o mesmo veto continua no gate, pra quem chama avaliar() sem triagem
    assert any("MUITO_ALTO" in m
               for m in _gates(direcao="under", familia="corners",
                               ritmo={"nivel": "MUITO_ALTO"}))
