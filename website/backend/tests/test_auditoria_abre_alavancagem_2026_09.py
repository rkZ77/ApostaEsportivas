"""A aba de auditoria passa a ABRIR a alavancagem (2026-09-11).

A aba de RED existe pra responder uma pergunta: por que o motor escolheu um
pick que perdeu. A alavancagem estava na lista de RED (`_TABELAS_COM_RESULTADO`)
e fora da lista de explicáveis (`_TABELAS_EXPLICAVEIS`) -- a tela mostrava o
prejuízo e o botão "por quê" devolvia 400. Era o inverso do propósito da aba, e
justamente no produto que mais dá RED em bilhete.

O que faltava não era a rota, era o DADO: a alavancagem não gravava
`engine_debug`. Com a V2 ela grava o documento de decisão do bilhete inteiro
(pernas, correlação par a par, descontos aplicados um a um, veredito de cada
gate), então a rota passa a ter o que abrir.

O segundo obstáculo era de esquema. A alavancagem é um BILHETE: as colunas dela
são `market_1`/`odd_1` por perna e `odd_combined` no total, enquanto todas as
outras tabelas têm `market`/`odd` no singular. A consulta do detalhe era uma
só, chapada, e teria quebrado na primeira tentativa.
"""
import os
import re

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _admin() -> str:
    with open(os.path.join(_BACKEND, "routers", "admin.py"), encoding="utf-8") as f:
        return f.read()


def _bloco(fonte: str, nome: str) -> str:
    """O corpo de um dicionário de módulo, do `{` até o `}` da coluna 0."""
    inicio = fonte.index(f"{nome} = {{")
    fim = fonte.index("\n}", inicio)
    return fonte[inicio:fim]


def test_alavancagem_esta_entre_as_tabelas_explicaveis():
    """O elo que faltava: ela era listada como RED e recusada no detalhe."""
    assert '"picks_alavancagem"' in _bloco(_admin(), "_TABELAS_EXPLICAVEIS")


def test_toda_tabela_de_red_com_engine_debug_e_explicavel():
    """A REGRA, e não o caso.

    Um produto que aparece na aba de RED e não abre é uma tela que cobra sem
    responder. Múltipla e bingo ficam de fora por enquanto porque ainda não
    gravam `engine_debug` -- quando gravarem, este teste é o lembrete de que a
    lista de explicáveis tem que crescer junto.
    """
    fonte = _admin()
    reds = set(re.findall(r'"(picks_\w+)"', _bloco(fonte, "_TABELAS_COM_RESULTADO")))
    explicaveis = set(re.findall(r'"(picks_\w+)"', _bloco(fonte, "_TABELAS_EXPLICAVEIS")))
    pendentes = reds - explicaveis
    assert pendentes <= {"picks_multiplas", "picks_bingo"}, (
        f"{pendentes} aparece(m) na aba de RED e não abre(m) no detalhe")


def test_o_detalhe_tem_consulta_propria_para_o_bilhete():
    """`market`/`odd` no singular não existem em `picks_alavancagem`: sem o
    mapa de colunas, abrir um bilhete quebraria a rota inteira."""
    fonte = _admin()
    assert "_COLUNAS_DO_DETALHE" in fonte
    colunas = _bloco(fonte, "_COLUNAS_DO_DETALHE")
    # As colunas do bilhete precisam ser renomeadas pro contrato que a tela já
    # consome (market, odd, home_team...), senão o front teria que aprender um
    # segundo formato só pra este produto.
    for esperado in ("market_1 AS market", "home_team_1 AS home_team",
                     "odd_combined AS odd", "fixture_id_1 AS fixture_id"):
        assert esperado in colunas, esperado


def test_a_consulta_padrao_continua_valendo_para_todo_o_resto():
    """A mudança não pode ter trocado a consulta de quem já funcionava."""
    fonte = _admin()
    padrao = fonte[fonte.index("_COLUNAS_PADRAO = "):fonte.index("_COLUNAS_PADRAO = ") + 400]
    for esperado in ("fixture_id", "home_team", "market", "odd", "engine_debug"):
        assert esperado in padrao, esperado
    assert "_COLUNAS_DO_DETALHE.get(tabela, _COLUNAS_PADRAO)" in fonte


def test_o_bilhete_vai_num_campo_proprio_e_so_quando_existe():
    """Chave ausente pra pick de perna única: a tela não pode ter que
    adivinhar pelo formato do dicionário, nem receber `bilhete: null` em todo
    pick simples do site."""
    fonte = _admin()
    assert '**({"bilhete": debug} if debug.get("gates") and debug.get("legs") else {})' in fonte


def test_a_coluna_engine_debug_da_alavancagem_nasce_na_migration():
    """Quem escreve a coluna é o motor e quem lê é o site, e a ordem de deploy
    entre os dois não é garantida -- por isso os dois lados fazem o ALTER."""
    with open(os.path.join(_BACKEND, "migrations.py"), encoding="utf-8") as f:
        migrations = f.read()
    assert ("ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS engine_debug JSONB"
            in migrations)
