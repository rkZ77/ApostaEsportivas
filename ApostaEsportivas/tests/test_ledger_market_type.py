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
