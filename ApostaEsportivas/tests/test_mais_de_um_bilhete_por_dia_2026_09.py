"""Múltipla e alavancagem passam a publicar mais de um por dia.

Decisao do usuario em 2026-09-05. O Free continua UM -- ele e' a vitrine
diaria, e duas dicas gratis por dia mudam o produto, nao o motor.

O QUE ESTES TESTES GUARDAM nao e' o teto (numero muda), e' a regra que o
sustenta: PERNA NAO SE REPETE ENTRE BILHETES. Dois bilhetes que dividem uma
perna nao sao duas apostas -- sao uma aposta com o dobro da exposicao, porque
o RED daquela perna derruba os dois juntos. Seria concentracao de risco
vestida de variedade.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import engine_pipelines.alavancagem_pipeline as alav
import engine_pipelines.multipla_pipeline as mult
import engine_pipelines.dica_pipeline as dica


def test_o_free_continua_um_por_dia():
    """A fonte da regra do Free e' `_has_today_dica`, e ela nao ganhou teto."""
    fonte = dica._has_today_dica.__doc__ or ""
    assert "MAX" not in fonte
    import inspect
    corpo = inspect.getsource(dica._has_today_dica)
    assert ">= 1" in corpo or "> 0" in corpo


def test_tetos_declarados():
    assert mult.MAX_MULTIPLAS_POR_DIA >= 2
    assert alav.MAX_CAMINHOS_POR_DIA >= 2
    # "bastante jogos" precisa ser um numero, senao a regra nao existe.
    assert alav.JOGOS_POR_CAMINHO_EXTRA > 0


def test_multipla_nao_repete_perna_entre_bilhetes():
    """Na V2 quem monta o dia inteiro e' o portfolio, nao um guloso chamado
    em laco (`_find_combo` deixou de existir aqui em 2026-09-11). A REGRA nao
    mudou, so' o lugar onde ela e' aplicada: perna gasta sai do pool."""
    from services.pick_engine_multipla import component, portfolio

    def perna(fixture_id):
        return {
            "market_type": "goals", "market_name": "goals", "value_label": "Over 1.5",
            "_direction": "over", "odd": 1.50, "melhor_odd": 1.50,
            "best_bookmaker": "Betano",
            "bookmaker_odds": [{"bookmaker": "Betano", "odd": 1.50}],
            "taxa_real": 0.76, "amostra": 32,
            "wilson": {"lower": 0.60, "upper": 0.88, "width": 0.28},
            "confidence": 0.80, "Q": 0.85, "ev": 0.14, "edge": 0.10,
            "risco": "BAIXO", "data_quality_score": 0.85,
            "projecao": {"classe": "folgada", "margem_em_sigmas": 0.9},
            "convergence": {"converged": True, "diff_pct": 0.04},
            "final_score": 0.88,
            "_fixture": {"fixture_id": fixture_id,
                         "home_team": f"A{fixture_id}", "away_team": f"B{fixture_id}",
                         "home_team_id": fixture_id * 10,
                         "away_team_id": fixture_id * 10 + 1,
                         "league_id": fixture_id},
        }

    pool, _ = component.avaliar_pool([perna(100 + i) for i in range(6)])
    resultado = portfolio.montar(pool, jogos_elegiveis=6)
    assert resultado["multiples"], resultado.get("reason")

    vistos = [(p["_fixture"]["fixture_id"], p["market_type"])
              for b in resultado["multiples"] for p in b["pernas"]]
    assert len(vistos) == len(set(vistos)), "a mesma perna entrou em dois bilhetes"


def test_o_teto_conta_o_dia_e_nao_a_execucao():
    """Rodar o motor duas vezes nao pode dobrar a exposicao: as duas funcoes
    de contagem leem `picks_*` por match_date."""
    import inspect
    for fn in (mult._multiplas_de_hoje, alav._caminhos_de_hoje):
        corpo = inspect.getsource(fn)
        assert "match_date" in corpo
        assert "COUNT(*)" in corpo
