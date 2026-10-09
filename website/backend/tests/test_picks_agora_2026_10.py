"""Picks ao vivo nos cards (09/10/2026): a rota le' SO' o cache que a
varredura ja' mantem e nunca chama a API-Football."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers import live  # noqa: E402


def _fixture(status, minuto, gh, ga):
    return {"fixture": {"status": {"short": status, "elapsed": minuto}, "timestamp": 0},
            "goals": {"home": gh, "away": ga}, "score": {"halftime": {"home": 0, "away": 0}},
            "teams": {"home": {"id": 1}, "away": {"id": 2}}, "league": {"id": 128}}


def _folha(esc_casa, esc_fora):
    return [{"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": esc_casa}]},
            {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": esc_fora}]}]


@pytest.fixture
def sem_api(monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("a rota nao pode chamar a API")
    monkeypatch.setattr(live.requests, "get", proibido)
    monkeypatch.setattr(live, "maybe_resolve_pending", lambda: False)
    monkeypatch.setattr(live, "_fix_cache", {})
    monkeypatch.setattr(live, "_stats_cache", {})


def _item(**k):
    return {"chave": "vip:1", "fixture_id": 10, "market": "Escanteios Mais/Menos",
            "market_type": "corners", "line": "Over 5.5", "prob": 0.62, **k}


def test_escanteios_ao_vivo_com_contador_e_chance(sem_api):
    agora = time.time()
    live._fix_cache[10] = (agora, _fixture("2H", 60, 1, 0))
    live._stats_cache[10] = (agora, _folha(1, 1), "2H")
    r = live.get_picks_agora({"itens": [_item()]}, current_user={})["vip:1"]
    assert r["atual"] == 2 and r["linha"] == 5.5 and r["direcao"] == "over"
    assert r["minuto"] == 60 and r["placar"] == [1, 0]
    assert 0 < r["chance"] < 0.62   # 2 aos 60', abaixo do ritmo: a chance cai
    # 4 aos 60' esta' acima do ritmo do pick: a chance sobe.
    live._stats_cache[10] = (agora, _folha(3, 1), "2H")
    assert live.get_picks_agora({"itens": [_item()]}, current_user={})["vip:1"]["chance"] > 0.62


def test_linha_batida_vale_100(sem_api):
    agora = time.time()
    live._fix_cache[10] = (agora, _fixture("2H", 70, 0, 0))
    live._stats_cache[10] = (agora, _folha(4, 3), "2H")
    r = live.get_picks_agora({"itens": [_item()]}, current_user={})["vip:1"]
    assert r["chance"] == 1.0 and r["travado"] is True


def test_sem_cache_nao_comecou_acabou_ou_velho_nao_aparece(sem_api):
    assert live.get_picks_agora({"itens": [_item()]}, current_user={}) == {}
    live._fix_cache[10] = (time.time(), _fixture("NS", None, None, None))
    assert live.get_picks_agora({"itens": [_item()]}, current_user={}) == {}
    live._fix_cache[10] = (time.time(), _fixture("FT", 90, 2, 1))
    assert live.get_picks_agora({"itens": [_item()]}, current_user={}) == {}
    live._fix_cache[10] = (time.time() - 3600, _fixture("2H", 60, 1, 0))
    assert live.get_picks_agora({"itens": [_item()]}, current_user={}) == {}


def test_gols_nao_precisam_de_folha(sem_api):
    live._fix_cache[10] = (time.time(), _fixture("1H", 30, 1, 0))
    r = live.get_picks_agora({"itens": [_item(market="Gols Mais/Menos", market_type="goals",
                                              line="Over 2.5", prob=0.55)]}, current_user={})["vip:1"]
    assert r["atual"] == 1 and r["chance"] is not None


def test_placar_do_raio_x_so_do_cache(sem_api):
    live._fix_cache[10] = (time.time(), _fixture("2H", 59, 0, 0))
    live._stats_cache[10] = (time.time(), _folha(5, 0), "2H")
    r = live.get_live_stats_bulk("10,11", so_cache=True, current_user={})
    assert r["10"]["status"] == "2H" and r["10"]["elapsed"] == 59 and r["10"]["home_corners"] == 5
    assert r["11"] == {}      # sem cache: nada, e nenhuma chamada
    assert live._SO_CACHE.get() is False


def test_cache_so_fica_ligado_dentro_da_leitura(sem_api):
    live._fix_cache[10] = (time.time(), _fixture("1H", 30, 1, 0))
    live.get_picks_agora({"itens": [_item()]}, current_user={})
    assert live._SO_CACHE.get() is False
