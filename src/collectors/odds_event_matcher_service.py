import os
import requests
import unicodedata
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")


class OddsEventMatcherService:

    BASE_URL = "https://api.the-odds-api.com/v4/sports"

    LEAGUE_TO_SPORT_KEY = {
        39: "soccer_epl",       # Premier League
        140: "soccer_spain_la_liga",
        78: "soccer_germany_bundesliga",
        475: "soccer_brazil_campeonato_paulista"
    }

    def normalize(self, text):
        if not text:
            return ""
        text = text.lower()
        text = unicodedata.normalize("NFKD", text).encode(
            "ascii", "ignore").decode()
        text = text.replace("fc", "").replace("cf", "").replace("sc", "")
        text = text.replace("football club", "").replace("club", "")
        text = text.replace("-", " ").replace("_", " ")
        text = " ".join(text.split())
        return text

    def get_odds_events(self, sport_key):
        url = f"{self.BASE_URL}/{sport_key}/events"
        params = {
            "apiKey": ODDS_API_KEY
        }
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()

    def match_event(self, league_id, home_team, away_team):
        if league_id not in self.LEAGUE_TO_SPORT_KEY:
            print(f"[WARN] Liga {league_id} sem sport_key configurado")
            return None

        sport_key = self.LEAGUE_TO_SPORT_KEY[league_id]
        events = self.get_odds_events(sport_key)

        home_n = self.normalize(home_team)
        away_n = self.normalize(away_team)

        print(f"[MATCH] Procurando jogo OddsAPI: {home_team} x {away_team}")
        print(f"[NORMALIZED] {home_n} x {away_n}")

        # ---------------------------
        # 1. MATCH EXATO
        # ---------------------------
        for ev in events:
            ev_home = self.normalize(ev["home_team"])
            ev_away = self.normalize(ev["away_team"])

            if ev_home == home_n and ev_away == away_n:
                print(f"[MATCH-EXATO] {ev['id']}")
                return ev["id"]

        # ---------------------------
        # 2. MATCH PARCIAL (Contém)
        # ---------------------------
        for ev in events:
            ev_home = self.normalize(ev["home_team"])
            ev_away = self.normalize(ev["away_team"])

            if home_n in ev_home and away_n in ev_away:
                print(f"[MATCH-PARCIAL] {ev['id']}")
                return ev["id"]

        print("[NO-MATCH] Nenhum evento encontrado na Odds API")
        return None
