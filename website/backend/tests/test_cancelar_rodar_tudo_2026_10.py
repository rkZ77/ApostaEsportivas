"""Cancelar o Rodar Tudo pelo /admin (2026-10-09, pedido do usuario).

Prende: o cancelar encerra a etapa em andamento (processo real), o laco nao
comeca a proxima, o status fica `cancelado` e nao `error`, e um pedido que
sobrou nao mata a rodada seguinte antes de comecar.
"""
import asyncio
import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from routers import admin  # noqa: E402


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    lento = tmp_path / "lento.py"
    lento.write_text("import time\nprint('comecou', flush=True)\ntime.sleep(60)\n")
    rapido = tmp_path / "rapido.py"
    rapido.write_text("print('ok')\n")
    monkeypatch.setattr(admin, "_PIPELINE_DIR", str(tmp_path))
    monkeypatch.setattr(admin, "_PIPELINE_SCRIPTS",
                        {"etapa_1": "rapido.py", "etapa_2": "lento.py", "etapa_3": "rapido.py"})
    monkeypatch.setattr(admin, "_TUDO_STEPS", ["etapa_1", "etapa_2", "etapa_3"])
    monkeypatch.setattr(admin, "_PIPELINE_ARGS", {})
    monkeypatch.setattr(admin, "_notificar_picks_publicados", lambda: None)
    monkeypatch.setattr(admin, "_ESPERA_PARA_MATAR", 1)
    for k in ("tudo", "etapa_1", "etapa_2", "etapa_3"):
        admin._pipeline_status.pop(k, None)
    admin._cancelamentos.clear()
    admin._processos.clear()


async def _cancelar_quando_a_etapa_2_rodar():
    for _ in range(200):
        if "etapa_2" in admin._processos:
            break
        await asyncio.sleep(0.05)
    r = await admin.cancel_pipeline(admin.PipelineCommandBody(command="tudo"),
                                    current_user={"email": "a@b"})
    return r


def test_cancelar_encerra_a_etapa_e_nao_comeca_a_proxima(scripts):
    async def cenario():
        tarefa = asyncio.ensure_future(admin._run_tudo())
        r = await _cancelar_quando_a_etapa_2_rodar()
        await asyncio.wait_for(tarefa, timeout=30)
        return r
    r = asyncio.run(cenario())
    assert r["encerradas"] == ["etapa_2"]
    assert admin._pipeline_status["etapa_1"]["status"] == "ok"
    assert admin._pipeline_status["etapa_2"]["status"] == "cancelado"
    assert "etapa_3" not in admin._pipeline_status          # nunca comecou
    tudo = admin._pipeline_status["tudo"]
    assert tudo["status"] == "cancelado" and "1 de 3" in tudo["log"]
    assert not admin._processos and not admin._cancelamentos


def test_cancelar_sem_nada_rodando_avisa(scripts):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin.cancel_pipeline(admin.PipelineCommandBody(command="tudo"),
                                          current_user={}))
    assert e.value.status_code == 409


def test_pedido_que_sobrou_nao_mata_a_rodada_seguinte(scripts, monkeypatch):
    monkeypatch.setattr(admin, "_TUDO_STEPS", ["etapa_1", "etapa_3"])
    admin._cancelamentos.add("tudo")
    asyncio.run(admin._run_tudo())
    assert admin._pipeline_status["tudo"]["status"] == "ok"
