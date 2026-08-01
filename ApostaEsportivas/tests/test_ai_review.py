import os

import pytest

from services.pick_engine.ai_review import AIReviewGate, AIReviewSettings, build_review_payload, normalize_review


@pytest.fixture
def env_limpo(monkeypatch):
    """Isola do .env, que e carregado no import de utils.db_utils."""
    for chave in list(os.environ):
        if chave.startswith(("AI_REVIEW", "DB_ENV")):
            monkeypatch.delenv(chave, raising=False)
    return monkeypatch


def _pick():
    return {"market_name": "Mais de gols", "market_type": "goals", "value_label": "Over 1.5",
            "odd": 1.6, "taxa_real": 0.72, "confidence": 0.74, "edge": 0.09,
            "ev": 0.15, "risco": "MEDIO", "context_raw": {"round_phase": "regular"}}


def test_payload_contains_review_fields():
    pick = {**_pick(), "data_quality_score": 86.5, "poisson_probability": 0.71, "market_sample": {"amostra_com_dado": 10}}
    payload = build_review_payload([pick], "vip", {"fixture_id": 10, "home_team": "A", "away_team": "B"})
    assert payload["fixture"]["id"] == 10
    assert payload["picks"][0]["probability"] == 0.72
    assert payload["picks"][0]["data_quality"] == 86.5
    assert payload["picks"][0]["model_probability"] == 0.71


def test_enforce_removes_rejected_selection():
    gate = AIReviewGate(AIReviewSettings(mode="enforce"), call_model=lambda *_: {"decision": "reject", "risk_level": "high", "reasons": ["Escalacao incerta"]})
    gate._load_cache = lambda _key: None
    gate._store_cache = lambda *_args: None
    gate._daily_limit_reached = lambda: False
    assert gate.apply([_pick()], "vip") == []


def test_shadow_keeps_pick_and_attaches_review():
    gate = AIReviewGate(AIReviewSettings(mode="shadow"), call_model=lambda *_: {"decision": "reject", "risk_level": "high", "reasons": ["Escalacao incerta"]})
    gate._load_cache = lambda _key: None
    gate._store_cache = lambda *_args: None
    gate._daily_limit_reached = lambda: False
    reviewed = gate.apply([_pick()], "vip")
    assert reviewed[0]["ai_review"]["decision"] == "reject"


def test_invalid_response_fails_open():
    assert normalize_review("fora do formato")["decision"] == "approve"


def test_provider_padrao_por_pipeline(env_limpo):
    env_limpo.setenv("AI_REVIEW_MODE", "shadow")
    env_limpo.setenv("AI_REVIEW_MODEL_VIP", "modelo-openai")
    env_limpo.setenv("AI_REVIEW_MODEL_MULTIPLA", "modelo-openai")
    assert AIReviewSettings.from_env("dica").provider == "anthropic"
    assert AIReviewSettings.from_env("alavancagem").provider == "anthropic"
    assert AIReviewSettings.from_env("vip").provider == "openai"
    assert AIReviewSettings.from_env("multipla").provider == "openai"
    assert AIReviewSettings.from_env("dica").model == "claude-opus-5"


def test_env_do_pipeline_vence_o_global(env_limpo):
    env_limpo.setenv("AI_REVIEW_MODE", "shadow")
    env_limpo.setenv("AI_REVIEW_MODE_VIP", "enforce")
    env_limpo.setenv("AI_REVIEW_MODEL_VIP", "modelo-openai")
    assert AIReviewSettings.from_env("vip").mode == "enforce"
    assert AIReviewSettings.from_env("alavancagem").mode == "shadow"


def test_openai_sem_modelo_desliga_em_vez_de_aprovar_calado(env_limpo):
    env_limpo.setenv("AI_REVIEW_MODE", "enforce")
    assert AIReviewSettings.from_env("vip").mode == "off"


def test_gate_desligado_nao_chama_provedor(env_limpo):
    def explode(*_):
        raise AssertionError("nao deveria chamar o provedor com o gate off")

    gate = AIReviewGate(AIReviewSettings(mode="off"), call_model=explode)
    reviewed = gate.apply([_pick()], "vip")
    assert len(reviewed) == 1
    assert reviewed[0]["ai_review"]["status"] == "disabled"
    assert reviewed[0]["odd"] == _pick()["odd"]
