"""Ambas recebem cartao (1+ e 2+) no bilhete montado · 17/10/2026."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bilhete_pessoal as bp  # noqa: E402

BASE = {"fixture_id": 10, "home_team_id": 1, "away_team_id": 2, "home": "Casa", "away": "Fora"}


def perna(**k):
    [p] = bp.validar_pernas([{**BASE, "tipo": "time", "mercado": "ambas_cartao", **k}])
    return p


def jogo(ha, aa, hv=0, av=0):
    return {"status": "FT", "home_yellow_cards": ha, "away_yellow_cards": aa,
            "home_red_cards": hv, "away_red_cards": av}


def test_validacao():
    assert perna()["minimo"] == 1
    assert perna(minimo=2)["minimo"] == 2
    with pytest.raises(bp.PernaInvalida):
        perna(minimo=3)


def test_liquida_pelo_time_com_menos_cartoes():
    um, dois = perna(), perna(minimo=2)
    assert bp.liquidar_perna(um, jogo(3, 1), None, False, False)[:2] == ("GREEN", 1)
    assert bp.liquidar_perna(um, jogo(3, 0), None, False, False)[0] == "RED"
    assert bp.liquidar_perna(dois, jogo(2, 1), None, False, False)[0] == "RED"
    # vermelho conta como cartao
    assert bp.liquidar_perna(dois, jogo(2, 1, av=1), None, False, False)[0] == "GREEN"


def test_sem_estatistica_fica_pendente():
    assert bp.liquidar_perna(perna(), jogo(None, 1), None, False, False) == (None, None, None)


def test_nao_vai_pro_ao_vivo():
    assert bp.mercado_ao_vivo(perna()) is None
