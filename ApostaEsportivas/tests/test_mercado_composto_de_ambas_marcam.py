"""Mercado COMPOSTO com "both teams score" nao e' ambas marcam.

A API-Football manda, alem do "Both Teams Score" simples:

    "Results/Both Teams Score"            1X2 + BTTS   ("Home/Yes", "Away/No", "Draw/Yes")
    "Total Goals/Both Teams To Score"     O/U + BTTS   ("o/yes 2.5", "u/no 2.5")

Os dois contem "both teams" e "score" e caiam em ("btts", "total").

JA ERAM descartados, mas por ACIDENTE de parse: _build_market_hit_fn exige
direction em (yes/sim/no/nao), "Home/Yes" nao bate, compute_taxa devolvia None e
a entrada morria rotulada "sem taxa calculavel (amostra insuficiente)". Mesma
situacao de "Goalkeeper Saves" antes de 2026-08-01, e a decisao aqui e' a mesma
que foi tomada la': descartar por DECISAO, nao por acidente.

Nao e' cosmetico. Achado em 2026-08-17 rodando o modo debug contra 44 fixtures
reais: sao ~10 entradas fantasma POR FIXTURE rotuladas "btts" no rastro, e foi
isso que fez um relatorio de auditoria afirmar "btts apareceu 440x e publicou 0x"
enquanto o motor publicava ambas marcam normalmente. Rastro sujo produz conclusao
errada mesmo com o motor certo.

Combinado de 1X2+BTTS ainda seria mercado de RESULTADO, fora do pool por decisao
de produto desde 2026-07-24 -- aceita-lo seria furar aquela regra por uma porta
lateral.
"""
import pytest

from services.pick_engine.stats_model import classify_market


@pytest.mark.parametrize("nome", [
    "Both Teams Score",
    "Both Teams To Score",
    "both teams score",
])
def test_ambas_marcam_simples_continua_reconhecida(nome):
    assert classify_market(nome) == ("btts", "total")


@pytest.mark.parametrize("nome", [
    "Results/Both Teams Score",
    "Total Goals/Both Teams To Score",
    "Both Teams Score/Total Goals",      # ordem invertida, mesma coisa
    "Double Chance/Both Teams To Score",
])
def test_composto_com_ambas_marcam_sai_do_pool(nome):
    assert classify_market(nome) is None, f"{nome!r} e' composto, nao BTTS"


def test_a_regra_e_a_barra_e_nao_uma_lista_de_nomes():
    """Trava o MECANISMO, nao os nomes vistos ate hoje.

    Nome de BTTS simples nunca tem barra (ver as chaves de marketTranslate.ts).
    Um composto novo que a API inventar amanha ja nasce excluido, sem precisar
    de outra linha aqui -- que e' o oposto do padrao "lista de excecoes" que
    precisa ser atualizada a cada mercado novo."""
    assert classify_market("Anything/Both Teams Score") is None
    assert classify_market("Both Teams Score/Anything") is None


def test_primeiro_tempo_continua_fora():
    """Regra anterior, nao pode ter sido quebrada pelo guard novo."""
    assert classify_market("Both Teams Score - First Half") is None
    assert classify_market("Both Teams To Score - First Half") is None


def test_o_composto_nao_vira_mercado_de_resultado_por_acidente():
    """"Results/Both Teams Score" contem "result". Se o guard de BTTS deixasse
    passar, a checagem seguinte poderia classificar como outcome e reabrir um
    mercado de resultado -- que esta' fora do pool por decisao de produto."""
    assert classify_market("Results/Both Teams Score") is None
