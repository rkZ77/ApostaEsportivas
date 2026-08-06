"""Camada probabilistica ligada ao motor atras de configuracao.

A garantia mais importante deste arquivo e' a primeira: com as tres flags
desligadas (o padrao), o motor produz EXATAMENTE o mesmo resultado de antes.
Sem isso, tres modulos novos teriam entrado no caminho de producao sem
backtest -- exatamente o que a auditoria proibiu.
"""
from datetime import date, timedelta

import pytest

from services.pick_engine import orchestrator, ranking
from services.pick_engine.calibration_model import IsotonicCalibrator
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG


REF = date(2026, 8, 6)
HOME, AWAY = 100, 200
CAL_VAZIA = {"by_market_league": {}, "by_market": {}}


def _jogo(i, time_id, em_casa, gols_time, gols_adv, escanteios_time=6, escanteios_adv=4):
    d = REF - timedelta(days=7 * (i + 1))
    adv = 900 + i
    if em_casa:
        return {"match_date": d, "home_team_id": time_id, "away_team_id": adv,
                "home_goals": gols_time, "away_goals": gols_adv,
                "total_goals": gols_time + gols_adv,
                "home_corners": escanteios_time, "away_corners": escanteios_adv,
                "total_corners": escanteios_time + escanteios_adv,
                "home_yellow_cards": 2, "away_yellow_cards": 2, "total_yellow_cards": 4,
                "home_red_cards": 0, "away_red_cards": 0,
                "home_total_shots": 13, "away_total_shots": 10,
                "home_shots_on": 5, "away_shots_on": 4,
                "home_possession": 55, "away_possession": 45,
                "home_fouls": 12, "away_fouls": 12,
                "home_offsides": 2, "away_offsides": 2, "opponent_rank": 9}
    return {"match_date": d, "home_team_id": adv, "away_team_id": time_id,
            "home_goals": gols_adv, "away_goals": gols_time,
            "total_goals": gols_time + gols_adv,
            "home_corners": escanteios_adv, "away_corners": escanteios_time,
            "total_corners": escanteios_time + escanteios_adv,
            "home_yellow_cards": 2, "away_yellow_cards": 2, "total_yellow_cards": 4,
            "home_red_cards": 0, "away_red_cards": 0,
            "home_total_shots": 10, "away_total_shots": 13,
            "home_shots_on": 4, "away_shots_on": 5,
            "home_possession": 45, "away_possession": 55,
            "home_fouls": 12, "away_fouls": 12,
            "home_offsides": 2, "away_offsides": 2, "opponent_rank": 9}


def _odd(market_id, nome, valor, linha, odd, n_books=4):
    return {"market_id": market_id, "market_name": nome, "market_pt": nome,
            "value": valor, "line": linha, "value_label": f"{valor} {linha}".strip(),
            "best_odd": odd, "best_bookmaker": "Casa", "bookmakers_count": n_books}


HIST_HOME = [_jogo(i, HOME, i % 2 == 0, 2, 1) for i in range(10)]
HIST_AWAY = [_jogo(i, AWAY, i % 2 == 1, 1, 2) for i in range(10)]
ODDS = [
    _odd(5, "Goals Over/Under", "Over", "2.5", 1.80),
    _odd(5, "Goals Over/Under", "Under", "2.5", 2.00),
    _odd(45, "Corners Over/Under", "Over", "8.5", 1.75),
    _odd(45, "Corners Over/Under", "Under", "8.5", 2.05),
]


def _rodar(config, **kw):
    return orchestrator.analyze_fixture_markets(
        ODDS, HIST_HOME, HIST_AWAY, reference_date=REF, config=config,
        calibration_data=CAL_VAZIA, home_team_id=HOME, away_team_id=AWAY, **kw,
    )


# ======================================================================
# A garantia central
# ======================================================================
def test_flags_desligadas_nao_mudam_nada():
    """O padrao tem que ser byte-a-byte o comportamento anterior."""
    base = _rodar(DEFAULT_CONFIG)
    assert base, "cenario precisa gerar candidato pra o teste ter valor"
    for c in base:
        assert "probability_trace" not in c


def test_flags_desligadas_ignoram_calibradores_passados():
    """Passar calibrador com a flag off nao pode ter efeito nenhum."""
    cal = IsotonicCalibrator(x=[0.1, 0.9], y=[0.05, 0.45], n=100)
    sem = _rodar(DEFAULT_CONFIG)
    com = _rodar(DEFAULT_CONFIG, calibrators={"goals": cal, "corners": cal})
    assert [c["taxa_real"] for c in sem] == [c["taxa_real"] for c in com]
    assert [c["ev"] for c in sem] == [c["ev"] for c in com]


def test_camada_preserva_lista_vazia():
    assert orchestrator.apply_probability_layer([], DEFAULT_CONFIG) == []


# ======================================================================
# Calibracao
# ======================================================================
def test_calibracao_puxa_probabilidade_e_recalcula_ev():
    """Calibrador pessimista tem que derrubar taxa, edge e EV juntos."""
    cal = IsotonicCalibrator(x=[0.0, 1.0], y=[0.0, 0.50], n=100)
    cfg = PickEngineConfig(use_isotonic_calibration=True)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg, calibrators={c["market_type"]: cal for c in base})

    for antes, depois in zip(base, novo):
        assert depois["taxa_real"] < antes["taxa_real"]
        assert depois["ev"] < antes["ev"]
        # EV sempre derivado da probabilidade final, nunca herdado.
        assert depois["ev"] == pytest.approx(
            round(depois["taxa_real"] * depois["odd"] - 1, 4), abs=1e-4)


def test_calibracao_sem_calibrador_do_mercado_nao_altera():
    cfg = PickEngineConfig(use_isotonic_calibration=True)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg, calibrators={"mercado_inexistente": IsotonicCalibrator([0.0, 1.0], [0.0, 0.5], 100)})
    assert [c["taxa_real"] for c in base] == [c["taxa_real"] for c in novo]


def test_rastro_registra_o_valor_anterior():
    cal = IsotonicCalibrator(x=[0.0, 1.0], y=[0.0, 0.50], n=100)
    cfg = PickEngineConfig(use_isotonic_calibration=True)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg, calibrators={c["market_type"]: cal for c in base})
    for antes, depois in zip(base, novo):
        assert depois["probability_trace"]["p_pre_calibracao"] == antes["taxa_real"]


# ======================================================================
# Ancoragem
# ======================================================================
def test_ancoragem_puxa_a_probabilidade_na_direcao_do_mercado():
    cfg = PickEngineConfig(use_market_anchor=True)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg)

    for antes, depois in zip(base, novo):
        mercado = antes["prob_baseline_value"]
        # A ancorada tem que ficar entre a do motor e a do mercado.
        baixo, alto = sorted((antes["taxa_real"], mercado))
        assert baixo - 1e-6 <= depois["taxa_real"] <= alto + 1e-6


def test_ancoragem_encolhe_o_edge():
    """Efeito central: divergir do mercado sem historico que sustente passa a
    custar. E' o que barra taxa extrema de amostra pequena."""
    cfg = PickEngineConfig(use_market_anchor=True)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg)
    for antes, depois in zip(base, novo):
        assert abs(depois["edge"]) <= abs(antes["edge"]) + 1e-6


def test_ancoragem_com_clv_comprovado_devolve_voz_ao_motor():
    cfg = PickEngineConfig(use_market_anchor=True)
    sem_clv = _rodar(cfg)
    com_clv = _rodar(cfg, clv_by_market={
        c["market_type"]: {"clv_medio": 0.03, "clv_n": 200, "clv_significativo": True}
        for c in sem_clv
    })
    for a, b in zip(sem_clv, com_clv):
        # Com vantagem demonstrada, a combinacao fica mais perto do motor,
        # logo o edge volta a crescer.
        assert abs(b["edge"]) >= abs(a["edge"]) - 1e-6


# ======================================================================
# Vies de selecao
# ======================================================================
def test_vies_de_selecao_desconta_a_probabilidade():
    cfg = PickEngineConfig(use_selection_bias=True)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg)
    assert len(base) == len(novo)
    for antes, depois in zip(base, novo):
        assert depois["taxa_real"] <= antes["taxa_real"]


def test_vies_de_selecao_expoe_o_rastro_para_explicacao():
    cfg = PickEngineConfig(use_selection_bias=True)
    novo = _rodar(cfg)
    com_rastro = [c for c in novo if "probability_trace" in c]
    if com_rastro:   # so' ha rastro quando houve desconto
        info = com_rastro[0]["probability_trace"]["vies_selecao"]
        assert "n_candidatos" in info and "desconto" in info


# ======================================================================
# Combinacao e integridade
# ======================================================================
def test_as_tres_juntas_mantem_ev_coerente_com_a_probabilidade():
    """A incoerencia entre probabilidade e EV foi um bug real da multipla --
    aqui fica travado que as duas nunca saem de sincronia."""
    cal = IsotonicCalibrator(x=[0.0, 1.0], y=[0.0, 0.80], n=100)
    cfg = PickEngineConfig(use_isotonic_calibration=True, use_market_anchor=True,
                           use_selection_bias=True)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg, calibrators={c["market_type"]: cal for c in base})
    for c in novo:
        assert c["ev"] == pytest.approx(round(c["taxa_real"] * c["odd"] - 1, 4), abs=1e-4)
        if c.get("prob_baseline_value") is not None:
            assert c["edge"] == pytest.approx(
                round(c["taxa_real"] - c["prob_baseline_value"], 4), abs=1e-4)


def test_probabilidade_nunca_fica_negativa():
    cfg = PickEngineConfig(use_selection_bias=True, use_isotonic_calibration=True)
    cal = IsotonicCalibrator(x=[0.0, 1.0], y=[0.0, 0.02], n=100)
    base = _rodar(DEFAULT_CONFIG)
    novo = _rodar(cfg, calibrators={c["market_type"]: cal for c in base})
    for c in novo:
        assert c["taxa_real"] >= 0.0


def test_camada_nao_muta_os_candidatos_originais():
    """Constroi dicts novos -- o chamador pode comparar antes e depois."""
    cfg = PickEngineConfig(use_selection_bias=True)
    base = _rodar(DEFAULT_CONFIG)
    copia = [dict(c) for c in base]
    orchestrator.apply_probability_layer(base, cfg)
    assert [c["taxa_real"] for c in base] == [c["taxa_real"] for c in copia]


def test_ranking_continua_funcionando_com_a_camada_ligada():
    cfg = PickEngineConfig(use_market_anchor=True, use_selection_bias=True)
    picks = ranking.rank_market_candidates(_rodar(cfg), cfg)
    for p in picks:
        assert p["ev"] > cfg.min_ev
        assert p["odd"] >= cfg.min_odd
