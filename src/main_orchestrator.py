
from datetime import datetime
from database.db_connection import get_connection
from main import main as run_pre_game
from services.pre_game_suggestion_service import save_pre_game_suggestion
from services.match_service import ensure_match_exists
from collectors.api_football_collector import ApiFootballCollector
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Pós-jogo: avaliação das recomendações


# Refatorado para usar serviço dedicado
def run_post_game_evaluation():
    from services.post_game_evaluation_service import evaluate_recommendations
    evaluate_recommendations()

# Métricas do robô


# Refatorado para usar serviço dedicado
def run_metrics():
    from services.metrics_service import get_metrics
    get_metrics()

# Orquestrador principal


def main():
    print("--- Fase Pré-Jogo: Sugestões ---")
    # Coleta dos jogos futuros
    collector = ApiFootballCollector()
    matches = collector.get_fixtures()
    from services.historical_stats_service import HistoricalStatsService
    stats_service = HistoricalStatsService()
    suggestions = []
    for fixture in matches:
        # Aceita formato do ApiFootballCollector
        required_keys = ["match_id", "homeTeam", "awayTeam",
                         "league", "country", "startTimestamp"]
        if not all(k in fixture for k in required_keys):
            print(f"[WARN] Fixture ignorado por formato inesperado: {fixture}")
            continue
        fixture_id = fixture["match_id"]
        league = fixture["league"]
        home_team_id = fixture["homeTeam"].get("id")
        away_team_id = fixture["awayTeam"].get("id")
        league_id = fixture.get("league_id") or None
        match_datetime = fixture["startTimestamp"]
        from services.team_service import ensure_team_exists, get_team_id_by_name
        # Ignora fixtures com times sem id
        if not home_team_id or not away_team_id:
            print(f"[WARN] Fixture ignorado: time sem id - {fixture}")
            continue
        # Garante que os times existem no banco
        ensure_team_exists(home_team_id, home_team, league_id)
        ensure_team_exists(away_team_id, away_team, league_id)
        if not all([fixture_id, league, home_team_id, away_team_id, home_team, away_team, match_datetime]):
            print(f"[WARN] Dados incompletos no fixture: {fixture}")
            continue
        # Garante que o jogo existe na tabela matches
        ensure_match_exists(fixture_id, league, home_team,
                            away_team, match_datetime)
        # Consulta estatísticas históricas dos times
        home_stats = stats_service.get_team_stats(home_team_id)
        away_stats = stats_service.get_team_stats(away_team_id)
        print(
            f"[PRE-JOGO] Estatísticas {home_team} (ID {home_team_id}): {home_stats}")
        print(
            f"[PRE-JOGO] Estatísticas {away_team} (ID {away_team_id}): {away_stats}")
        for market in ["goals", "corners", "cards"]:
            for side in ["total", "home", "away"]:
                suggestions.append(
                    (fixture_id, league, home_team, away_team, market, side, match_datetime))
        print(
            f"[PRE-JOGO] Estatísticas {away_team} (ID {away_team_id}): {away_stats}")
        for market in ["goals", "corners", "cards"]:
            for side in ["total", "home", "away"]:
                suggestions.append(
                    (fixture_id, league, home_team, away_team, market, side, match_datetime))
    # Salvar sugestões sem odds/probabilidade/resultado
    count_saved = 0
    for s in suggestions:
        save_pre_game_suggestion(*s)
        count_saved += 1
    print(f"[INFO] Sugestões pré-jogo salvas: {count_saved}")
    try:
        run_pre_game()
    except Exception as e:
        print(f"[AVISO] Erro na fase pré-jogo: {e}. Continuando fluxo.")
    print("--- Fase Pós-Jogo: Avaliação ---")
    run_post_game_evaluation()
    print("--- Fase de Métricas ---")
    run_metrics()


if __name__ == "__main__":
    main()
