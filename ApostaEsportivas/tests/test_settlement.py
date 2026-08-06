"""Liquidacao de pick: a matematica de GREEN/RED/PUSH/HALF-* por mercado.

O caso que originou esta bateria e' real e esta em producao: fixture 1546854
(Fortaleza EC 3 x 2 Palmeiras, 05/08/2026), pick "Escanteios Mais/Menos ·
Over 9.5". O jogo teve 6 + 4 = 10 escanteios e o sistema gravou RED. A
comparacao `10 > 9.5` sempre esteve certa -- o que estava errado era o valor
comparado: a folha de estatistica ainda nao tinha sido publicada pela API e
`home_stats.get("Corner Kicks", 0)` devolveu 0.

Dai as duas familias de teste aqui: a aritmetica de cada linha (inteira,
meia, quarto-de-bola) em cada mercado, e -- igualmente importante -- a
recusa em liquidar quando o numero nao e' conhecido.
"""
from decimal import Decimal

import pytest

from services import settlement as s


# ─────────────────────────────────────────────────────────────────────────────
# O caso relatado, explicitamente
# ─────────────────────────────────────────────────────────────────────────────
def test_over_9_5_escanteios_com_10_escanteios_e_green():
    """Fortaleza EC x Palmeiras: 6 + 4 = 10 escanteios, linha Over 9.5."""
    parsed = s.parse_line("Over 9.5")
    assert parsed["op"] == "over"
    assert parsed["value"] == Decimal("9.5")

    resultado, factor = s.settle_over_under(6 + 4, parsed["value"], parsed["op"])
    assert resultado == "GREEN"
    assert factor == Decimal("1")
    assert s.profit_units(factor, Decimal("1.70")) == Decimal("0.70")


@pytest.mark.parametrize("linha", ["Over 9.5", "over 9.5", "Mais de 9.5",
                                    "Acima de 9.5", "Mais de 9,5", "OVER 9.50"])
def test_over_9_5_em_todas_as_escritas_da_linha(linha):
    """A mesma linha escrita em pt-BR, en, com virgula ou com zero a direita
    tem que dar o mesmo resultado -- 10 escanteios e' GREEN em todas."""
    parsed = s.parse_line(linha)
    assert s.settle_over_under(10, parsed["value"], parsed["op"])[0] == "GREEN"


# ─────────────────────────────────────────────────────────────────────────────
# Grade de linhas: 9 a 11, um quarto de cada vez
# ─────────────────────────────────────────────────────────────────────────────
LINHAS_CRITICAS = ["9", "9.0", "9.25", "9.5", "9.75",
                   "10", "10.0", "10.25", "10.5", "10.75", "11"]


@pytest.mark.parametrize("linha,esperado", [
    # valor observado = 10 em todos os casos
    ("9",     "GREEN"),      # 10 > 9
    ("9.0",   "GREEN"),
    ("9.25",  "GREEN"),      # 10 > 9.5 e 10 > 9.0
    ("9.5",   "GREEN"),      # <- o caso relatado
    ("9.75",  "HALF-WIN"),   # ganha o Over 9.5, devolve o Over 10.0
    ("10",    "PUSH"),       # 10 == 10 -> stake devolvida
    ("10.0",  "PUSH"),
    ("10.25", "HALF-LOSS"),  # devolve o Over 10.0, perde o Over 10.5
    ("10.5",  "RED"),
    ("10.75", "RED"),
    ("11",    "RED"),
])
def test_over_com_valor_10_em_toda_a_grade(linha, esperado):
    parsed = s.parse_line(f"Over {linha}")
    assert s.settle_over_under(10, parsed["value"], parsed["op"])[0] == esperado


@pytest.mark.parametrize("linha,esperado", [
    ("9",     "RED"),        # 10 nao e' menor que 9
    ("9.0",   "RED"),
    ("9.25",  "RED"),
    ("9.5",   "RED"),
    ("9.75",  "HALF-LOSS"),  # devolve o Under 10.0, perde o Under 9.5
    ("10",    "PUSH"),
    ("10.0",  "PUSH"),
    ("10.25", "HALF-WIN"),   # ganha o Under 10.5, devolve o Under 10.0
    ("10.5",  "GREEN"),
    ("10.75", "GREEN"),
    ("11",    "GREEN"),
])
def test_under_com_valor_10_em_toda_a_grade(linha, esperado):
    parsed = s.parse_line(f"Under {linha}")
    assert s.settle_over_under(10, parsed["value"], parsed["op"])[0] == esperado


@pytest.mark.parametrize("linha", LINHAS_CRITICAS)
def test_over_e_under_da_mesma_linha_sao_sempre_opostos(linha):
    """Somados, os fatores de Over X e Under X do mesmo jogo tem que dar zero:
    o que um lado ganha o outro perde, sem sobra nem furo."""
    valor = 10
    ln = s.to_decimal(linha)
    _, f_over = s.settle_over_under(valor, ln, "over")
    _, f_under = s.settle_over_under(valor, ln, "under")
    assert f_over + f_under == Decimal("0")


@pytest.mark.parametrize("valor", range(0, 16))
@pytest.mark.parametrize("linha", LINHAS_CRITICAS)
def test_fator_sempre_num_dos_cinco_valores_validos(linha, valor):
    """Nenhuma combinacao de linha e valor pode produzir um fator fora da
    tabela -- e nenhuma pode devolver None, ja' que a linha e' valida."""
    resultado, factor = s.settle_over_under(valor, s.to_decimal(linha), "over")
    assert resultado in s.RESULT_LABELS
    assert factor in (Decimal("1"), Decimal("0.5"), Decimal("0"),
                      Decimal("-0.5"), Decimal("-1"))


# ─────────────────────────────────────────────────────────────────────────────
# Invariante 1: estatistica ausente nunca vira zero
# ─────────────────────────────────────────────────────────────────────────────
def test_estatistica_ausente_nao_liquida():
    """A regressao exata do caso Fortaleza x Palmeiras: sem o numero de
    escanteios, Over 9.5 NAO pode virar RED."""
    assert s.settle_over_under(None, Decimal("9.5"), "over") == (None, Decimal("0"))


def test_zero_de_verdade_continua_liquidando():
    """Nao se pode confundir 'ausente' com 'zero': um jogo que de fato teve 0
    escanteios perde um Over 9.5 normalmente."""
    assert s.settle_over_under(0, Decimal("9.5"), "over")[0] == "RED"
    assert s.settle_over_under(0, Decimal("9.5"), "under")[0] == "GREEN"


# ─────────────────────────────────────────────────────────────────────────────
# Invariante 2: entrada ilegivel nunca vira RED
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("linha", ["9.3", "9.1", "0.6", "-9.3"])
def test_linha_fora_da_grade_asiatica_nao_liquida(linha):
    assert s.settle_over_under(10, s.to_decimal(linha), "over") == (None, Decimal("0"))


@pytest.mark.parametrize("op", [None, "", "yes", "no", "handicap"])
def test_sem_operador_over_under_nao_liquida(op):
    """Sem 'over'/'under' explicito o mercado nao e' liquidado. A versao
    anterior tratava operador ausente como UNDER (o `else` de cada bloco), e
    era assim que o handicap de cartoes era graduado."""
    assert s.settle_over_under(10, Decimal("9.5"), op) == (None, Decimal("0"))


@pytest.mark.parametrize("linha", ["", None, "Draw/Away", "abc", "Sim"])
def test_linha_sem_numero_nao_liquida_over_under(linha):
    parsed = s.parse_line(linha)
    assert s.settle_over_under(10, parsed["value"], parsed["op"]) == (None, Decimal("0"))


def test_linha_negativa_em_meia_bola_nao_cai_em_red_silencioso():
    """`Decimal("-9.5") % 1` da' -0.5, nunca 0.5: com a classificacao por
    modulo do Decimal, toda linha negativa escapava dos tres blocos e caia no
    `return RED` que fechava a funcao."""
    assert s.line_grid(Decimal("-9.5")) == "half"
    assert s.line_grid(Decimal("-9.25")) == "quarter"
    assert s.line_grid(Decimal("-10")) == "whole"
    resultado, _ = s.settle_over_under(-10, Decimal("-9.5"), "over")
    assert resultado == "RED"  # -10 nao e' maior que -9.5 · decidido, nao acidental


# ─────────────────────────────────────────────────────────────────────────────
# Conversao numerica: virgula, float, Decimal, string
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada,esperado", [
    ("9.5", Decimal("9.5")), ("9,5", Decimal("9.5")), (" 9.5 ", Decimal("9.5")),
    (9.5, Decimal("9.5")), (10, Decimal("10")), (Decimal("9.5"), Decimal("9.5")),
    ("+0.25", Decimal("0.25")), ("-1.5", Decimal("-1.5")), ("9.50", Decimal("9.50")),
])
def test_to_decimal_aceita_todas_as_formas_da_linha(entrada, esperado):
    assert s.to_decimal(entrada) == esperado


@pytest.mark.parametrize("entrada", [None, "", "abc", "over", True, False, [], {}])
def test_to_decimal_recusa_o_que_nao_e_numero(entrada):
    assert s.to_decimal(entrada) is None


def test_virgula_decimal_nao_e_lida_como_dois_numeros():
    """'9,5' tem que virar 9.5 e nao 9: sem a troca de virgula por ponto, a
    varredura de numeros devolveria ['9', '5'] e a linha viraria 9."""
    assert s.parse_line("Mais de 9,5")["value"] == Decimal("9.5")


def test_float_nao_contamina_a_comparacao_de_push():
    """0.1+0.2 != 0.3 em float; a linha entra por str() justamente pra que a
    igualdade que decide PUSH seja exata."""
    assert s.settle_over_under(10, 10.0, "over")[0] == "PUSH"
    assert s.settle_over_under(2, 2.0, "under")[0] == "PUSH"


# ─────────────────────────────────────────────────────────────────────────────
# Handicap asiatico
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("handicap,casa,fora,esperado", [
    # placar 1x1
    ("0",     1, 1, "PUSH"),
    ("+0.25", 1, 1, "HALF-WIN"),    # empata o 0.0, ganha o +0.5
    ("+0.5",  1, 1, "GREEN"),
    ("+0.75", 1, 1, "GREEN"),
    ("-0.25", 1, 1, "HALF-LOSS"),   # empata o 0.0, perde o -0.5
    ("-0.5",  1, 1, "RED"),
    ("-0.75", 1, 1, "RED"),
    ("-1",    1, 1, "RED"),
    # placar 2x1 (casa vence por 1)
    ("-1",    2, 1, "PUSH"),
    ("-0.75", 2, 1, "HALF-WIN"),
    ("-1.25", 2, 1, "HALF-LOSS"),
    ("-1.5",  2, 1, "RED"),
    ("-0.5",  2, 1, "GREEN"),
])
def test_handicap_casa(handicap, casa, fora, esperado):
    assert s.settle_asian_handicap("home", s.to_decimal(handicap), casa, fora)[0] == esperado


@pytest.mark.parametrize("handicap,casa,fora,esperado", [
    ("+0.5",  1, 1, "GREEN"),
    ("0",     1, 1, "PUSH"),
    ("-0.5",  1, 1, "RED"),
    ("+0.25", 1, 1, "HALF-WIN"),
    ("-0.25", 1, 1, "HALF-LOSS"),
    ("+1",    2, 1, "PUSH"),
    ("+1.5",  2, 1, "GREEN"),
])
def test_handicap_fora(handicap, casa, fora, esperado):
    assert s.settle_asian_handicap("away", s.to_decimal(handicap), casa, fora)[0] == esperado


def test_handicap_de_escanteios_usa_os_dois_lados():
    """A funcao e' generica: o chamador decide se passa gols, escanteios ou
    cartoes. Escanteios 6 x 4, linha 'Home -0.5' -> casa cobre por 2."""
    parsed = s.parse_line("Home -0.5")
    assert parsed["side"] == "home"
    assert s.settle_asian_handicap(parsed["side"], parsed["value"], 6, 4)[0] == "GREEN"


def test_handicap_sem_lado_na_linha_nao_liquida():
    """'-0.5' sozinho nao diz de que lado e' a aposta. Chutar o mandante era
    uma aposta cega no resultado do usuario."""
    parsed = s.parse_line("-0.5")
    assert parsed["side"] is None
    assert s.settle_asian_handicap(parsed["side"], parsed["value"], 6, 4) == (None, Decimal("0"))


def test_handicap_sem_estatistica_nao_liquida():
    assert s.settle_asian_handicap("home", Decimal("-0.5"), None, 4) == (None, Decimal("0"))


@pytest.mark.parametrize("texto,lado", [
    ("Home +0.25", "home"), ("Casa -1", "home"), ("Mandante +0.5", "home"),
    ("Away -5.5", "away"), ("Visitante +1", "away"), ("Fora -0.5", "away"),
])
def test_lado_do_handicap_sai_do_texto_da_linha(texto, lado):
    assert s.parse_line(texto)["side"] == lado


# ─────────────────────────────────────────────────────────────────────────────
# Resultado 1X2 / Dupla Chance
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("linha,casa,fora,esperado", [
    ("1", 2, 1, "GREEN"), ("1", 1, 1, "RED"), ("1", 0, 1, "RED"),
    ("X", 1, 1, "GREEN"), ("X", 2, 1, "RED"),
    ("2", 0, 1, "GREEN"), ("2", 1, 1, "RED"),
    ("Home", 2, 1, "GREEN"), ("Casa", 2, 1, "GREEN"),
    ("Away", 0, 1, "GREEN"), ("Visitante", 0, 1, "GREEN"),
    ("Empate", 1, 1, "GREEN"), ("Draw", 1, 1, "GREEN"),
])
def test_resultado_1x2(linha, casa, fora, esperado):
    assert s.settle_outcome(casa, fora, linha)[0] == esperado


@pytest.mark.parametrize("linha,casa,fora,esperado", [
    ("1X", 2, 1, "GREEN"), ("1X", 1, 1, "GREEN"), ("1X", 0, 1, "RED"),
    ("X2", 0, 1, "GREEN"), ("X2", 1, 1, "GREEN"), ("X2", 2, 1, "RED"),
    ("12", 2, 1, "GREEN"), ("12", 0, 1, "GREEN"), ("12", 1, 1, "RED"),
    ("Home/Draw", 1, 1, "GREEN"), ("Draw/Away", 1, 1, "GREEN"),
    ("Draw/Away", 2, 1, "RED"), ("Home/Away", 1, 1, "RED"),
    ("Casa ou Empate", 1, 1, "GREEN"), ("Empate ou Visitante", 0, 1, "GREEN"),
])
def test_dupla_chance(linha, casa, fora, esperado):
    assert s.settle_outcome(casa, fora, linha)[0] == esperado


def test_1x2_nao_e_confundido_com_dupla_chance_pelo_nome_do_mercado():
    """'Resultado Final (1X2)' contem o texto '1x'. Procurar as chaves de
    dupla chance dentro do NOME DO MERCADO transformava todo pick de 1X2 em
    '1 ou X': com a selecao 'Home' e o jogo empatado, o sistema gravava GREEN.
    A selecao sai so' da linha."""
    assert s.settle_outcome(1, 1, "Home")[0] == "RED"
    assert s.settle_outcome(1, 1, "1")[0] == "RED"
    assert s.settle_outcome(1, 1, "2")[0] == "RED"


def test_resultado_pelo_nome_do_time():
    assert s.settle_outcome(2, 1, "Fortaleza EC", "Fortaleza EC", "Palmeiras")[0] == "GREEN"
    assert s.settle_outcome(1, 2, "Fortaleza EC", "Fortaleza EC", "Palmeiras")[0] == "RED"
    assert s.settle_outcome(1, 2, "Palmeiras", "Fortaleza EC", "Palmeiras")[0] == "GREEN"


def test_dupla_chance_pelo_nome_do_time():
    assert s.settle_outcome(1, 1, "Fortaleza EC ou Empate",
                            "Fortaleza EC", "Palmeiras")[0] == "GREEN"
    assert s.settle_outcome(0, 1, "Fortaleza EC ou Empate",
                            "Fortaleza EC", "Palmeiras")[0] == "RED"


@pytest.mark.parametrize("linha", ["", None, "qualquer coisa", "3:0"])
def test_linha_de_resultado_nao_reconhecida_nao_liquida(linha):
    assert s.settle_outcome(2, 1, linha) == (None, Decimal("0"))


# ─────────────────────────────────────────────────────────────────────────────
# BTTS
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("linha,casa,fora,esperado", [
    ("Sim", 1, 1, "GREEN"), ("Sim", 2, 0, "RED"), ("Sim", 0, 0, "RED"),
    ("Yes", 1, 3, "GREEN"),
    ("Nao", 2, 0, "GREEN"), ("Não", 0, 0, "GREEN"), ("No", 1, 1, "RED"),
])
def test_btts(linha, casa, fora, esperado):
    op = s.parse_line(linha)["op"]
    assert s.settle_btts(casa, fora, op)[0] == esperado


@pytest.mark.parametrize("linha", ["", None, "Over 2.5", "talvez"])
def test_btts_com_linha_nao_reconhecida_nao_liquida(linha):
    op = s.parse_line(linha)["op"]
    assert s.settle_btts(1, 1, op) == (None, Decimal("0"))


# ─────────────────────────────────────────────────────────────────────────────
# Dinheiro
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("factor,odd,esperado", [
    (Decimal("1"),    "2.00", Decimal("1.00")),
    (Decimal("1"),    "1.70", Decimal("0.70")),
    (Decimal("0.5"),  "2.00", Decimal("0.50")),
    (Decimal("0"),    "2.00", Decimal("0")),
    (Decimal("-0.5"), "2.00", Decimal("-0.5")),
    (Decimal("-1"),   "2.00", Decimal("-1")),
])
def test_profit_por_unidade(factor, odd, esperado):
    assert s.profit_units(factor, odd) == esperado


def test_profit_recusa_entrada_invalida_em_vez_de_devolver_perda():
    """None nao e' -1: um fator ilegivel nao e' uma aposta perdida."""
    assert s.profit_units(None, "2.0") is None
    assert s.profit_units(Decimal("1"), "abc") is None


@pytest.mark.parametrize("resultado,odd,esperado", [
    ("GREEN",     "2.00", Decimal("2.00")),
    ("PUSH",      "2.00", Decimal("1")),
    ("RED",       "2.00", Decimal("0")),
    ("HALF-WIN",  "3.00", Decimal("2.00")),   # (1 + 3) / 2
    ("HALF-LOSS", "3.00", Decimal("0.5")),
])
def test_retorno_da_perna(resultado, odd, esperado):
    assert s.leg_payout_factor(resultado, odd) == esperado


# ─────────────────────────────────────────────────────────────────────────────
# Bilhete combinado (multipla / alavancagem)
# ─────────────────────────────────────────────────────────────────────────────
def test_multipla_toda_green_paga_a_odd_publicada():
    label, profit, odd = s.combine_legs(["GREEN", "GREEN"], ["1.20", "1.25"], "1.50")
    assert (label, profit, odd) == ("GREEN", Decimal("0.50"), Decimal("1.50"))


def test_multipla_com_uma_perna_red_e_red():
    label, profit, _ = s.combine_legs(["GREEN", "RED"], ["1.20", "1.25"], "1.50")
    assert (label, profit) == ("RED", Decimal("-1"))


def test_perna_anulada_nao_derruba_o_bilhete():
    """PUSH numa perna significa stake devolvida NAQUELA perna: o bilhete
    segue vivo com a odd recalculada. O checker em lote convertia PUSH em RED
    (matava o bilhete) e o caminho ao vivo devolvia PUSH do bilhete inteiro
    (zerava o lucro) -- os dois erravam, em direcoes opostas."""
    label, profit, odd = s.combine_legs(["GREEN", "PUSH"], ["2.00", "1.50"], "3.00")
    assert label == "GREEN"
    assert odd == Decimal("2.00")     # 3.00 / 1.50 -> so' a perna que valeu
    assert profit == Decimal("1.00")


def test_bilhete_com_todas_as_pernas_anuladas_e_push():
    label, profit, odd = s.combine_legs(["PUSH", "PUSH"], ["2.00", "1.50"], "3.00")
    assert (label, profit, odd) == ("PUSH", Decimal("0"), Decimal("1"))


def test_meia_perna_ganha_ajusta_o_bilhete():
    label, profit, odd = s.combine_legs(["GREEN", "HALF-WIN"], ["2.00", "3.00"], "6.00")
    assert odd == Decimal("4.00")     # 6.00 * ((1+3)/2) / 3
    assert (label, profit) == ("GREEN", Decimal("3.00"))


def test_meia_perna_perdida_pode_deixar_o_bilhete_no_prejuizo():
    """Duas meias-pernas perdidas a 2.00 num bilhete de 4.00: so' o quarto de
    stake em que as DUAS anulam sobrevive, e ele volta pela odd base de 1.00
    (4.00 / 2 / 2). Retorno 0.25, prejuizo de 0.75 -- nao e' um PUSH."""
    label, profit, odd = s.combine_legs(["HALF-LOSS", "HALF-LOSS"], ["2.00", "2.00"], "4.00")
    assert odd == Decimal("0.25")
    assert (label, profit) == ("RED", Decimal("-0.75"))


def test_uma_meia_perna_perdida_com_o_resto_anulado_perde_meia_stake():
    label, profit, odd = s.combine_legs(["HALF-LOSS", "PUSH"], ["2.00", "2.00"], "4.00")
    assert odd == Decimal("0.5")
    assert (label, profit) == ("HALF-LOSS", Decimal("-0.5"))


def test_bilhete_com_perna_pendente_continua_aberto():
    assert s.combine_legs(["GREEN", None], ["1.20", "1.25"], "1.50") == (None, None, None)


def test_bilhete_sem_odd_publicada_usa_o_produto_das_pernas():
    label, profit, odd = s.combine_legs(["GREEN", "GREEN"], ["2.00", "1.50"], None)
    assert (label, odd) == ("GREEN", Decimal("3.00"))
    assert profit == Decimal("2.00")


def test_bilhete_com_rotulo_de_perna_invalido_nao_liquida():
    assert s.combine_legs(["GREEN", "TALVEZ"], ["2.00", "1.50"], "3.00") == (None, None, None)
