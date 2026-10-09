"""Resultado final e chance dupla no bilhete pessoal (09/10/2026): a perna
entra, liquida pelo placar e o acompanhamento ao vivo le' a mesma selecao."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import bilhete_pessoal as bp  # noqa: E402

BASE = {"fixture_id": 10, "home_team_id": 1, "away_team_id": 2, "home": "Casa", "away": "Fora"}


def resultado(escolha):
    return {**BASE, "tipo": "time", "mercado": "resultado", "escolha": escolha}


def test_escolha_desconhecida_e_recusada():
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([resultado("3")])


def test_um_resultado_por_jogo():
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([resultado("1"), resultado("X")])
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([resultado("1"), resultado("1X")])
    # Jogos diferentes, um resultado em cada: pode.
    assert len(bp.validar_pernas([resultado("1"), {**resultado("2"), "fixture_id": 11}])) == 2


def test_escolha_minuscula_vira_maiuscula():
    [p] = bp.validar_pernas([resultado("x2")])
    assert p["escolha"] == "X2"


@pytest.mark.parametrize("escolha, hg, ag, esperado", [
    ("1", 2, 1, "GREEN"), ("1", 1, 1, "RED"),
    ("X", 0, 0, "GREEN"), ("X", 0, 1, "RED"),
    ("2", 0, 1, "GREEN"), ("2", 3, 1, "RED"),
    ("1X", 1, 1, "GREEN"), ("1X", 0, 2, "RED"),
    ("12", 2, 0, "GREEN"), ("12", 2, 2, "RED"),
    ("X2", 1, 2, "GREEN"), ("X2", 2, 1, "RED"),
])
def test_liquida_pelo_placar(escolha, hg, ag, esperado):
    jogo = {"status": "FT", "home_goals": hg, "away_goals": ag}
    res, _, _ = bp.liquidar_perna(resultado(escolha), jogo, None, False, False)
    assert res == esperado


def test_sem_placar_espera():
    assert bp.liquidar_perna(resultado("1"), {"status": "FT"}, None, False, False)[0] is None


@pytest.mark.parametrize("escolha", ["1", "X", "2", "1X", "12", "X2"])
def test_ao_vivo_le_a_mesma_selecao(escolha):
    from routers.live import _calc_result
    market, mtype, line = bp.mercado_ao_vivo(resultado(escolha))
    jogo = {"status": "FT", "home_goals": 1, "away_goals": 1}
    esperado = bp.liquidar_perna(resultado(escolha), jogo, None, False, False)[0]
    assert _calc_result(market, line, None, 1, 1, mtype, "Casa", "Fora") == esperado
