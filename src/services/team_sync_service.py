import os
import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()  # <- ESSENCIAL

API_KEY = os.getenv("API_FOOTBALL_KEY")

if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida no ambiente")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "football_stats")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "Pereira2310!")

HEADERS = {
    "x-apisports-key": API_KEY
}

LEAGUES = [
    {"league_id": 39, "season": 2025},   # Premier League
    {"league_id": 140, "season": 2025},  # La Liga
    {"league_id": 78, "season": 2025},   # Bundesliga
    {"league_id": 475, "season": 2026},  # Paulistão A1
]

# =========================
# CONEXÃO COM BANCO
# =========================

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

# =========================
# SYNC DE TIMES
# =========================

def sync_teams():
    if not API_KEY:
        raise RuntimeError("API_FOOTBALL_KEY não definida no ambiente")

    conn = get_connection()
    cur = conn.cursor()

    for item in LEAGUES:
        print(f"[INFO] Buscando times da liga {item['league_id']} - temporada {item['season']}")

        url = "https://v3.football.api-sports.io/teams"
        params = {
            "league": item["league_id"],
            "season": item["season"]
        }

        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()
        data = r.json().get("response", [])

        print(f"[INFO] {len(data)} times encontrados")

        for t in data:
            team = t.get("team")
            if not team:
                continue

            cur.execute("""
    INSERT INTO teams (id, name, country, league_id, season)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (id) DO NOTHING
""", (
    team["id"],
    team["name"],
    team["country"],
    item["league_id"],
    item["season"]
))

        conn.commit()
        print(f"[OK] Liga {item['league_id']} sincronizada\n")

    cur.close()
    conn.close()
    print("[FINALIZADO] Times sincronizados com sucesso.")

# =========================
# MAIN
# =========================

if __name__ == "__main__":
    sync_teams()