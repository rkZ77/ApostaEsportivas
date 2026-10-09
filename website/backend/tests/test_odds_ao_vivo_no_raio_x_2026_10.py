"""Odds ao vivo no Raio-X (09/10/2026): com o jogo rolando, a rota de odds do
jogo devolve a cotacao de /odds/live no formato do pre-jogo, reaproveitada do
feed global que o ao vivo ja' busca. A rota nunca chama a API (decisao do
usuario: nao gastar cota a mais)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers import fixtures as fx  # noqa: E402
from routers import live  # noqa: E402

AO_VIVO = [
    {"id": 59, "name": "Fulltime Result", "values": [
        {"value": "Home", "odd": "2.10"}, {"value": "Draw", "odd": "3.20"},
        {"value": "Away", "odd": "3.60", "suspended": True}]},
    {"id": 69, "name": "Double Chance", "values": [{"value": "1X", "odd": "1.25"}]},
    {"id": 25, "name": "Match Goals", "values": [
        {"value": "Over", "odd": "1.85", "handicap": "2.5"},
        {"value": "Under", "odd": "1.95", "handicap": "3"}]},
    {"id": 1, "name": "Both Teams To Score", "values": [{"value": "Yes", "odd": "1.70"}]},
    {"id": 2, "name": "1st Half Winner", "values": [{"value": "Home", "odd": "3.0"}]},
]


def test_traduz_para_o_formato_do_pre_jogo():
    saida = {(o["market_id"], o["valor"]): o["odd"] for o in fx.odds_ao_vivo_no_formato_do_raio_x(AO_VIVO)}
    assert saida == {
        (1, "Home"): 2.10, (1, "Draw"): 3.20,          # suspensa fica de fora
        (12, "Home/Draw"): 1.25,
        (5, "Over 2.5"): 1.85, (5, "Under 3.0"): 1.95,
        (8, "Yes"): 1.70,                               # 1o tempo ignorado
    }


class _Cur:
    def __init__(self, linha):
        self.linha = linha

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self.linha

    def fetchall(self):
        return [{"market_id": 1, "value_name": "Home", "odd_value": 1.5, "bookmaker_name": "Betano"}]

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


def _rota(monkeypatch, linha_do_jogo, mundo, idade=0):
    """Chama a rota com o feed global em `mundo` (buscado ha' `idade` segundos).
    Qualquer chamada a API derruba o teste: a rota nao pode gastar cota."""
    monkeypatch.setattr(fx, "get_connection", lambda: _Conn(_Cur(linha_do_jogo)))
    monkeypatch.setattr(fx.cache_publico, "obter", lambda chave, ttl, f: f())

    def proibido(*a, **k):
        raise AssertionError("o Raio-X nao pode chamar /odds/live")
    monkeypatch.setattr(live, "_fetch_live_odds", proibido)
    monkeypatch.setattr(live, "_fetch_live_odds_mundo", proibido)
    monkeypatch.setattr(fx.requests, "get", proibido)
    monkeypatch.setattr(live, "_odds_mundo_cache", (time.time() - idade, mundo))
    return fx.get_odds_do_jogo(10, current_user={})


def test_fora_do_jogo_nao_usa_o_ao_vivo(monkeypatch):
    r = _rota(monkeypatch, {"status": "NS", "na_janela": False}, {10: AO_VIVO})
    assert r["ao_vivo"] is False and r["odds"][0]["casa"] == "Betano"


def test_jogo_rolando_reaproveita_o_feed_global(monkeypatch):
    r = _rota(monkeypatch, {"status": "2H", "na_janela": True}, {10: AO_VIVO})
    assert r["ao_vivo"] is True
    assert {"market_id": 1, "valor": "Home", "odd": 2.10, "casa": "ao vivo"} in r["odds"]


def test_feed_velho_ou_sem_o_jogo_fica_no_pre_jogo(monkeypatch):
    assert _rota(monkeypatch, {"status": "1H", "na_janela": True}, {10: AO_VIVO}, idade=3600)["ao_vivo"] is False
    assert _rota(monkeypatch, {"status": "1H", "na_janela": True}, {99: AO_VIVO})["ao_vivo"] is False
    assert _rota(monkeypatch, {"status": "1H", "na_janela": True}, {})["ao_vivo"] is False


def test_jogo_encerrado_fica_no_pre_jogo(monkeypatch):
    assert _rota(monkeypatch, {"status": "FT", "na_janela": True}, {10: AO_VIVO})["ao_vivo"] is False