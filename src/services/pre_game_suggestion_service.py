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
        self.historical_service = HistoricalStatsService()
        self.value_service = ValueAnalysisService()
        self.prob_model = ProbabilityModelService()

    # ------------------------------------------
    # FUNÇÃO AUXILIAR PARA ACHAR team_id NO BANCO
    # ------------------------------------------
    def _resolve_team_id(self, team_name):
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()

        cur.execute("""
            SELECT id
            FROM teams
            WHERE LOWER(name) = LOWER(%s)
            LIMIT 1
        """, (team_name,))

        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            print(f"[WARN] Team não encontrado no banco: {team_name}")
            return None

        return row[0]

    # ------------------------------------------
    # SALVAR APOSTA
    # ------------------------------------------
    def save_recommendation(self, match_id, market, side, line, odd, ev, probability):
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO bet_recommendations (
                match_id, market, team_side, line, odd, probability,
                expected_value, recommendation, created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (match_id, market, team_side, line)
            DO NOTHING
        """, (
            match_id, market, side, line, odd, probability, ev,
            "PENDING", datetime.datetime.utcnow()
        ))

        conn.commit()
        cur.close()
        conn.close()

    # ------------------------------------------
    # PROCESSO PRINCIPAL
    # ------------------------------------------
    def generate_pre_game(self, fixture):
        """
        fixture esperado:
        {
            "fixture_id": 123,
            "league_id": 39,
            "home_team": "Manchester United",
            "away_team": "Manchester City",
            "match_datetime": 1768717200
        }
        """

        fixture_id = fixture["fixture_id"]
        league_id = fixture["league_id"]
        home = fixture["home_team"]
        away = fixture["away_team"]

        print(f"\n[PRE-JOGO] Processando {home} x {away} ({fixture_id})")

        # ------------------------------------------------------------
        # 1) Match com Odds API (garante que pegaremos o EVENT_ID real)
        # ------------------------------------------------------------
        event_id = self.matcher.match_event(league_id, home, away)
        if not event_id:
            print("[SKIP] Sem event_id na Odds API")
            return

        print(f"[EVENT MATCH] Encontrado event_id = {event_id}")

        # ------------------------------------------------------------
        # 2) Pegar odds reais do jogo
        # ------------------------------------------------------------
        odds = self.odds_service.get_odds_by_event_id(
            sport_key=self.matcher.LEAGUE_TO_SPORT_KEY[league_id],
            event_id=event_id
        )

        if not odds:
            print("[SKIP] Odds não encontradas")
            return

        print(f"[ODDS] Encontradas {len(odds)} odds")

        # ------------------------------------------------------------
        # 3) Estatísticas históricas
        # ------------------------------------------------------------
        home_team_id = self._resolve_team_id(home)
        away_team_id = self._resolve_team_id(away)

        if not home_team_id or not away_team_id:
            print("[SKIP] team_id não encontrado no banco")
            return

        home_stats = self.historical_service.get_team_stats(home_team_id)
        away_stats = self.historical_service.get_team_stats(away_team_id)

        # ------------------------------------------------------------
        # 4) Value Analysis + Probabilidades avançadas para cada odd
        # ------------------------------------------------------------
        for item in odds:
            market = item["market"]
            side = item["side"]
            odd = float(item["odd"])
            line = item["line"] if item["line"] is not None else 0.0

            prob_data = self.prob_model.compute_probabilities(
                home_stats,
                away_stats,
                market,
                line
            )

            if not prob_data:
                continue

            if side == "Over":
                prob = prob_data["prob_over"]
            else:
                prob = prob_data["prob_under"]

            value = self.value_service.calculate_value(prob, odd)

            if not value["has_value"]:
                print(
                    f"[NO VALUE] {market} {side} {line} @ {odd} | Prob={prob:.3f}")
                continue

            # ------------------------------------------------------------
            # SALVA RECOMENDAÇÃO
            # ------------------------------------------------------------
            self.save_recommendation(
                match_id=fixture_id,
                market=market,
                side=side,
                line=line,
                odd=odd,
                ev=value["expected_value"],
                probability=prob
            )

            print(
                f"[SAVE] {market} {side} {line} @ {odd} | Prob={prob:.3f} | EV={value['expected_value']:.3f}"
            )


if __name__ == "__main__":
    service = PreGameSuggestionService()
