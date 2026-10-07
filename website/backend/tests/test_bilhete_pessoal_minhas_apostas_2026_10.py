"""Bilhete pessoal em Minhas Apostas (07/10/2026): a perna de time vira o
mercado que o acompanhamento ao vivo da IA ja' sabe ler, e o resultado da
liquidacao vence a leitura ao vivo."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import bilhete_pessoal as bp  # noqa: E402
import market_form  # noqa: E402

BASE = {"fixture_id": 10, "home_team_id": 1, "away_team_id": 2, "home": "Casa", "away": "Fora"}


def time(**k):
    return {**BASE, "tipo": "time", "mercado": "escanteios", "direcao": "mais", "linha": 9.5, **k}


@pytest.mark.parametrize("perna, esperado", [
    (time(), ("Escanteios", "corners", "Over 9.5")),
    (time(mercado="cartoes_time", lado_time="away", direcao="menos", linha=3.5),
     ("Cartões Fora", "cards", "Under 3.5")),
    (time(mercado="gols_time", lado_time="home", linha=1.5, periodo="1t"),
     ("Gols Casa 1º Tempo", "goals", "Over 1.5")),
    (time(mercado="btts"), ("Ambas Marcam", "btts", "Sim")),
    (time(mercado="faltas", linha=22), ("Faltas", "fouls", "Over 22")),
])
def test_mercado_ao_vivo(perna, esperado):
    assert bp.mercado_ao_vivo(perna) == esperado


def test_escopo_e_tempo_saem_certos_pro_motor_ao_vivo():
    market, mtype, _ = bp.mercado_ao_vivo(time(mercado="escanteios_time", lado_time="away", periodo="1t"))
    assert market_form.escopo_do_mercado(market) == "away"
    assert market_form.e_mercado_de_primeiro_tempo(market, mtype)
    market, _, _ = bp.mercado_ao_vivo(time(mercado="chutes_alvo", periodo="2t"))
    assert market_form.e_mercado_de_segundo_tempo(market)


def test_perna_de_jogador_nao_tem_mercado_ao_vivo():
    assert bp.mercado_ao_vivo({**BASE, "tipo": "jogador", "estat": "chutes", "minimo": 2}) is None


def test_resultado_gravado_vence_a_leitura_ao_vivo(monkeypatch):
    from routers import live
    monkeypatch.setattr(live, "_enrich_leg", lambda *a, **k: {
        "is_live": False, "pick_status": "winning", "is_locked": False,
        "current_val": 12, "home_stats": {}, "away_stats": {}})
    leg = live._perna_pessoal_ao_vivo(time(resultado="RED", valor=8, descricao="Escanteios +9.5"))
    assert leg["pick_status"] == "losing" and leg["is_locked"]
    assert leg["current_val"] == 8 and leg["descricao"] == "Escanteios +9.5"
    assert "home_stats" not in leg


def test_perna_de_jogador_mostra_o_estado_do_jogo(monkeypatch):
    from routers import live
    monkeypatch.setattr(live, "_fetch_fixture", lambda fid: {
        "fixture": {"status": {"short": "2H", "elapsed": 60}, "timestamp": 1},
        "goals": {"home": 1, "away": 0}})
    leg = live._perna_pessoal_ao_vivo({**BASE, "tipo": "jogador", "estat": "chutes", "minimo": 2,
                                       "player_id": 7, "player_name": "Hulk",
                                       "descricao": "Hulk · 2+ chutes"})
    assert leg["is_live"] and leg["pick_status"] == "neutral" and leg["stat_label"] == "Hulk"
    assert leg["market"] == "Hulk · 2+ chutes"


def _leg_de_cartao(monkeypatch, amarelo_casa, verm_casa, amarelo_fora):
    from routers import live
    monkeypatch.setattr(live, "_enrich_leg", lambda *a, **k: {
        "is_live": True, "is_ft": False, "pick_status": "losing", "is_locked": True,
        "current_val": amarelo_casa + 2 * verm_casa + amarelo_fora,
        "home_stats": {"Yellow Cards": amarelo_casa, "Red Cards": verm_casa},
        "away_stats": {"Yellow Cards": amarelo_fora, "Red Cards": 0}})
    return live


def test_cartao_do_bilhete_pessoal_conta_so_amarelo(monkeypatch):
    live = _leg_de_cartao(monkeypatch, 2, 1, 1)
    # Menos de 4.5: com o vermelho valendo 2 seriam 5 (perdendo e travado);
    # pela regra do bilhete sao 3 amarelos, ainda ganhando.
    leg = live._perna_pessoal_ao_vivo(time(mercado="cartoes", direcao="menos", linha=4.5))
    assert leg["current_val"] == 3 and leg["pick_status"] == "winning" and not leg["is_locked"]


def test_cartao_do_time_le_o_lado_certo(monkeypatch):
    live = _leg_de_cartao(monkeypatch, 2, 1, 3)
    leg = live._perna_pessoal_ao_vivo(time(mercado="cartoes_time", lado_time="away", linha=2.5))
    assert leg["current_val"] == 3 and leg["pick_status"] == "winning" and leg["is_locked"]


def test_dia_de_brasilia_de_timestamp_utc():
    from routers import live
    # 01:30 UTC de 08/10 ainda e' 07/10 em Brasilia.
    assert live._data_br(dt.datetime(2026, 10, 8, 1, 30)) == dt.date(2026, 10, 7)
