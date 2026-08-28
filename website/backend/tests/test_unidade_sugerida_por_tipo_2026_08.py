"""A unidade sugerida cobre TODO tipo de pick, e respeita o teto do follow.

DUAS FALHAS DA MESMA FAMILIA, as duas encontradas ao levar o card pro app.

1. O BLOCO PAROU DE CRESCER ENQUANTO OS PRODUTOS CRESCIAM

`/suggestions/today` calculava `suggested_stake_units` para vip, dica e
multipla. Faltas nasceu em 01/08, Player Stats em 27/08 e Pick Boost em 28/08 --
os tres chegavam na tela SEM o campo.

No site isso nao aparecia como erro: o card cai num Kelly local quando o campo
falta. Mas o Kelly local nao conhece `stake_pct` e nao produz o mesmo numero. No
APP, que nao tem Kelly nenhum de proposito (pra nao existir uma segunda
implementacao da mesma conta), o card simplesmente nao dizia quanto apostar.

2. O TETO DE UNIDADES ERA UMA SEGUNDA LISTA

`max_units` tinha `free` e `multipla`, e todo tipo novo caia no default de
9999 · sem teto. A sugestao podia passar do que `POST /banca/follow` aceita, e o
usuario so' descobriria no erro, DEPOIS de confirmar -- o mesmo defeito que
MAX_UNITS_POR_TIPO ja' corrigiu do lado do card.

Agora o teto sai de `banca.STAKE_LIMITS`, que e' quem de fato recusa.
"""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from routers.banca import STAKE_LIMITS  # noqa: E402
from routers.suggestions import _compute_suggested_stake_units  # noqa: E402

#: Banca de exemplo · 10 mil de bolo e unidade de 100.
BANCA = (10_000.0, 100.0)

#: Pick forte de proposito: alta confianca e odd boa fazem o Kelly pedir MUITO,
#: que e' o cenario em que o teto precisa morder.
FORTE = dict(stake_pct=None, confidence=0.88, odd=2.10, ev=0.85)


@pytest.mark.parametrize("tipo", sorted(STAKE_LIMITS))
def test_nenhum_tipo_sugere_mais_do_que_o_follow_aceita(tipo):
    """E' a asserção que resume o arquivo · a sugestao nunca pode ser recusada
    pela rota que ela existe pra alimentar."""
    if tipo == "alavancagem":
        pytest.skip("banca composta progressiva, sem teto fixo (STAKE_LIMITS = 9999)")

    unidades = _compute_suggested_stake_units(tipo, **FORTE, bankroll=BANCA[0],
                                              unit_value=BANCA[1])
    minimo, maximo = STAKE_LIMITS[tipo]
    assert minimo <= unidades <= maximo, f"{tipo}: {unidades} fora de {minimo}-{maximo}"


@pytest.mark.parametrize("tipo", ["faltas", "goleiros", "player_stats", "boost"])
def test_os_mercados_proprios_recebem_sugestao(tipo):
    """Antes de 28/08 o campo nem era calculado pra eles · o app ficava sem
    nada e o site caia num Kelly que nao e' o mesmo numero."""
    unidades = _compute_suggested_stake_units(tipo, **FORTE, bankroll=BANCA[0],
                                              unit_value=BANCA[1])
    assert unidades >= 1


def test_o_boost_e_mais_conservador_que_um_pick_de_perna_unica():
    """Combinado quebra inteiro quando uma perna erra · e' a mesma razao do
    peso 2 em stake_plan e do teto 5 em STAKE_LIMITS."""
    boost = _compute_suggested_stake_units("boost", **FORTE, bankroll=BANCA[0],
                                           unit_value=BANCA[1])
    faltas = _compute_suggested_stake_units("faltas", **FORTE, bankroll=BANCA[0],
                                            unit_value=BANCA[1])
    assert boost <= faltas


def test_sem_banca_cai_em_uma_unidade():
    """Divisao por unidade zero nao pode virar excecao no meio do /today."""
    assert _compute_suggested_stake_units("vip", **FORTE, bankroll=0, unit_value=0) == 1


def test_a_rota_calcula_pros_mercados_proprios():
    """A lista de tipos vive dentro de get_today_suggestions · sem ela o calculo existe e
    nunca e' chamado."""
    import ast

    fonte = open(os.path.join(_BACKEND, "routers", "suggestions.py"),
                 encoding="utf-8").read()
    corpo = next(
        ast.get_source_segment(fonte, no)
        for no in ast.walk(ast.parse(fonte))
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))
        and no.name == "get_today_suggestions"
    )
    for chave in ("faltas", "goleiros", "player_stats", "boost"):
        assert f'"{chave}"' in corpo, f"{chave} fora do calculo de stake"
