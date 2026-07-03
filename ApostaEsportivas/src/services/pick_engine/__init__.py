"""Motor de picks modular -- Fase 1 (base deterministica).

Ponto de entrada publico: analyze_fixture_markets() + rank_market_candidates()
+ explain(). Fases 2/3 adicionam context_model.py / team_profile_model.py /
news_model.py / consensus.py sem reabrir os modulos desta fase."""
from services.pick_engine.orchestrator import analyze_fixture_markets, explain
from services.pick_engine.ranking import rank_market_candidates
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG, DICA_CONFIG

__all__ = [
    "analyze_fixture_markets",
    "rank_market_candidates",
    "explain",
    "PickEngineConfig",
    "DEFAULT_CONFIG",
    "DICA_CONFIG",
]
