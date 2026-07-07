"""Motor de picks modular -- Fase 1 (base deterministica) + Fase 2
(contexto + perfil das equipes/matchup).

Ponto de entrada publico: analyze_fixture_markets() + rank_market_candidates()
+ explain(). Fase 3 adiciona news_model.py / consensus.py sem reabrir os
modulos existentes."""
from services.pick_engine.orchestrator import analyze_fixture_markets, explain
from services.pick_engine.ranking import rank_market_candidates, rank_all_candidates, select_final_picks
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG, DICA_CONFIG
from services.pick_engine import (
    context_model, team_profile_model, competition_profile,
    probability_model, variance_model, team_strength, data_validation,
    bayesian_model,
)

__all__ = [
    "analyze_fixture_markets",
    "rank_market_candidates",
    "rank_all_candidates",
    "select_final_picks",
    "explain",
    "PickEngineConfig",
    "DEFAULT_CONFIG",
    "DICA_CONFIG",
    "context_model",
    "team_profile_model",
    "competition_profile",
    "probability_model",
    "variance_model",
    "team_strength",
    "data_validation",
    "bayesian_model",
]
