"""Faltas e goleiros nao passam pelo ranking generico (pipeline proprio, ver a
docstring de cada um), entao herdaram EDGE_MIN e ficaram sem piso de
probabilidade -- assimetria de arquitetura, nao decisao.

O custo apareceu em 2026-08-08: picks_goleiros gerou "Everson - 6 ou mais
defesas" a odd 11.00 com probabilidade de 15.4%. Passou no EDGE_MIN pela pura
aritmetica (0.154 * 11.00 - 1 = +0.69), num pick que perde 6 vezes a cada 7.
Em faltas o mesmo buraco ja estava escrito no proprio codigo: com a tabela
comecando em 0.26, qualquer odd a partir de ~4.00 passava sozinha.

ONDE O PISO DE DEFESAS MORA HOJE (2026-08-28): o goleiros_pipeline foi apagado
e defesas virou o metodo `saves` do Player Stats, entao o piso que este arquivo
protege passou a ser `player_stats_engine/config.PROB_MINIMA`. As assercoes
mudaram de endereco, e nao de exigencia -- o caso do Everson continua sendo o
que elas travam.
"""
from engine_pipelines import faltas_pipeline, player_stats_pipeline
from services.pick_engine.config import DEFAULT_CONFIG
from services.player_stats_engine import config as ps_cfg


def test_os_dois_pipelines_usam_o_MESMO_piso_do_resto_do_motor():
    """Nao e' um numero novo: e' o min_taxa que ranking.py ja aplica em VIP,
    free, multipla e alavancagem. Redigitar aqui abriria espaco pros dois
    valores divergirem em silencio."""
    assert faltas_pipeline.PROB_MIN == DEFAULT_CONFIG.min_taxa
    # Player Stats pode ser MAIS duro que a casa (hoje 0.62 contra 0.60) porque
    # prop de jogador tem amostra menor · o que ele nao pode e' ficar abaixo.
    assert ps_cfg.PROB_MINIMA >= DEFAULT_CONFIG.min_taxa


def test_piso_corta_a_cauda_que_o_edge_sozinho_aprovava():
    """Os dois casos reais que motivaram o piso, um de cada pipeline."""
    everson_6_defesas = 0.1539      # odd 11.00, edge +0.69
    faixa_mais_fraca_de_faltas = 0.26   # odd 4.00, edge +0.04
    assert everson_6_defesas < ps_cfg.PROB_MINIMA
    assert faixa_mais_fraca_de_faltas < faltas_pipeline.PROB_MIN


def test_edge_continua_valendo_junto_com_o_piso():
    """Piso nao substitui margem: probabilidade alta com odd ruim tambem nao e'
    pick. Os dois cortes tem que sobreviver lado a lado."""
    assert ps_cfg.EDGE_MINIMO > 0
    assert faltas_pipeline.EDGE_MIN > 0


def test_piso_e_checado_antes_do_edge_nos_dois():
    """Ordem importa so' pra leitura do codigo (o resultado e' o mesmo), mas
    checar probabilidade primeiro deixa o motivo do descarte obvio pra quem
    for depurar: 'nao tinha chance', nao 'nao tinha margem'."""
    import inspect
    fonte = inspect.getsource(faltas_pipeline)
    assert (fonte.index('probability", 0) < PROB_MIN')
            < fonte.index('edge", 0) < EDGE_MIN')), "faltas: piso antes do edge"

    # No Player Stats os dois cortes vivem em `_aprovado`, e a ordem e' a
    # mesma pela mesma razao.
    aprovado = inspect.getsource(player_stats_pipeline._aprovado)
    assert (aprovado.index("cfg.PROB_MINIMA")
            < aprovado.index("cfg.EDGE_MINIMO")), "saves: piso antes do edge"
