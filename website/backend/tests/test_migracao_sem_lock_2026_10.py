"""Migracao da subida so' envia o DDL que falta (12/10/2026). Sem banco."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import migrations  # noqa: E402


class _CurCru:
    def __init__(self, colunas):
        self.colunas, self.enviados, self._r = set(colunas), [], []

    def execute(self, sql, args=None):
        texto = " ".join(sql.split())
        if "information_schema.columns" in texto:
            self._r = [{"column_name": c} for c in self.colunas]
        elif texto.startswith("SELECT to_regclass"):
            self._r = [{"x": False}]
        else:
            self.enviados.append(texto)

    def fetchall(self):
        return self._r

    def fetchone(self):
        return self._r[0]


def _cursor(colunas):
    cru = _CurCru(colunas)
    return migrations._CursorQueSoMudaOQueFalta(cru), cru


def test_coluna_que_ja_existe_nem_e_enviada():
    cur, cru = _cursor({"ativa"})
    cur.execute("ALTER TABLE leagues ADD COLUMN IF NOT EXISTS ativa BOOLEAN NOT NULL DEFAULT TRUE;")
    assert cru.enviados == []


def test_coluna_nova_e_enviada():
    cur, cru = _cursor(set())
    cur.execute("ALTER TABLE leagues ADD COLUMN IF NOT EXISTS ativa BOOLEAN;")
    assert len(cru.enviados) == 1


def test_varios_comandos_numa_string_vao_direto():
    cur, cru = _cursor({"a"})
    cur.execute("ALTER TABLE t ADD COLUMN IF NOT EXISTS a INT, ADD COLUMN IF NOT EXISTS b INT")
    cur.execute("ALTER TABLE t ADD COLUMN IF NOT EXISTS a INT; ALTER TABLE t ADD COLUMN IF NOT EXISTS b INT;")
    assert len(cru.enviados) == 2


def test_o_que_nao_e_ddl_vai_direto():
    cur, cru = _cursor(set())
    cur.execute("UPDATE leagues SET ativa = TRUE WHERE league_id = %s", (1,))
    cur.execute("INSERT INTO x VALUES (1)")
    assert len(cru.enviados) == 2
