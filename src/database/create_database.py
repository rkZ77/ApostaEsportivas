import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DB_NAME = "football_stats"
USER = "postgres"
PASSWORD = "Pereira2310!"
HOST = "localhost"
PORT = 5432


def create_database():
    conn = psycopg2.connect(dbname="postgres", user=USER,
                            password=PASSWORD, host=HOST, port=PORT)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if not cursor.fetchone():
        cursor.execute(f"CREATE DATABASE {DB_NAME}")
    cursor.close()
    conn.close()


def create_tables():
    conn = psycopg2.connect(dbname=DB_NAME, user=USER,
                            password=PASSWORD, host=HOST, port=PORT)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS teams (
        id SERIAL PRIMARY KEY,
        sofascore_id INTEGER UNIQUE,
        name TEXT
    );
    CREATE TABLE IF NOT EXISTS matches (
        id SERIAL PRIMARY KEY,
        sofascore_event_id INTEGER UNIQUE,
        home_team_id INTEGER REFERENCES teams(id),
        away_team_id INTEGER REFERENCES teams(id),
        match_date TIMESTAMP,
        match_datetime TIMESTAMP NOT NULL,
        status TEXT
    );
    CREATE TABLE IF NOT EXISTS match_statistics (
        id SERIAL PRIMARY KEY,
        match_id INTEGER REFERENCES matches(id),
        team_id INTEGER REFERENCES teams(id),
        goals_for INTEGER,
        goals_against INTEGER,
        corners INTEGER,
        cards INTEGER,
        UNIQUE (match_id, team_id)
    );
    CREATE TABLE IF NOT EXISTS bet_recommendations (
        id SERIAL PRIMARY KEY,
        match_id INTEGER REFERENCES matches(id),
        market TEXT NOT NULL,
        team_side TEXT NOT NULL,
        line FLOAT NOT NULL,
        odd FLOAT,
        probability FLOAT,
        expected_value FLOAT,
        recommendation TEXT,
        result TEXT,
        evaluated_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL,
        UNIQUE (match_id, market, team_side, line)
    );
    ''')
    conn.commit()
    cursor.close()
    conn.close()


if __name__ == "__main__":
    create_database()
    create_tables()
