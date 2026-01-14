import os
import requests
from datetime import datetime, timezone
API_BASE_URL = "https://v3.football.api-sports.io"

LEAGUES = [
    {"name": "Premier League", "league_id": 39, "season": 2025},
    {"name": "La Liga", "league_id": 140, "season": 2025},
    {"name": "Bundesliga", "league_id": 78, "season": 2025},
    {"name": "Paulistão A1", "league_id": 475, "season": 2026},
]


def get_api_key():
    api_key = os.getenv("API_FOOTBALL_KEY")
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv("API_FOOTBALL_KEY")
        except ImportError:
            pass
    if not api_key:
        raise RuntimeError(
            "API_FOOTBALL_KEY não configurada no ambiente ou .env")
    return api_key


class ApiFootballCollector:
    def __init__(self):
        self.api_key = get_api_key()
        self.headers = {"x-apisports-key": self.api_key}

    def get_past_fixtures(self):
        from datetime import timezone
        now_utc = int(datetime.now(timezone.utc).timestamp())
        all_matches = []
        print("[INFO] Jogos passados via API-Football")
        for league in LEAGUES:
            params = {
                "league": league["league_id"],
                "season": league["season"]
            }
            url = f"{API_BASE_URL}/fixtures"
            print("[DEBUG] Chamando API-Football:", url)
            print("[DEBUG] HEADERS:", self.headers)
            print("[DEBUG] PARAMS:", params)
            try:
                resp = requests.get(url, headers=self.headers,
                                    params=params, timeout=30)
                print("[DEBUG] STATUS CODE:", resp.status_code)
                print("[DEBUG] RESPONSE TEXT (parcial):", resp.text[:300])
                if resp.status_code != 200:
                    print(f"[ERRO] Status {resp.status_code} - {resp.text}")
                data = resp.json()
                fixtures = data.get("response", [])
                filtered = [f for f in fixtures if f["fixture"]
                            ["timestamp"] < now_utc]
                print(
                    f"[DEBUG] {league['name']} ({league['league_id']}): {len(filtered)} jogos passados")
                for f in filtered:
                    fixture = f["fixture"]
                    home = f["teams"]["home"]
                    away = f["teams"]["away"]
                    league_info = f["league"]
                    match = {
                        "match_id": fixture["id"],
                        "homeTeam": {"name": home["name"]},
                        "awayTeam": {"name": away["name"]},
                        "league": league_info["name"],
                        "country": league_info["country"],
                        "startTimestamp": fixture["timestamp"]
                    }
                    all_matches.append(match)
            except Exception as e:
                print(
                    f"[ERRO] Falha ao buscar jogos da liga {league['name']}: {e}")
        print(
            f"[INFO] Total de jogos passados processados: {len(all_matches)}")
        return all_matches

    def get_fixtures(self):
        from datetime import timezone
        import time
        now_utc = int(datetime.now(timezone.utc).timestamp())
        all_matches = []
        print("[INFO] Jogos obtidos via API-Football")
        for league in LEAGUES:
            params = {
                "league": league["league_id"],
                "season": league["season"]
            }
            url = f"{API_BASE_URL}/fixtures"
            print("[DEBUG] Chamando API-Football:", url)
            print("[DEBUG] HEADERS:", self.headers)
            print("[DEBUG] PARAMS:", params)
            try:
                resp = requests.get(url, headers=self.headers,
                                    params=params, timeout=30)
                print("[DEBUG] STATUS CODE:", resp.status_code)
                print("[DEBUG] RESPONSE TEXT (parcial):", resp.text[:300])
                if resp.status_code != 200:
                    print(f"[ERRO] Status {resp.status_code} - {resp.text}")
                data = resp.json()
                fixtures = data.get("response", [])
                # Filtrar apenas jogos a partir de agora (UTC)
                filtered = [f for f in fixtures if f["fixture"]
                            ["timestamp"] >= now_utc]
                print(
                    f"[DEBUG] {league['name']} ({league['league_id']}): {len(filtered)} jogos")
                for f in filtered:
                    fixture = f["fixture"]
                    home = f["teams"]["home"]
                    away = f["teams"]["away"]
                    league_info = f["league"]
                    match = {
                        "match_id": fixture["id"],
                        "homeTeam": {"name": home["name"]},
                        "awayTeam": {"name": away["name"]},
                        "league": league_info["name"],
                        "country": league_info["country"],
                        "startTimestamp": fixture["timestamp"]
                    }
                    all_matches.append(match)
            except Exception as e:
                print(
                    f"[ERRO] Falha ao buscar jogos da liga {league['name']}: {e}")
        print(f"[INFO] Total de jogos processados: {len(all_matches)}")
        return all_matches

    def get_fixture_statistics(self, fixture_id):
        try:
            resp = requests.get(f"{API_BASE_URL}/fixtures/statistics",
                                headers=self.headers, params={"fixture": fixture_id}, timeout=30)
            data = resp.json()
            stats = {"home": {}, "away": {}}
            for team_stats in data.get("response", []):
                team = team_stats.get("team", {})
                side = "home" if team_stats.get(
                    "teams", {}).get("home", False) else "away"
                statistics = {item["type"]: item["value"]
                              for item in team_stats.get("statistics", [])}
                stats[side] = statistics
            return stats
        except Exception as e:
            print(
                f"[ERRO] Falha ao buscar estatísticas do fixture {fixture_id}: {e}")
            return {"home": {}, "away": {}}
