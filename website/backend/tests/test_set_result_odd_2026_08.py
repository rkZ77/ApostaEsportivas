"""Alterar resultado no /admin funciona nos SEIS tipos de pick (16/08).

Marcar RED numa alavancagem pelo painel devolvia erro em qualquer ambiente. A
causa nao tinha nada a ver com alavancagem: `/picks/set-result` fazia
`SELECT odd FROM {tabela}` com o nome da coluna cravado, e `odd` nao existe em
todas as tabelas -- alavancagem guarda `odd_combined` e multipla guarda
`total_odd`. O Postgres respondia "column odd does not exist" e a rota estourava
500 antes de escrever qualquer coisa.

O mapeamento certo ja existia no arquivo, escrito inline dentro de
`/picks/search`. Duas copias da mesma regra e' o padrao de bug que este projeto
ja documentou varias vezes (ver market_form.escopo_do_mercado); agora e uma
constante so.

Nada aqui abre conexao: o conftest ja bloqueia get_connection.
"""
import inspect

import pytest

from routers.admin import _ODD_COL, _PICK_TABLES, admin_set_pick_result


def test_todo_tipo_de_pick_tem_coluna_de_odd_declarada():
    """Se um pipeline novo entrar em _PICK_TABLES e esquecer daqui, a rota
    volta a estourar KeyError -- e so' pra aquele tipo, que e' o jeito mais
    facil de nao perceber."""
    assert set(_ODD_COL) == set(_PICK_TABLES), (
        f"faltando em _ODD_COL: {set(_PICK_TABLES) - set(_ODD_COL)}"
    )


@pytest.mark.parametrize("tipo,coluna", [
    ("vip", "odd"), ("free", "odd"), ("faltas", "odd"), ("goleiros", "odd"),
    ("multipla", "total_odd"), ("alavancagem", "odd_combined"),
])
def test_coluna_de_odd_de_cada_tabela(tipo, coluna):
    """Os nomes vem do DDL de cada pipeline · nao sao intercambiaveis."""
    assert _ODD_COL[tipo] == coluna


def test_rota_nao_crava_mais_o_nome_da_coluna():
    """A forma exata do bug. Se voltar, volta assim."""
    src = inspect.getsource(admin_set_pick_result)
    assert "SELECT odd FROM" not in src, "voltou o nome de coluna cravado"
    assert "_ODD_COL[" in src


def test_red_nao_depende_da_odd():
    """RED e PUSH sao -1u e 0u por definicao, entao eles tem que funcionar mesmo
    quando a odd vem nula. Era a operacao que o usuario estava tentando fazer."""
    src = inspect.getsource(admin_set_pick_result)
    # GREEN e HALF-WIN precisam da odd (o valor depende dela) e por isso estao
    # guardados por `and odd`; RED, PUSH e HALF-LOSS nao podem estar.
    assert 'body.result == "RED"' in src
    i_red = src.index('body.result == "RED"')
    linha_red = src[i_red:src.index("\n", i_red)]
    assert "and odd" not in linha_red, "RED nao pode depender da odd"
