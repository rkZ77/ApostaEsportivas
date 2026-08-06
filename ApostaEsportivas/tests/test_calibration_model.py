"""Regressao isotonica (PAVA) para calibracao de probabilidade.

A propriedade que torna esta mudanca segura e' a monotonicidade: uma
transformacao monotona nunca reordena candidatos, entao ligar a calibracao
muda QUANTO se aposta, nunca EM QUE se aposta.
"""
import random

import pytest

from services.pick_engine.calibration_model import (
    IsotonicCalibrator, MIN_AMOSTRA_FIT, _pava, fit_por_grupo,
)


# ----------------------------------------------------------------------
# PAVA
# ----------------------------------------------------------------------
def test_pava_preserva_sequencia_ja_monotona():
    y = [0.1, 0.3, 0.5, 0.9]
    assert _pava(y, [1.0] * 4) == pytest.approx(y)


def test_pava_funde_violacao_na_media():
    # 0.8 seguido de 0.2 viola; a solucao monotona funde os dois em 0.5.
    saida = _pava([0.1, 0.8, 0.2, 0.9], [1.0] * 4)
    assert saida == pytest.approx([0.1, 0.5, 0.5, 0.9])


def test_pava_saida_e_sempre_nao_decrescente():
    random.seed(7)
    y = [random.random() for _ in range(200)]
    saida = _pava(y, [1.0] * len(y))
    assert all(saida[i] <= saida[i + 1] + 1e-12 for i in range(len(saida) - 1))


def test_pava_preserva_a_media_global():
    """Minimos quadrados sob restricao monotona nao desloca a media."""
    y = [0.9, 0.1, 0.8, 0.2, 0.7, 0.3]
    saida = _pava(y, [1.0] * len(y))
    assert sum(saida) / len(saida) == pytest.approx(sum(y) / len(y))


# ----------------------------------------------------------------------
# Ajuste
# ----------------------------------------------------------------------
def _amostra_superconfiante(n=200, seed=3):
    """Modelo que declara p mas acontece so' 0.7*p -- otimista de forma
    sistematica, o padrao que a auditoria mediu em `cards`."""
    rng = random.Random(seed)
    probs, desfechos = [], []
    for _ in range(n):
        p = rng.uniform(0.5, 0.95)
        probs.append(p)
        desfechos.append(1 if rng.random() < p * 0.7 else 0)
    return probs, desfechos


def test_fit_exige_amostra_minima():
    assert IsotonicCalibrator.fit([0.6] * 5, [1] * 5) is None
    probs, des = _amostra_superconfiante(MIN_AMOSTRA_FIT)
    assert IsotonicCalibrator.fit(probs, des) is not None


def test_fit_ignora_desfecho_nao_binario():
    """PUSH nao e' acerto nem erro da probabilidade declarada."""
    probs = [0.6] * 40
    des = [1, 0] * 15 + [None] * 10  # type: ignore[list-item]
    cal = IsotonicCalibrator.fit(probs, des)
    assert cal is not None
    assert cal.n == 30


def test_calibrador_corrige_superconfianca_pra_baixo():
    probs, des = _amostra_superconfiante(400)
    cal = IsotonicCalibrator.fit(probs, des)
    assert cal is not None
    # Um modelo que promete 90% e entrega ~63% tem que ser puxado pra baixo.
    assert cal.predict(0.90) < 0.90


def test_predicao_e_monotona_logo_nunca_reordena():
    """A propriedade central: se p1 < p2, entao cal(p1) <= cal(p2). Sem isso
    a calibracao poderia trocar a ordem de dois candidatos."""
    probs, des = _amostra_superconfiante(300)
    cal = IsotonicCalibrator.fit(probs, des)
    grade = [i / 100 for i in range(1, 100)]
    saidas = [cal.predict(p) for p in grade]
    assert all(saidas[i] <= saidas[i + 1] + 1e-9 for i in range(len(saidas) - 1))


def test_predicao_fica_no_intervalo_valido():
    probs, des = _amostra_superconfiante(300)
    cal = IsotonicCalibrator.fit(probs, des)
    for p in (0.0, 0.01, 0.5, 0.99, 1.0):
        assert 0.0 <= cal.predict(p) <= 1.0


def test_extrapolacao_e_constante_nas_pontas():
    """Fora da faixa observada nao se inventa tendencia."""
    probs, des = _amostra_superconfiante(200)
    cal = IsotonicCalibrator.fit(probs, des)
    assert cal.predict(0.0) == cal.predict(min(cal.x) - 0.1)
    assert cal.predict(1.0) == cal.predict(max(cal.x) + 0.1)


def test_modelo_ja_calibrado_quase_nao_e_alterado():
    """Nao pode 'corrigir' quem ja' esta certo."""
    rng = random.Random(11)
    probs, des = [], []
    for _ in range(600):
        p = rng.uniform(0.35, 0.9)
        probs.append(p)
        des.append(1 if rng.random() < p else 0)
    cal = IsotonicCalibrator.fit(probs, des)
    for alvo in (0.45, 0.60, 0.75):
        assert cal.predict(alvo) == pytest.approx(alvo, abs=0.12)


def test_predicao_none_para_entrada_none():
    probs, des = _amostra_superconfiante(100)
    cal = IsotonicCalibrator.fit(probs, des)
    assert cal.predict(None) is None


# ----------------------------------------------------------------------
# Serializacao e agrupamento
# ----------------------------------------------------------------------
def test_serializacao_preserva_a_curva():
    probs, des = _amostra_superconfiante(200)
    cal = IsotonicCalibrator.fit(probs, des)
    copia = IsotonicCalibrator.from_dict(cal.to_dict())
    for p in (0.3, 0.55, 0.8, 0.95):
        assert copia.predict(p) == cal.predict(p)


def test_from_dict_vazio_devolve_none():
    assert IsotonicCalibrator.from_dict(None) is None
    assert IsotonicCalibrator.from_dict({}) is None


def test_fit_por_grupo_ignora_grupo_sem_amostra():
    linhas = (
        [{"market_type": "goals", "probability": 0.7, "result": "GREEN"} for _ in range(40)]
        + [{"market_type": "goals", "probability": 0.6, "result": "RED"} for _ in range(40)]
        + [{"market_type": "raro", "probability": 0.8, "result": "GREEN"} for _ in range(3)]
    )
    cals = fit_por_grupo(linhas, "market_type")
    assert "goals" in cals
    assert "raro" not in cals   # amostra insuficiente: melhor nao corrigir


def test_fit_por_grupo_ignora_push():
    linhas = [{"market_type": "goals", "probability": 0.7, "result": "PUSH"} for _ in range(50)]
    assert fit_por_grupo(linhas, "market_type") == {}
