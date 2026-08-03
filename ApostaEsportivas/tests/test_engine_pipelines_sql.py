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


INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+(\w+)\s*\((?P<cols>[^)]*)\)\s*VALUES\s*\((?P<vals>[^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)


@pytest.mark.parametrize(
    "path",
    sorted(PIPELINES_DIR.glob("*_pipeline.py")),
    ids=lambda p: p.name,
)
def test_insert_tem_uma_posicao_por_coluna(path):
    """Cada coluna listada precisa de exatamente uma posicao no VALUES --
    contando tanto %s quanto literais interpolados ({HOJE_BR}, 'fouls'). Um
    desalinhamento aqui grava dado na coluna errada em vez de dar erro."""
    src = path.read_text(encoding="utf-8-sig")
    achou = False
    for m in INSERT_RE.finditer(src):
        achou = True
        tabela = m.group(1)
        n_cols = len([c for c in m.group("cols").split(",") if c.strip()])
        n_vals = len([v for v in m.group("vals").split(",") if v.strip()])
        assert n_cols == n_vals, (
            f"{path.name}: INSERT INTO {tabela} tem {n_cols} colunas "
            f"e {n_vals} posicoes no VALUES"
        )
    if not achou:
        pytest.skip(f"{path.name} nao tem INSERT literal")
