"""medir_erro_das_casas: a matematica de "casa fora da curva" (09/10/2026)."""
from collections import defaultdict

import pytest

from scripts import medir_erro_das_casas as m


def _res():
    return {"margem_casa": defaultdict(m.Acum), "margem_mercado": defaultdict(m.Acum),
            "base": defaultdict(m.Acum), "sinais": []}


def _jogo():
    """Over/Under 2.5 (mercado 5), tres casas. Fechamento a 10 min: todas
    1,95/1,95 (justo 50%). A 200 min a casa 1 paga Over 2,20 enquanto as
    outras pagam 1,90 -- ela esta' fora da curva e o fechamento confirma."""
    linhas = []
    for casa in (1, 2, 3):
        linhas += [(casa, 5, "Over 2.5", None, 1.95, 10),
                   (casa, 5, "Under 2.5", None, 1.95, 10)]
    linhas += [(1, 5, "Over 2.5", None, 2.20, 200), (1, 5, "Under 2.5", None, 1.70, 200)]
    for casa in (2, 3):
        linhas += [(casa, 5, "Over 2.5", None, 1.90, 200),
                   (casa, 5, "Under 2.5", None, 1.90, 200)]
    return linhas


def test_linha_junta_os_dois_lados_e_separa_handicap_com_sinal():
    assert m.linha_do_valor("Over 2.5", None) == m.linha_do_valor("Under 2.5", None) == "2.5"
    assert m.linha_do_valor("Home", None) == ""
    assert m.linha_do_valor("Home", "-1") != m.linha_do_valor("Away", "1")


def test_sem_margem_so_aceita_grupo_completo():
    ov, probs = m.sem_margem({"Over 2.5": 1.90, "Under 2.5": 1.90})
    assert ov == pytest.approx(2 / 1.9)
    assert probs["Over 2.5"] == pytest.approx(0.5)
    assert m.sem_margem({"Over 2.5": 1.90}) is None                       # um lado so'
    assert m.sem_margem({"1:0": 7.0, "0:0": 8.0}) is None                  # placar
    assert m.sem_margem({"Home": 2.5, "Away": 2.8}) is None                # 1X2 sem empate


def test_casa_fora_da_curva_vira_sinal_e_o_fechamento_julga():
    res = _res()
    assert m.analisar_jogo(_jogo(), "2026-10-01", res) is True
    # So' a casa 1 no Over, nas janelas de 60 e 180 (a foto de 200 min).
    assert {(s[1], s[3]) for s in res["sinais"]} == {(1, 60), (1, 180)}
    for _, casa, mercado, _, desvio, clv in res["sinais"]:
        assert desvio == pytest.approx(0.10)
        assert clv == pytest.approx(0.10)
    assert res["margem_casa"][1].media == pytest.approx(2 / 1.95 - 1)


def test_sem_foto_perto_do_apito_nao_ha_fechamento():
    longe = [(c, mk, v, lv, o, mn + 100) for c, mk, v, lv, o, mn in _jogo()]
    res = _res()
    assert m.analisar_jogo(longe, "2026-10-01", res) is False
    # Com o corte de 3h a foto de 110 min vira fechamento, e a janela de 60
    # (que cairia nela mesma) e' pulada.
    res = _res()
    assert m.analisar_jogo(longe, "2026-10-01", res, fechamento_max=180) is True
    assert {s[3] for s in res["sinais"]} <= {360, 720}
