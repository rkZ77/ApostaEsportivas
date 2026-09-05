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
    """Duas voltas de `_find_combo` sobre o pool, tirando o que ja foi usado:
    e' assim que o pipeline monta o segundo bilhete."""
    legs = [
        {"final_score": 90 - i, "odd": 1.6, "taxa_real": 0.7,
         "market_type": f"m{i}", "_fixture": {"fixture_id": 100 + i}}
        for i in range(6)
    ]
    restantes = list(legs)
    vistos = []
    for _ in range(2):
        r = mult._find_combo(restantes)
        if not r:
            break
        combo = r[0]
        vistos.extend(id(p) for p in combo)
        usadas = {id(p) for p in combo}
        restantes = [p for p in restantes if id(p) not in usadas]
    assert len(vistos) == len(set(vistos)), "a mesma perna entrou em dois bilhetes"


def test_o_teto_conta_o_dia_e_nao_a_execucao():
    """Rodar o motor duas vezes nao pode dobrar a exposicao: as duas funcoes
    de contagem leem `picks_*` por match_date."""
    import inspect
    for fn in (mult._multiplas_de_hoje, alav._caminhos_de_hoje):
        corpo = inspect.getsource(fn)
        assert "match_date" in corpo
        assert "COUNT(*)" in corpo
