"""O numero que decidiu cada perna fica gravado (11/10/2026).

O card do pick simples mostra "Final: 18 escanteios"; Multipla, Bingo,
Alavancagem e Boost mostravam so' o selo. Nenhum teste toca banco.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers import live  # noqa: E402


class _Cur:
    def __init__(self, games=None, falhar_em=None):
        self.games, self.falhar_em, self.sqls = games, falhar_em, []

    def execute(self, sql, args=None):
        self.sqls.append((" ".join(sql.split()), args))
        if self.falhar_em and self.falhar_em in sql:
            raise RuntimeError("coluna nao existe")

    def fetchone(self):
        return {"games": self.games}

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits, self.rollbacks = cur, 0, 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_multipla_grava_o_valor_de_cada_perna():
    cur = _Cur(games=[{"market": "Escanteios"}, {"market": "Gols"}])
    saida = json.loads(live._gravar_resultado_das_pernas(
        cur, "picks_multiplas", 1, ["RED", "GREEN"], [18.0, None]))
    assert saida[0] == {"market": "Escanteios", "result": "RED", "settled_value": 18.0}
    assert "settled_value" not in saida[1]          # sem numero (resultado 1X2), nada inventado


def test_perna_em_aberto_nao_ganha_valor():
    cur = _Cur(games=[{"market": "A"}, {"market": "B"}])
    saida = json.loads(live._gravar_resultado_das_pernas(
        cur, "picks_multiplas", 1, ["RED", None], [3.0, 1.0]))
    assert "settled_value" not in saida[1]


def test_sem_valores_continua_como_antes():
    cur = _Cur(games=[{"market": "A"}])
    saida = json.loads(live._gravar_resultado_das_pernas(cur, "picks_multiplas", 1, ["GREEN"]))
    assert saida == [{"market": "A", "result": "GREEN"}]


def test_alavancagem_grava_pernas_final(monkeypatch):
    monkeypatch.setattr(live, "_sync_followed_result", lambda *a, **k: None)
    cur = _Cur()
    conn = _Conn(cur)
    live._save_alavancagem_result(9, ["GREEN", "RED"], 2.5, conn, [1.5, 1.7],
                                  forced_result="RED", pernas=[(1, 4.0), (3, 12.0)])
    sql, args = next((s, a) for s, a in cur.sqls if "pernas_final" in s)
    assert json.loads(args[2]) == [
        {"perna": 1, "result": "GREEN", "settled_value": 4.0},
        {"perna": 3, "result": "RED", "settled_value": 12.0},
    ]


def test_alavancagem_sem_a_coluna_grava_so_o_resultado(monkeypatch):
    monkeypatch.setattr(live, "_sync_followed_result", lambda *a, **k: None)
    cur = _Cur(falhar_em="pernas_final")
    conn = _Conn(cur)
    live._save_alavancagem_result(9, ["RED"], 2.0, conn, [2.0], forced_result="RED",
                                  pernas=[(1, 5.0)])
    assert conn.rollbacks == 1
    assert any("SET result=%s, profit=%s WHERE" in s for s, _ in cur.sqls)
    assert conn.commits == 1
