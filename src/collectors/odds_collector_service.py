import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

class OddsCollectorService:

    def get_odds_by_event_id(self, sport_key, event_id):
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds"

        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": "totals,corners_totals,cards_totals",
            "oddsFormat": "decimal"
        }

        r = requests.get(url, params=params)
        r.raise_for_status()

        data = r.json()
        return self._parse_markets(data)

    def _parse_markets(self, event):
        odds = []

        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    odds.append({
                        "bookmaker": bookmaker["key"],
                        "market": market["key"],
                        "side": outcome["name"],
                        "line": outcome.get("point"),
                        "odd": outcome["price"]
                    })

        return odds