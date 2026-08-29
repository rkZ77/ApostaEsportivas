"""Chute NO ALVO nao pode ser liquidado como chute TOTAL.

REGRESSAO REAL, medida em PROD (2026-08-29). "Finalizações no Gol Mais/Menos" e'
como a casa escreve chute NO ALVO em portugues. Nenhuma chave do classificador
pegava esse nome, e ele caia na regra generica de `shots` -- por conter
"finaliza" -- sendo liquidado contra o TOTAL de chutes.

As duas familias tem uma ordem de grandeza de diferenca: ~8,5 chutes no alvo
por jogo contra ~25 chutes totais. Toda linha Under estourava por construcao.

O estrago: 13 RED em 18 picks desse mercado (-11,26u). Conferindo pick a pick
contra `match_statistics`, NOVE deles tinham ganhado -- Goias x Juventude
(fixture 1520825) e' o caso limpo: Under 8.5 com 7 chutes no alvo e 25 chutes
totais, marcado RED.

O `market_type` gravado no pick estava CERTO nos 18. O bug nao era falta de
dado, era ordem de precedencia.
"""
import routers.live as rl


#: A folha do fixture 1520825 (Goias x Juventude, 18/08/2026), o caso que
#: expos o bug: 7 no alvo, 25 totais, e uma linha Under 8.5.
FOLHA_CASA = {"Shots on Goal": 4, "Total Shots": 12}
FOLHA_FORA = {"Shots on Goal": 3, "Total Shots": 13}

NO_ALVO = 7.0
TOTAIS = 25.0


def _valor(market, market_type=None):
    valor, label, _ = rl._stat_for_market(
        market, "Under 8.5", FOLHA_CASA, FOLHA_FORA, 1, 0, market_type=market_type)
    return valor, label


def test_finalizacoes_no_gol_e_chute_no_alvo():
    """O nome em PT, com o market_type gravado -- o caso dos 18 picks."""
    valor, label = _valor("Finalizações no Gol Mais/Menos", "shots_on_target")
    assert valor == NO_ALVO
    assert label == "Chutes no Alvo"


def test_finalizacoes_no_gol_sem_market_type():
    """Sem market_type gravado o texto tem que decidir sozinho, e decidir certo.

    E' o caminho de pick antigo e de qualquer pick que chegue sem a coluna
    estruturada -- foi exatamente por aqui que o erro entrou.
    """
    valor, label = _valor("Finalizações no Gol Mais/Menos")
    assert valor == NO_ALVO
    assert label == "Chutes no Alvo"


def test_finalizacoes_sem_gol_continua_sendo_chute_total():
    """O outro lado do par nao pode ser arrastado junto.

    "Finalizações Mais/Menos" (sem "no Gol") E' chute total, e uma correcao
    que puxasse os dois pra "no alvo" so' trocaria a direcao do mesmo erro.
    """
    for mtype in ("shots", None):
        valor, label = _valor("Finalizações Mais/Menos", mtype)
        assert valor == TOTAIS, mtype
        assert label == "Chutes"


def test_o_under_que_dava_red_agora_da_green():
    """O veredito, nao so' o valor · 7 chutes no alvo passam sob a linha 8.5."""
    res = rl._calc_result(
        "Finalizações no Gol Mais/Menos", "Under 8.5",
        NO_ALVO, 1, 0, market_type="shots_on_target",
        home_team="Goias", away_team="Juventude",
        home_stats=FOLHA_CASA, away_stats=FOLHA_FORA,
    )
    assert res == "GREEN"

    # E o mesmo jogo contra o total de chutes seguiria RED · e' a prova de que
    # a diferenca entre GREEN e RED era so' a familia escolhida.
    assert rl._calc_result(
        "Finalizações Mais/Menos", "Under 8.5",
        TOTAIS, 1, 0, market_type="shots",
        home_team="Goias", away_team="Juventude",
        home_stats=FOLHA_CASA, away_stats=FOLHA_FORA,
    ) == "RED"


def test_nomes_em_ingles_seguem_separados():
    assert _valor("Total ShotOnGoal")[0] == NO_ALVO
    assert _valor("Total Shots")[0] == TOTAIS
