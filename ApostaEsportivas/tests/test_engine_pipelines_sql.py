"""Garante que os pipelines nao voltem a mandar SQL quebrado ou desalinhado
pro Postgres. Sao falhas que nenhum teste de logica pega e que so aparecem em
runtime, contra o banco -- as duas ja aconteceram em producao.
"""
import ast
import re
from pathlib import Path

import pytest

PIPELINES_DIR = Path(__file__).resolve().parents[1] / "src" / "engine_pipelines"
SRC_DIR = Path(__file__).resolve().parents[1] / "src"

# utils/data_br.py exporta esses como TRECHO DE SQL pra interpolar em f-string.
# Num literal comum eles chegam no Postgres como a chave literal "{HOJE_BR}".
PLACEHOLDERS_SQL = re.compile(r"\{(HOJE_BR|ONTEM_BR|AGORA_BR|TZ_BR|data_br\()")

# Docstring que documenta o uso do helper (utils/data_br.py) cita o mesmo
# placeholder sem ser SQL executado. Filtra por palavra-chave de SQL em vez de
# tentar reconhecer docstring: e' a diferenca que importa aqui.
SQL_KEYWORDS = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", re.IGNORECASE)

PY_FILES = sorted(SRC_DIR.rglob("*.py"))


def _string_literals(tree: ast.AST):
    """So' ast.Constant: uma f-string vira ast.JoinedStr e nao passa por aqui."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(SRC_DIR)))
def test_sql_com_placeholder_de_data_e_sempre_f_string(path):
    """Regressao de 2026-08-02: alavancagem_pipeline.py::_fixtures_with_odds_today
    tinha `cur.execute(\"\"\"... {HOJE_BR} ...\"\"\")` sem o prefixo f. O SQL saia com
    a chave literal e o Postgres respondia `syntax error at or near "{"`, entao a
    alavancagem parou de gerar qualquer pick -- em silencio, porque o traceback
    se perdia no meio do log do pipeline completo."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except SyntaxError as e:
        pytest.fail(f"{path} nao compila: {e}")

    ofensores = [
        (node.lineno, PLACEHOLDERS_SQL.search(node.value).group(0))
        for node in _string_literals(tree)
        if PLACEHOLDERS_SQL.search(node.value) and SQL_KEYWORDS.search(node.value)
    ]
    assert not ofensores, (
        f"{path.relative_to(SRC_DIR)}: placeholder de data em string NAO-f "
        f"(vira chave literal no SQL): {ofensores}"
    )


# Duas formas de INSERT, porque os pipelines usam as duas:
#
#   INSERT INTO t (cols) VALUES (...)
#   INSERT INTO t (cols) SELECT ... WHERE NOT EXISTS (...)
#
# A segunda entrou em dica_pipeline.py em 2026-08-17 (guarda atomica contra o
# VIP publicar o mesmo pick). Quando so' a primeira era reconhecida, o arquivo
# inteiro caia no pytest.skip -- ou seja a checagem de alinhamento parou de
# cobrir justamente o INSERT que tinha acabado de ganhar 3 posicoes novas.
# Teste que vira skip sozinho ao mudar o codigo e' pior que teste ausente:
# a suite continua verde e ninguem percebe que a cobertura sumiu.
INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+(\w+)\s*\((?P<cols>[^)]*)\)\s*"
    r"(?:VALUES\s*\((?P<vals>[^)]*)\)|SELECT\s+(?P<sel>.*?)(?=\s+WHERE\b|\s+ON\s+CONFLICT\b))",
    re.IGNORECASE | re.DOTALL,
)


def _conta_posicoes(lista: str) -> int:
    """Itens separados por virgula no nivel de cima -- virgula dentro de
    parenteses (ex.: COALESCE(v.line, '')) nao separa posicao nenhuma."""
    profundidade = itens = 0
    atual = ""
    for ch in lista:
        if ch == "(":
            profundidade += 1
        elif ch == ")":
            profundidade -= 1
        if ch == "," and profundidade == 0:
            if atual.strip():
                itens += 1
            atual = ""
        else:
            atual += ch
    if atual.strip():
        itens += 1
    return itens


@pytest.mark.parametrize(
    "path",
    sorted(PIPELINES_DIR.glob("*_pipeline.py")),
    ids=lambda p: p.name,
)
def test_insert_tem_uma_posicao_por_coluna(path):
    """Cada coluna listada precisa de exatamente uma posicao no VALUES/SELECT --
    contando tanto %s quanto literais interpolados ({HOJE_BR}, 'fouls'). Um
    desalinhamento aqui grava dado na coluna errada em vez de dar erro."""
    src = path.read_text(encoding="utf-8-sig")
    achou = False
    for m in INSERT_RE.finditer(src):
        achou = True
        tabela = m.group(1)
        lista = m.group("vals") if m.group("vals") is not None else m.group("sel")
        n_cols = _conta_posicoes(m.group("cols"))
        n_vals = _conta_posicoes(lista)
        assert n_cols == n_vals, (
            f"{path.name}: INSERT INTO {tabela} tem {n_cols} colunas "
            f"e {n_vals} posicoes"
        )
    if not achou:
        pytest.skip(f"{path.name} nao tem INSERT literal")


def test_a_forma_insert_select_e_mesmo_reconhecida():
    """Trava o motivo do skip anterior: se o regex voltar a so' entender VALUES,
    dica_pipeline.py silenciosamente para de ser conferido."""
    dica = (PIPELINES_DIR / "dica_pipeline.py").read_text(encoding="utf-8-sig")
    achados = [m for m in INSERT_RE.finditer(dica)]
    assert achados, "dica_pipeline.py tem INSERT e ele precisa ser reconhecido"
    assert any(m.group("sel") is not None for m in achados), \
        "o INSERT ... SELECT da guarda contra o VIP tem que ser reconhecido"


def test_o_contador_ignora_virgula_dentro_de_parenteses():
    assert _conta_posicoes("%s, %s, COALESCE(a, b), %s") == 4
    assert _conta_posicoes("a, b") == 2
    assert _conta_posicoes("") == 0
