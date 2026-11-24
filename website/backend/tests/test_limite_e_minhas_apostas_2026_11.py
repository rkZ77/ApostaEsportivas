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
