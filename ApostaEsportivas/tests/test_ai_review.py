import os

import pytest

from services.pick_engine.ai_review import (
    AIReviewGate, AIReviewSettings, build_review_payload, normalize_review,
)


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


def test_todo_pipeline_revisa_na_openai(env_limpo):
    """09/11/2026: o projeto so' usa OpenAI. Free, alavancagem e faltas, que
    iam pra Anthropic, herdam o modelo OpenAI do VIP."""
    env_limpo.setenv("AI_REVIEW_MODE", "shadow")
    env_limpo.setenv("AI_REVIEW_MODEL_VIP", "modelo-openai")
    for pipeline in ("dica", "alavancagem", "faltas", "vip", "multipla", "bingo", "live"):
        s = AIReviewSettings.from_env(pipeline)
        assert s.provider == "openai" and s.model == "modelo-openai", pipeline


def test_variavel_antiga_da_anthropic_nao_derruba_o_gate(env_limpo):
    """Railway com AI_REVIEW_PROVIDER_DICA=anthropic e AI_REVIEW_MODEL_DICA
    claude-*: mandar o ID claude pra OpenAI so' daria erro, e erro bloqueia o
    pick. O gate ignora os dois e usa o modelo OpenAI do projeto."""
    env_limpo.setenv("AI_REVIEW_MODE", "enforce")
    env_limpo.setenv("AI_REVIEW_PROVIDER_DICA", "anthropic")
    env_limpo.setenv("AI_REVIEW_MODEL_DICA", "claude-sonnet-5")
    env_limpo.setenv("AI_REVIEW_MODEL_VIP", "gpt-modelo")
    s = AIReviewSettings.from_env("dica")
    assert (s.provider, s.model, s.mode) == ("openai", "gpt-modelo", "enforce")


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
