"""
Busca convocados, técnico e formação de seleções via API-Football.
Usado exclusivamente para enriquecer o contexto de jogos da Copa do Mundo.
"""

import os
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"x-apisports-key": API_KEY}
BASE = "https://v3.football.api-sports.io"


class WorldCupSquadService:

    def __init__(self):
        self.cache = {}

    # =========================================================================
    # MÉTODO PRINCIPAL
    # =========================================================================
    def get_squad_info(self, team_id: int) -> dict:
        """
        Retorna:
        {
            "coach": "Dorival Junior",
            "formation": "4-2-3-1",
            "players": {
                "GK":  ["Alisson Becker", "Ederson"],
                "DEF": ["Marquinhos", "Gabriel Magalhaes", ...],
                "MID": ["Casemiro", "Bruno Guimaraes", ...],
                "FWD": ["Vinicius Jr", "Rodrygo", ...]
            }
        }
        """
        if team_id in self.cache:
            return self.cache[team_id]

        print(f"[WC_SQUAD] Buscando squad info para team {team_id}...")

        squad_info = {
            "coach": self._fetch_coach(team_id),
            "formation": self._fetch_recent_formation(team_id),
            "players": self._fetch_squad(team_id),
        }

        self.cache[team_id] = squad_info
        return squad_info

    # =========================================================================
    # BUSCA DE DADOS
    # =========================================================================
    def _fetch_squad(self, team_id: int) -> dict:
        players = {"GK": [], "DEF": [], "MID": [], "FWD": []}
        try:
            r = requests.get(
                f"{BASE}/players/squads",
                headers=HEADERS,
                params={"team": team_id},
                timeout=15,
            )
            r.raise_for_status()

            response = r.json().get("response", [])
            if not response:
                return players

            for p in response[0].get("players", []):
                name = p.get("name", "")
                pos = p.get("position", "")
                if pos == "Goalkeeper":
                    players["GK"].append(name)
                elif pos == "Defender":
                    players["DEF"].append(name)
                elif pos == "Midfielder":
                    players["MID"].append(name)
                elif pos == "Attacker":
                    players["FWD"].append(name)

        except Exception as e:
            print(f"[WC_SQUAD] Erro ao buscar squad team {team_id}: {e}")

        return players

    def _fetch_coach(self, team_id: int) -> str | None:
        try:
            r = requests.get(
                f"{BASE}/coachs",
                headers=HEADERS,
                params={"team": team_id},
                timeout=15,
            )
            r.raise_for_status()

            response = r.json().get("response", [])
            if not response:
                return None

            # Prioriza técnico sem data de saída (atual)
            for coach_data in response:
                for entry in coach_data.get("career", []):
                    if (
                        entry.get("team", {}).get("id") == team_id
                        and entry.get("end") is None
                    ):
                        return coach_data.get("name")

            # Fallback: primeiro da lista
            return response[0].get("name")

        except Exception as e:
            print(f"[WC_SQUAD] Erro ao buscar técnico team {team_id}: {e}")
            return None

    def get_injuries(
        self,
        team_id: int,
        fixture_id: int = None,
        season: int = 2026,
        league_id: int = 1,
    ) -> list:
        """
        Retorna lesionados e suspensos do time.
        Usa fixture_id para precisão máxima; cai em nível de temporada se não fornecido.
        Formato: [{"name": "Player", "type": "Injured", "reason": "Hamstring"}, ...]
        """
        try:
            if fixture_id:
                params = {"fixture": fixture_id, "team": team_id}
            else:
                params = {"team": team_id, "season": season, "league": league_id}

            r = requests.get(
                f"{BASE}/injuries",
                headers=HEADERS,
                params=params,
                timeout=15,
            )
            r.raise_for_status()

            result = []
            for item in r.json().get("response", []):
                player = item.get("player", {})
                name = player.get("name", "")
                if not name:
                    continue
                result.append({
                    "name": name,
                    "type": item.get("type", ""),
                    "reason": item.get("reason", "") or "",
                })
            return result

        except Exception as e:
            print(f"[WC_SQUAD] Erro ao buscar lesionados/suspensos team {team_id}: {e}")
            return []

    def _fetch_recent_formation(self, team_id: int) -> str | None:
        """Busca formação nos últimos 3 jogos do time."""
        try:
            r = requests.get(
                f"{BASE}/fixtures",
                headers=HEADERS,
                params={"team": team_id, "last": 3},
                timeout=15,
            )
            r.raise_for_status()

            fixtures = r.json().get("response", [])
            if not fixtures:
                return None

            for fx_item in fixtures:
                fx_id = fx_item["fixture"]["id"]
                lr = requests.get(
                    f"{BASE}/fixtures/lineups",
                    headers=HEADERS,
                    params={"fixture": fx_id, "team": team_id},
                    timeout=15,
                )
                lr.raise_for_status()

                lineups = lr.json().get("response", [])
                if lineups and lineups[0].get("formation"):
                    return lineups[0]["formation"]

        except Exception as e:
            print(f"[WC_SQUAD] Erro ao buscar formação team {team_id}: {e}")

        return None
