import sqlite3

DB_PATH = "data/football_stats.db"

def create_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sofascore_id INTEGER UNIQUE,
        name TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sofascore_event_id INTEGER UNIQUE,
        home_team_id INTEGER,
        away_team_id INTEGER,
        match_date INTEGER,
        status TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS match_statistics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        team_id INTEGER,
        goals_for INTEGER,
        goals_against INTEGER,
        corners INTEGER,
        cards INTEGER
    );
    """)

    conn.commit()
    conn.close()
    print("Banco SQLite criado com sucesso.")

if __name__ == "__main__":
    create_database()
