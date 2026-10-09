# -*- coding: utf-8 -*-
"""Efeito tatico medido (2026-10-08) -- ver services/pick_engine/efeito_tatico.py
e scripts/medir_efeito_tatico.py.

Prende: a regressao de Poisson com offset recupera coeficientes conhecidos e
estima o erro-padrao com a sobredispersao; feature ausente e' neutra; a
montagem das linhas nao vaza futuro; so' efeito real e estavel e' aprovado;
no motor, shadow nao muda nada publicado, `on` so' mexe em mercado aprovado e
tira o termo Perfil (sem contar duas vezes), e desfalque sai quando o
contexto atual ja' o conta.
"""
import math
import random
from datetime import date, timedelta

import pytest

from services.pick_engine import efeito_tatico as et
from services.pick_engine import analyze_fixture_markets
from services.pick_engine.config import VIP_CONFIG
from scripts import medir_efeito_tatico as med


def _poisson(rng, lam):
    """Knuth -- suficiente pra lambda pequeno de teste."""
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


# ---------------------------------------------------------------------------
# 1. A regressao
# ---------------------------------------------------------------------------
def test_regressao_recupera_coeficientes_conhecidos():
    rng = random.Random(7)
    X, y, off = [], [], []
    for _ in range(3000):
        x1, x2 = rng.gauss(0, 1), rng.gauss(0, 1)
        base = rng.uniform(2, 6)
        y.append(_poisson(rng, base * math.exp(0.1 + 0.3 * x1)))
        X.append([1.0, x1, x2])
        off.append(math.log(base))
    fit = et.ajustar_poisson(X, y, off, ridge=0.0)
    b0, b1, b2 = fit["beta"]
    assert b0 == pytest.approx(0.1, abs=0.05)
    assert b1 == pytest.approx(0.3, abs=0.04)
    assert abs(b2) < 3 * fit["ep"][2]          # efeito nulo fica dentro do ruido


def test_erro_padrao_cresce_com_sobredispersao():
    rng = random.Random(3)
    X, y_p, y_od, off = [], [], [], []
    for _ in range(2000):
        x = rng.gauss(0, 1)
        X.append([1.0, x])
        off.append(math.log(4.0))
        y_p.append(_poisson(rng, 4.0))
        y_od.append(_poisson(rng, 4.0 * rng.gammavariate(0.5, 2.0)))   # mistura gama
    a = et.ajustar_poisson(X, y_p, off)
    b = et.ajustar_poisson(X, y_od, off)
    assert b["dispersao"] > 2 * a["dispersao"] and b["ep"][1] > 1.3 * a["ep"][1]


def test_feature_ausente_e_neutra():
    z = et.padronizar({"posse_propria": None}, {"posse_propria": 50}, {"posse_propria": 5})
    assert z == [0.0] * len(et.FEATURES)


def test_multiplicador_tem_teto():
    assert et.multiplicador({"a": 5.0}) == pytest.approx(1.25)
    assert et.multiplicador({"a": -5.0}) == pytest.approx(0.8)
    assert et.multiplicador({}) == 1.0


def test_lambda_tatico_por_escopo():
    mult = {"home": {"multiplicador": 1.2}, "away": {"multiplicador": 0.9}}
    assert et.lambda_tatico(2.0, "home", None, None, mult) == pytest.approx(2.4)
    assert et.lambda_tatico(1.0, "away", None, None, mult) == pytest.approx(0.9)
    # total: reescala pela soma dos lados ajustados
    assert et.lambda_tatico(3.0, "total", 2.0, 1.0, mult) == pytest.approx(3.0 * (2.4 + 0.9) / 3)
    assert et.lambda_tatico(None, "total", 2.0, 1.0, mult) is None


def test_desfalque_sai_quando_o_contexto_ja_conta():
    tabela = {"gols": {"coefs": {"ausentes_defesa_adv": {"beta": 0.2}},
                       "medias": {"ausentes_defesa_adv": 0.5},
                       "desvios": {"ausentes_defesa_adv": 0.7}, "aprovado": True}}
    perf = {"metricas": {}}
    ex_c = {"ausentes_defesa_propria": 0}
    ex_f = {"ausentes_defesa_propria": 3, "ausentes_defesa_adv": 0}
    ex_c["ausentes_defesa_adv"] = 3
    com = et.multiplicadores(perf, perf, ex_c, ex_f, tabela)
    sem = et.multiplicadores(perf, perf, ex_c, ex_f, tabela, excluir_desfalques=True)
    assert com["gols"]["home"]["multiplicador"] > 1.0
    assert sem["gols"]["home"]["multiplicador"] == 1.0
    assert sem["gols"]["redundante_com_contexto"]


def test_regime_curto_do_tecnico_usa_o_historico_inteiro():
    jogos = [{"match_date": date(2026, 9, d)} for d in range(1, 11)]
    assert et._do_regime(jogos, {"inicio": "2026-09-08"}) == jogos          # 3 jogos < 5
    assert len(et._do_regime(jogos, {"inicio": "2026-09-04"})) == 7
    assert et._do_regime(jogos, None) == jogos


# ---------------------------------------------------------------------------
# 2. A montagem sem vazamento e a validacao
# ---------------------------------------------------------------------------
def _liga(n_rodadas=50, efeito=0.0, seed=11, n_times=12):
    """Partidas sinteticas: cada time tem um estilo de posse; o escanteio do
    time depende do CHOQUE de posse dos dois (o que a media de feitos/cedidos
    nao enxerga) com intensidade `efeito`."""
    rng = random.Random(seed)
    estilo = {t: rng.uniform(35, 65) for t in range(1, n_times + 1)}
    jogos, dia, fid = [], date(2025, 1, 1), 1
    for r in range(n_rodadas):
        times = list(estilo)
        rng.shuffle(times)
        for i in range(0, n_times, 2):
            c, f = times[i], times[i + 1]
            pc = max(20, min(80, 50 + (estilo[c] - estilo[f]) / 2 + rng.gauss(0, 3)))
            choque = (estilo[c] - 50) * (estilo[f] - 50) / 100
            m = {"fixture_id": fid, "match_date": dia, "league_id": 71, "season": 2025,
                 "home_team_id": c, "away_team_id": f,
                 "home_possession": pc, "away_possession": 100 - pc,
                 "home_passes": 400 + 6 * (pc - 50), "away_passes": 400 + 6 * (50 - pc),
                 "home_goals": _poisson(rng, 1.4), "away_goals": _poisson(rng, 1.1)}
            for lado, base in (("home", 5.2), ("away", 4.4)):
                m[f"{lado}_corners"] = _poisson(rng, base * math.exp(efeito * choque))
            jogos.append(m)
            fid += 1
        dia += timedelta(days=7)
    return jogos


def test_montagem_nao_le_o_futuro():
    jogos = _liga(n_rodadas=20)
    linhas = med.montar_linhas(jogos, {}, {}, {})
    alvo = [l for l in linhas if l["fixture_id"] == jogos[100]["fixture_id"]]
    # Bagunca TODAS as partidas a partir da 100 (inclusive): as linhas de
    # antes nao podem mudar, e a da propria 100 tambem nao (ela so' le' passado).
    futuro = [dict(m) for m in jogos]
    for m in futuro[100:]:
        m["home_possession"], m["home_corners"] = 99, 40
    linhas2 = med.montar_linhas(futuro, {}, {}, {})
    antes = {(l["fixture_id"], l["lado"]): l["cru"] for l in linhas
             if l["fixture_id"] <= jogos[100]["fixture_id"]}
    depois = {(l["fixture_id"], l["lado"]): l["cru"] for l in linhas2
              if l["fixture_id"] <= jogos[100]["fixture_id"]}
    assert antes == depois and alvo


def test_ausente_habitual_conta_por_setor():
    ant = [{"titulares": {1, 2, 3, 9}} for _ in range(5)]
    atual = {"titulares": {1, 3}}
    assert med._ausentes(atual, ant, {2: "D", 9: "F"}) == (1, 1)
    assert med._ausentes(None, ant, {}) == (None, None)
    assert med._ausentes(atual, ant[:2], {}) == (None, None)


@pytest.fixture
def _so_escanteios(monkeypatch):
    monkeypatch.setattr(et, "ESTATISTICAS", {"escanteios": ("corners", "corners")})
    monkeypatch.setattr(med, "MAX_LINHAS", 4000)


def test_efeito_real_e_aprovado_fora_da_amostra(_so_escanteios):
    linhas = med.montar_linhas(_liga(n_rodadas=60, efeito=0.45), {}, {}, {})
    r = med.rodar(linhas)["escanteios"]
    assert "choque_de_posse" in r["descoberta"]["coefs"]
    assert "choque_de_posse" in r["estaveis"]
    assert r["validacao"]["d_loglik"] > 0
    assert r["aprovado"] is True


def test_sem_efeito_nada_e_aprovado(_so_escanteios):
    linhas = med.montar_linhas(_liga(n_rodadas=60, efeito=0.0, seed=5), {}, {}, {})
    r = med.rodar(linhas)["escanteios"]
    assert r["aprovado"] is False


def test_validacao_separa_por_competicao_e_tipo(_so_escanteios, monkeypatch):
    monkeypatch.setattr(med, "MIN_COMPETICAO", 50)
    linhas = med.montar_linhas(_liga(n_rodadas=60, efeito=0.45), {}, {}, {})
    av = med.rodar(linhas)["escanteios"]["validacao"]
    assert "71" in av["por_competicao"] and "liga" in av["por_tipo"]
    merc = av["mercado"]
    assert {"brier_base", "d_brier", "d_logloss", "ece_base", "ece_tatico"} <= set(merc)


def test_estabilidade_reprova_sinal_que_inverte():
    desc = {"coefs": {"a": {"beta": 0.3, "z": 4}, "b": {"beta": 0.2, "z": 3}}}
    conf = {"todos": {"a": {"beta": 0.25, "z": 2.5}, "b": {"beta": -0.1, "z": -1.5}}}
    assert med.estaveis(desc, conf) == ["a"]
    assert med.estaveis(desc, None) == []


# ---------------------------------------------------------------------------
# 3. No motor
# ---------------------------------------------------------------------------
CASA, FORA = 100, 200
CAL = {"by_market_league": {}, "by_market": {}}


def _jogo(d, posse):
    return {"match_date": date(2026, 9, d), "league_id": 71,
            "home_team_id": CASA, "away_team_id": FORA,
            "home_goals": 2, "away_goals": 1, "total_goals": 3,
            "home_corners": 6, "away_corners": 4, "total_corners": 10,
            "home_yellow_cards": 2, "away_yellow_cards": 2, "total_yellow_cards": 4,
            "home_red_cards": 0, "away_red_cards": 0,
            "home_possession": posse, "away_possession": 100 - posse,
            "home_passes": 500, "away_passes": 350}


HIST = [_jogo(d, 62) for d in range(1, 21)]
ODDS = [{"market_id": 45, "market_name": "Corners Over Under", "value": v, "line": "9.5",
         "best_odd": o, "bookmakers_count": 6, "value_label": f"{v} 9.5"}
        for v, o in (("Over", 1.80), ("Under", 2.00))]
TABELA = {"escanteios": {"coefs": {"posse_propria": {"beta": 0.15, "ep": 0.03}},
                         "medias": {"posse_propria": 50.0}, "desvios": {"posse_propria": 6.0},
                         "aprovado": True}}


def _rodar(monkeypatch, tabela=TABELA, ids=True):
    monkeypatch.setattr(et, "tabela_em_cache", lambda: tabela)
    monkeypatch.setenv("MOTOR_CONTEXTO", "off")
    return analyze_fixture_markets(
        ODDS, HIST, HIST, reference_date=date(2026, 10, 8), config=VIP_CONFIG,
        calibration_data=CAL, home_team_id=CASA if ids else None,
        away_team_id=FORA if ids else None,
        matchup_data={"corners": {"delta": 1.0}})


def test_shadow_registra_mas_nao_muda_o_pick(monkeypatch):
    monkeypatch.setenv("MOTOR_TATICO", "off")
    sem = _rodar(monkeypatch)
    monkeypatch.setenv("MOTOR_TATICO", "shadow")
    com = _rodar(monkeypatch)
    assert [(c["taxa_real"], c["ev"], c["poisson_probability"]) for c in sem] == \
           [(c["taxa_real"], c["ev"], c["poisson_probability"]) for c in com]
    t = com[0]["tatico_sombra"]
    assert t["lambda_tatico"] != t["lambda"] and t["prob"] != t["prob_modelo"]
    assert t["aplicado"] is False and "ev_com_tatico" in t
    assert com[0]["profile_score"] is not None


def test_on_troca_a_leitura_do_modelo_e_tira_o_perfil(monkeypatch):
    monkeypatch.setenv("MOTOR_TATICO", "on")
    c = _rodar(monkeypatch)[0]
    t = c["tatico_sombra"]
    assert t["aplicado"] is True
    assert c["poisson_probability"] == t["prob"]
    assert c["profile_score"] is None and c["profile_score_removido"] is True


def test_on_nao_mexe_em_mercado_nao_aprovado(monkeypatch):
    nao = {"escanteios": {**TABELA["escanteios"], "aprovado": False}}
    monkeypatch.setenv("MOTOR_TATICO", "off")
    base = _rodar(monkeypatch, nao)[0]
    monkeypatch.setenv("MOTOR_TATICO", "on")
    c = _rodar(monkeypatch, nao)[0]
    assert c["taxa_real"] == base["taxa_real"] and c["tatico_sombra"]["aplicado"] is False
    assert c["profile_score"] is not None


class _Cur:
    def __init__(self):
        self.sqls = []
        self.connection = self

    def execute(self, sql, params=None):
        self.sqls.append((sql, params))

    def fetchall(self):
        return []

    def rollback(self):
        pass


def test_consultas_do_perfil_so_leem_jogo_antes_do_apito():
    from datetime import datetime
    from services.pick_engine import contexto_atual as ca
    apito = datetime(2026, 10, 8, 16)
    cur = _Cur()
    ca._referencia_tatica(cur, 71, 2026, apito)
    ca._carreira_do_tecnico(cur, 9, apito)
    (s1, p1), (s2, p2) = cur.sqls
    assert "match_date < %s" in s1 and p1[-1] == apito
    assert "tl.match_date < %s" in s2 and apito in p2
    assert ca._carreira_do_tecnico(_Cur(), None, apito) == []


def test_ausentes_por_posicao_so_conta_titular_habitual():
    from services.pick_engine import contexto_atual as ca
    escal = [(None, 1, "T", "4-3-3", [1, 2, 3, 9]) for _ in range(5)]
    r = ca.ausentes_por_posicao(escal, {2, 9, 77}, {2: "D", 9: "F", 77: "D"})
    assert r["defesa"] == 1 and r["ataque"] == 1 and 77 not in r["jogadores"]
    assert ca.ausentes_por_posicao(escal[:2], {2}, {}) is None


def test_dossie_separa_observado_modelo_e_limites(monkeypatch):
    from services.pick_engine import dossie_da_partida as d
    monkeypatch.setattr(et, "tabela_em_cache", lambda: {})
    r = d._leitura_tatica({}, HIST, HIST, CASA, FORA)
    assert set(r) >= {"observado", "limites"}
    assert "efeito_medido_do_confronto" not in (r.get("modelo") or {})
    assert any("PPDA" in l for l in r["limites"])
    monkeypatch.setattr(et, "tabela_em_cache", lambda: TABELA)
    r = d._leitura_tatica({}, HIST, HIST, CASA, FORA)
    assert r["modelo"]["efeito_medido_do_confronto"]["escanteios"]["validado_fora_da_amostra"]


@pytest.mark.parametrize("arquivo", ["faltas_pipeline.py", "player_stats_pipeline.py",
                                     "pick_boost_pipeline.py"])
def test_motores_de_modelo_proprio_registram_o_tatico(arquivo):
    import os
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    fonte = open(os.path.join(src, "engine_pipelines", arquivo), encoding="utf-8").read()
    assert "efeito_tatico.preparar_partida(" in fonte and '"efeito_tatico"' in fonte


def test_log_de_decisao_grava_o_tatico():
    from engine_pipelines import decision_log
    assert decision_log._candidate_summary({"tatico_sombra": {"prob": 0.6}})["tatico_sombra"]


def test_sem_tabela_ou_sem_ids_nada_muda(monkeypatch):
    monkeypatch.setenv("MOTOR_TATICO", "on")
    assert all("tatico_sombra" not in c for c in _rodar(monkeypatch, tabela={}))
    assert all("tatico_sombra" not in c for c in _rodar(monkeypatch, ids=False))
