"""Motor Ao Vivo liga sozinho com jogo das nossas ligas em campo e desliga
quando nao sobra nenhum (08/10/2026, pedido do usuario)."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers import live_picks as lp  # noqa: E402


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    monkeypatch.setitem(lp._watch_state, "ativo", False)
    monkeypatch.setitem(lp._watch_state, "origem", None)
    monkeypatch.setitem(lp._desligado_no_painel_em, "dia", None)
    monkeypatch.delenv("LIVE_AUTO", raising=False)
    monkeypatch.setattr(lp, "_pipeline_dir", lambda: "/motor")
    ligou = []
    monkeypatch.setattr(lp, "_ligar_laco", lambda *a, **k: ligou.append(k.get("origem")))
    return ligou


def _rodar(monkeypatch, jogo=True, reivindica=True):
    monkeypatch.setattr(lp, "_ha_jogo_na_janela", lambda: jogo)
    monkeypatch.setattr(lp, "_reivindicar_laco", lambda: reivindica)
    return asyncio.run(lp.supervisionar_automatico())


def test_liga_com_jogo_em_campo(monkeypatch, estado_limpo):
    assert _rodar(monkeypatch) == "ligou"
    assert estado_limpo == ["auto"]


def test_sem_jogo_nao_liga(monkeypatch, estado_limpo):
    assert _rodar(monkeypatch, jogo=False) is None and estado_limpo == []


def test_outro_worker_ja_tem_o_laco(monkeypatch, estado_limpo):
    assert _rodar(monkeypatch, reivindica=False) is None and estado_limpo == []


def test_ja_ligado_nao_liga_de_novo(monkeypatch, estado_limpo):
    monkeypatch.setitem(lp._watch_state, "ativo", True)
    assert _rodar(monkeypatch) is None


def test_respeita_o_desliga_do_painel_no_dia(monkeypatch, estado_limpo):
    monkeypatch.setitem(lp._desligado_no_painel_em, "dia", lp._hoje_br())
    assert _rodar(monkeypatch) is None and estado_limpo == []


def test_variavel_desliga_o_automatico(monkeypatch, estado_limpo):
    monkeypatch.setenv("LIVE_AUTO", "off")
    assert _rodar(monkeypatch) is None


def test_laco_automatico_desliga_quando_acaba_o_jogo(monkeypatch):
    """Ligado pelo automatico, sem jogo: sai do laco em vez de hibernar."""
    monkeypatch.setitem(lp._watch_state, "ativo", True)
    monkeypatch.setitem(lp._watch_state, "origem", "auto")
    monkeypatch.setattr(lp, "_ha_jogo_na_janela", lambda: False)
    monkeypatch.setattr(lp, "_salvar_watch", lambda *a, **k: None)
    rodou = []

    async def rodar(*a, **k):
        rodou.append(1)
    monkeypatch.setattr(lp, "_rodar", rodar)
    asyncio.run(asyncio.wait_for(lp._laco_de_acompanhamento(8, False, None), timeout=5))
    assert rodou == []
    assert lp._watch_state["ativo"] is False
    assert "sem jogo" in lp._watch_state["motivo_parada"]


def test_laco_do_painel_continua_hibernando(monkeypatch):
    """O do painel nao muda: sem jogo ele hiberna, nao desliga."""
    monkeypatch.setitem(lp._watch_state, "ativo", True)
    monkeypatch.setitem(lp._watch_state, "origem", "painel")
    monkeypatch.setattr(lp, "_ha_jogo_na_janela", lambda: False)
    monkeypatch.setattr(lp, "_salvar_watch", lambda *a, **k: None)
    monkeypatch.setattr(lp, "_INTERVALO_HIBERNANDO_MIN", 0)

    async def roda_um_pouco():
        tarefa = asyncio.create_task(lp._laco_de_acompanhamento(8, False, None))
        await asyncio.sleep(0.05)
        hibernando = lp._watch_state["hibernando"]
        lp._watch_state["ativo"] = False
        await asyncio.wait_for(tarefa, timeout=5)
        return hibernando
    assert asyncio.run(roda_um_pouco()) is True
