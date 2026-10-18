"""Faltas em sombra (18/10/2026): a chave do pipeline e a medicao que liquida
as escolhas do motor pelas faltas do jogo."""
import pytest

from engine_pipelines import faltas_pipeline as fp
from scripts import medir_faltas_sombra as mf


def test_padrao_e_sombra_e_so_on_publica(monkeypatch):
    monkeypatch.delenv("MOTOR_FALTAS", raising=False)
    assert fp.modo_faltas() == "sombra"
    monkeypatch.setenv("MOTOR_FALTAS", "on")
    assert fp.modo_faltas() == "on"
    monkeypatch.setenv("MOTOR_FALTAS", "qualquer")
    assert fp.modo_faltas() == "sombra"


def test_liquida_over_pelas_faltas_do_jogo():
    r = mf.liquidar({"line": "Over 20.5", "odd": 1.61, "taxa_real": 0.68}, 24)
    assert r["g"] == 1 and r["lucro"] == pytest.approx(0.61) and r["preco"] == pytest.approx(1 / 1.61)
    assert mf.liquidar({"line": "Over 20.5", "odd": 1.61}, 19)["lucro"] == -1.0
    assert mf.liquidar({"line": "Over 20.5", "odd": 1.61}, None) is None
    assert mf.liquidar({"line": "21.5", "odd": None}, 30) is None


def test_veredito_exige_amostra_e_margem():
    pouco = mf.resumo([{"g": 1, "lucro": 0.8, "p": 0.6, "preco": 0.55}] * 10)
    assert "INSUFICIENTE" in mf.veredito(pouco)
    ganha = mf.resumo([{"g": 1, "lucro": 0.8, "p": 0.6, "preco": 0.55}] * 45
                      + [{"g": 0, "lucro": -1.0, "p": 0.6, "preco": 0.55}] * 15)
    assert "Pode voltar" in mf.veredito(ganha)
    perde = mf.resumo([{"g": 1, "lucro": 0.8, "p": 0.6, "preco": 0.55}] * 20
                      + [{"g": 0, "lucro": -1.0, "p": 0.6, "preco": 0.55}] * 40)
    assert "PERDE" in mf.veredito(perde)


def test_sombra_nao_publica_nem_chama_a_revisao_de_ia():
    import inspect
    fonte = inspect.getsource(fp.run_faltas_engine)
    assert 'gate = None if sombra else review_gate("faltas")' in fonte
    # O `continue` da sombra vem antes da revisao e do INSERT.
    assert fonte.index("if sombra:") < fonte.index("gate.apply(") < fonte.index("_salvar(cur")
