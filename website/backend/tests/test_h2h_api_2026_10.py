"""Confronto pela API quando o banco nao tem (12/10/2026): uma consulta por
par, guardada 30 dias, e nunca com a cota apertada."""
import json

import pytest

import h2h_api


def _item(data, casa, fora, gh, ga, status="FT"):
    return {"fixture": {"date": data, "status": {"short": status}},
            "teams": {"home": {"id": casa}, "away": {"id": fora}},
            "goals": {"home": gh, "away": ga}}


def test_resposta_vira_o_formato_do_raio_x():
    jogos = h2h_api.jogos_da_resposta([
        _item("2024-01-10T20:00:00+00:00", 499, 517, 2, 1),
        _item("2025-03-01T18:00:00+00:00", 517, 499, 0, 0),
        _item("2026-12-01T18:00:00+00:00", 499, 517, None, None, status="NS"),
    ], 8)
    assert [j["data"][:4] for j in jogos] == ["2025", "2024"]     # mais recente primeiro
    assert jogos[1] == {"data": "2024-01-10T20:00:00", "home_team_id": 499, "away_team_id": 517,
                        "home_goals": 2, "away_goals": 1, "escanteios": None, "amarelos": None}


class _Cur:
    def __init__(self, guardado=None):
        self.guardado = guardado
        self.gravado = None
        self.params = None
        self._r = None
        self.connection = self

    def commit(self): pass
    def rollback(self): pass

    def execute(self, sql, params=None):
        if "SELECT jogos" in sql:
            self.params = params
            self._r = {"jogos": self.guardado} if self.guardado is not None else None
        elif "INSERT INTO h2h_api_cache" in sql:
            self.gravado = params

    def fetchone(self):
        return self._r


class _Resp:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


@pytest.fixture
def api(monkeypatch):
    chamadas = []
    monkeypatch.setenv("API_FOOTBALL_KEY", "x")
    monkeypatch.setattr(h2h_api.api_quota, "registrar", lambda *a, **k: None)
    monkeypatch.setattr(h2h_api.api_quota, "estado_atual", lambda: {"pct_usado": 40.0})
    resposta = {"response": [_item("2025-03-01T18:00:00+00:00", 517, 499, 1, 3)]}

    def get(url, headers=None, params=None, timeout=None):
        chamadas.append(params)
        return _Resp(resposta)
    monkeypatch.setattr(h2h_api.requests, "get", get)
    return chamadas


def test_par_em_ordem_unica_e_grava_o_que_a_api_trouxe(api):
    cur = _Cur()
    jogos = h2h_api.confronto(cur, 517, 499)
    assert api == [{"h2h": "499-517", "last": 20}]
    assert cur.params[:2] == (499, 517)
    assert cur.gravado[:2] == (499, 517) and json.loads(cur.gravado[2]) == jogos
    assert jogos[0]["home_goals"] == 1


def test_do_cache_nao_chama_a_api_nem_quando_e_vazio(api):
    assert h2h_api.confronto(_Cur(guardado=[]), 1, 2) == []
    assert h2h_api.confronto(_Cur(guardado=json.dumps([{"home_goals": 1}])), 1, 2) == [{"home_goals": 1}]
    assert api == []


def test_cota_apertada_ou_recusa_nao_consulta_nem_grava(api, monkeypatch):
    monkeypatch.setattr(h2h_api.api_quota, "estado_atual", lambda: {"pct_usado": 93.0})
    cur = _Cur()
    assert h2h_api.confronto(cur, 1, 2) is None and api == []

    monkeypatch.setattr(h2h_api.api_quota, "estado_atual", lambda: {})
    monkeypatch.setattr(h2h_api.requests, "get",
                        lambda *a, **k: _Resp({"errors": {"requests": "limit"}, "response": []}))
    assert h2h_api.confronto(cur, 1, 2) is None
    assert cur.gravado is None
