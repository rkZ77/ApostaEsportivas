"""
Pipeline principal de análise de apostas esportivas.
Pré-jogo, baseado em estatísticas históricas.
"""


from collectors.api_football_collector import ApiFootballCollector
from collectors.betano_collector import BetanoCollector
from analytics.goals_model import prob_goals_total, prob_goals_team
from analytics.corners_model import prob_corners_total, prob_corners_team
from analytics.cards_model import prob_cards_total, prob_cards_team
from services.value_analysis_service import calculate_expected_value, classify_ev
from services.bet_recommendation_service import save_recommendation

LEAGUE_IDS = [39, 140, 78, 475]
HISTORICAL_GAMES = 10
collector = ApiFootballCollector()
betano = BetanoCollector()


def main():
    matches = collector.get_fixtures()
    print(
        f"[DEBUG] Total jogos retornados API-Football: {len(matches) if matches else 0}")
    if not matches:
        print("[INFO] Nenhum jogo das ligas suportadas hoje ou amanhã.")
        return
    for match in matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        # Exemplo de uso de estatísticas históricas (ajuste conforme integração real)
        # home_id = ... # obter id do time se disponível
        # away_id = ...
        # home_stats = collector.get_team_historical_stats(home_id, HISTORICAL_GAMES)
        # away_stats = collector.get_team_historical_stats(away_id, HISTORICAL_GAMES)
        print(f"[DEBUG] Jogo encontrado: {home_team} x {away_team}")
        # home_id = match["homeTeam"]["id"]  # Não existe mais campo id no time
        # away_id = match["awayTeam"]["id"]  # Não existe mais campo id no time
        match_event_id = match["match_id"]

        home_stats = sofa.get_team_historical_stats(home_id, HISTORICAL_GAMES)
        away_stats = sofa.get_team_historical_stats(away_id, HISTORICAL_GAMES)
        odds = betano.get_odds_by_match(home_team, away_team)
        print(f"[DEBUG] Odds retornadas: {odds if odds else '{}'}")

        if not odds:
            print(
                "[INFO] Jogo sem odds disponíveis na Betano. Nenhuma sugestão gerada.")
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
