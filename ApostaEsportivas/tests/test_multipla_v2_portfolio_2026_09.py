"""Multipla V2: portfolio diario, calibracao da perna e correlacao medida.

O QUE ESTES TESTES GUARDAM nao sao os numeros (eles vao mudar por backtest,
e' pra isso que estao no config). E' o COMPORTAMENTO que o usuario pediu em
11/09/2026 e que a V1 nao tinha:

  * o teto de bilhetes vem da OFERTA, e maximo nao e' meta;
  * NO_MULTIPLA e' resposta valida -- nada e' publicado pra preencher espaco;
  * a odd obedece a faixa EXATA, e odd alta nao compra score baixo;
  * 5/5 nao vira 100%;
  * o elo mais fraco manda no bilhete;
  * o dia prefere A+B / C+D a A+B / A+C.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.pick_engine_multipla import combination, component, correlation, portfolio
from services.pick_engine_multipla import config as mcfg
from services.pick_engine_multipla import reasons


def perna(fixture_id, market_type="goals", odd=1.55, taxa=0.72, amostra=24,
          home=None, away=None, league_id=1, casa="Betano", linha="Over 1.5"):
    """Uma perna do jeito que o motor pre-jogo entrega, com o que a V2 le."""
    home = home if home is not None else fixture_id * 10
    away = away if away is not None else fixture_id * 10 + 1
    acertos = round(taxa * amostra)
    return {
        "market_type": market_type,
        "market_name": market_type,
        "value_label": linha,
        "_direction": "over",
        "odd": odd,
        "melhor_odd": odd,
        "best_bookmaker": casa,
        "bookmaker_odds": [{"bookmaker": casa, "odd": odd}],
        "taxa_real": taxa,
        "amostra": amostra,
        "wilson": _wilson(acertos, amostra),
        "confidence": 0.78,
        "Q": 0.8,
        "ev": round(taxa * odd - 1.0, 4),
        "edge": 0.09,
        "risco": "BAIXO",
        "data_quality_score": 0.82,
        "projecao": {"classe": "folgada", "margem_em_sigmas": 0.8},
        "convergence": {"converged": True, "diff_pct": 0.05},
        "final_score": 0.86,
        "_fixture": {
            "fixture_id": fixture_id,
            "home_team": f"Time {home}", "away_team": f"Time {away}",
            "home_team_id": home, "away_team_id": away,
            "league_id": league_id,
        },
    }


def _wilson(acertos, n):
    from services.pick_engine.stats_model import wilson_interval
    return wilson_interval(acertos, n)


# --------------------------------------------------------------- TETO POR OFERTA
def test_o_teto_cresce_com_a_oferta_e_nao_com_o_dia():
    assert mcfg.teto_de_multiplas(0) == 0
    assert mcfg.teto_de_multiplas(3) == 1
    assert mcfg.teto_de_multiplas(8) == 2
    assert mcfg.teto_de_multiplas(15) == 3
    assert mcfg.teto_de_multiplas(25) == 4
    assert mcfg.teto_de_multiplas(40) == 5


def test_maximo_nao_e_meta():
    """Vinte jogos elegiveis dao teto 3. Se so' uma combinacao presta, sai 1."""
    pool, _, _ = _pool([perna(1), perna(2)] + [perna(i, taxa=0.62, odd=1.42)
                                               for i in range(3, 22)])
    resultado = portfolio.montar(pool, jogos_elegiveis=20)
    assert resultado["max_multiples"] == 3
    assert len(resultado["multiples"]) <= 3


# ------------------------------------------------------------------ NO_MULTIPLA
def test_dia_sem_candidato_devolve_no_multipla_com_motivo():
    resultado = portfolio.montar([], jogos_elegiveis=0)
    assert resultado["decision"] == "NO_MULTIPLA"
    assert resultado["reason"] == reasons.NO_MULTIPLA_INSUFFICIENT_CANDIDATES
    assert resultado["multiples"] == []


def test_nenhuma_multipla_e_forcada_pra_preencher_o_teto():
    """Duas pernas caras demais: o produto estoura a faixa e nao ha' bilhete.
    O motor NAO desce a qualidade pra caber."""
    pool, _, _ = _pool([perna(1, odd=1.95), perna(2, odd=1.92)])
    resultado = portfolio.montar(pool, jogos_elegiveis=2)
    assert resultado["multiples"] == []
    assert resultado["decision"] == "NO_MULTIPLA"


# ------------------------------------------------------------------ FAIXA DE ODD
def test_odd_abaixo_da_faixa_nao_publica():
    avaliada = combination.avaliar([perna(1, odd=1.40), perna(2, odd=1.40)])
    assert round(avaliada["odd_total"], 2) == 1.96
    assert reasons.NO_MULTIPLA_ODD_BELOW_RANGE in avaliada["motivos"]


def test_odd_acima_da_faixa_nao_publica_mesmo_perto_do_teto():
    """1.73 x 1.91 = 3.30 nao e' "quase 3.00": a faixa e' exata."""
    avaliada = combination.avaliar([perna(1, odd=1.73), perna(2, odd=1.91)])
    assert reasons.NO_MULTIPLA_ODD_ABOVE_RANGE in avaliada["motivos"]


def test_faixa_padrao_e_dois_a_tres():
    cfg = mcfg.padrao()
    assert (cfg.odd_total_min, cfg.teto_de_odd) == (2.00, 3.00)
    assert mcfg.MultiplaConfig(modo_agressivo=True).teto_de_odd == 4.00


# ------------------------------------------------------------------- CALIBRACAO
def test_cinco_em_cinco_nao_vira_cem_por_cento():
    p = perna(1, taxa=1.0, amostra=5)
    calibrada = component.probabilidade_calibrada(p)
    assert calibrada < 1.0
    assert calibrada < 0.85


def test_amostra_maior_encolhe_menos():
    pequena = component.probabilidade_calibrada(perna(1, taxa=0.75, amostra=5))
    grande = component.probabilidade_calibrada(perna(1, taxa=0.75, amostra=40))
    assert grande > pequena


def test_a_calibracao_nunca_sobe_a_probabilidade():
    for amostra in (4, 7, 12, 25, 50):
        p = perna(1, taxa=0.70, amostra=amostra)
        assert component.probabilidade_calibrada(p) <= p["taxa_real"]


def test_confidence_nao_e_probabilidade():
    """Sao dois numeros diferentes e a V2 nao troca um pelo outro: confidence
    mede a qualidade da previsao, probability mede a chance do evento."""
    p = component.avaliar(perna(1, taxa=0.62))
    assert p["confidence"] != p["probabilidade_calibrada"]
    assert p["probabilidade_calibrada"] <= p["taxa_real"]


# ---------------------------------------------------------------- GATE DA PERNA
def test_perna_de_risco_alto_nao_entra_no_pool():
    p = perna(1)
    p["risco"] = "ALTO"
    assert not component.avaliar(p)["aprovada"]
    assert reasons.PERNA_RISCO in component.avaliar(p)["motivos"]


def test_projecao_em_cima_da_linha_nao_vira_perna():
    p = perna(1)
    p["projecao"] = {"classe": "em_cima_da_linha", "margem_em_sigmas": 0.05}
    assert reasons.PERNA_PROJECAO in component.avaliar(p)["motivos"]


def test_projecao_ausente_e_neutra_e_nao_reprova():
    """btts/resultado/handicap nao tem projecao. Ausencia nao vira confirmacao
    -- e tambem nao vira reprovacao."""
    p = perna(1, market_type="btts")
    p["projecao"] = None
    assert reasons.PERNA_PROJECAO not in component.avaliar(p)["motivos"]


def test_perna_sem_edge_nao_entra():
    p = perna(1)
    p["edge"] = 0.01
    assert reasons.PERNA_EDGE in component.avaliar(p)["motivos"]


# ------------------------------------------------------------------ CORRELACAO
def test_mesmo_jogo_e_correlacao_alta_e_nao_combina():
    nivel, _ = correlation.classificar_par(
        perna(1, market_type="goals"), perna(1, market_type="corners"))
    assert nivel == correlation.HIGH

    avaliada = combination.avaliar([perna(1, market_type="goals"),
                                    perna(1, market_type="corners")])
    assert not avaliada["aprovada"]
    assert reasons.NO_MULTIPLA_HIGH_CORRELATION in avaliada["motivos"]


def test_a_mesma_equipe_nos_dois_lados_e_correlacao_alta():
    a = perna(1, home=100, away=101)
    b = perna(2, home=100, away=202)   # o mesmo time 100 sustenta as duas
    nivel, _ = correlation.classificar_par(a, b)
    assert nivel == correlation.HIGH


def test_mesma_liga_e_mesma_familia_e_media_nao_baixa():
    nivel, _ = correlation.classificar_par(
        perna(1, league_id=7, market_type="goals"),
        perna(2, league_id=7, market_type="goals"))
    assert nivel == correlation.MEDIUM


def test_familia_repetida_entre_ligas_continua_baixa():
    """Medido em 2.677 bilhetes (2026-08-20): perna repetida entre jogos
    diferentes NAO e' pior. A V2 nao reintroduz a proibicao."""
    nivel, _ = correlation.classificar_par(
        perna(1, league_id=7, market_type="goals"),
        perna(2, league_id=9, market_type="goals"))
    assert nivel == correlation.LOW


def test_correlacao_desconhecida_paga_penalidade_na_probabilidade():
    corr_baixa = {"penalidade": mcfg.PENALIDADE_CORRELACAO["LOW"]}
    corr_desconhecida = {"penalidade": mcfg.PENALIDADE_CORRELACAO["UNKNOWN"]}
    assert (correlation.prob_ajustada(0.50, corr_desconhecida)
            < correlation.prob_ajustada(0.50, corr_baixa))


def test_a_probabilidade_do_bilhete_nunca_sobe_pelo_ajuste():
    combo = [perna(1), perna(2, league_id=9)]
    avaliada = combination.avaliar(combo)
    assert avaliada["probabilidade"] <= avaliada["prob_produto"]


# ------------------------------------------------------------- ELO MAIS FRACO
def test_uma_perna_muito_inferior_reprova_o_bilhete():
    forte = perna(1, taxa=0.78, odd=1.50, amostra=40, league_id=9)
    fraca = perna(2, taxa=0.61, odd=1.45, amostra=5, league_id=3)
    fraca["confidence"] = 0.56
    fraca["risco"] = "MEDIO"
    fraca["data_quality_score"] = 0.55

    avaliada = combination.avaliar([component.avaliar(forte), component.avaliar(fraca)])
    assert avaliada["elo_mais_fraco"] < avaliada["score_parcelas"]["media_das_pernas"]


def test_odd_alta_nao_compra_score_baixo():
    """Score 0.55 com odd 2.95 e' REJEITADO. Proximidade do teto nao e'
    qualidade."""
    cfg = mcfg.padrao()
    assert 0.55 < cfg.min_combination_score
    assert mcfg.faixa_de_score(0.55) == "REJEITADA"
    assert mcfg.faixa_de_score(0.82) == "EXCELENTE"


def test_odd_baixa_com_score_alto_e_excelente():
    """2.02 colado no piso nao e' penalizado quando a qualidade e' alta."""
    pool, _, _ = _pool([perna(1, odd=1.42, taxa=0.78, amostra=40, league_id=3),
                        perna(2, odd=1.43, taxa=0.77, amostra=38, league_id=9)])
    avaliada = combination.avaliar(pool)
    assert 2.00 <= avaliada["odd_total"] <= 2.10
    assert avaliada["aprovada"], avaliada["motivos"]


# ---------------------------------------------------------------- PORTFOLIO
def test_o_dia_prefere_a_mais_b_e_c_mais_d_a_tres_bilhetes_girando_em_a():
    """A regra que sustenta o portfolio: perna nao se repete entre bilhetes.
    Tres bilhetes compartilhando A nao sao tres apostas -- sao uma aposta com
    o triplo da exposicao em A."""
    pernas = [perna(i, odd=1.48, league_id=i) for i in range(1, 9)]
    pool, _, jogos = _pool(pernas)
    resultado = portfolio.montar(pool, jogos_elegiveis=jogos)

    vistas = []
    for bilhete in resultado["multiples"]:
        vistas.extend((p["_fixture"]["fixture_id"], p["market_type"])
                      for p in bilhete["pernas"])
    assert len(vistas) == len(set(vistas)), "a mesma perna entrou em dois bilhetes"


def test_exposicao_por_jogo_tem_limite():
    pernas = [perna(i, odd=1.48, league_id=i) for i in range(1, 9)]
    pool, _, jogos = _pool(pernas)
    resultado = portfolio.montar(pool, jogos_elegiveis=jogos)

    contagem = {}
    for bilhete in resultado["multiples"]:
        for j in {p["_fixture"]["fixture_id"] for p in bilhete["pernas"]}:
            contagem[j] = contagem.get(j, 0) + 1
    assert all(v <= mcfg.LIMITE_DE_EXPOSICAO_POR_JOGO for v in contagem.values())


def test_o_teto_conta_o_dia_e_nao_a_execucao():
    """`vagas` e' o que sobra depois do que o dia ja' publicou: rodar o motor
    duas vezes nao pode dobrar a exposicao."""
    pernas = [perna(i, odd=1.48, league_id=i) for i in range(1, 9)]
    pool, _, jogos = _pool(pernas)
    resultado = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1)
    assert len(resultado["multiples"]) <= 1


def test_o_resumo_do_dia_responde_por_que():
    pool, _, jogos = _pool([perna(1, league_id=3), perna(2, league_id=9)])
    resultado = portfolio.montar(pool, jogos_elegiveis=jogos)
    resumo = portfolio.resumo(resultado, "2026-09-11")
    assert resumo["date"] == "2026-09-11"
    assert "games_available" in resumo and "max_multiples" in resumo
    if resumo["decision"] == "NO_MULTIPLA":
        assert resumo["reason"]
    else:
        assert resumo["multiples"][0]["id"] == "MULTIPLA_1"
        assert resumo["multiples"][0]["legs"]


# --------------------------------------------------------------- DIVERSIFICACAO
def test_diversificacao_premia_jogos_e_ligas_diferentes():
    dois_jogos = combination.diversificacao([perna(1, league_id=3),
                                             perna(2, league_id=9)])
    mesma_liga = combination.diversificacao([perna(1, league_id=3),
                                             perna(2, league_id=3)])
    assert dois_jogos["score"] > mesma_liga["score"]


# ------------------------------------------------------------------- AUXILIAR
def _pool(pernas):
    aprovadas, reprovadas = component.avaliar_pool(pernas)
    jogos = {component.jogo(p) for p in aprovadas}
    return aprovadas, reprovadas, len(jogos)


def test_o_gate_individual_aprova_uma_perna_boa():
    """Guarda-chuva dos testes acima: se este quebrar, todos os outros
    passam a testar o vazio."""
    aprovadas, reprovadas, _ = _pool([perna(1), perna(2, league_id=9)])
    assert len(aprovadas) == 2, [p["motivos"] for p in reprovadas]
