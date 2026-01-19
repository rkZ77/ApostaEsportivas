import datetime
import psycopg2

from src.collectors.odds_event_matcher_service import OddsEventMatcherService
from src.collectors.odds_collector_service import OddsCollectorService
from src.services.historical_stats_service import HistoricalStatsService
from src.services.value_analysis_service import ValueAnalysisService
from src.services.probability_model_service import ProbabilityModelService


DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "football_stats"
DB_USER = "postgres"
DB_PASS = "Pereira2310!"


class PreGameSuggestionService:

    def __init__(self):
        self.matcher = OddsEventMatcherService()
        self.odds_service = OddsCollectorService()
        self.value_service = ValueAnalysisService()

    def _get_connection(self):
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )

    def generate_pre_game(self, fixture: dict):
        """
        fixture esperado:
        {
            "fixture_id": 123,
            "league_id": 39,
            "home_team": "Brighton",
            "away_team": "Bournemouth",
            "match_datetime": datetime
        }
        """

        fixture_id = fixture["fixture_id"]
        league_id = fixture["league_id"]
        home = fixture["home_team"]
        away = fixture["away_team"]

        print(f"\n[PRE-JOGO] Processando {home} x {away} ({fixture_id})")

        # 1) Match com Odds API
        event_id = self.matcher.match_event(league_id, home, away)
        if not event_id:
            print("[SKIP] Sem event_id na Odds API")
            return

        # 2) Buscar odds reais
        odds = self.odds_service.fetch_odds_by_event(
            sport_key=self.matcher.LEAGUE_TO_SPORT_KEY[league_id],
            event_id=event_id
        )

        if not odds:
            print("[SKIP] Odds não encontradas")
            return

        print(f"[ODDS] {len(odds)} odds encontradas")

        conn = self._get_connection()
        cur = conn.cursor()

        for item in odds:
            market = item["market"]
            side = item["side"]
            odd = float(item["odd"])
            line = item.get("line", 0)

            # modelo simples (placeholder)
            probability = 1 / odd
            result = self.value_service.calculate_value(probability, odd)

            if not result["has_value"]:
                continue

            cur.execute("""
                INSERT INTO bet_recommendations (
                    fixture_id, market, team_side, line,
                    odd, probability, expected_value,
                    recommendation, created_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (
                fixture_id,
                market,
                side,
                line,
                odd,
                probability,
                result["expected_value"],
                "PENDING",
                datetime.datetime.utcnow()
            ))

            print(f"[SAVE] {market} {side} @ {odd}")

        conn.commit()
        cur.close()
        conn.close()
