import os
import requests
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
if not ODDS_API_KEY:
    raise RuntimeError("ODDS_API_KEY não definida no ambiente")

BASE_URL = "https://api.the-odds-api.com/v4/sports/soccer/odds"

BOOKMAKERS_ALLOWED = ["bet365", "pinnacle"]

# Mapeamento interno de mercados
MARKET_MAP = {
    "GOALS": {
        "api_market": "totals",
        "lines": [1.5, 2.5, 3.5]
    },
    "CORNERS": {
        "api_market": "corners_totals",
        "lines": [8.5, 9.5, 10.5]
    },
    "CARDS": {
        "api_market": "cards_totals",
        "lines": [3.5, 4.5, 5.5]
    }
}


class OddsCollectorService:

    def __init__(self):
        self.headers = {}
        self.params_base = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": ",".join(
                m["api_market"] for m in MARKET_MAP.values()
            ),
            "oddsFormat": "decimal"
        }

    def get_odds_for_fixture(self, home_team: str, away_team: str):
        """
        Retorna odds normalizadas por mercado.
        """
        params = self.params_base.copy()
        params["home_team"] = home_team
        params["away_team"] = away_team

        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()

        events = response.json()
        if not events:
            return []

        odds_results = []

        for event in events:
            for bookmaker in event.get("bookmakers", []):
                if bookmaker["key"] not in BOOKMAKERS_ALLOWED:
                    continue

                for market in bookmaker.get("markets", []):
                    normalized = self._parse_market(market)
                    odds_results.extend(normalized)

        return odds_results

    # ===========================
    # NORMALIZAÇÃO
    # ===========================
    def _parse_market(self, market_data):
        results = []

        for market_key, config in MARKET_MAP.items():
            if market_data["key"] != config["api_market"]:
                continue

            for outcome in market_data.get("outcomes", []):
                if outcome["name"].lower() != "over":
                    continue

                line = float(outcome.get("point", 0))
                if line not in config["lines"]:
                    continue

                results.append({
                    "market": market_key,
                    "line": line,
                    "odd": float(outcome["price"])
                })

        return results
