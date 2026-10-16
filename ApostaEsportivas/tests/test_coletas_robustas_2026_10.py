"""Coletas que nao caem por um item ruim (2026-10-16).

Depois do Club Leon sem id derrubar a classificacao da Liga MX, uma auditoria
das coletas achou o mesmo formato de defeito em varios lugares: um item ruim
(id nulo, payload torto, erro de API numa liga) matava o lote, o estagio ou
o atualizar inteiro, ou -- pior -- virava dado errado em silencio.
"""
import os

import pytest

os.environ.setdefault("API_FOOTBALL_KEY", "teste")

from collectors.match_statistics_sync_service import MatchStatisticsSyncService
from collectors.calendario_service import linhas_da_temporada

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

CASA, FORA = 10, 20


def _folha(team_id, nome):
    return {"team": {"id": team_id}, "statistics": [nome]}


def test_lado_da_folha_pelo_id_do_visitante_quando_o_mandante_vem_nulo():
    folha = [_folha(None, "c"), _folha(FORA, "f")]
    casa, fora, _, _ = MatchStatisticsSyncService._separar_lados(folha, CASA, FORA)
    assert (casa, fora) == (["c"], ["f"])


def test_lado_da_folha_nunca_e_chutado():
    """Antes: stats[0] nao e' o mandante => stats[1] e'. Com os dois ids
    nulos isso trocava escanteio/cartao de casa e fora sem erro."""
    folha = [_folha(None, "a"), _folha(None, "b")]
    with pytest.raises(ValueError):
        MatchStatisticsSyncService._separar_lados(folha, CASA, FORA)


def test_lado_da_folha_invertida_continua_certo():
    folha = [_folha(FORA, "f"), _folha(CASA, "c")]
    casa, fora, _, _ = MatchStatisticsSyncService._separar_lados(folha, CASA, FORA)
    assert (casa, fora) == (["c"], ["f"])


def test_calendario_sem_jogo_repetido_no_lote():
    jogo = {"fixture": {"id": 1, "status": {"short": "NS"}}, "teams": {}, "league": {}}
    linhas = linhas_da_temporada([jogo, jogo], 71, 2026)
    assert len(linhas) == 1


def test_estagio_que_falha_nao_derruba_os_seguintes(monkeypatch):
    import atualizar_jogos as mod
    rodou = []
    coletor = mod.DataCollectorMain.__new__(mod.DataCollectorMain)

    def _ok(nome):
        return lambda *a, **kw: rodou.append(nome)

    def _quebra(*_a, **_kw):
        raise KeyError("status")

    coletor.run_stage_0 = _quebra
    for n in ("1", "2", "3", "4", "6", "5"):
        setattr(coletor, f"run_stage_{n}", _ok(n))
    coletor.run_stage_escalacao = _ok("escalacao")
    coletor.run_stage_extra = lambda qual, teto: rodou.append(qual)

    with pytest.raises(SystemExit) as saida:
        coletor.run_all(mode="custom", days=7)
    assert saida.value.code == 1
    assert rodou == ["1", "2", "3", "4", "escalacao", "eventos", "clima", "6", "5"]


def test_status_nao_apaga_o_arbitro_ja_gravado():
    with open(os.path.join(SRC, "collectors", "fixture_status_sync_service.py"),
              encoding="utf-8") as fh:
        assert "referee = COALESCE(%s, referee)" in fh.read()
