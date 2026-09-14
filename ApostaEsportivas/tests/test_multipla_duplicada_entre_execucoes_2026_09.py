"""A multipla identica que saia quando o motor rodava duas vezes no dia.

O DEFEITO (achado do usuario, 2026-09-14)
-----------------------------------------
A V2 ja' impedia perna repetida entre bilhetes -- DENTRO de uma execucao. O
`publicados` do portfolio nascia vazio a cada chamada, e o pipeline isentava
`picks_multiplas` do cruzamento de pernas ja' usadas no dia. Junte os dois: a
segunda execucao do mesmo dia via o pool intacto, reescolhia a melhor
combinacao (que continuava sendo a melhor, nada tinha mudado) e gravava o
bilhete de novo no slot seguinte.

O teto por dia nao pegava, o indice unico nao pegava (os slots eram dois de
verdade) e nenhum teste pegava: todos montavam o portfolio de uma vez so'.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.pick_engine_multipla import component, portfolio

from test_multipla_v2_portfolio_2026_09 import _pool, perna


def _assinatura(bilhete):
    return sorted((p["_fixture"]["fixture_id"], p["market_type"], p["value_label"])
                  for p in bilhete["pernas"])


def test_segunda_execucao_do_dia_nao_repete_o_bilhete_da_primeira():
    pernas = [perna(i, odd=1.48, league_id=i) for i in range(1, 9)]
    pool, _, jogos = _pool(pernas)

    primeira = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1)
    assert len(primeira["multiples"]) == 1

    # O pool da segunda execucao e' o MESMO: nada no dia mudou, e era
    # exatamente por isso que a mesma combinacao vencia de novo.
    segunda = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1,
                               publicados_do_dia=primeira["multiples"])
    assert segunda["multiples"], segunda.get("reason")
    assert _assinatura(segunda["multiples"][0]) != _assinatura(primeira["multiples"][0])


def test_perna_ja_publicada_hoje_nao_volta_ao_pool():
    pernas = [perna(i, odd=1.48, league_id=i) for i in range(1, 9)]
    pool, _, jogos = _pool(pernas)
    primeira = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1)
    usadas = {(p["_fixture"]["fixture_id"], p["market_type"], p["value_label"])
              for p in primeira["multiples"][0]["pernas"]}

    segunda = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1,
                               publicados_do_dia=primeira["multiples"])
    for bilhete in segunda["multiples"]:
        for p in bilhete["pernas"]:
            chave = (p["_fixture"]["fixture_id"], p["market_type"], p["value_label"])
            assert chave not in usadas, "perna do bilhete de hoje voltou ao pool"


def test_exposicao_por_jogo_conta_o_dia_e_nao_a_execucao():
    """Tres execucoes seguidas nao podem furar o limite por jogo, que e' o
    que a V1 nem tinha como notar."""
    pernas = [perna(i, odd=1.48, league_id=i) for i in range(1, 13)]
    pool, _, jogos = _pool(pernas)

    dia = []
    for _ in range(3):
        rodada = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1,
                                  publicados_do_dia=dia)
        dia.extend(rodada["multiples"])

    contagem = {}
    for bilhete in dia:
        for j in {component.jogo(p) for p in bilhete["pernas"]}:
            contagem[j] = contagem.get(j, 0) + 1
    assert contagem, "o dia nao publicou nada, o teste passaria vazio"
    from services.pick_engine_multipla import config as mcfg
    assert all(v <= mcfg.LIMITE_DE_EXPOSICAO_POR_JOGO for v in contagem.values())


def test_o_id_do_bilhete_continua_a_numeracao_do_dia():
    pernas = [perna(i, odd=1.48, league_id=i) for i in range(1, 9)]
    pool, _, jogos = _pool(pernas)
    primeira = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1)
    segunda = portfolio.montar(pool, jogos_elegiveis=jogos, vagas=1,
                               publicados_do_dia=primeira["multiples"])
    assert primeira["multiples"][0]["id"] == "MULTIPLA_1"
    assert segunda["multiples"][0]["id"] == "MULTIPLA_2"
