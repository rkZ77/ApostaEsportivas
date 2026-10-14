"""/admin/motor/por-que (14/10/2026): jogo a jogo da liga, o que cada motor fez.

O caso que nenhuma tela mostrava: jogo SEM ODD. Os pipelines so' leem jogo
com odd (JOIN odds_values), entao ele nem aparece em engine_decisions.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import routers.admin as admin  # noqa: E402


class Cur:
    def __init__(self, respostas):
        self.respostas = respostas
        self._ult = []

    def execute(self, sql, params=None):
        for trecho, linhas in self.respostas:
            if trecho in sql:
                self._ult = linhas
                return
        self._ult = []

    def fetchall(self):
        return list(self._ult)

    def fetchone(self):
        return self._ult[0] if self._ult else None

    def close(self):
        pass


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def rollback(self):
        pass

    def close(self):
        pass


def _rodar(monkeypatch, respostas, **kw):
    monkeypatch.setattr(admin, "get_connection", lambda: Conn(Cur(respostas)))
    return admin.motor_por_que(current_user={}, **kw)


LIGAS = ("FROM leagues", [{"league_id": 40, "name": "Championship", "ativa": True}])
JOGOS = ("FROM fixtures", [
    {"fixture_id": 1, "home_team": "QPR", "away_team": "Derby", "quando": "2026-10-14 15:45:00", "status": "NS"},
    {"fixture_id": 2, "home_team": "Leeds", "away_team": "Hull", "quando": "2026-10-14 16:00:00", "status": "NS"},
])


def test_sem_liga_devolve_so_o_seletor(monkeypatch):
    r = _rodar(monkeypatch, [LIGAS])
    assert r == {"ligas": [{"league_id": 40, "name": "Championship", "ativa": True}], "jogos": []}


def test_jogo_sem_odd_e_jogo_avaliado(monkeypatch):
    r = _rodar(monkeypatch, [
        LIGAS, JOGOS,
        ("FROM odds_values", [{"fixture_id": 2, "n": 120, "mercados": 9}]),
        ("FROM engine_decisions", [{"fixture_id": 2, "pipeline": "VIP_ENGINE", "status": "avaliado",
                                    "reason": None, "aprovados": 0, "candidatos": 7}]),
    ], liga=40, data="2026-10-14")
    sem_odd, avaliado = r["jogos"]
    assert sem_odd["odds"] == 0 and "Sem odd coletada" in sem_odd["resumo"]
    assert avaliado["pipelines"][0]["rotulo"] == "Premium"
    assert "nenhum passou" in avaliado["pipelines"][0]["explicacao"]


def test_odd_sem_decisao_diz_que_o_pipeline_nao_rodou(monkeypatch):
    r = _rodar(monkeypatch, [
        LIGAS, JOGOS,
        ("FROM odds_values", [{"fixture_id": 1, "n": 50, "mercados": 4},
                              {"fixture_id": 2, "n": 50, "mercados": 4}]),
    ], liga=40, data="2026-10-14")
    assert all("nenhum motor registrou" in j["resumo"] for j in r["jogos"])
