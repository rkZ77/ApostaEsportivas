"""O ledger nao pode liquidar com menos informacao do que o pick carrega.

`picks_ledger` nao copia o `result` das tabelas de origem: ele RECALCULA o
resultado de cada perna, o que e' proposital -- multipla e alavancagem guardam
so' o resultado COMBINADO, e o ledger precisa da perna isolada.

O que estava errado era o recalculo usar apenas o NOME do mercado, que e' texto
da casa de aposta e e' ambiguo, ignorando o `market_type` que a propria perna
carrega e que segue inteiro pro INSERT duas linhas adiante.

O preco disso apareceu em PROD: "Finalizações no Gol Mais/Menos" e' chute NO
ALVO, mas contem "finaliza" e o classificador por texto o mandava pra chutes
TOTAIS -- ~28 por jogo contra ~8 no alvo. As tabelas de origem estavam CERTAS
(o caminho ao vivo sempre olhou o market_type primeiro) e o ledger discordava
delas em 79 linhas, 13 mostrando RED num pick que tinha ganhado. E o ledger e'
justamente o que alimenta a pagina publica de resultados.
"""
import inspect

from services import picks_ledger_sync_service as ledger


def test_resolve_leg_result_passa_o_market_type():
    """Trava o argumento, nao o comportamento.

    Um teste de comportamento aqui exigiria banco: `_resolve_leg_result` busca
    a folha antes de liquidar. O que precisa ser travado e' mais simples e mais
    duravel -- que a chamada leve a coluna estruturada.
    """
    fonte = inspect.getsource(ledger._resolve_leg_result)
    assert "evaluate_pick" in fonte
    assert "market_type=leg.get(\"market_type\")" in fonte


def test_a_perna_grava_o_mesmo_market_type_que_usou_pra_liquidar():
    """Liquidar por uma familia e gravar outra deixaria o ledger incoerente
    consigo mesmo · o relatorio por mercado somaria pick liquidado como chute
    total na linha de chute no alvo."""
    fonte = inspect.getsource(ledger.sync)
    assert "leg.get(\"market_type\")" in fonte


# ──────────────────────────────────────────────────────────────────────────
# COBERTURA DE PRODUTOS (2026-08-29)
# ──────────────────────────────────────────────────────────────────────────
#
# O ledger e' o unico lugar que responde CLV, atribuicao por liga/arbitro/faixa
# de odd e desempenho por modelo de IA. Player Stats e Pick Boost ficaram FORA
# dele desde que nasceram: liquidavam, entravam na banca do usuario e no placar
# publico, e a auditoria era cega justamente nos dois motores mais novos.
#
# Nao ha' erro quando um produto falta -- a tabela simplesmente nao aparece nas
# consultas, e quem le' o painel conclui que aquele motor nao tem historico.
def test_o_ledger_conhece_toda_tabela_de_pick():
    from services.picks_ledger_sync_service import _PICK_TYPE_BY_TABLE

    esperado = {
        "picks_vip", "picks_free", "picks_multiplas", "picks_alavancagem",
        "picks_faltas", "picks_goleiros", "picks_live",
        "picks_player_stats", "picks_boost",
    }
    assert esperado <= set(_PICK_TYPE_BY_TABLE), esperado - set(_PICK_TYPE_BY_TABLE)


def test_o_extractor_visita_as_tabelas_novas():
    """`fetch_all_legs` so' visita o que esta' escrito nele · tabela ausente da
    lista nao gera perna nenhuma, e o ledger fica sem o produto inteiro."""
    import inspect

    from services import pick_legs_extractor

    corpo = inspect.getsource(pick_legs_extractor.fetch_all_legs)
    for tabela in ("picks_faltas", "picks_goleiros", "picks_live",
                   "picks_player_stats", "picks_boost"):
        assert tabela in corpo, f"{tabela} fora de fetch_all_legs"


def test_picks_boost_entra_apesar_das_colunas_com_sufixo_de_perna():
    """picks_boost nao tem `bet_house` nem `market_id` (tem _ft/_ht, porque e'
    um combinado). O SELECT pedia as duas colunas cruas, levantava "column does
    not exist" e o `except` de fetch_all_legs engolia a tabela INTEIRA."""
    import inspect

    from services import pick_legs_extractor

    corpo = inspect.getsource(pick_legs_extractor.fetch_vip_free_legs)
    assert "bet_house_ft AS bet_house" in corpo
    assert "market_id_ft AS market_id" in corpo
