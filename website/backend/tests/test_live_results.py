"""Liquidacao no caminho AO VIVO (routers/live.py).

Este e' o caminho que gravou o resultado errado do caso que originou a
auditoria: fixture 1546854 (Fortaleza EC 3 x 2 Palmeiras, 05/08/2026), pick
"Escanteios Mais/Menos · Over 9.5" gravado RED com o jogo tendo 10
escanteios. O jogo nem chegou a entrar em `match_statistics`, entao o checker
em lote nunca o viu -- quem gravou foi aqui, a partir de uma resposta de
/fixtures/statistics ainda vazia lida como 0 escanteios.

A matematica em si vive em services/settlement.py e tem bateria propria
(ApostaEsportivas/tests/test_settlement.py). O que se testa aqui e' a ponte:
leitura da folha da API, atribuicao de lado, e a recusa em liquidar sem dado.
"""
import pytest

from routers.live import (
    _calc_result, _multipla_combined_result, _parse_stats, _pick_status,
    _profit_for_result, _stat_for_market,
)


def folha(home_id=10, away_id=20, home=None, away=None):
    """Resposta de /fixtures/statistics no formato cru da API-Football."""
    def bloco(tid, valores):
        return {"team": {"id": tid},
                "statistics": [{"type": k, "value": v} for k, v in (valores or {}).items()]}
    return [bloco(home_id, home), bloco(away_id, away)]


# ─────────────────────────────────────────────────────────────────────────────
# Profit por resultado
# ─────────────────────────────────────────────────────────────────────────────
def test_green_pays_odd_minus_one():
    assert _profit_for_result("GREEN", 2.0) == 1.0
    assert _profit_for_result("GREEN", 1.5) == 0.5


def test_red_loses_full_unit():
    assert _profit_for_result("RED", 2.0) == -1.0


def test_push_breaks_even():
    assert _profit_for_result("PUSH", 1.8) == 0.0


def test_half_win_pays_half_the_odd_gain():
    assert _profit_for_result("HALF-WIN", 2.0) == 0.5


def test_half_loss_loses_half_unit():
    assert _profit_for_result("HALF-LOSS", 2.0) == -0.5


# ─────────────────────────────────────────────────────────────────────────────
# Leitura da folha de estatistica
# ─────────────────────────────────────────────────────────────────────────────
def test_lado_da_folha_vem_do_team_id_e_nao_da_ordem():
    """A API nao garante que o indice 0 seja o mandante. Assumir a ordem
    liquidava todo mercado de um lado so' (Escanteios Casa, handicap) com o
    numero do adversario."""
    raw = folha(home_id=10, away_id=20,
                home={"Corner Kicks": 6}, away={"Corner Kicks": 4})
    invertida = list(reversed(raw))
    h, a = _parse_stats(invertida, home_id=10, away_id=20)
    assert h["Corner Kicks"] == 6
    assert a["Corner Kicks"] == 4


def test_sem_os_ids_cai_na_ordem_da_resposta():
    h, a = _parse_stats(folha(home={"Corner Kicks": 6}, away={"Corner Kicks": 4}))
    assert (h["Corner Kicks"], a["Corner Kicks"]) == (6, 4)


def test_contador_nulo_nao_entra_como_zero():
    """A API manda `null` no contador que ainda nao publicou. Virar 0 e' o que
    produziu o RED do caso Fortaleza x Palmeiras."""
    h, a = _parse_stats(folha(home={"Corner Kicks": None, "Fouls": 12},
                              away={"Corner Kicks": None, "Fouls": 8}))
    assert "Corner Kicks" not in h and "Corner Kicks" not in a
    assert h["Fouls"] == 12


def test_folha_vazia_vira_dicionarios_vazios():
    assert _parse_stats([]) == ({}, {})


def test_percentual_e_convertido():
    h, _ = _parse_stats(folha(home={"Ball Possession": "57%"}, away={}))
    assert h["Ball Possession"] == 57


# ─────────────────────────────────────────────────────────────────────────────
# Valor do mercado: ausencia nunca vira zero
# ─────────────────────────────────────────────────────────────────────────────
def test_escanteios_somam_os_dois_lados():
    h, a = _parse_stats(folha(home={"Corner Kicks": 6}, away={"Corner Kicks": 4}))
    valor, label, _ = _stat_for_market("Escanteios Mais/Menos", "Over 9.5", h, a, 3, 2, "corners")
    assert (valor, label) == (10.0, "Escanteios")


def test_escanteios_sem_folha_devolvem_none_e_nao_zero():
    valor, _, _ = _stat_for_market("Escanteios Mais/Menos", "Over 9.5", {}, {}, 3, 2, "corners")
    assert valor is None


def test_escanteios_com_um_lado_faltando_devolvem_none():
    """Meia folha nao e' folha: somar 6 + (ausente como 0) daria 6 escanteios
    num jogo que teve 10."""
    h, a = _parse_stats(folha(home={"Corner Kicks": 6}, away={}))
    valor, _, _ = _stat_for_market("Escanteios Mais/Menos", "Over 9.5", h, a, 3, 2, "corners")
    assert valor is None


def test_lado_unico_so_precisa_do_proprio_lado():
    h, a = _parse_stats(folha(home={"Corner Kicks": 6}, away={}))
    valor, label, _ = _stat_for_market("Escanteios Casa Mais/Menos", "Over 5.5",
                                       h, a, 3, 2, "corners")
    assert (valor, label) == (6.0, "Escanteios Casa")


def test_cartao_vermelho_vale_dois():
    h, a = _parse_stats(folha(home={"Yellow Cards": 1, "Red Cards": 1},
                              away={"Yellow Cards": 2, "Red Cards": 0}))
    valor, _, _ = _stat_for_market("Cartões Mais/Menos", "Over 4.5", h, a, 3, 2, "cards")
    assert valor == 5.0  # (1 + 2) + (2 + 0)


# ─────────────────────────────────────────────────────────────────────────────
# O caso relatado
# ─────────────────────────────────────────────────────────────────────────────
def test_caso_fortaleza_x_palmeiras_over_9_5_com_10_escanteios():
    h, a = _parse_stats(folha(home_id=154, away_id=121,
                              home={"Corner Kicks": 6}, away={"Corner Kicks": 4}),
                        home_id=154, away_id=121)
    valor, _, _ = _stat_for_market("Escanteios Mais/Menos", "Over 9.5", h, a, 3, 2, "corners")
    assert _calc_result("Escanteios Mais/Menos", "Over 9.5", valor, 3, 2,
                        market_type="corners") == "GREEN"


def test_folha_ainda_nao_publicada_nao_liquida_o_pick():
    """A regressao exata: sem escanteios na resposta da API, o pick fica
    pendente. RED aqui e' uma aposta perdida por um dado que ninguem tinha."""
    valor, _, _ = _stat_for_market("Escanteios Mais/Menos", "Over 9.5", {}, {}, 3, 2, "corners")
    assert _calc_result("Escanteios Mais/Menos", "Over 9.5", valor, 3, 2,
                        market_type="corners") is None


def test_pick_sem_valor_conhecido_aparece_como_indefinido_no_ticker():
    assert _pick_status(None, "Over 9.5") == "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Grade de linhas (mesma do checker em lote · os dois motores tem que bater)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("linha,esperado", [
    ("Over 9",      "GREEN"), ("Over 9.0",   "GREEN"),
    ("Over 9.25",   "GREEN"), ("Over 9.5",   "GREEN"),
    ("Over 9.75",   "HALF-WIN"),
    ("Over 10",     "PUSH"),  ("Over 10.0",  "PUSH"),
    ("Over 10.25",  "HALF-LOSS"),
    ("Over 10.5",   "RED"),   ("Over 10.75", "RED"), ("Over 11", "RED"),
    ("Under 9",     "RED"),   ("Under 9.5",  "RED"),
    ("Under 9.75",  "HALF-LOSS"),
    ("Under 10",    "PUSH"),
    ("Under 10.25", "HALF-WIN"),
    ("Under 10.5",  "GREEN"), ("Under 11",   "GREEN"),
])
def test_grade_de_linhas_com_10_escanteios(linha, esperado):
    assert _calc_result("Escanteios Mais/Menos", linha, 10.0, 3, 2,
                        market_type="corners") == esperado


@pytest.mark.parametrize("linha", ["Mais de 9.5", "Acima de 9.5", "Mais de 9,5", "over 9.50"])
def test_linha_em_portugues_e_com_virgula(linha):
    assert _calc_result("Escanteios Mais/Menos", linha, 10.0, 3, 2,
                        market_type="corners") == "GREEN"


@pytest.mark.parametrize("linha", ["", "linha ilegivel", "9.3"])
def test_linha_ilegivel_nao_vira_red(linha):
    assert _calc_result("Escanteios Mais/Menos", linha, 10.0, 3, 2,
                        market_type="corners") is None


# ─────────────────────────────────────────────────────────────────────────────
# Handicap, resultado e BTTS
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("market,mtype,linha,esperado", [
    ("Handicap Asiático",            "handicap_goals",   "Home -0.5",  "GREEN"),
    ("Handicap Asiático",            "handicap_goals",   "Home -1",    "PUSH"),
    ("Handicap Asiático",            "handicap_goals",   "Home -1.25", "HALF-LOSS"),
    ("Handicap Asiático",            "handicap_goals",   "Home -0.75", "HALF-WIN"),
    ("Handicap Asiático",            "handicap_goals",   "Away +1",    "PUSH"),
])
def test_handicap_de_gols(market, mtype, linha, esperado):
    assert _calc_result(market, linha, None, 3, 2, market_type=mtype) == esperado


def test_handicap_de_escanteios_usa_os_lados_separados():
    h, a = _parse_stats(folha(home={"Corner Kicks": 6}, away={"Corner Kicks": 4}))
    assert _calc_result("Corners Asian Handicap", "Home -0.5", None, 3, 2,
                        market_type="handicap_corners",
                        home_stats=h, away_stats=a) == "GREEN"
    assert _calc_result("Corners Asian Handicap", "Away -5.5", None, 3, 2,
                        market_type="handicap_corners",
                        home_stats=h, away_stats=a) == "RED"


def test_handicap_de_escanteios_sem_folha_nao_liquida():
    assert _calc_result("Corners Asian Handicap", "Home -0.5", None, 3, 2,
                        market_type="handicap_corners",
                        home_stats={}, away_stats={}) is None


@pytest.mark.parametrize("linha,casa,fora,esperado", [
    ("Home", 3, 2, "GREEN"), ("Home", 1, 1, "RED"),
    ("X", 1, 1, "GREEN"), ("Draw/Away", 1, 1, "GREEN"), ("Draw/Away", 3, 2, "RED"),
])
def test_resultado_e_dupla_chance(linha, casa, fora, esperado):
    assert _calc_result("Resultado Final (1X2)", linha, None, casa, fora,
                        market_type="result") == esperado


def test_1x2_empatado_com_selecao_de_casa_e_red():
    """'Resultado Final (1X2)' contem '1x'; procurar chave de dupla chance no
    nome do mercado transformava o pick em '1 ou X' e gravava GREEN no empate."""
    assert _calc_result("Resultado Final (1X2)", "Home", None, 1, 1,
                        market_type="result") == "RED"


@pytest.mark.parametrize("linha,casa,fora,esperado", [
    ("Sim", 3, 2, "GREEN"), ("Sim", 3, 0, "RED"),
    ("Não", 3, 0, "GREEN"), ("No", 1, 1, "RED"),
])
def test_btts(linha, casa, fora, esperado):
    assert _calc_result("Ambas as Equipes Marcam", linha, None, casa, fora,
                        market_type="btts") == esperado


# ─────────────────────────────────────────────────────────────────────────────
# Bilhete combinado
# ─────────────────────────────────────────────────────────────────────────────
def test_bilhete_todo_green():
    assert _multipla_combined_result(["GREEN", "GREEN"], [1.2, 1.25], 1.5) == "GREEN"


def test_bilhete_com_perna_red():
    assert _multipla_combined_result(["GREEN", "RED"], [1.2, 1.25], 1.5) == "RED"


def test_bilhete_com_perna_pendente_fica_aberto():
    assert _multipla_combined_result(["GREEN", None], [1.2, 1.25], 1.5) is None


def test_perna_anulada_nao_zera_o_bilhete():
    """A regra antiga devolvia PUSH pro bilhete inteiro em qualquer mistura --
    um GREEN + PUSH virava lucro zero. Uma perna anulada so' sai da conta."""
    assert _multipla_combined_result(["GREEN", "PUSH"], [2.0, 1.5], 3.0) == "GREEN"


def test_bilhete_todo_anulado_e_push():
    assert _multipla_combined_result(["PUSH", "PUSH"], [2.0, 1.5], 3.0) == "PUSH"


def test_mistura_sem_as_odds_das_pernas_nao_arrisca_um_numero():
    assert _multipla_combined_result(["GREEN", "PUSH"]) is None
