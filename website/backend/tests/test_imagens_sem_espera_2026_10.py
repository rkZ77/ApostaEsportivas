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


class _ClienteFalso:
    """AsyncClient dublado: conta as idas ao provedor e demora um pouco."""

    def __init__(self, chamadas, status=200, conteudo=b"png"):
        self.chamadas, self.status, self.conteudo = chamadas, status, conteudo
        self.is_closed = False

    async def get(self, url):
        self.chamadas.append(url)
        await asyncio.sleep(0.05)
        return _Resp(self.status, self.conteudo)


def test_mesma_foto_ao_mesmo_tempo_vai_uma_vez_ao_provedor(monkeypatch, tmp_path):
    """24/11/2026: o log de PROD mostrava a mesma foto buscada 2x no segundo."""
    monkeypatch.setattr(main, "_logo_disk_cache", tmp_path)
    monkeypatch.setattr(main, "_reduzir_logo", lambda bruto, paletizar=True: bruto)
    chamadas = []
    monkeypatch.setattr(main, "_cliente_imagens", lambda: _ClienteFalso(chamadas))

    async def cinco_juntas():
        return await asyncio.gather(*[main._serve_logo("player", 5, paletizar=False)
                                      for _ in range(5)])
    respostas = asyncio.run(cinco_juntas())
    assert [r.status_code for r in respostas] == [200] * 5
    assert all(r.body == b"png" for r in respostas)
    assert len(chamadas) == 1


def test_espera_o_aquecimento_em_vez_de_buscar_em_dobro(monkeypatch, tmp_path):
    """O aquecimento do Raio-X ja' esta' buscando a foto: a tela espera ela
    chegar no disco em vez de ir ao provedor de novo."""
    import threading
    import time
    monkeypatch.setattr(main, "_logo_disk_cache", tmp_path)
    chamadas = []
    monkeypatch.setattr(main, "_cliente_imagens", lambda: _ClienteFalso(chamadas))
    with main._aquecendo_lock:
        main._aquecendo.add(("player", 6))

    def aquecimento():
        time.sleep(0.3)
        (tmp_path / f"player_6_{main._LOGO_CACHE_V}.png").write_bytes(b"do-aquecimento")
        with main._aquecendo_lock:
            main._aquecendo.discard(("player", 6))
    threading.Thread(target=aquecimento).start()

    r = asyncio.run(main._serve_logo("player", 6, paletizar=False))
    assert r.status_code == 200 and r.body == b"do-aquecimento"
    assert chamadas == []


def test_sem_foto_ao_mesmo_tempo_tambem_vira_uma_busca(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_logo_disk_cache", tmp_path)
    chamadas = []
    monkeypatch.setattr(main, "_cliente_imagens", lambda: _ClienteFalso(chamadas, status=404))

    async def tres():
        return await asyncio.gather(*[main._serve_logo("player", 8, paletizar=False)
                                      for _ in range(3)])
    respostas = asyncio.run(tres())
    assert [r.status_code for r in respostas] == [404] * 3
    assert all("max-age" in r.headers.get("cache-control", "") for r in respostas)
    assert len(chamadas) == 1


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
