"""Faltas atravessando o motor ao vivo inteiro.

O contador de faltas ja' vinha do feed antes desta mudanca (live_feed) e
morria em `montar_estado` -- publicado pela API, invisivel pro motor. Estes
testes guardam a travessia completa: estado -> ritmo -> residual -> cotacao.
Cada elo tem uma lista/dicionario proprio por familia, e esquecer UM deles nao
levanta erro nenhum: a familia simplesmente nao aparece, que e' como ela ficou
invisivel da primeira vez.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.pick_engine_live import live_odds, residual_model, rhythm_model
from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG
from services.pick_engine_live.live_state import montar_estado
from services.pick_engine import probability_model


def _bruto(minuto=60):
    return {"fixture": {"id": 1, "status": {"short": "2H", "elapsed": minuto}},
            "goals": {"home": 1, "away": 0},
            "teams": {"home": {"id": 10, "name": "A"}, "away": {"id": 20, "name": "B"}},
            "league": {"id": 71, "name": "Serie A"}}


def test_o_estado_passa_a_carregar_as_faltas():
    estado = montar_estado(_bruto(), {"Fouls": 9, "Corner Kicks": 3},
                           {"Fouls": 7, "Corner Kicks": 2}, [])
    assert estado["fouls_home"] == 9
    assert estado["fouls_away"] == 7
    assert estado["fouls_total"] == 16


def test_um_lado_sem_folha_nao_inventa_total():
    """Mesma regra das outras familias: sem os dois lados, nao ha total."""
    estado = montar_estado(_bruto(), {"Fouls": 9}, {"Corner Kicks": 2}, [])
    assert estado["fouls_total"] is None


def test_o_ritmo_enxerga_faltas():
    estado = montar_estado(_bruto(), {"Fouls": 12}, {"Fouls": 12}, [])
    familias = {f["familia"] for f in rhythm_model.ritmo(estado, 60)["familias"]}
    assert "fouls" in familias


def test_o_residual_tem_baseline_de_faltas():
    # Sem baseline a familia cairia na constante de outra coisa ou em nada.
    assert residual_model.BASELINE_PADRAO["fouls"] > 0
    # E a dispersao vem do pre-jogo, que e' quem manda no numero.
    assert probability_model.dispersao("fouls", "total") > 1.0


def test_a_familia_e_cotavel():
    assert "fouls" in live_odds.FAMILIAS_V1
    assert "fouls" in live_odds.NOMES_POR_FAMILIA
    assert live_odds.ROTULO_PT["fouls"] == "Faltas Mais/Menos"
    assert "fouls" in DEFAULT_LIVE_CONFIG.familias


def test_odd_de_faltas_vira_linha_cotavel():
    # Formato real do feed ao vivo: a direcao no `value` e a linha no
    # `handicap`, campos separados -- nao "Over 21.5" numa string so'.
    odds = [{"name": "Total Fouls", "values": [
        {"value": "Over", "handicap": "21.5", "odd": "1.85", "suspended": False},
        {"value": "Under", "handicap": "21.5", "odd": "1.95", "suspended": False}]}]
    linhas = live_odds.extrair_linhas(odds)
    faltas = [l for l in linhas if l["familia"] == "fouls"]
    assert faltas, "mercado de faltas ao vivo nao foi reconhecido"
    assert {l["direcao"] for l in faltas} == {"over", "under"}
