from collectors.api_football_collector import ApiFootballCollector
from database.db_connection import get_connection


class HistoryIngestionService:
    def __init__(self, league_id=475, season=2026):
        self.collector = ApiFootballCollector()
        self.league_id = league_id
        self.season = season

    def ingest_historical_matches(self):
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Buscar todos jogos finalizados (status FT) por liga/season
            finished_matches = []
            for league in [self.league_id]:
                params = {"league": league, "season": self.season}
                url = f"https://v3.football.api-sports.io/fixtures"
                resp = self.collector.headers and requests.get(
                    url, headers=self.collector.headers, params=params, timeout=30)
                data = resp.json()
                fixtures = data.get("response", [])
                # Filtrar status FT
                for f in fixtures:
                    if f["fixture"]["status"]["short"] == "FT":
                        fixture = f["fixture"]
                        home = f["teams"]["home"]
                        away = f["teams"]["away"]
                        finished_matches.append({
                            "fixture_id": fixture["id"],
                            "homeTeam": {"id": home["id"], "name": home["name"]},
                            "awayTeam": {"id": away["id"], "name": away["name"]},
                            "match_datetime": fixture["date"],
                        })
            print(
                f"[INFO] Jogos finalizados encontrados: {len(finished_matches)}")

            # Ignorar fixtures já existentes
            cursor.execute("SELECT match_id FROM matches")
            existing_ids = set(row[0] for row in cursor.fetchall())
            new_matches = [
                m for m in finished_matches if m["fixture_id"] not in existing_ids]
            print(f"[INFO] Jogos novos ingeridos: {len(new_matches)}")

            for match in new_matches:
                fixture_id = match["fixture_id"]
                home_team = match["homeTeam"]
                away_team = match["awayTeam"]
                match_datetime = match["match_datetime"]

                # Salvar times
                for team in [home_team, away_team]:
                    cursor.execute(
                        "INSERT INTO teams (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                        (team["name"],))

                # Buscar IDs dos times
                cursor.execute(
                    "SELECT id FROM teams WHERE name=%s", (home_team["name"],))
                home_team_id = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT id FROM teams WHERE name=%s", (away_team["name"],))
                away_team_id = cursor.fetchone()[0]

                # Salvar match
                cursor.execute(
                    "INSERT INTO matches (match_id, home_team_id, away_team_id, match_date, status) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (match_id) DO NOTHING",
                    (fixture_id, home_team_id, away_team_id, match_datetime, "FT"))
                cursor.execute(
                    "SELECT id FROM matches WHERE match_id=%s", (fixture_id,))
                match_id = cursor.fetchone()[0]

                # Buscar estatísticas
                stats = self.collector.get_fixture_statistics(fixture_id)
                for team, is_home in [(home_team, True), (away_team, False)]:
                    team_db_id = home_team_id if is_home else away_team_id
                    goals_for = stats.get("home", {}).get(
                        "Goals") if is_home else stats.get("away", {}).get("Goals")
                    goals_against = stats.get("away", {}).get(
                        "Goals") if is_home else stats.get("home", {}).get("Goals")
                    corners = stats.get("home", {}).get(
                        "Corner Kicks", 0) if is_home else stats.get("away", {}).get("Corner Kicks", 0)
                    cards = (
                        stats.get("home", {}).get("Yellow Cards", 0) +
                        stats.get("home", {}).get("Red Cards", 0)
                        if is_home else
                        stats.get("away", {}).get("Yellow Cards", 0) +
                        stats.get("away", {}).get("Red Cards", 0)
                    )
                    cursor.execute(
                        "INSERT INTO match_statistics (match_id, team_id, goals_for, goals_against, corners, cards) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (match_id, team_id) DO NOTHING",
                        (match_id, team_db_id, goals_for, goals_against, corners, cards))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[ERRO] {e}")
            raise e
        finally:
            cursor.close()
            conn.close()
