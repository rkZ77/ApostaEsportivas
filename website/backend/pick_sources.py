"""As tabelas de pick que o usuario pode SEGUIR, declaradas UMA vez.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
O mesmo `LEFT JOIN ... AND uf.pick_type = '...'` seguido de um `CASE
uf.pick_type WHEN ... THEN alias.result END` estava escrito a mao em quatro
consultas diferentes (`routers/leaderboard.py` duas vezes,
`routers/public.py::public_leaderboard`, e o espelho em `routers/banca.py`).
Cada copia envelheceu no seu proprio ritmo: em 29/08 o ranking do /api
contava 4 tipos, o ranking publico contava 8 e a banca contava 9 -- tres telas
descrevendo o MESMO usuario com tres numeros diferentes.

E o modo de falhar e' silencioso por construcao: tipo que falta no CASE vira
NULL, e todo agregado filtra `result IS NOT NULL`. A aposta nao da erro, nao
aparece zerada, simplesmente some. Quem so' apostou no tipo esquecido nem
entra na lista.

Entao a lista mora aqui e as consultas a montam. Produto novo = uma linha
nesta tupla, e todas as telas passam a conta-lo juntas.

`opcional=True` e' pra tabela que o SITE nao cria: `picks_live` nasce do motor
(engine_pipelines/live_pipeline.py), entao um ambiente que nunca rodou o motor
ao vivo nao a tem, e um LEFT JOIN nela derrubaria a consulta INTEIRA -- o
ranking sumiria da Home por causa de um produto que aquele ambiente nem
publica. `fontes(cur)` checa a existencia uma vez e devolve so' o que da' pra
consultar.
"""

#: (pick_type, tabela, alias, coluna_de_odd, opcional)
_FONTES: tuple = (
    ("vip",          "picks_vip",          "pv",  "odd",          False),
    ("free",         "picks_free",         "pf",  "odd",          False),
    ("multipla",     "picks_multiplas",    "pm",  "total_odd",    False),
    ("alavancagem",  "picks_alavancagem",  "pa",  "odd_combined", False),
    ("faltas",       "picks_faltas",       "pfa", "odd",          False),
    ("goleiros",     "picks_goleiros",     "pg",  "odd",          False),
    ("player_stats", "picks_player_stats", "pps", "odd",          False),
    ("boost",        "picks_boost",        "pbo", "odd",          False),
    ("live",         "picks_live",         "pli", "odd",          True),
)


def tabela_existe(cur, tabela: str) -> bool:
    """`to_regclass` devolve NULL em vez de estourar quando a tabela nao
    existe · e' a checagem que nao suja a transacao (um erro de SQL exigiria
    rollback e derrubaria a consulta que vem depois)."""
    try:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS existe", (f"public.{tabela}",))
        row = cur.fetchone()
        return bool(row["existe"] if isinstance(row, dict) or hasattr(row, "keys") else row[0])
    except Exception:
        return False


def fontes(cur) -> list:
    """As fontes consultaveis nesta instancia, na ordem declarada."""
    return [f for f in _FONTES if not f[4] or tabela_existe(cur, f[1])]


def joins_sql(fontes_ativas: list, coluna_de_id: str = "uf.pick_id",
              coluna_de_tipo: str = "uf.pick_type") -> str:
    return "\n            ".join(
        f"LEFT JOIN {tabela} {alias} ON {alias}.id = {coluna_de_id}"
        f" AND {coluna_de_tipo} = '{tipo}'"
        for tipo, tabela, alias, _odd, _opc in fontes_ativas
    )


def case_sql(fontes_ativas: list, coluna: str, coluna_de_tipo: str = "uf.pick_type",
             envolver: str = "{expr}", senao: str = "NULL") -> str:
    """CASE que escolhe `coluna` da tabela certa. `coluna` pode ser 'result',
    'profit' ou o literal 'odd' -- 'odd' usa a coluna de odd declarada por
    fonte, porque multipla e alavancagem chamam a delas de outro nome."""
    ramos = []
    for tipo, _tabela, alias, col_odd, _opc in fontes_ativas:
        campo = col_odd if coluna == "odd" else coluna
        expr = envolver.format(expr=f"{alias}.{campo}")
        ramos.append(f"WHEN '{tipo}' THEN {expr}")
    corpo = "\n                        ".join(ramos)
    return f"CASE {coluna_de_tipo}\n                        {corpo}\n                        ELSE {senao}\n                    END"
