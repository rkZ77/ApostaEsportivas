"""Motor de picks modular -- Fase 1 (base deterministica) + Fase 2
(contexto + perfil das equipes/matchup).

Ponto de entrada publico: analyze_fixture_markets() + rank_market_candidates()
+ explain(). Fase 3 adiciona news_model.py / consensus.py sem reabrir os
modulos existentes."""
from services.pick_engine.orchestrator import analyze_fixture_markets, explain
from services.pick_engine.ranking import (
    rank_market_candidates, rank_all_candidates, select_final_picks,
    rank_all_candidates_debug, select_final_picks_debug, evaluate_all_lines,
)
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG, DICA_CONFIG
from services.pick_engine.staking import calculate_stake
from services.pick_engine.ai_review import AIReviewGate, AIReviewSettings, review_gate
from services.pick_engine import (
    context_model, team_profile_model, competition_profile,
    probability_model, variance_model, team_strength, data_validation,
    bayesian_model, homologation, referee_model, red_analysis,
)

__all__ = [
    "analyze_fixture_markets",
    "rank_market_candidates",
    "rank_all_candidates",
    "select_final_picks",
    "rank_all_candidates_debug",
    "select_final_picks_debug",
    "evaluate_all_lines",
    "explain",
    "PickEngineConfig",
    "DEFAULT_CONFIG",
    "DICA_CONFIG",
    "calculate_stake",
    "AIReviewGate",
    "AIReviewSettings",
    "review_gate",
    "context_model",
    "team_profile_model",
    "competition_profile",
    "probability_model",
    "variance_model",
    "team_strength",
    "data_validation",
    "bayesian_model",
    "homologation",
    "referee_model",
    "red_analysis",
]
