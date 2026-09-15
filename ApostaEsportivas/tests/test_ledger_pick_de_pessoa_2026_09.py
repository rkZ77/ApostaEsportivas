"""O ledger recalculava pick de JOGADOR com a folha da PARTIDA.

`_resolve_leg_result` liquida a perna por conta própria, e isso existe por um
motivo bom: em múltipla e alavancagem o `result` da origem é da aposta inteira,
não da perna. Em pick individual esse motivo não existe -- e no de jogador o
recálculo é pior que inútil, porque o contador da pessoa (chutes do Neymar)
mora em `player_match_stats` e o checker só sabe ler `match_statistics`.

"Neymar, 1 ou mais chutes no alvo" avaliado contra os chutes no alvo do JOGO
dá GREEN quase sempre. Medido em PROD em 15/09/2026: das 22 pernas de
player_stats no ledger, 22 estavam GREEN, e o painel do /admin mostrava 100% de
acerto num produto que na origem fazia 10 GREEN contra 7 RED. Três delas eram
picks ANULADOS por escalação -- o jogador não entrou em campo e o ledger
contava acerto.
"""
from services import picks_ledger_sync_service as ledger


def perna(tabela, resultado, odd=1.91):
    return {"source_table": tabela, "result": resultado, "odd": odd,
            "fixture_id": 1, "market": "Player Shots On Target",
            "line": "Neymar - 1 ou mais chutes no alvo"}


def test_o_red_da_origem_continua_red():
    assert ledger._resolve_leg_result(None, None,
                                       perna("picks_player_stats", "RED")) == ("RED", -1.0)


def test_o_green_paga_a_odd():
    resultado, lucro = ledger._resolve_leg_result(
        None, None, perna("picks_player_stats", "GREEN"))
    assert resultado == "GREEN"
    assert round(lucro, 2) == 0.91


def test_pick_anulado_devolve_a_entrada_e_nao_vira_acerto():
    """O caso das três divergências: jogador fora da escalação."""
    assert ledger._resolve_leg_result(None, None,
                                       perna("picks_player_stats", "PUSH", 1.5)) == ("PUSH", 0.0)


def test_goleiro_entra_pela_mesma_porta():
    assert ledger._resolve_leg_result(None, None,
                                       perna("picks_goleiros", "RED", 2.0)) == ("RED", -1.0)


def test_pendente_na_origem_segue_pendente():
    assert ledger._resolve_leg_result(None, None,
                                       perna("picks_player_stats", None)) == (None, None)


def test_pick_de_partida_nao_passa_por_aqui():
    """A regra é só das tabelas de pessoa: o VIP continua sendo recalculado,
    que é o comportamento que sustenta múltipla e alavancagem."""
    assert "picks_vip" not in ledger._TABELAS_DE_JOGADOR
    assert "picks_multiplas" not in ledger._TABELAS_DE_JOGADOR
    # Sem fixture_id/market o caminho de recálculo devolve (None, None) em vez
    # de copiar o resultado da origem.
    assert ledger._resolve_leg_result(
        None, None, {"source_table": "picks_vip", "result": "GREEN", "odd": 2.0}) == (None, None)
