"""Resultado na hora, e nao no apito final nem na visita (11/10/2026).

Dois pedidos do usuario:
  1. "mercados de 1º tempo so' dao green quando o jogo acaba" -- o pick de 1o
     tempo era liquidado so' com `is_ft`, mesmo com o numero congelado desde
     o intervalo.
  2. "so' atualiza quando eu entro no site" -- a varredura era puxada por
     visita; agora o agendador a puxa a cada volta, com os mesmos freios.

Nenhum teste toca rede nem banco.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers import live  # noqa: E402


FOLHA = [
    {"team": {"id": 10},
     "statistics": [{"type": "Corner Kicks", "value": 6},
                    {"type": "Yellow Cards", "value": 3}, {"type": "Red Cards", "value": 0}],
     "statistics_1h": [{"type": "Corner Kicks", "value": 2},
                       {"type": "Yellow Cards", "value": 2}, {"type": "Red Cards", "value": 0}]},
    {"team": {"id": 20},
     "statistics": [{"type": "Corner Kicks", "value": 4},
                    {"type": "Yellow Cards", "value": 2}, {"type": "Red Cards", "value": 0}],
     "statistics_1h": [{"type": "Corner Kicks", "value": 1},
                       {"type": "Yellow Cards", "value": 1}, {"type": "Red Cards", "value": 0}]},
]


def _fixture(status, halftime=(0, 1), gols=(1, 1)):
    ht = {"home": halftime[0], "away": halftime[1]} if halftime else {}
    return {
        "fixture": {"status": {"short": status, "elapsed": 50}, "timestamp": 1_700_000_000},
        "goals": {"home": gols[0], "away": gols[1]},
        "score": {"halftime": ht},
        "teams": {"home": {"id": 10}, "away": {"id": 20}},
        "league": {"id": 71},
    }


@pytest.fixture
def jogo(monkeypatch):
    def _instalar(status, **kw):
        monkeypatch.setattr(live, "_fetch_fixture", lambda fid: _fixture(status, **kw))
        monkeypatch.setattr(live, "_fetch_stats", lambda fid, st: FOLHA)
    return _instalar


def _perna(market, line, market_type=None):
    return live._enrich_leg(1, market, line, "Casa", "Fora", 10, 20, 1.9,
                            market_type=market_type)


# ── 1º tempo fecha no intervalo ─────────────────────────────────────────────
@pytest.mark.parametrize("linha, esperado", [("Under 1.5", "GREEN"), ("Over 1.5", "RED"),
                                             ("Over 0.5", "GREEN")])
def test_gol_do_1o_tempo_liquida_no_intervalo(jogo, linha, esperado):
    jogo("HT")
    perna = _perna("Gols Mais/Menos - 1º Tempo", linha, "goals_1h")
    assert perna["periodo_encerrado"] is True
    assert live._locked_leg_result(perna) == esperado


def test_resultado_do_1o_tempo_liquida_no_intervalo(jogo):
    jogo("HT")
    perna = _perna("Resultado 1º Tempo", "2", "result")
    assert live._locked_leg_result(perna) == "GREEN"


def test_escanteio_do_1o_tempo_espera_o_2o_tempo_comecar(jogo):
    """No apito do intervalo o escanteio dos acrescimos ainda pode estar
    chegando no provedor · a folha so' vale com o 2o tempo rolando."""
    jogo("HT")
    perna = _perna("Total de Escanteios (1º Tempo)", "Under 3.5", "corners_1h")
    assert live._locked_leg_result(perna) is None

    jogo("2H")
    perna = _perna("Total de Escanteios (1º Tempo)", "Under 3.5", "corners_1h")
    assert perna["current_val"] == 3
    assert live._locked_leg_result(perna) == "GREEN"


def test_cartao_do_1o_tempo_continua_esperando_a_validacao(jogo):
    jogo("2H")
    perna = _perna("Cartões 1º Tempo", "Under 5.5", "cards_1h")
    assert perna["periodo_encerrado"] is False
    assert live._locked_leg_result(perna) is None


def test_sem_placar_do_intervalo_nao_liquida(jogo):
    jogo("2H", halftime=None)
    perna = _perna("Gols Mais/Menos - 1º Tempo", "Under 1.5", "goals_1h")
    assert live._locked_leg_result(perna) is None


def test_com_o_1o_tempo_rolando_so_trava_o_que_ja_passou(jogo):
    jogo("1H", halftime=None, gols=(1, 0))
    assert live._locked_leg_result(_perna("Gols Mais/Menos - 1º Tempo", "Under 1.5", "goals_1h")) is None
    assert live._locked_leg_result(_perna("Gols Mais/Menos - 1º Tempo", "Over 0.5", "goals_1h")) == "GREEN"


def test_jogo_inteiro_nao_fecha_no_intervalo(jogo):
    jogo("HT")
    perna = _perna("Gols Mais/Menos", "Under 2.5", "goals")
    assert perna["periodo_encerrado"] is False
    assert live._locked_leg_result(perna) is None


def test_2o_tempo_nao_fecha_no_intervalo(jogo):
    jogo("2H")
    perna = _perna("Gols Mais/Menos - 2º Tempo", "Under 2.5")
    assert perna["periodo_encerrado"] is False
    assert live._locked_leg_result(perna) is None


# ── a varredura roda sem visita ─────────────────────────────────────────────
def _varredura_ligada(monkeypatch, pendente=True):
    monkeypatch.setattr(live, "_varredura_habilitada", lambda: True)
    monkeypatch.setattr(live, "_ha_pendente_em_jogo", lambda: pendente)
    monkeypatch.setattr(live, "_sweep_state", {"last": 0.0, "running": False})
    disparos = []

    class _Thread:
        def __init__(self, target, name=None, daemon=None):
            pass

        def start(self):
            disparos.append(1)
    monkeypatch.setattr(live.threading, "Thread", _Thread)
    return disparos


def test_cota_estourada_nao_dispara(monkeypatch):
    disparos = _varredura_ligada(monkeypatch)
    assert live.maybe_resolve_pending(pode_gastar=lambda: False) is False
    assert disparos == []


def test_cota_so_e_consultada_quando_ha_pendente(monkeypatch):
    _varredura_ligada(monkeypatch, pendente=False)
    consultas = []
    live.maybe_resolve_pending(pode_gastar=lambda: consultas.append(1) or True)
    assert consultas == []


def test_com_cota_dispara(monkeypatch):
    disparos = _varredura_ligada(monkeypatch)
    assert live.maybe_resolve_pending(pode_gastar=lambda: True) is True
    assert disparos == [1]


def test_agendador_puxa_as_varreduras(monkeypatch):
    import agendador as ag
    import bilhete_pessoal
    import stats_sweep

    chamadas = {"picks": [], "stats": 0, "bilhetes": 0}
    monkeypatch.setattr(live, "maybe_resolve_pending",
                        lambda pode_gastar=None: chamadas["picks"].append(pode_gastar) or True)

    def _stats():
        chamadas["stats"] += 1
    monkeypatch.setattr(stats_sweep, "maybe_sync_finished_stats", _stats)

    class _Conn:
        def close(self):
            pass
    monkeypatch.setattr(ag, "_conexao", lambda: _Conn())

    def _bilhetes(conn):
        chamadas["bilhetes"] += 1
        return 1
    monkeypatch.setattr(bilhete_pessoal, "liquidar_de_todos", _bilhetes)
    monkeypatch.setattr(ag, "_ultima_dos_bilhetes", {"ts": 0.0})

    assert ag.varrer_resultados(agora_ts=10_000) == ["picks", "bilhetes"]
    assert chamadas["picks"] == [ag._cota_permite_agora]   # o teto de cota vai junto
    assert chamadas["stats"] == 1
    # Um minuto depois: picks e stats tem relogio proprio, bilhete espera 3 min.
    ag.varrer_resultados(agora_ts=10_060)
    assert chamadas["bilhetes"] == 1
    ag.varrer_resultados(agora_ts=10_000 + ag._INTERVALO_BILHETES)
    assert chamadas["bilhetes"] == 2


def test_bilhetes_de_todos_os_usuarios(monkeypatch):
    import bilhete_pessoal

    class _Cur:
        def execute(self, sql, args=None):
            pass

        def fetchall(self):
            return [{"user_id": 7}, {"user_id": 9}]

    class _Conn:
        commits = 0

        def cursor(self):
            return _Cur()

        def commit(self):
            _Conn.commits += 1

        def rollback(self):
            pass

    vistos = []
    monkeypatch.setattr(bilhete_pessoal, "liquidar_pendentes",
                        lambda cur, uid: vistos.append(uid) or 1)
    assert bilhete_pessoal.liquidar_de_todos(_Conn()) == 2
    assert vistos == [7, 9]
    assert _Conn.commits == 2
