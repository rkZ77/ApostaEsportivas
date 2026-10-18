"""Pagina publica de um jogo (18/10/2026) · ver jogo_publico.py.

O que estes testes seguram:
  - o slug e' o mesmo do front (frontend/src/lib/jogoPublico.test.ts);
  - a rota so' le' o banco: nenhuma chamada a API-Football;
  - so' o basico sai: nada de estatistica, arbitro, jogador ou odd do Pro;
  - jogo inexistente e' 404 e nao fica no cache;
  - o sitemap lista os jogos futuros, e sem banco ele sai sem eles.
"""

import os
from datetime import datetime

import pytest
from fastapi import HTTPException

import cache_publico
import jogo_publico
from routers import public as public_router

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Cur:
    def __init__(self, respostas):
        self.respostas = respostas
        self._ultimo = []

    def execute(self, sql, params=None):
        for trecho, linhas in self.respostas.items():
            if trecho in sql:
                self._ultimo = linhas
                return
        self._ultimo = []

    def fetchone(self):
        return self._ultimo[0] if self._ultimo else None

    def fetchall(self):
        return list(self._ultimo)

    def close(self):
        pass


class _Conn:
    def __init__(self, respostas):
        self.respostas = respostas

    def cursor(self):
        return _Cur(self.respostas)

    def close(self):
        pass


_JOGO = {
    "fixture_id": 99, "league_id": 71, "season": 2026,
    "home_team_id": 1, "away_team_id": 2,
    "home_team": "Atlético-MG", "away_team": "São Paulo",
    "match_datetime": datetime(2026, 10, 18, 16, 0), "status": "NS",
    "round": "Regular Season - 30", "league_name": "Brasileirão",
}

_TABELA = [
    {"team_id": 1, "rank": 3, "points": 50, "played": 29, "goals_diff": 12,
     "home_played": 15, "home_win": 10, "home_draw": 3, "home_lose": 2,
     "home_goals_for": 28, "home_goals_against": 12,
     "away_played": 14, "away_win": 5, "away_draw": 2, "away_lose": 7,
     "away_goals_for": 15, "away_goals_against": 19},
    {"team_id": 2, "rank": 6, "points": 44, "played": 29, "goals_diff": 4,
     "home_played": 14, "home_win": 8, "home_draw": 4, "home_lose": 2,
     "home_goals_for": 22, "home_goals_against": 10,
     "away_played": 15, "away_win": 4, "away_draw": 4, "away_lose": 7,
     "away_goals_for": 14, "away_goals_against": 22},
]


@pytest.fixture
def banco(monkeypatch):
    respostas = {
        "FROM fixtures WHERE fixture_id": [_JOGO],
        "FROM match_statistics": [],
        "FROM league_standings": _TABELA,
    }
    monkeypatch.setattr(jogo_publico, "get_connection", lambda: _Conn(respostas))
    import routers.fixtures as fixtures_router
    monkeypatch.setattr(
        fixtures_router, "_formas_recentes",
        lambda chaves, antes_de, n=5: {c: (["V", "V", "E", "D", "V"] if c[0] == 1 else ["D", "E"])
                                       for c in chaves},
    )
    cache_publico.invalidar("jogo_publico:")
    return respostas


def test_slug_igual_ao_do_front():
    assert jogo_publico.slug_do_jogo("Atlético-MG", "São Paulo") == "atletico-mg-x-sao-paulo"
    assert jogo_publico.slug_do_jogo("Bayern München", "Paris Saint Germain") == "bayern-munchen-x-paris-saint-germain"
    assert jogo_publico.slug_do_jogo("  Grêmio  ", "Athletico Paranaense") == "gremio-x-athletico-paranaense"
    assert jogo_publico.slug_do_jogo(None, "") == "casa-x-fora"


def test_entrega_so_o_basico(banco):
    dados = public_router.public_jogo(99)
    assert dados["slug"] == "atletico-mg-x-sao-paulo"
    assert dados["placar"] is None
    assert dados["casa"]["forma"] == ["V", "V", "E", "D", "V"]
    # O mandante leva a campanha EM CASA; o visitante, a de FORA.
    assert dados["casa"]["tabela"]["lado"]["vitorias"] == 10
    assert dados["fora"]["tabela"]["lado"]["vitorias"] == 4
    assert dados["fora"]["tabela"]["posicao"] == 6

    # Nada do que o Pro paga: estatistica, arbitro, jogador, odd, pick.
    texto = repr(dados).lower()
    for proibido in ("corner", "escanteio", "cart", "referee", "arbitro", "odd",
                     "market", "jogador", "player", "pick"):
        assert proibido not in texto, proibido


def test_nao_chama_a_api(banco, monkeypatch):
    import httpx
    import requests

    def explode(*a, **k):
        raise AssertionError("a pagina publica nao pode gastar cota da API-Football")

    monkeypatch.setattr(requests, "get", explode)
    monkeypatch.setattr(httpx, "get", explode)
    monkeypatch.setattr(httpx.Client, "get", explode)
    assert public_router.public_jogo(99)["fixture_id"] == 99


def test_jogo_inexistente_e_404_e_nao_fica_no_cache(banco):
    banco["FROM fixtures WHERE fixture_id"] = []
    with pytest.raises(HTTPException) as erro:
        public_router.public_jogo(12345)
    assert erro.value.status_code == 404
    assert not any(k.startswith("jogo_publico:12345") for k in cache_publico._dados)


def test_sitemap_lista_os_jogos_futuros(monkeypatch):
    import agent_web
    monkeypatch.setattr(jogo_publico, "get_connection", lambda: _Conn({
        "FROM fixtures": [{"fixture_id": 99, "home_team": "Atlético-MG", "away_team": "São Paulo",
                           "match_datetime": datetime(2026, 10, 18, 16, 0)}],
    }))
    xml_txt = agent_web.sitemap_xml()
    assert f"{agent_web.SITE}/jogo/99/atletico-mg-x-sao-paulo" in xml_txt


def test_sitemap_sai_sem_banco(monkeypatch):
    import agent_web

    def sem_banco():
        raise RuntimeError("banco fora")

    monkeypatch.setattr(jogo_publico, "get_connection", sem_banco)
    xml_txt = agent_web.sitemap_xml()
    assert "/jogo/" not in xml_txt
    assert "</urlset>" in xml_txt


def test_robots_nao_bloqueia_a_pagina_publica():
    """`Disallow: /jogos` e' prefixo: um `Disallow: /jogo` pegaria a vitrine."""
    caminho = os.path.join(os.path.dirname(_BACKEND), "frontend", "public", "robots.txt")
    with open(caminho, encoding="utf-8") as f:
        regras = [l.split(":", 1)[1].strip() for l in f if l.lower().startswith("disallow:")]
    assert not any("/jogo/1/a-x-b".startswith(r) for r in regras if r)
