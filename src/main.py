"""
Pipeline principal de análise de apostas esportivas.
Pré-jogo, baseado em estatísticas históricas.
"""


from collectors.api_football_collector import ApiFootballCollector
from collectors.odds_api_collector import OddsApiCollector
from analytics.goals_model import prob_goals_total, prob_goals_team
from analytics.corners_model import prob_corners_total, prob_corners_team
from analytics.cards_model import prob_cards_total, prob_cards_team
from services.value_analysis_service import calculate_expected_value, classify_ev
from services.bet_recommendation_service import save_recommendation

LEAGUE_IDS = [39, 140, 78, 475]
HISTORICAL_GAMES = 10
collector = ApiFootballCollector()
odds_api = OddsApiCollector()


def main():
    matches = collector.get_fixtures()
    print(
        f"[DEBUG] Total jogos retornados API-Football: {len(matches) if matches else 0}")
    if not matches:
        print("[INFO] Nenhum jogo das ligas suportadas hoje ou amanhã.")
        return
    from services.team_service import get_team_id_by_name
    from services.historical_stats_service import HistoricalStatsService
    stats_service = HistoricalStatsService()
    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        match_event_id = match["match_id"]
        # Resolve team_id via tabela teams
        home_team_id = get_team_id_by_name(home_team)
        away_team_id = get_team_id_by_name(away_team)
        if not home_team_id or not away_team_id:
            print(
                f"[WARN] Não foi possível resolver team_id para: {home_team} ou {away_team}. Nenhuma sugestão gerada.")
            continue
        home_stats = stats_service.get_team_stats(home_team_id)
        away_stats = stats_service.get_team_stats(away_team_id)
        odds = odds_api.get_odds_by_match(home_team, away_team)
        print(f"[DEBUG] Odds retornadas: {odds if odds else '{}'}")

        if not odds:
            print(
                "[INFO] Jogo sem odds disponíveis na Odds API. Nenhuma sugestão gerada.")
            continue

        # Mercado: ESCANTEIOS
        # Visitante
        if odds.get("corners_away_over_5_5"):
            prob = prob_corners_team(away_stats["avg_corners"], 5.5)
            ev = calculate_expected_value(prob, odds["corners_away_over_5_5"])
            save_recommendation(
                match_event_id,
                "corners",
                "away",
                5.5,
                odds["corners_away_over_5_5"],
                prob,
                ev,
                classify_ev(ev)
            )

        # Mercado: CARTÕES
        # Total
        if odds.get("cards_over_4_5"):
            prob = prob_cards_total(
                home_stats["avg_cards"], away_stats["avg_cards"], 4.5)
            ev = calculate_expected_value(prob, odds["cards_over_4_5"])
            save_recommendation(match_event_id, "cards", "total",
                                4.5, odds["cards_over_4_5"], prob, ev, classify_ev(ev))
        # Mandante
        if odds.get("cards_home_over_2_5"):
            prob = prob_cards_team(home_stats["avg_cards"], 2.5)
            ev = calculate_expected_value(prob, odds["cards_home_over_2_5"])
            save_recommendation(match_event_id, "cards", "home", 2.5,
                                odds["cards_home_over_2_5"], prob, ev, classify_ev(ev))
        # Visitante
        if odds.get("cards_away_over_2_5"):
            prob = prob_cards_team(away_stats["avg_cards"], 2.5)
            ev = calculate_expected_value(prob, odds["cards_away_over_2_5"])
            save_recommendation(match_event_id, "cards", "away", 2.5,
                                odds["cards_away_over_2_5"], prob, ev, classify_ev(ev))


if __name__ == "__main__":
    main()
