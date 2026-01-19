import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

BASE_URL = "https://api.the-odds-api.com/v4"


class OddsCollectorService:

    def fetch_odds_by_event(self, sport_key, event_id):
        all_odds = []

        for market in ["totals", "corners_totals", "cards_totals"]:
            odds = self._fetch_market(sport_key, event_id, market)
            if odds:
                all_odds.extend(odds)

        return all_odds

    def _fetch_market(self, sport_key, event_id, market):
        url = f"{BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": market,
            "oddsFormat": "decimal"
        }

        r = requests.get(url, params=params)

        if r.status_code != 200:
            print(
                f"[ODDS] Mercado '{market}' indisponível para event {event_id}")
            return []

        data = r.json()
        return self._parse(data, market)

    def _parse(self, event, market_key):
        odds = []

        for bookmaker in event.get("bookmakers", []):
            if bookmaker["key"] not in ["bet365", "betano", "superbet"]:
                continue

            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    odds.append({
                        "bookmaker": bookmaker["key"],
                        "market": market_key,
                        "side": outcome["name"],
                        "line": outcome.get("point", 0.0),
                        "odd": outcome["price"]
                    })

        return odds
