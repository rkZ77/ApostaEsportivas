"""DDL de auto-provisionamento que nao trava o site (11/10/2026).

O coletor de estatistica fazia ~25 ALTER TABLE em match_statistics a cada
abertura, todos pedindo lock exclusivo -- o "Atualizar Jogos" derrubava o
site. Nenhum teste toca banco: o cursor e' um catalogo de mentira.
"""
from utils import esquema


class _Cur:
    """Catalogo: tabelas existentes e as colunas de cada uma."""

    def __init__(self, tabelas: dict):
        self.tabelas = {t: set(c) for t, c in tabelas.items()}
        self.executados: list[str] = []
        self._ultimo = None

    def execute(self, sql, args=None):
        texto = " ".join(sql.split())
        if texto.startswith("SELECT to_regclass"):
            nome = args[0].split(".", 1)[1]
            self._ultimo = [(nome in self.tabelas or nome.startswith("idx_existente"),)]
        elif "information_schema.columns" in texto:
            self._ultimo = [(c,) for c in self.tabelas.get(args[0], ())]
        else:
            self.executados.append(texto)

    def fetchone(self):
        return self._ultimo[0]

    def fetchall(self):
        return self._ultimo


def test_banco_em_dia_nao_emite_ddl_nenhum():
    cur = _Cur({"match_statistics": {"round", "home_goals_90"}})
    n = esquema.garantir(cur, [
        "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS round TEXT;",
        "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS home_goals_90 INTEGER;",
        "CREATE INDEX IF NOT EXISTS idx_existente_x ON match_statistics (x)",
        "CREATE TABLE IF NOT EXISTS match_statistics (id INT)",
    ])
    assert n == 0
    assert cur.executados == []          # nem o SET: nada pediu lock


def test_so_o_que_falta_roda_e_com_lock_timeout():
    cur = _Cur({"match_statistics": {"round"}})
    n = esquema.garantir(cur, [
        "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS round TEXT;",
        "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS events_checked_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS idx_novo ON match_statistics (y)",
    ])
    assert n == 2
    assert cur.executados[0] == "SET LOCAL lock_timeout = '3s'"
    assert "events_checked_at" in cur.executados[1]
    assert "idx_novo" in cur.executados[2]


def test_tabela_nova_cria_e_depois_as_colunas_na_ordem():
    cur = _Cur({})
    esquema.garantir(cur, [
        "CREATE TABLE IF NOT EXISTS team_lineups (fixture_id INT)",
        "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS lineups_checked_at TIMESTAMP",
    ])
    assert cur.executados[1].startswith("CREATE TABLE")
    assert cur.executados[2].startswith("ALTER TABLE")


class _CurComRestricao(_Cur):
    def __init__(self, tabelas, restricoes):
        super().__init__(tabelas)
        self.restricoes = set(restricoes)

    def execute(self, sql, args=None):
        if "pg_constraint" in sql:
            self._ultimo = [(1,)] if args in self.restricoes else [None]
            return
        super().execute(sql, args)


def test_drop_so_quando_ainda_existe():
    """DROP ... IF EXISTS tambem pede o lock: so' roda se ainda tiver o que soltar."""
    sqls = ["ALTER TABLE picks_alavancagem DROP CONSTRAINT IF EXISTS picks_alavancagem_match_date_key",
            "DROP INDEX IF EXISTS idx_existente_velho"]
    em_dia = _CurComRestricao({}, [])
    assert esquema.faltando(em_dia, sqls[:1]) == []
    velho = _CurComRestricao({}, [("picks_alavancagem", "picks_alavancagem_match_date_key")])
    assert esquema.faltando(velho, sqls) == sqls


def test_coluna_comparada_sem_caixa():
    cur = _Cur({"match_statistics": {"Round"}})
    assert esquema.faltando(cur, ["ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS round TEXT"]) == []


def test_coletor_de_estatistica_nao_emite_alter_cru(monkeypatch):
    """O defeito era o `cur.execute("ALTER TABLE ...")` direto na abertura."""
    import inspect

    # O modulo exige a chave no import; sozinho, este teste nao a teria.
    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")

    from collectors import match_statistics_sync_service as svc
    fonte = inspect.getsource(svc.MatchStatisticsSyncService._ensure_columns)
    assert "self.cur.execute(\n                f\"ALTER TABLE" not in fonte
    assert "self.cur.execute(f\"ALTER TABLE" not in fonte
    assert "esquema.garantir" in fonte
