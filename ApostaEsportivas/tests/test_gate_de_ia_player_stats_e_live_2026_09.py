"""O gate de IA nos dois motores que nao tinham: Player Stats e ao vivo.

O modo de falha que estes testes guardam nao e' "o gate nao roda" -- e' o
gate rodando com o payload EM BRANCO. `build_review_payload` nasceu dos
motores de mercado de time e le nomes (`market_name`, `taxa_real`) que nem o
Player Stats nem o ao vivo usam: sem tradutor, a chamada acontece, custa
dinheiro, grava evento no painel e a IA opina sobre um pick vazio.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engine_pipelines.player_stats_pipeline import _pick_para_ia as ps_para_ia
from engine_pipelines.live_pipeline import _pick_para_ia as live_para_ia
from services.pick_engine.ai_review import build_review_payload, DEFAULT_PROVIDERS


class _Metodo:
    label, slug = "Chutes no alvo", "shots_on"


def test_player_stats_chega_na_ia_com_o_pick_preenchido():
    c = {
        "analise": {"odd": 1.80, "probability": 0.71, "edge": 0.09,
                    "ev": 0.12, "amostra": 8},
        "jogador": {"player_name": "Fulano", "team_name": "Time A"},
        "metodo": _Metodo(), "rotulo_linha": "2 ou mais chutes no alvo",
        "composicao": {"atuacoes": 8},
    }
    pick = build_review_payload([ps_para_ia(c)], "player_stats")["picks"][0]
    assert pick["odd"] == 1.80
    assert pick["probability"] == 0.71
    assert pick["market"] == "Chutes no alvo"
    # QUEM e' o jogador precisa atravessar: e' o que distingue prop de jogador
    # de mercado de time, e sem isso a IA nao tem sobre o que opinar.
    assert "Fulano" in pick["selection"]


def test_live_chega_na_ia_com_o_minuto_e_o_ja_observado():
    candidato = {"familia": "corners", "market": "Escanteios Mais/Menos",
                 "line": "Over 9.5", "linha": 9.5, "odd": 1.95,
                 "probability": 0.68, "confidence": 0.7, "edge": 0.06, "ev": 0.10}
    estado = {"minuto": 80, "home_goals": 1, "away_goals": 0, "corners_total": 4}
    pick = build_review_payload([live_para_ia(candidato, estado)], "live")["picks"][0]
    assert pick["odd"] == 1.95
    # Sem minuto e contador, "Over 9.5 aos 80 com 4" e "aos 20 com 4" viram o
    # mesmo pick pra quem le' o payload.
    assert pick["match_context"]["minuto"] == 80
    assert pick["match_context"]["ja_observado"] == 4


def test_os_dois_motores_usam_openai():
    assert DEFAULT_PROVIDERS["player_stats"] == "openai"
    assert DEFAULT_PROVIDERS["live"] == "openai"


# --- O modelo OpenAI que o Railway nao declara -----------------------------
#
# `player_stats` e `live` ganharam gate depois que as variaveis do Railway
# foram criadas (so' existem _VIP, _MULTIPLA e _GOLEIROS). Sem heranca eles
# nasceriam com o gate DESLIGADO em producao, em silencio.

import pytest
from services.pick_engine.ai_review import AIReviewSettings


@pytest.fixture
def _env_do_railway(monkeypatch):
    """So' as tres variaveis que existem hoje em producao."""
    for chave in list(os.environ):
        if chave.startswith("AI_REVIEW_MODEL"):
            monkeypatch.delenv(chave, raising=False)
    monkeypatch.setenv("AI_REVIEW_MODE", "enforce")
    monkeypatch.setenv("AI_REVIEW_MODEL_VIP", "gpt-5.4-2026-03-05")
    monkeypatch.setenv("AI_REVIEW_MODEL_MULTIPLA", "gpt-5.4-2026-03-05")
    monkeypatch.setenv("AI_REVIEW_MODEL_GOLEIROS", "gpt-5.4-2026-03-05")


@pytest.mark.parametrize("pipeline", ["player_stats", "live"])
def test_pipeline_openai_sem_variavel_propria_herda_a_do_vip(_env_do_railway, pipeline):
    s = AIReviewSettings.from_env(pipeline)
    assert s.provider == "openai"
    assert s.model == "gpt-5.4-2026-03-05"
    # O que importa nao e' o ID: e' o gate continuar LIGADO. Sem modelo,
    # `from_env` rebaixa o modo pra "off" e o veto deixa de existir.
    assert s.mode == "enforce"


def test_variavel_propria_ainda_vence_a_heranca(_env_do_railway, monkeypatch):
    monkeypatch.setenv("AI_REVIEW_MODEL_LIVE", "gpt-outro")
    assert AIReviewSettings.from_env("live").model == "gpt-outro"


# --- O veto de verdade, com o tradutor no meio -----------------------------

from services.pick_engine.ai_review import AIReviewGate


def _gate(decision):
    return AIReviewGate(AIReviewSettings(mode="enforce"),
                        call_model=lambda *_: {"decision": decision,
                                               "risk_level": "high", "reasons": ["teste"]})


def _candidato_ps():
    return {"analise": {"odd": 1.8, "probability": 0.7, "edge": 0.09, "ev": 0.1,
                        "amostra": 8},
            "jogador": {"player_name": "Fulano", "team_name": "Time A"},
            "metodo": _Metodo(), "rotulo_linha": "2 ou mais", "composicao": {}}


def test_player_stats_vetado_nao_publica():
    assert _gate("reject").apply([ps_para_ia(_candidato_ps())], "player_stats") == []


def test_player_stats_aprovado_volta_com_o_parecer():
    saida = _gate("approve").apply([ps_para_ia(_candidato_ps())], "player_stats")
    assert len(saida) == 1
    # O parecer precisa VOLTAR: e' ele que o pipeline enxerta no candidato pra
    # o engine_debug gravar. Sem isso o campo continuaria nascendo None, que
    # era o defeito original.
    assert saida[0]["ai_review"]["decision"] == "approve"


def test_live_vetado_nao_grava_pick():
    candidato = {"familia": "cards", "market": "Cartoes Mais/Menos",
                 "line": "Over 4.5", "linha": 4.5, "odd": 1.9,
                 "probability": 0.7, "confidence": 0.7, "edge": 0.05, "ev": 0.09}
    estado = {"minuto": 70, "home_goals": 0, "away_goals": 0, "cards_points_total": 3}
    assert _gate("reject").apply([live_para_ia(candidato, estado)], "live") == []


def test_live_falha_do_provedor_aprova_o_pick_do_motor():
    """Falha aberto, como nos outros seis: provedor fora do ar nao pode
    derrubar o pick que o motor ja decidiu."""
    def explode(*_):
        raise RuntimeError("provedor fora do ar")
    gate = AIReviewGate(AIReviewSettings(mode="enforce"), call_model=explode)
    candidato = {"familia": "fouls", "line": "Over 21.5", "linha": 21.5, "odd": 1.85,
                 "probability": 0.66, "confidence": 0.6, "edge": 0.05, "ev": 0.07}
    saida = gate.apply([live_para_ia(candidato, {"minuto": 50, "fouls_total": 12})], "live")
    assert len(saida) == 1
    assert saida[0]["ai_review"]["status"] == "unavailable"
