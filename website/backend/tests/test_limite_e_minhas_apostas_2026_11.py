"""24/11/2026: "quando da' muita request o site cai".

O QUE A INVESTIGACAO ACHOU (PROD, 7 dias): nenhum 5xx; o que derrubava a tela
era 429 do limite de requisicoes e rota presa esperando.

  1. O limite contava POR IP. Celular no Brasil sai por CGNAT (muita gente num
     IP so'), entao varias pessoas dividiam os mesmos 300/min.
  2. O /admin acompanhando o pipeline gastava o MESMO balde do resto do site: em
     23/11 o 429 caiu ate' em /api/auth/me.
  3. /api/live/my-picks levava 3 a 6 s: buscava na API-Football o jogo de todo
     pick que o usuario ja' seguiu na vida, a cada 5 min (o front chama a cada
     60 s), e o laco nem mostrava os ja' resolvidos.
"""
import os

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "x" * 32)

import main  # noqa: E402
import auth_utils  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _token(sub: str) -> str:
    return auth_utils.create_access_token({"sub": sub, "id": int(sub)})


@pytest.fixture
def cliente(monkeypatch):
    async def ok():
        return {"ok": True}

    rotas = [APIRoute("/api/_teste_ok", ok, methods=["GET"]),
             APIRoute("/api/admin/_teste_ok", ok, methods=["GET"])]
    for r in rotas:
        main.app.router.routes.insert(0, r)
    main._rate_store.clear()
    monkeypatch.setattr(main, "RATE_LIMIT", 3)
    monkeypatch.setattr(main, "RATE_LIMIT_ADMIN", 5)
    try:
        yield TestClient(main.app, raise_server_exceptions=False)
    finally:
        for r in rotas:
            main.app.router.routes.remove(r)
        main._rate_store.clear()


# ── chave do limite ─────────────────────────────────────────────────────────
class _Req:
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.client = type("C", (), {"host": "1.2.3.4"})()


def test_logado_conta_por_usuario_visitante_por_ip():
    assert main._chave_do_limite(_Req({main.COOKIE_NAME: _token("7")})) == "u:7"
    assert main._chave_do_limite(
        _Req(headers={"Authorization": f"Bearer {_token('8')}"})) == "u:8"
    assert main._chave_do_limite(_Req()) == "ip:1.2.3.4"


def test_token_forjado_nao_ganha_balde_proprio():
    """Sem conferir a assinatura, inventar um `sub` por requisicao fugiria do
    limite pra sempre."""
    forjado = _token("7")[:-4] + "AAAA"
    assert main._chave_do_limite(_Req({main.COOKIE_NAME: forjado})) == "ip:1.2.3.4"


# ── o limite de verdade ─────────────────────────────────────────────────────
def test_dois_usuarios_no_mesmo_ip_nao_dividem_o_limite(cliente):
    a = {main.COOKIE_NAME: _token("1")}
    for _ in range(3):
        assert cliente.get("/api/_teste_ok", cookies=a).status_code == 200
    assert cliente.get("/api/_teste_ok", cookies=a).status_code == 429
    # Mesmo IP (o do TestClient), outra pessoa: passa.
    assert cliente.get("/api/_teste_ok", cookies={main.COOKIE_NAME: _token("2")}).status_code == 200


def test_429_diz_quando_tentar_de_novo(cliente):
    for _ in range(3):
        cliente.get("/api/_teste_ok")
    r = cliente.get("/api/_teste_ok")
    assert r.status_code == 429 and r.headers.get("retry-after") == str(main.RATE_WINDOW)


def test_admin_tem_balde_proprio(cliente):
    """O painel do pipeline nao derruba o resto do site pro proprio admin."""
    a = {main.COOKIE_NAME: _token("1")}
    for _ in range(5):
        assert cliente.get("/api/admin/_teste_ok", cookies=a).status_code == 200
    assert cliente.get("/api/admin/_teste_ok", cookies=a).status_code == 429
    assert cliente.get("/api/_teste_ok", cookies=a).status_code == 200


# ── /suggestions/odds-agora ─────────────────────────────────────────────────
class _CurOdds:
    def __init__(self, n):
        self.n, self._r = n, []

    def execute(self, sql, params=None):
        self._r = ([{"pick_type": "vip", "id": i, "fixture_id": 100 + i, "market_type": "goals",
                     "market": "Gols", "line": "Over 2.5", "odd": 1.80} for i in range(self.n)]
                   if "picks_vip" in sql else [])

    def fetchall(self):
        return self._r

    def close(self):
        pass


class _ConnOdds:
    def __init__(self, n):
        self._cur = _CurOdds(n)

    def cursor(self):
        return self._cur

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def odds(monkeypatch):
    import threading
    import time
    from routers import live, suggestions
    chamadas = []

    def ler(fid):
        chamadas.append(fid)
        time.sleep(0.2)
        return [{"fid": fid}]
    monkeypatch.setattr(live, "_fetch_prematch_odds", ler)
    monkeypatch.setattr(live, "_find_prematch_odd", lambda *a, **k: (1.90, "Casa"))
    monkeypatch.setattr(live, "_casas_ativas", lambda: [])
    monkeypatch.setattr(suggestions, "get_connection", lambda: _ConnOdds(8))
    suggestions._odds_agora_cache.update({"ts": 0.0, "dados": {}})
    yield suggestions, chamadas, threading
    suggestions._odds_agora_cache.update({"ts": 0.0, "dados": {}})


def test_odds_agora_le_em_paralelo(odds):
    import time
    suggestions, chamadas, _ = odds
    t0 = time.time()
    r = suggestions.odds_agora_prejogo(current_user={})
    assert len(r["picks"]) == 8 and len(chamadas) == 8
    assert time.time() - t0 < 1.0        # 8 x 0,2 s em serie dariam 1,6 s


def test_odds_agora_uma_atualizacao_por_vez(odds):
    """Quem chega durante a atualizacao leva a leitura anterior na hora."""
    import time
    suggestions, chamadas, threading = odds
    suggestions._odds_agora_cache.update({"ts": 1.0, "dados": {"vip:0": {"odd": 1.5}}})
    t = threading.Thread(target=suggestions.odds_agora_prejogo, kwargs={"current_user": {}})
    t.start()
    time.sleep(0.05)
    t0 = time.time()
    r = suggestions.odds_agora_prejogo(current_user={})
    assert time.time() - t0 < 0.1 and r["picks"] == {"vip:0": {"odd": 1.5}}
    t.join()
    assert len(chamadas) == 8            # so' a primeira foi a API


# ── /admin/overview ─────────────────────────────────────────────────────────
def test_admin_overview_uma_ida_por_tabela(monkeypatch):
    """Eram ~28 consultas em serie (2-6 s). Agora uma por tabela de picks, e o
    formato da resposta e' o mesmo de antes."""
    from routers import admin
    consultas = []

    class _Cur:
        def execute(self, sql, params=None):
            consultas.append(" ".join(sql.split()))
            self._sql = sql

        def fetchone(self):
            if "ontem_green" in self._sql:
                return {"n": 4, "pendentes": 1, "ontem_green": 2, "ontem_red": 1,
                        "ontem_push": 0, "ontem_pendentes": 0, "velhos": 1}
            return {}

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(admin, "get_connection", lambda: _Conn())
    monkeypatch.setattr(admin, "_api_football_status", lambda: None)
    r = admin.admin_overview(current_user={})
    assert len(consultas) <= 15, len(consultas)
    assert not any("COUNT(*) FROM player_match_stats" in c for c in consultas)
    assert r["picks_hoje"]["vip"] == {"n": 4, "pendentes": 1}
    assert r["ontem"]["vip"] == {"green": 2, "red": 1, "push": 0, "pendentes": 0}
    assert r["pendentes_antigos"] == 8      # 1 por tabela, nas 8 do bloco "ontem"


# ── /live/my-picks ──────────────────────────────────────────────────────────
def test_minhas_apostas_so_aquece_o_que_vai_aparecer():
    fonte = open(os.path.join(RAIZ, "routers", "live.py"), encoding="utf-8").read()
    rota = fonte[fonte.index('@router.get("/my-picks")'):]
    aquece = rota[rota.index("Pré-aquece o cache de fixtures"):rota.index("_fetch_fixtures_bulk(list(all_fixture_ids))")]
    assert "def _vai_aparecer" in aquece
    # Cada familia de pick passa pelo filtro antes de entrar no lote.
    for trecho in ('vip_map.values():\n        if p["fixture_id"] and _vai_aparecer(p)',
                   'free_map.values():\n        if p["fixture_id"] and _vai_aparecer(p)',
                   'live_map.values():\n        if p["fixture_id"] and _vai_aparecer(p)',
                   "m.values() if _vai_aparecer(p)",
                   "alavancagem_map.values():\n        if not _vai_aparecer(p)"):
        assert trecho in aquece, trecho
