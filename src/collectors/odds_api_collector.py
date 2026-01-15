"""
Coletor de odds da The Odds API POR JOGO usando requests.
"""

import requests
from typing import Dict
import os


class OddsApiCollector:
    BASE_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"

    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ODDS_API_KEY não configurada no ambiente ou .env")

    def get_odds_by_match(self, home_team: str, away_team: str) -> Dict[str, float]:
        odds = {
            "goals_over_2_5": None,
            "corners_over_9_5": None,
            "cards_over_4_5": None,
        }
        params = {
            "apiKey": self.api_key,
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=30)
            data = resp.json()
            # Exemplo: busca odds de over 2.5 goals
            for match in data:
                if home_team in match["home_team"] and away_team in match["away_team"]:
                    for bookmaker in match.get("bookmakers", []):
                        for market in bookmaker.get("markets", []):
                            if market["key"] == "totals":
                                for outcome in market.get("outcomes", []):
                                    if outcome["name"] == "Over 2.5":
                                        odds["goals_over_2_5"] = outcome["price"]
            # Adapte para outros mercados conforme necessário
        except Exception as e:
            print(f"[ERRO] Falha ao buscar odds da Odds API: {e}")
        return odds
