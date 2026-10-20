"""Desfalques (/injuries) contam na cota e saem do cache do banco (20/10/2026).

news_model chamava a API por fora de utils/api_client, sem registrar: o painel
somava ~3,4 mil requisicoes por dia a menos que a API cobrava. E cada processo
do motor (pipeline do Rodar Tudo, ciclo do ao vivo) pedia de novo."""
from types import SimpleNamespace as NS

from services.pick_engine import news_model as nm


def _resposta():
    return NS(headers={"x-ratelimit-requests-remaining": "100"}, raise_for_status=lambda: None,
              json=lambda: {"response": [{"player": {"id": 9, "name": "Fulano", "type": "Missing Fixture",
                                                    "reason": "Knee Injury"}}]})


def test_registra_na_cota_e_grava_no_cache(monkeypatch):
    chamadas, registros, gravados = [], [], []
    monkeypatch.setattr(nm.requests, "get", lambda *a, **k: chamadas.append(k["params"]) or _resposta())
    monkeypatch.setattr(nm, "_registrar", lambda r, origem: registros.append(origem))
    monkeypatch.setattr(nm, "_cache_ler", lambda f, t: None)
    monkeypatch.setattr(nm, "_cache_gravar", lambda f, t, lista: gravados.append((f, t, lista)))
    lista = nm.fetch_injuries(5, fixture_id=77)
    assert lista[0]["name"] == "Fulano" and lista[0]["type"] == "Missing Fixture"
    assert registros == ["motor_desfalques"]
    assert gravados == [(77, 5, lista)]


def test_cache_fresco_nao_chama_a_api(monkeypatch):
    monkeypatch.setattr(nm, "_cache_ler", lambda f, t: [{"name": "Guardado"}])
    monkeypatch.setattr(nm.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("chamou a API")))
    assert nm.fetch_injuries(5, fixture_id=77) == [{"name": "Guardado"}]


def test_lista_vazia_guardada_tambem_vale(monkeypatch):
    """[] = a API respondeu e ninguem esta' fora · nao e' "sem cache"."""
    monkeypatch.setattr(nm, "_cache_ler", lambda f, t: [])
    monkeypatch.setattr(nm.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("chamou a API")))
    assert nm.fetch_injuries(5, fixture_id=77) == []


def test_falha_nao_grava_cache(monkeypatch):
    gravados = []
    monkeypatch.setattr(nm, "_cache_ler", lambda f, t: None)
    monkeypatch.setattr(nm, "_cache_gravar", lambda *a: gravados.append(a))
    monkeypatch.setattr(nm.requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rede")))
    assert nm.fetch_injuries(5, fixture_id=77) == []
    assert gravados == []
