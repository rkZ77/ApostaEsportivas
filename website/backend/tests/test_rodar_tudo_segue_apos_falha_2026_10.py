"""Bug de 07/10: o "Rodar Tudo" do painel parava na primeira etapa com erro.
O Dica quebrou e VIP, multipla, bingo, alavancagem, faltas, jogador, Pick Boost
e resultados nao rodaram -- nem o aviso de picks publicados saiu."""
import asyncio

from routers import admin


def _rodar(monkeypatch, passos, quebram):
    rodados, avisos = [], []

    async def falso(cmd, script, args=None, extra=None, espelhar_em=None):
        rodados.append(cmd)
        admin._pipeline_status[cmd] = (
            {"status": "error", "error": "Traceback...\nTypeError: string indices"}
            if cmd in quebram else {"status": "ok"})

    monkeypatch.setattr(admin, "_TUDO_STEPS", passos)
    monkeypatch.setattr(admin, "_run_and_track", falso)
    monkeypatch.setattr(admin, "_notificar_picks_publicados", lambda: avisos.append(1))
    asyncio.run(admin._run_tudo())
    return rodados, avisos


def test_etapa_que_falha_nao_para_as_seguintes(monkeypatch):
    passos = ["atualizar_jogos", "gerar_free", "gerar_vip", "atualizar_resultados"]
    rodados, avisos = _rodar(monkeypatch, passos, quebram={"gerar_free"})
    assert rodados == passos
    st = admin._pipeline_status["tudo"]
    assert st["status"] == "error"
    assert "'gerar_free': TypeError: string indices" in st["error"]
    assert avisos == [1]          # o VIP gravou: o aviso sai


def test_sem_gerador_ok_nao_avisa(monkeypatch):
    passos = ["gerar_free", "atualizar_resultados"]
    _, avisos = _rodar(monkeypatch, passos, quebram={"gerar_free"})
    assert avisos == []


def test_tudo_ok(monkeypatch):
    passos = ["atualizar_jogos", "gerar_vip"]
    _, avisos = _rodar(monkeypatch, passos, quebram=set())
    assert admin._pipeline_status["tudo"]["status"] == "ok"
    assert avisos == [1]
