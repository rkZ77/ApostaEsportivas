-- Tabela de árbitros (identificador único por nome, como teams tem team_id)
CREATE TABLE IF NOT EXISTS referees (
    referee_id  SERIAL PRIMARY KEY,
    name        VARCHAR(255) UNIQUE NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW()
);

-- Tabela de médias do árbitro por temporada
CREATE TABLE IF NOT EXISTS referee_stats (
    referee_id   INTEGER NOT NULL REFERENCES referees(referee_id),
    season       INTEGER NOT NULL,
    games        INTEGER DEFAULT 0,
    avg_yellow   NUMERIC(5,2),
    avg_red      NUMERIC(5,2),
    avg_fouls    NUMERIC(5,2),
    avg_corners  NUMERIC(5,2),
    avg_goals    NUMERIC(5,2),
    max_yellow   INTEGER,
    min_yellow   INTEGER,
    last_updated TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (referee_id, season)
);
