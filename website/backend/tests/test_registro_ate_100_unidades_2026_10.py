"""Registrar a stake que a pessoa apostou de verdade (2026-10-07).

O teto por produto (STAKE_LIMITS) e' o da SUGESTAO e continua igual. O registro
aceita ate' REGISTRO_MAX_UNIDADES em qualquer produto: quem apostou 23u na casa
precisa conseguir lancar 23u.
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ.setdefault("JWT_SECRET", "teste")

import pytest  # noqa: E402
import routers.banca as banca  # noqa: E402


@pytest.mark.parametrize("tipo", sorted(banca.STAKE_LIMITS))
def test_todo_produto_registra_ate_100(tipo):
    minimo, maximo = banca.limites_de_registro(tipo)
    assert maximo >= 100
    assert minimo == banca.STAKE_LIMITS[tipo][0]


def test_a_sugestao_continua_com_o_teto_de_prudencia():
    assert banca.STAKE_LIMITS["vip"][1] == 20
    assert banca.STAKE_LIMITS["multipla"][1] == 5
    assert banca.STAKE_LIMITS["live"][1] == 4
