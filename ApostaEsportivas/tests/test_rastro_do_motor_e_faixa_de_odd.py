# -*- coding: utf-8 -*-
"""O rastro do motor, e a odd que morre antes da conta (2026-08-27).

DUAS PERGUNTAS DO USUARIO, UMA MUDANCA
--------------------------------------
1. "Cade o mercado de gols? Por que so' tem Under? Quero ver geral."

   `analyze_fixture_markets` devolve UM candidato por familia -- a linha que
   venceu la' dentro. O log de decisao gravava exatamente isso, entao a tela
   do admin mostrava "goals Under 2.5" e mais nada: o Over da mesma linha, as
   outras linhas do mesmo mercado e as familias inteiras eliminadas antes
   (handicap, resultado, cartoes sem arbitro) nao deixavam rastro nenhum.

2. "Quando a odd estiver fora do padrao ja' descarta, nem calcula, porque nao
   vai adiantar calcular."

   A faixa ja' era filtro duro desde 14/08, mas so' na hora de aprovar: a
   linha passava por compute_taxa, encolhimento bayesiano, Poisson, arbitro e
   estabilidade pra ser reprovada por um numero que se sabia antes de tudo
   isso.

O QUE ESTE TESTE TRAVA
----------------------
  * linha fora da faixa nao chega a ser calculada (nao tem taxa/EV no rastro);
  * ela AINDA APARECE no rastro, nomeada e com o motivo -- descartar sem
    calcular nao pode virar descartar sem contar;
  * o Over que perdeu para o Under aparece junto do Under que venceu;
  * a familia eliminada antes das linhas aparece com o motivo;
  * e o principal: o pick escolhido continua o MESMO com e sem o descarte
    antecipado. Se essa invariante cair, a "otimizacao" mudou decisao.
"""
from datetime import date

import pytest

from services.pick_engine import analyze_fixture_markets
from services.pick_engine.config import PickEngineConfig, VIP_CONFIG
from services.pick_engine import ranking

HOJE = date(2026, 8, 27)
CASA, FORA = 100, 200

CALIBRACAO_VAZIA = {"by_market_league": {}, "by_market": {}}


def _jogo(dia):
    """Jogo de placar alto, sempre igual: a taxa nao e' o assunto aqui."""
    return {
        "match_date": date(2026, 7, dia),
        "home_team_id": CASA, "away_team_id": FORA,
        "home_goals": 3, "away_goals": 1, "total_goals": 4,
        "home_corners": 7, "away_corners": 4, "total_corners": 11,
        "home_yellow_cards": 2, "away_yellow_cards": 2, "total_yellow_cards": 4,
        "home_red_cards": 0, "away_red_cards": 0,
    }


HISTORICO = [_jogo(dia) for dia in range(10, 30)]


def _odd(market_name, value, line, market_id, odd):
    return {
        "market_id": market_id, "market_name": market_name,
        "value": value, "line": line,
        "best_odd": odd, "bookmakers_count": 6,
    }


# Over/Under nas duas pontas: 1.5 sai barato demais pra faixa do VIP
# (1.50-1.90) e 4.5 sai caro demais. 2.5 fica dentro, nos dois sentidos.
ODDS = [
    _odd("Goals Over/Under", "Over", "1.5", 5, 1.18),
    _odd("Goals Over/Under", "Under", "1.5", 5, 4.60),
    _odd("Goals Over/Under", "Over", "2.5", 5, 1.62),
    _odd("Goals Over/Under", "Under", "2.5", 5, 1.78),
    _odd("Goals Over/Under", "Over", "4.5", 5, 3.40),
    _odd("Goals Over/Under", "Under", "4.5", 5, 1.22),
    # Familia eliminada antes de qualquer linha (decisao de produto).
    _odd("Asian Handicap", "Home -1", "-1", 4, 1.75),
]


def _analisa(config, rastro=None):
    return analyze_fixture_markets(
        ODDS, HISTORICO, HISTORICO,
        reference_date=HOJE,
        calibration_data=CALIBRACAO_VAZIA,
        home_team_id=CASA, away_team_id=FORA,
        config=config, rastro=rastro,
    )


def _linhas(rastro):
    return [r for r in rastro if r["nivel"] == "linha"]


def _familias(rastro):
    return [r for r in rastro if r["nivel"] == "familia"]


# ── a odd fora da faixa nao e' calculada ─────────────────────────────────
def test_odd_fora_da_faixa_nao_chega_a_ser_calculada():
    rastro = []
    _analisa(VIP_CONFIG, rastro)

    fora = [r for r in _linhas(rastro)
            if r["status"] == "descartada_sem_calcular"
            and "faixa" in (r.get("motivo") or "")]

    assert fora, "nenhuma linha caiu pela faixa · o cenario nao exercita a regra"
    for r in fora:
        # O ponto inteiro: sem conta nenhuma feita em cima dela.
        assert r.get("taxa_real") is None
        assert r.get("ev") is None
        assert r.get("line_score") is None


def test_a_linha_descartada_ainda_aparece_com_nome_e_motivo():
    """Descartar sem calcular nao pode virar descartar sem contar · era
    exatamente esse o buraco que fazia a tela dizer "so' tem Under"."""
    rastro = []
    _analisa(VIP_CONFIG, rastro)

    barata = [r for r in _linhas(rastro)
              if r.get("odd") == 1.18 and r["status"] == "descartada_sem_calcular"]

    assert len(barata) == 1
    assert barata[0]["market_type"] == "goals"
    assert barata[0]["line"] is not None
    assert "1.18" in barata[0]["motivo"]


def test_o_motivo_vem_da_mesma_funcao_que_o_gate_de_aprovacao():
    """Se as duas listas divergirem, o motor descarta antes uma linha que o
    ranking teria aceitado -- que e' a unica forma de essa mudanca virar bug."""
    assert ranking.motivo_de_odd_fora(1.18, VIP_CONFIG)
    assert ranking.motivo_de_odd_fora(4.60, VIP_CONFIG)
    assert ranking.motivo_de_odd_fora(1.78, VIP_CONFIG) is None


# ── e o pick continua o mesmo ────────────────────────────────────────────
def test_descartar_antes_nao_muda_o_pick_escolhido():
    """A invariante que sustenta a mudanca toda.

    `enforce_odd_band=False` faz o motor calcular tudo (comportamento
    historico); `True` faz ele pular as mesmas linhas antes da conta. O
    mercado vencedor e a linha vencedora tem que sair identicos, porque as
    linhas puladas nunca poderiam virar pick nos dois casos.
    """
    solto = PickEngineConfig(enforce_odd_band=False,
                             min_odd=VIP_CONFIG.conservative_odd_low,
                             max_odd=VIP_CONFIG.conservative_odd_high)
    apertado = PickEngineConfig(enforce_odd_band=True,
                                min_odd=VIP_CONFIG.conservative_odd_low,
                                max_odd=VIP_CONFIG.conservative_odd_high)

    def assinatura(cands):
        return sorted((c["market_type"], c.get("value"), c.get("line"), c["odd"])
                      for c in cands)

    assert assinatura(_analisa(solto)) == assinatura(_analisa(apertado))


# ── o rastro mostra o mercado inteiro ────────────────────────────────────
def test_o_over_que_perdeu_aparece_junto_do_que_venceu():
    rastro = []
    candidatos = _analisa(VIP_CONFIG, rastro)

    vencedor = next(c for c in candidatos if c["market_type"] == "goals")
    avaliadas = [r for r in _linhas(rastro)
                 if r["market_type"] == "goals" and r["status"] == "avaliada"]

    assert len(avaliadas) >= 2, "as duas pontas da linha 2.5 tinham que estar aqui"
    assert any(r["escolhida_do_mercado"] for r in avaliadas)
    # E a que venceu e' a mesma que saiu como candidato.
    escolhida = next(r for r in avaliadas if r["escolhida_do_mercado"])
    assert escolhida["direcao"] == vencedor["value"]
    # A outra ponta existe no rastro com os numeros dela calculados.
    perdedora = next(r for r in avaliadas if not r["escolhida_do_mercado"])
    assert perdedora["taxa_real"] is not None


def test_familia_eliminada_antes_das_linhas_aparece_com_motivo():
    rastro = []
    _analisa(VIP_CONFIG, rastro)

    handicap = [r for r in _familias(rastro)
                if str(r["market_type"]).startswith("handicap")]

    assert handicap
    assert handicap[0]["status"] == "eliminada"
    assert "handicap" in handicap[0]["motivo"]


def test_sem_rastro_o_motor_e_identico():
    """`rastro=None` e' o caminho de todo chamador que nao pediu nada · nao
    pode nem custar nem mudar resultado."""
    assert _analisa(VIP_CONFIG) == _analisa(VIP_CONFIG, rastro=[])
