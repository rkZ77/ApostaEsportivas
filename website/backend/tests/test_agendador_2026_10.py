"""Agendador de volta (08/10/2026) · as travas que faltaram em 01/08."""
import asyncio
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import agendador as ag  # noqa: E402

BR = ag.BR


def _prod(monkeypatch, ambiente="production", app_env="production", efeitos="on", chave=None):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", ambiente)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("SIDE_EFFECTS", efeitos)
    if chave is None:
        monkeypatch.delenv("AGENDADOR", raising=False)
    else:
        monkeypatch.setenv("AGENDADOR", chave)


# ── so' em producao ─────────────────────────────────────────────────────────
def test_liga_so_no_ambiente_production(monkeypatch):
    _prod(monkeypatch)
    assert ag.habilitado()


@pytest.mark.parametrize("kw", [
    {"ambiente": "no-prod"},          # mesmo codigo, mesmo banco: o caso de 01/08
    {"ambiente": "dev"},
    {"ambiente": ""},                 # rodando fora do Railway
    {"app_env": "development"},
    {"efeitos": "off"},
    {"chave": "off"},
])
def test_qualquer_trava_desliga(monkeypatch, kw):
    _prod(monkeypatch, **kw)
    assert not ag.habilitado()


def test_iniciar_fora_da_producao_nao_cria_laco(monkeypatch):
    _prod(monkeypatch, ambiente="no-prod")
    assert ag.iniciar() is False


# ── cota ────────────────────────────────────────────────────────────────────
def test_cota():
    assert ag.cota_permite({"usado": 1000, "limite": 7500}, 0.8) == (True, None)
    pode, motivo = ag.cota_permite({"usado": 6100, "limite": 7500}, 0.8)
    assert not pode and "81%" in motivo
    assert ag.cota_permite(None, 0.8)[0] is False          # sem leitura, nao gasta
    assert ag.cota_permite({"usado": 0, "limite": None}, 0.8)[0] is False


@pytest.mark.parametrize("valor, esperado", [(None, 0.8), ("0.5", 0.5), ("9", 1.0), ("x", 0.8)])
def test_teto_de_cota(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("AGENDADOR_TETO_COTA", raising=False)
    else:
        monkeypatch.setenv("AGENDADOR_TETO_COTA", valor)
    assert ag.teto_de_cota() == esperado


# ── quando roda ─────────────────────────────────────────────────────────────
def _uma_volta(monkeypatch, hora, minuto=0, ja_tem=(), terminou=()):
    reivindicadas, disparadas = set(ja_tem), []
    monkeypatch.setattr(ag, "terminou_hoje", lambda t, d: t in terminou)

    def reivindicar(t, d, origem="agendador"):
        if t in reivindicadas:
            return False
        reivindicadas.add(t)
        return True
    monkeypatch.setattr(ag, "reivindicar", reivindicar)

    async def executar(t, d):
        disparadas.append(t.nome)
    monkeypatch.setattr(ag, "executar", executar)

    async def rodar():
        nomes = await ag.uma_volta(datetime(2026, 10, 8, hora, minuto, tzinfo=BR))
        await asyncio.sleep(0)
        return nomes
    return asyncio.run(rodar())


def test_tudo_as_9h(monkeypatch):
    assert _uma_volta(monkeypatch, 9, 5) == ["tudo"]


def test_quem_clicou_de_manha_nao_ganha_segunda_geracao(monkeypatch):
    assert "tudo" not in _uma_volta(monkeypatch, 9, 5, ja_tem={"tudo"})


def test_fechamento_espera_o_tudo_terminar(monkeypatch):
    assert "fechamento" not in _uma_volta(monkeypatch, 10, 0, ja_tem={"tudo"})
    assert "fechamento" in _uma_volta(monkeypatch, 10, 0, ja_tem={"tudo"}, terminou={"tudo"})


def test_deploy_de_tarde_ainda_gera_o_dia(monkeypatch):
    assert "tudo" in _uma_volta(monkeypatch, 15, 30)


def test_fora_da_janela_nada(monkeypatch):
    assert _uma_volta(monkeypatch, 2, 0) == []


def test_madrugada_resultados_e_medicoes(monkeypatch):
    assert _uma_volta(monkeypatch, 3, 10) == ["resultados_madrugada"]
    assert _uma_volta(monkeypatch, 6, 10) == ["medicoes"]


def test_toda_tarefa_aponta_pra_um_comando_que_existe():
    from routers import admin
    for t in ag.TAREFAS:
        assert t.comando in ("tudo", "medicoes") or t.comando in admin._PIPELINE_SCRIPTS, t.nome


def test_medicoes_existem_no_motor():
    from routers import admin
    for _, _, caminho, _ in ag.MEDICOES:
        assert os.path.exists(os.path.join(admin._PIPELINE_DIR, caminho)), caminho
