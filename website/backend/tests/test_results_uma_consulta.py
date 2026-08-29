"""A pagina de resultados publicos numa consulta so' (routers/public.py).

MEDIDO EM 2026-08-13, contra producao:

    /public/results        1893ms   <- definia o tempo de carga da Home
    trabalho real no banco    <5ms

Nao era SQL. `_collect_results` rodava uma consulta por fonte de pick (6) e
`_count_recent` outra por fonte (6): 12 idas e voltas so' pra montar a lista de
recentes, num total de 18 na rota. Com o banco longe do app, ida e volta e' o
custo.

O caminho novo usa `_build_union` (que ja existia, ja normalizava as colunas e
ja era usado pelo sumario) com COUNT(*) OVER () pra trazer pagina e total
juntos: 12 idas viram 1, e a rota cai de 18 pra 7.

Verificado contra producao antes de subir: mesmo CONJUNTO de linhas do caminho
antigo (301 e 172), total identico, ordem estavel entre chamadas, 3 paginas
iguais a uma busca de 30, e filtro por mes preservado.

Nenhum teste aqui toca banco: le-se o codigo.
"""
import ast
import inspect
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(BACKEND, "routers", "public.py")


@pytest.fixture(scope="module")
def fonte():
    with open(PUBLIC, encoding="utf-8") as fh:
        return fh.read()


def _funcao(fonte, nome):
    arvore = ast.parse(fonte)
    return next(n for n in ast.walk(arvore)
                if isinstance(n, ast.FunctionDef) and n.name == nome)


# ── O ganho ───────────────────────────────────────────────────────────────
def test_pagina_e_total_saem_da_mesma_consulta(fonte):
    """Duas consultas pra mesma varredura era metade do problema."""
    corpo = ast.unparse(_funcao(fonte, "_pagina_de_resultados"))
    assert "COUNT(*) OVER ()" in corpo


def test_endpoint_nao_chama_mais_o_caminho_de_12_consultas(fonte):
    """A regressao a evitar: alguem reintroduzir a dupla antiga no endpoint."""
    corpo = ast.unparse(_funcao(fonte, "public_results"))
    assert "_pagina_de_resultados" in corpo
    assert "_count_recent" not in corpo
    assert "_collect_results" not in corpo


def test_union_reaproveita_o_helper_que_ja_existia(fonte):
    """`_build_union` ja normalizava as 6 fontes e ja era usado pelo sumario.
    Montar um UNION proprio aqui criaria duas definicoes da mesma coisa."""
    corpo = ast.unparse(_funcao(fonte, "_pagina_de_resultados"))
    assert "_build_union" in corpo


# ── Paginacao ─────────────────────────────────────────────────────────────
def test_ordem_tem_desempate_deterministico(fonte):
    """SEM ISTO A PAGINA 2 REPETE LINHA DA 1.

    Foi encontrado comparando contra producao: mesmo total e mesmas colunas,
    conteudo diferente na pagina 2. Sem criterio de desempate o Postgres pode
    devolver empates em ordem diferente a cada consulta, e o LIMIT/OFFSET passa
    a recortar de listas diferentes.
    """
    corpo = ast.unparse(_funcao(fonte, "_pagina_de_resultados"))
    assert "array_position" in corpo, \
        "ORDER BY sem desempate estavel: paginacao volta a repetir/pular linha"


def test_desempate_deriva_da_constante_e_nao_de_lista_na_mao(fonte):
    """Registrar um mercado novo (faltas/goleiros ja custou isso uma vez) nao
    pode exigir lembrar de atualizar uma lista escrita aqui."""
    corpo = ast.unparse(_funcao(fonte, "_pagina_de_resultados"))
    # `builders` e' `_builders(cur)`, que e' `_SUB_BUILDERS` menos a fonte
    # opcional ausente · continua derivado da constante, nunca de lista na mao.
    assert "builders.keys()" in corpo and "_builders(cur)" in corpo


# ── Resiliencia preservada ────────────────────────────────────────────────
def test_caminho_por_fonte_continua_existindo_como_fallback(fonte):
    """A versao por fonte isolada nasceu pra uma tabela quebrada nao apagar as
    outras (coluna que faltou numa migracao derruba aquela fonte, nao o
    historico inteiro). UNION nao tem essa propriedade: se uma perna quebra,
    quebra tudo. Por isso o UNION e' tentado primeiro e cai no laco se falhar."""
    corpo = ast.unparse(_funcao(fonte, "_pagina_de_resultados"))
    assert "except Exception" in corpo
    assert "_collect_results" in corpo and "_count_recent" in corpo


def test_fallback_desfaz_a_transacao_antes_de_tentar_de_novo(fonte):
    """Consulta que falhou deixa a transacao abortada: sem rollback, TODA
    consulta seguinte falha com 'current transaction is aborted' e o fallback
    nao salvaria nada."""
    for nome in ("_pagina_de_resultados", "_collect_results", "_count_recent"):
        corpo = ast.unparse(_funcao(fonte, nome))
        assert "rollback()" in corpo, f"{nome} sem rollback no caminho de erro"


def test_fonte_quebrada_nao_derruba_as_outras_no_fallback(fonte):
    """A propriedade inteira que justifica o fallback existir."""
    corpo = ast.unparse(_funcao(fonte, "_collect_results"))
    assert "continue" in corpo
