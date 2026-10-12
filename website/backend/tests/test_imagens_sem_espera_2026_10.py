"""Fotos e escudos sem espera (12/10/2026). Sem rede: o provedor e' dublado."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import main  # noqa: E402
from routers import fixtures  # noqa: E402


class _Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


def test_sem_foto_no_provedor_fica_guardado(monkeypatch, tmp_path):
    """Jogador sem foto ia ao provedor a CADA visita (ate' 8s)."""
    monkeypatch.setattr(main, "_logo_disk_cache", tmp_path)
    chamadas = []
    monkeypatch.setattr(main.httpx, "get", lambda url, timeout=None: chamadas.append(url) or _Resp(404))
    assert main._buscar_e_guardar_imagem("player", 9, paletizar=False) is None
    assert main._buscar_e_guardar_imagem("player", 9, paletizar=False) is None
    assert len(chamadas) == 1                          # a segunda nem pergunta

    r = asyncio.run(main._serve_logo("player", 9, paletizar=False))
    assert r.status_code == 404
    assert "max-age" in r.headers.get("cache-control", "")   # o navegador tambem guarda


def test_erro_de_rede_nao_vira_sem_foto(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_logo_disk_cache", tmp_path)
    monkeypatch.setattr(main.httpx, "get", lambda url, timeout=None: _Resp(503))
    main._buscar_e_guardar_imagem("player", 9, paletizar=False)
    assert not list(tmp_path.glob("*.sem"))


def test_foto_baixada_vai_pro_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_logo_disk_cache", tmp_path)
    monkeypatch.setattr(main.httpx, "get", lambda url, timeout=None: _Resp(200, b"png"))
    monkeypatch.setattr(main, "_reduzir_logo", lambda bruto, paletizar=True: bruto)
    assert main._buscar_e_guardar_imagem("player", 7, paletizar=False) == b"png"
    assert list(tmp_path.glob("player_7_*.png"))


def test_raio_x_pede_o_aquecimento_dos_jogadores_e_escudos(monkeypatch):
    pedidos = []
    monkeypatch.setattr(fixtures, "aquecer_imagens", lambda itens: pedidos.extend(itens))
    dados = {"fixture": {"home_team_id": 10, "away_team_id": 20},
             "jogadores": {"home": {"lista": [{"player_id": 1}, {"player_id": 2}]},
                           "away": {"lista": [{"player_id": 3}]}}}
    fixtures._aquecer_imagens_do_raio_x(dados)
    assert set(pedidos) == {("player", 1), ("player", 2), ("player", 3), ("team", 10), ("team", 20)}


def test_main_entrega_o_aquecimento_ao_raio_x():
    assert fixtures.aquecer_imagens is main.aquecer_imagens
