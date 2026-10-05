"""Regra de 27/09: sinal so' entra na conta do motor depois de medido.

Desfalques/tecnico entraram no Score Final no mesmo dia sem medicao. Agora o
padrao e' `shadow`: calculado e gravado, fora da nota. E os scripts de medicao
passam a separar descoberta de confirmacao, pra o acaso nao virar regra.
"""
import os
import sys

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, os.path.join(SRC, "scripts"))

from services.pick_engine import news_model  # noqa: E402

_SINAL = {"home": {"titulares_desfalcados": ["A", "B"], "outros_desfalcados": []},
          "away": {"titulares_desfalcados": [], "outros_desfalcados": []}}


@pytest.mark.parametrize("valor,esperado", [
    (None, "shadow"), ("on", "on"), ("OFF", "off"), ("shadow", "shadow"), ("lixo", "shadow"),
])
def test_modo_padrao_e_shadow(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("MOTOR_DESFALQUES", raising=False)
    else:
        monkeypatch.setenv("MOTOR_DESFALQUES", valor)
    assert news_model.modo_desfalques() == esperado


def test_em_shadow_o_sinal_nao_entra_na_nota_mas_e_gravado():
    """O orchestrator calcula os dois e so' passa adiante o da nota com `on`."""
    import inspect
    from services.pick_engine import orchestrator
    fonte = inspect.getsource(orchestrator)
    assert 'news_score_sombra if news_model.modo_desfalques() == "on" else None' in fonte
    assert '"news_score_sombra": news_score_sombra' in fonte


def test_o_log_de_decisao_grava_a_sombra():
    from engine_pipelines import decision_log
    resumo = decision_log._candidate_summary({"news_score_sombra": 0.34})
    assert resumo["news_score_sombra"] == 0.34


def test_sinal_continua_derrubando_a_nota():
    assert news_model.news_score(_SINAL) < 0.5


# ── medir_sinais_novos: descoberta x confirmacao ──────────────────────────
def _faixas(desc_a, desc_b, conf_a, conf_b, n=60):
    """Duas faixas, residuos constantes com ruido pequeno, metade antes e
    metade depois do corte (dia 10)."""
    import itertools
    ruido = itertools.cycle((-0.5, 0.5))
    return {
        "A": [(d, v + next(ruido)) for d, v in [(1, desc_a)] * n + [(20, conf_a)] * n],
        "B": [(d, v + next(ruido)) for d, v in [(1, desc_b)] * n + [(20, conf_b)] * n],
    }


def test_sinal_que_some_na_confirmacao_e_ruido():
    import medir_sinais_novos as m
    texto = m.veredito(_faixas(1.0, 0.0, 0.0, 0.0), corte=10)
    assert texto.startswith("so' na descoberta")


def test_sinal_que_se_repete_e_confirmado():
    import medir_sinais_novos as m
    assert m.veredito(_faixas(1.0, 0.0, 1.0, 0.0), corte=10).startswith("CONFIRMADO")


def test_par_de_faixas_e_escolhido_so_na_descoberta():
    """Na confirmacao o par mais distante e' B>A, mas o testado e' o da
    descoberta (A>B), que la' tem sinal trocado: nao confirma."""
    import medir_sinais_novos as m
    assert not m.veredito(_faixas(1.0, 0.0, 0.0, 1.0), corte=10).startswith("CONFIRMADO")


# ── medir_calibracao_dos_picks ────────────────────────────────────────────
def _perna(prob, odd, green):
    return {"probability": prob, "odd": odd, "result": "GREEN" if green else "RED"}


def test_faixa_mostra_prob_mercado_e_acerto():
    import medir_calibracao_dos_picks as m
    pernas = [_perna(0.70, 2.0, i % 2 == 0) for i in range(40)]
    r = m.linha_de_faixa(pernas)
    assert r["prob"] == pytest.approx(0.70)
    assert r["mercado"] == pytest.approx(0.50)
    assert r["acerto"] == pytest.approx(0.50)
    assert r["roi"] == pytest.approx(0.0)


def test_faixa_pequena_nao_imprime():
    import medir_calibracao_dos_picks as m
    assert m.linha_de_faixa([_perna(0.7, 2.0, True)] * (m.MIN_N - 1)) is None
