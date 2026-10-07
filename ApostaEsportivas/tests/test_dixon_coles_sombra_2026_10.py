"""Dixon-Coles em sombra (2026-10-07): a conta, e a garantia de ser so' sombra."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest  # noqa: E402

from services.pick_engine import probability_model as pm  # noqa: E402


def test_rho_zero_e_poisson_independente():
    lh, la = 1.4, 1.1
    assert pm.dixon_coles_prob(lh, la, "btts", direction="yes", rho=0) == pytest.approx(
        pm.btts_probability(lh, la), abs=1e-3)
    # Under 2.5 com rho 0 = Poisson do total (soma de Poisson e' Poisson)
    assert pm.dixon_coles_prob(lh, la, "total", 2.5, "under", rho=0) == pytest.approx(
        pm.prob_under(2.5, lh + la), abs=1e-3)


def test_rho_negativo_aumenta_placares_baixos():
    m0 = pm.placares_dixon_coles(1.3, 1.0, 0)
    m1 = pm.placares_dixon_coles(1.3, 1.0, -0.12)
    assert m1[0][0] > m0[0][0] and m1[1][1] > m0[1][1]
    assert m1[1][0] < m0[1][0]
    assert sum(map(sum, m1)) == pytest.approx(1.0)


def test_over_e_under_somam_um_e_sem_lambda_nao_ha_conta():
    o = pm.dixon_coles_prob(1.5, 1.2, "total", 2.5, "over")
    u = pm.dixon_coles_prob(1.5, 1.2, "total", 2.5, "under")
    assert o + u == pytest.approx(1.0, abs=1e-3)
    assert pm.dixon_coles_prob(None, 1.2, "btts", direction="yes") is None


def test_sombra_nao_entra_na_conta_do_motor():
    """A probabilidade corrigida so' e' gravada: o orquestrador nao pode usar
    `dixon_coles_sombra` em lugar nenhum alem do proprio rastro."""
    fonte = open(os.path.join(os.path.dirname(pm.__file__), "orchestrator.py"), encoding="utf-8").read()
    usos = [l for l in fonte.splitlines() if "dixon_coles" in l and not l.strip().startswith("#")]
    assert all("dixon_coles_sombra" in l or "dixon_coles_prob" in l for l in usos)
    # Uma linha de codigo so' com o nome · a chave do rastro. Nenhuma leitura.
    assert sum("dixon_coles_sombra" in l for l in usos) == 1
