import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

BASE_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds"

MARKETS_MAP = {
    "GOLS": "totals",
    "CORNERS": "corners_totals",
    "CARDS": "cards_totals"
}

class OddsCollectorService:

    def get_odds_for_fixture(self, home_team, away_team):
        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": ",".join(MARKETS_MAP.values()),
            "oddsFormat": "decimal"
        }

        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()

        events = response.json()

        # 🔎 filtro local por times
        for event in events:
            if (
                event["home_team"].lower() == home_team.lower()
                and event["away_team"].lower() == away_team.lower()
            ):
                return self._extract_markets(event)

        return []

    def _extract_markets(self, event):
        odds_list = []

        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    odds_list.append({
                        "market": market["key"],
                        "line": outcome.get("point"),
                        "odd": outcome.get("price")
                    })

        return odds_list
