# -*- coding: utf-8 -*-
"""O mapeamento do coletor de jogador, que nunca foi conferido (2026-08-28).

O cabecalho de `player_stats_collector_service` avisa em MAIUSCULAS desde
01/08: os nomes de campo vieram da documentacao, nao de uma resposta real,
porque a cota do dia ja' tinha estourado quando ele foi escrito. "Confirmar na
primeira execucao antes de confiar nos numeros", diz a nota. Meses depois, nada
tinha confirmado -- e o Player Stats inteiro, mais a aba de Jogadores do
/admin, foram construidos em cima disso.

POR QUE A FALHA E' MUDA

`_num()` devolve None em vez de estourar quando o campo nao existe. Isso protege
a execucao (e por isso fica), mas transforma "a API renomeou o grupo" em coluna
NULL silenciosa. O motor le' aquilo como "o provedor nao publicou" e nao gera
pick -- indistinguivel de um dia sem oportunidade.

O QUE ESTES TESTES FAZEM, E O QUE ELES NAO PODEM FAZER

Nao dao pra confirmar o mapeamento sozinhos: so' uma resposta real da API
confirma, e isso e' uma requisicao. O que eles garantem e' que a FERRAMENTA de
conferencia funciona, e que a ordem do mapa nao pode divergir do INSERT em
silencio -- que era a outra metade do risco.
"""
import re

import pytest

from collectors import player_stats_collector_service as col


#: Resposta como a documentacao da API-Football descreve o bloco `statistics`.
RESPOSTA_DOC = {
    "games": {"minutes": 90, "position": "M", "rating": "7.2", "substitute": False},
    "shots": {"total": 3, "on": 1},
    "goals": {"total": 0, "conceded": 0, "assists": None, "saves": None},
    "passes": {"total": 40, "key": 2, "accuracy": "85"},
    "tackles": {"total": 2, "blocks": 0, "interceptions": 1},
    "duels": {"total": 10, "won": 6},
    "dribbles": {"attempts": 3, "success": 1, "past": None},
    "fouls": {"drawn": 2, "committed": 1},
    "cards": {"yellow": 1, "red": 0},
}


# ── a ferramenta ─────────────────────────────────────────────────────────
def test_a_resposta_da_documentacao_bate_com_o_mapa():
    """E' o unico "confere" que da' pra fazer sem gastar requisicao: a forma
    que o coletor foi escrito pra ler continua sendo a que ele le'."""
    laudo = col.conferir_mapeamento(RESPOSTA_DOC)

    assert laudo["ausentes"] == []
    assert len(laudo["ok"]) == len(col.MAPA_DE_CAMPOS)


def test_campo_renomeado_pela_api_e_APONTADO_e_nao_engolido():
    """O cenario que a nota do arquivo teme · antes ele virava NULL calado."""
    resposta = {**RESPOSTA_DOC, "shots": {"totalShots": 3, "onTarget": 1}}

    laudo = col.conferir_mapeamento(resposta)

    assert any("shots_total" in linha for linha in laudo["ausentes"])
    assert any("shots_on" in linha for linha in laudo["ausentes"])


def test_grupo_inteiro_removido_aparece_todo():
    resposta = {k: v for k, v in RESPOSTA_DOC.items() if k != "cards"}

    laudo = col.conferir_mapeamento(resposta)

    assert sorted(l.split(" <- ")[0] for l in laudo["ausentes"]) == \
        ["cards_red", "cards_yellow"]


def test_o_que_a_api_manda_e_ninguem_le_tambem_aparece():
    """Nao e' defeito · e' o mapa do que ainda da' pra extrair sem recoletar
    (a coluna `raw` guarda o bloco inteiro)."""
    laudo = col.conferir_mapeamento(RESPOSTA_DOC)

    assert "passes.accuracy" in laudo["ignorados"]
    assert "dribbles.past" in laudo["ignorados"]


def test_bloco_vazio_nao_e_mapeamento_quebrado():
    """Jogador que nao entrou vem com o bloco vazio · conferir contra ele daria
    19 ausentes e um alarme falso."""
    laudo = col.conferir_mapeamento({})

    assert laudo["vazia"] is True


def test_o_shape_nao_gasta_a_conferencia_num_bloco_vazio():
    """Ele roda UMA vez por execucao · se o primeiro jogador da lista for um
    reserva que nao entrou, a conferencia era desperdicada nele."""
    servico = col.PlayerStatsCollectorService()

    servico._mostrar_shape({})
    assert servico._ja_mostrou_shape is False

    servico._mostrar_shape(RESPOSTA_DOC)
    assert servico._ja_mostrou_shape is True


# ── a ordem, que e' a outra metade do risco ──────────────────────────────
def test_a_ordem_do_mapa_e_a_ordem_das_colunas_do_insert():
    """A tupla do INSERT e' POSICIONAL. Uma coluna fora de ordem grava chute no
    campo de falta, e nada estoura -- os dois sao inteiro pequeno.

    Ate' 28/08 as duas listas eram escritas na mao, em lugares diferentes do
    arquivo, e nada as ligava. Agora a linha e' montada a partir do mapa, e este
    teste garante que o mapa esta' na ordem do INSERT.
    """
    fonte = open(col.__file__, encoding="utf-8").read()

    bloco = fonte[fonte.index("INSERT INTO player_match_stats"):]
    bloco = bloco[bloco.index("(") + 1:bloco.index(") VALUES")]
    colunas_do_insert = [c.strip() for c in re.split(r",\s*", bloco) if c.strip()]

    # As colunas de identificacao vem antes das estatisticas, e `raw` depois.
    esperado = [coluna for coluna, _caminho in col.MAPA_DE_CAMPOS]
    inicio = colunas_do_insert.index(esperado[0])

    assert colunas_do_insert[inicio:inicio + len(esperado)] == esperado, \
        "MAPA_DE_CAMPOS saiu da ordem do INSERT · a tupla e' posicional"


def test_o_mapa_cobre_as_colunas_de_estatistica_e_nada_mais():
    """Coluna de estatistica que ficasse fora do mapa deixaria de ser gravada,
    e o INSERT quebraria por contagem -- mas so' em producao, na primeira
    fixture."""
    colunas = [c for c, _ in col.MAPA_DE_CAMPOS]

    assert len(colunas) == len(set(colunas)), "coluna repetida no mapa"
    assert "saves" in colunas, "defesas e' o metodo medido do Player Stats"
    assert "shots_on" in colunas
    assert "fouls_committed" in colunas
