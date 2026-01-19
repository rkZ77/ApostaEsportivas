import requests
import datetime
from unidecode import unidecode
from dotenv import load_dotenv
import os

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")


class OddsEventMatcherService:

    LEAGUE_TO_SPORT_KEY = {
        39: "soccer_epl",
        140: "soccer_spain_la_liga",
        78: "soccer_germany_bundesliga",
        475: "soccer_brazil_camp_paulista"
    }

    def normalize(self, name):
        return unidecode(name).lower().strip()

    def fetch_events(self, sport_key):
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events"
        params = {
            "apiKey": ODDS_API_KEY
        }

        r = requests.get(url, params=params)
        if r.status_code != 200:
            print(f"[EVENTS] Falha ao buscar eventos: status {r.status_code}")
            return []

        return r.json()

    def match_event(self, league_id, home_name, away_name):
        if league_id not in self.LEAGUE_TO_SPORT_KEY:
            print(f"[WARN] Liga {league_id} sem sport_key configurado")
            return None

        sport_key = self.LEAGUE_TO_SPORT_KEY[league_id]

        print(f"[MATCH] Procurando jogo OddsAPI: {home_name} x {away_name}")

        home_norm = self.normalize(home_name)
        away_norm = self.normalize(away_name)

        events = self.fetch_events(sport_key)

        best_match = None

        for event in events:
            e_home = self.normalize(event["home_team"])
            e_away = self.normalize(event["away_team"])

            if home_norm in e_home and away_norm in e_away:
                best_match = event["id"]
                break

            if e_home in home_norm and e_away in away_norm:
                best_match = event["id"]
                break

        if best_match:
            print(f"[EVENT MATCH] Encontrado event_id = {best_match}")
        else:
            print("[EVENT MATCH] Nenhuma correspondência encontrada")

        return best_match
