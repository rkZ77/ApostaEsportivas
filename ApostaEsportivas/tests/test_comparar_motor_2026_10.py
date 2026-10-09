# -*- coding: utf-8 -*-
"""O comparador obrigatorio (scripts/comparar_motor.py) e as pecas novas que
ele mede: seletor por valor e stake pela probabilidade.

Prende: a formula do EV, o EV no limite inferior penaliza amostra curta, o
seletor so' reordena aprovados, a stake pela probabilidade nunca passa a de
hoje quando confidence > probabilidade, a comparacao e' PAREADA nas mesmas
partidas (sem pick = 0), e o veredito exige margem, as duas metades e CLV.
"""
from datetime import date

import pytest

from services.pick_engine import ranking
from services.pick_engine.staking import calculate_stake, calculate_stake_por_probabilidade
from scripts import comparar_motor as cm


# ---------------------------------------------------------------------------
# EV e seletor
# ---------------------------------------------------------------------------
def test_ev_e_a_formula_por_unidade():
    p, o = 0.6, 1.9
    assert p * (o - 1) - (1 - p) == pytest.approx(p * o - 1)
    c = {"taxa_real": p, "odd": o, "amostra": 10_000}
    assert ranking.ev_limite_inferior(c, z=0) == pytest.approx(round(p * o - 1, 4))


def test_ev_no_limite_inferior_cobra_amostra_curta():
    curto = {"taxa_real": 0.62, "odd": 1.85, "amostra": 8}
    longo = {"taxa_real": 0.62, "odd": 1.85, "amostra": 60}
    assert ranking.ev_limite_inferior(curto) < ranking.ev_limite_inferior(longo)
    efetiva = {**longo, "amostra_efetiva": 8}
    assert ranking.ev_limite_inferior(efetiva) == ranking.ev_limite_inferior(curto)


def test_seletor_por_valor_troca_confianca_por_valor():
    # A: mais confianca, paga pouco. B: um pouco menos provavel, paga mais.
    a = {"market_type": "goals", "taxa_real": 0.72, "odd": 1.45, "amostra": 30,
         "final_score": 0.80, "is_best_pick": True}
    b = {"market_type": "corners", "taxa_real": 0.62, "odd": 1.90, "amostra": 30,
         "final_score": 0.70}
    assert cm.escolher([a, b], "score") is a
    assert cm.escolher([a, b], "valor") is b
    assert cm.escolher([], "valor") is None


# ---------------------------------------------------------------------------
# Stake
# ---------------------------------------------------------------------------
def test_stake_pela_probabilidade_nao_passa_a_de_hoje_quando_confidence_e_maior():
    for conf, p, odd in ((0.82, 0.66, 1.80), (0.75, 0.60, 1.95), (0.70, 0.58, 1.85)):
        ev = round(p * odd - 1, 4)
        hoje = calculate_stake(confidence=conf, odd=odd, ev=ev, pick_type="vip")
        prob = calculate_stake_por_probabilidade(p, conf, odd, ev, "vip")
        assert prob[0] <= hoje[0]


def test_stake_pela_probabilidade_respeita_ev_nao_positivo():
    assert calculate_stake_por_probabilidade(0.5, 0.9, 1.9, -0.05, "vip") == (0.01, 1)


# ---------------------------------------------------------------------------
# Comparacao pareada e veredito
# ---------------------------------------------------------------------------
def _l(d, lucro, mt="goals", linha="Over 2.5", clv=0.0, prob=0.6):
    return {"data": date(2026, 9, d), "profit": lucro, "market_type": mt, "linha": linha,
            "clv": clv, "prob": prob, "result": "GREEN" if lucro > 0 else "RED",
            "units": 2, "league_id": 71}


def test_comparacao_e_pareada_e_sem_pick_vale_zero():
    atual = {1: _l(1, 0.8), 2: _l(2, -1.0)}
    var = {1: _l(1, 0.8), 3: _l(3, 0.9, "corners")}
    p = cm.pareado(atual, var)
    assert p["n"] == 3 and p["diferente"] == 2
    assert p["d"] == pytest.approx(((0.0) + (0 - -1.0) + 0.9) / 3)


def test_veredito_exige_margem_metades_e_clv():
    atual = {i: _l(i % 28 + 1, -1.0 if i % 2 else 0.85, "goals") for i in range(80)}
    melhor = {i: _l(i % 28 + 1, 0.85, "corners") for i in range(80)}
    assert cm.veredito(cm.pareado(atual, melhor)).startswith("MELHOR")
    igual = cm.pareado(atual, dict(atual))
    assert cm.veredito(igual).startswith("IDENTICA")
    # Mesma taxa de acerto do atual, so' em partidas trocadas: e' sorte.
    ruido = {i: _l(i % 28 + 1, -1.0 if (i + 1) % 2 else 0.85, "corners") for i in range(80)}
    v = cm.veredito(cm.pareado(atual, ruido))
    assert not v.startswith("MELHOR")
    clv_pior = {i: _l(i % 28 + 1, 0.85, "corners", clv=-0.2) for i in range(80)}
    assert "CLV pior" in cm.veredito(cm.pareado(atual, clv_pior))
    assert cm.veredito({"n": 0}).startswith("AMOSTRA")


def test_ganho_so_numa_metade_nao_passa():
    atual = {i: _l(i % 28 + 1, 0.0) for i in range(60)}
    so_inicio = {i: _l(i % 28 + 1, 1.0 if i < 30 else -0.2, "corners") for i in range(60)}
    v = cm.veredito(cm.pareado(atual, so_inicio))
    assert "metades" in v or "nao passa" in v


def test_drawdown_e_resumo():
    assert cm.drawdown([1, -2, -1, 3, -4]) == -4.0
    r = cm.resumo([_l(1, 0.8), _l(2, -1.0)])
    assert r["n"] == 2 and r["acerto"] == 0.5 and r["lucro_stake"] == pytest.approx(-0.4)


def test_replay_de_uma_partida_roda_o_motor_de_verdade_em_todas_as_variantes(monkeypatch):
    """Motor real (analyze_fixture_markets + ranking), banco simulado. Prende
    que cada variante sai com linha graduada e que contexto/tatico ligados
    numa variante nao vazam pra `atual`."""
    from services.pick_engine import efeito_tatico as et
    CASA, FORA = 100, 200
    hist = [{"match_date": date(2026, 8, d), "league_id": 71, "home_team_id": CASA,
             "away_team_id": FORA, "home_goals": 3, "away_goals": 1, "total_goals": 4,
             "home_corners": 6, "away_corners": 4, "total_corners": 10,
             "home_yellow_cards": 2, "away_yellow_cards": 2, "total_yellow_cards": 4,
             "home_red_cards": 0, "away_red_cards": 0, "home_possession": 60,
             "away_possession": 40, "home_passes": 500, "away_passes": 350}
            for d in range(1, 29)]
    odds = [{"market_id": 5, "market_name": "Goals Over/Under", "value": v, "line": "2.5",
             "best_odd": o, "consensus_odd": o, "bookmakers_count": 6, "value_label": f"{v} 2.5"}
            for v, o in (("Over", 1.62), ("Under", 2.30))]

    class _Odds:
        def load_odds_structured(self, fid):
            return odds

    class _Checker:
        def get_fixture_result(self, fid, cur):
            return {"ok": True}

    monkeypatch.setattr(cm.bt, "_load_history", lambda *a, **k: hist)
    monkeypatch.setattr(cm.bt, "_conversao_ate", lambda *a, **k: None)
    monkeypatch.setattr(cm.bt, "_grade", lambda ch, st, p: {"result": "GREEN", "profit": p["odd"] - 1})
    monkeypatch.setattr(cm, "_fechamento", lambda *a, **k: 1.55)
    monkeypatch.setattr(et, "tabela_em_cache", lambda: {})
    fx = {"fixture_id": 9, "match_date": date(2026, 9, 5), "league_id": 71, "season": 2026,
          "home_team_id": CASA, "away_team_id": FORA}
    r = cm.rodar_partida(fx, None, None, _Odds(), _Checker(),
                         {"by_market_league": {}, "by_market": {}}, cur=None)
    assert set(r) == set(cm.VARIANTES)
    a = r["atual"]
    assert a and a["result"] == "GREEN" and a["clv"] == pytest.approx(round(a["odd"] / 1.55 - 1, 4))
    # Sem contexto e sem tabela tatica, as variantes de motor sao identicas ao atual.
    assert (r["contexto_on"]["market_type"], r["contexto_on"]["linha"]) == (a["market_type"], a["linha"])
    assert (r["tatico_on"]["prob"]) == a["prob"]


def test_replay_nao_consulta_o_tecnico_de_hoje():
    import os
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    fonte = open(os.path.join(src, "scripts", "comparar_motor.py"), encoding="utf-8").read()
    assert 'os.environ["MOTOR_CONTEXTO_COACHS"] = "off"' in fonte
    assert "replay=True" in fonte and "_tabela_antes_de(inicio)" in fonte
