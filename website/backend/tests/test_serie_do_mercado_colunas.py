"""`_COLUNAS_DA_SERIE` e `market_form._ADAPTADOR` são o mesmo contrato em dois
lugares · e faltar em qualquer um dos dois some com a seção sem erro nenhum.

`folha_do_jogo` só copia as chaves que o adaptador conhece, e só consegue copiar
o que a consulta trouxe. Se a coluna não vem no SELECT, `_stat_side` devolve None
para todo jogo, nenhuma barra resolve, `_series_da_perna` devolve None e "Como
esse mercado vem se comportando" simplesmente não aparece. Nada quebra, nada é
logado.

Caso real (17/08/2026): pick free Internacional x Remo, "Total Shots Over 26.5".
`Total Shots` e `Offsides` tinham sido adicionados ao `_ADAPTADOR` justamente
para fechar esse buraco, mas as colunas nunca entraram no SELECT · a correção
ficou pela metade e o sintoma continuou idêntico. O motor não sofria do mesmo
(lê por MatchStatsService, lista própria), então calculava taxa de 60,4% em 15
jogos enquanto o card não achava um único jogo.
"""
import re

import market_form
from routers.suggestions import _COLUNAS_DA_SERIE


def _colunas_selecionadas() -> set:
    """Nomes de coluna do SELECT, sem o alias da tabela."""
    return {
        m.group(1)
        for m in re.finditer(r"ms\.(\w+)", _COLUNAS_DA_SERIE)
    }


def test_toda_familia_do_adaptador_tem_coluna_no_select():
    """A trava principal, escrita pela CAUSA e não pelos nomes de hoje:
    registrar família nova no adaptador e esquecer do SELECT reintroduz o bug."""
    selecionadas = _colunas_selecionadas()
    faltando = []
    for chave, col_casa, col_fora in market_form._ADAPTADOR:
        for coluna in (col_casa, col_fora):
            if coluna not in selecionadas:
                faltando.append(f"{chave} -> {coluna}")
    assert not faltando, (
        "coluna no _ADAPTADOR mas ausente de _COLUNAS_DA_SERIE "
        f"(a seção some em silêncio): {faltando}"
    )


def test_chutes_e_impedimentos_estao_no_select():
    """As duas que estavam faltando de verdade, travadas pelo nome."""
    selecionadas = _colunas_selecionadas()
    for coluna in ("home_total_shots", "away_total_shots",
                   "home_offsides", "away_offsides"):
        assert coluna in selecionadas, f"{coluna} sumiu do SELECT"


def test_o_que_ja_funcionava_continua_no_select():
    selecionadas = _colunas_selecionadas()
    for coluna in ("home_corners", "away_corners",
                   "home_yellow_cards", "away_red_cards",
                   "home_fouls", "away_shots_on",
                   "home_goals", "away_goals"):
        assert coluna in selecionadas


def test_mercado_de_total_soma_os_dois_lados():
    """O que o usuário pediu: a barra de um mercado de TOTAL tem que ser o total
    da partida (casa + fora), não a contribuição de um time só."""
    from routers.live import _stat_side

    casa = {"Total Shots": 16}
    fora = {"Total Shots": 14}
    assert _stat_side(casa, fora, ("Total Shots",), "total") == 30
    assert _stat_side(casa, fora, ("Total Shots",), "home") == 16
    assert _stat_side(casa, fora, ("Total Shots",), "away") == 14


def test_contador_ausente_nunca_vira_zero():
    """Ausência não é zero: um jogo sem o contador tem que sair da série, senão
    a média desce por dado que não existe."""
    from routers.live import _stat_side

    assert _stat_side({}, {"Total Shots": 14}, ("Total Shots",), "total") is None
    assert _stat_side({"Total Shots": 16}, {}, ("Total Shots",), "total") is None


def test_folha_do_jogo_le_chutes_e_impedimentos():
    """Ponta a ponta do adaptador: linha de match_statistics vira folha com as
    chaves que `_stat_for_market` sabe ler."""
    ms = {
        "home_total_shots": 16, "away_total_shots": 14,
        "home_offsides": 2, "away_offsides": 3,
        "home_corners": 5, "away_corners": 4,
    }
    casa, fora = market_form.folha_do_jogo(ms)
    assert casa["Total Shots"] == 16 and fora["Total Shots"] == 14
    assert casa["Offsides"] == 2 and fora["Offsides"] == 3


def test_coluna_nula_nao_entra_na_folha():
    casa, fora = market_form.folha_do_jogo(
        {"home_total_shots": None, "away_total_shots": None})
    assert "Total Shots" not in casa and "Total Shots" not in fora
