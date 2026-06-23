-- ============================================================
-- SCHEMA DEV — ApostaEsportivas
-- Cole no SQL Editor do Supabase (novo projeto dev)
-- ============================================================

-- ─── USERS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                    SERIAL PRIMARY KEY,
    name                  VARCHAR(255) NOT NULL,
    email                 VARCHAR(255) UNIQUE NOT NULL,
    password_hash         VARCHAR(255) NOT NULL,
    plan                  VARCHAR(20)  NOT NULL DEFAULT 'free',
    active                BOOLEAN      NOT NULL DEFAULT true,
    expires_at            TIMESTAMP,
    subscription_type     VARCHAR(20),
    created_at            TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP    NOT NULL DEFAULT NOW(),
    phone                 VARCHAR(30),
    username              VARCHAR(30)  UNIQUE,
    avatar_url            TEXT,
    trial_used            BOOLEAN DEFAULT FALSE,
    cpf                   VARCHAR(14)  UNIQUE,
    referral_code         VARCHAR(10)  UNIQUE,
    referred_by           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reset_token           VARCHAR(100),
    reset_token_expires_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ─── PAYMENTS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mp_payment_id   VARCHAR(50) UNIQUE NOT NULL,
    plan_key        VARCHAR(20) NOT NULL,
    amount          NUMERIC(10,2) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'approved',
    expires_at      TIMESTAMP NOT NULL,
    payment_method  VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ─── BANCA ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_banca (
    user_id           INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    bankroll_start    NUMERIC(10,2) NOT NULL DEFAULT 100,
    bankroll_goal     NUMERIC(10,2),
    unit_value        NUMERIC(10,2),
    alav_bankroll_init NUMERIC(10,2),
    updated_at        TIMESTAMP DEFAULT NOW()
);

-- ─── FOLLOWED PICKS ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_followed_picks (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pick_id     INTEGER NOT NULL,
    pick_type   VARCHAR(20) NOT NULL,
    stake_units NUMERIC(5,2) NOT NULL DEFAULT 1,
    followed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, pick_id, pick_type)
);

-- ─── SOCIAL ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pick_reactions (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pick_id    INTEGER NOT NULL,
    pick_type  VARCHAR(20) NOT NULL,
    reaction   VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, pick_id, pick_type, reaction)
);

CREATE TABLE IF NOT EXISTS pick_comments (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_name       TEXT NOT NULL,
    user_plan       TEXT NOT NULL DEFAULT 'free',
    user_avatar_url TEXT,
    pick_id         INTEGER NOT NULL,
    pick_type       VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_name       TEXT NOT NULL,
    user_plan       TEXT NOT NULL DEFAULT 'free',
    user_avatar_url TEXT,
    content         TEXT NOT NULL,
    deleted_at      TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ─── FIXTURES ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id     INTEGER PRIMARY KEY,
    league_id      INTEGER,
    season         INTEGER,
    home_team_id   INTEGER,
    away_team_id   INTEGER,
    home_team      TEXT,
    away_team      TEXT,
    match_datetime TIMESTAMP,
    status         VARCHAR(10),
    referee        VARCHAR(255),
    created_at     TIMESTAMP DEFAULT NOW(),
    last_updated   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fixtures_league ON fixtures(league_id);
CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures(match_datetime);

-- ─── LEAGUES ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS leagues (
    league_id  INTEGER PRIMARY KEY,
    name       VARCHAR(255),
    country    VARCHAR(100),
    logo       TEXT,
    flag       TEXT,
    season     INTEGER
);

-- ─── TEAMS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS teams (
    team_id      INTEGER,
    name         VARCHAR(255),
    country      VARCHAR(100),
    league_id    INTEGER,
    season       INTEGER,
    created_at   TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (team_id, league_id, season)
);

-- ─── MATCH STATISTICS ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS match_statistics (
    fixture_id              INTEGER PRIMARY KEY,
    league_id               INTEGER,
    season                  INTEGER,
    home_team_id            INTEGER,
    away_team_id            INTEGER,
    home_goals              INTEGER,
    away_goals              INTEGER,
    total_goals             INTEGER,
    home_corners            INTEGER,
    away_corners            INTEGER,
    total_corners           INTEGER,
    home_yellow_cards       INTEGER,
    away_yellow_cards       INTEGER,
    total_yellow_cards      INTEGER,
    home_red_cards          INTEGER,
    away_red_cards          INTEGER,
    total_red_cards         INTEGER,
    status                  VARCHAR(10),
    match_date              DATE,
    home_shots_on           INTEGER,
    away_shots_on           INTEGER,
    home_shots_off          INTEGER,
    away_shots_off          INTEGER,
    home_total_shots        INTEGER,
    away_total_shots        INTEGER,
    home_blocked_shots      INTEGER,
    away_blocked_shots      INTEGER,
    home_goalkeeper_saves   INTEGER,
    away_goalkeeper_saves   INTEGER,
    home_fouls              INTEGER,
    away_fouls              INTEGER,
    home_offsides           INTEGER,
    away_offsides           INTEGER,
    home_possession         NUMERIC(5,2),
    away_possession         NUMERIC(5,2),
    home_passes             INTEGER,
    away_passes             INTEGER,
    home_passes_accuracy    NUMERIC(5,2),
    away_passes_accuracy    NUMERIC(5,2),
    referee                 VARCHAR(255),
    last_updated            TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_match_stats_league ON match_statistics(league_id, season);
CREATE INDEX IF NOT EXISTS idx_match_stats_teams  ON match_statistics(home_team_id, away_team_id);

-- ─── TEAM STATISTICS (médias por time/liga/temporada/contexto) ─
CREATE TABLE IF NOT EXISTS team_statistics (
    id                        SERIAL PRIMARY KEY,
    team_id                   INTEGER NOT NULL,
    league_id                 INTEGER NOT NULL,
    season                    INTEGER NOT NULL,
    context_type              VARCHAR(10) NOT NULL,  -- HOME | AWAY | ALL
    games_count               INTEGER,
    avg_goals_for             NUMERIC(5,2),
    avg_goals_against         NUMERIC(5,2),
    avg_total_goals           NUMERIC(5,2),
    avg_corners_for           NUMERIC(5,2),
    avg_corners_against       NUMERIC(5,2),
    avg_total_corners         NUMERIC(5,2),
    avg_yellow_for            NUMERIC(5,2),
    avg_yellow_against        NUMERIC(5,2),
    avg_total_yellow          NUMERIC(5,2),
    avg_red_for               NUMERIC(5,2),
    avg_red_against           NUMERIC(5,2),
    avg_total_red             NUMERIC(5,2),
    avg_shots_on_for          NUMERIC(5,2),
    avg_shots_on_against      NUMERIC(5,2),
    avg_shots_off_for         NUMERIC(5,2),
    avg_shots_off_against     NUMERIC(5,2),
    avg_total_shots_for       NUMERIC(5,2),
    avg_total_shots_against   NUMERIC(5,2),
    avg_blocked_for           NUMERIC(5,2),
    avg_blocked_against       NUMERIC(5,2),
    avg_saves_for             NUMERIC(5,2),
    avg_saves_against         NUMERIC(5,2),
    avg_fouls_for             NUMERIC(5,2),
    avg_fouls_against         NUMERIC(5,2),
    avg_offsides_for          NUMERIC(5,2),
    avg_offsides_against      NUMERIC(5,2),
    avg_possession_for        NUMERIC(5,2),
    avg_possession_against    NUMERIC(5,2),
    avg_passes_for            NUMERIC(5,2),
    avg_passes_against        NUMERIC(5,2),
    avg_passes_accuracy_for   NUMERIC(5,2),
    avg_passes_accuracy_against NUMERIC(5,2),
    last_updated              TIMESTAMP DEFAULT NOW(),
    UNIQUE (team_id, league_id, season, context_type)
);

-- ─── ODDS ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS odds_bookmakers (
    id             SERIAL PRIMARY KEY,
    fixture_id     INTEGER NOT NULL,
    bookmaker_id   INTEGER NOT NULL,
    bookmaker_name VARCHAR(100),
    last_update    TIMESTAMP,
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW(),
    UNIQUE (fixture_id, bookmaker_id)
);

CREATE TABLE IF NOT EXISTS odds_markets (
    id               SERIAL PRIMARY KEY,
    bookmaker_row_id INTEGER NOT NULL REFERENCES odds_bookmakers(id) ON DELETE CASCADE,
    bet_id           INTEGER NOT NULL,
    bet_name         VARCHAR(200),
    fixture_id       INTEGER,
    market_pt        TEXT,
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW(),
    UNIQUE (bookmaker_row_id, bet_id)
);

CREATE TABLE IF NOT EXISTS odds_values (
    id              SERIAL PRIMARY KEY,
    market_row_id   INTEGER NOT NULL REFERENCES odds_markets(id) ON DELETE CASCADE,
    value_name      TEXT,
    odd_value       NUMERIC(8,3),
    fixture_id      INTEGER,
    league_id       INTEGER,
    season          INTEGER,
    match_datetime  TIMESTAMP,
    home_team_id    INTEGER,
    home_team       TEXT,
    away_team_id    INTEGER,
    away_team       TEXT,
    bookmaker_id    INTEGER,
    bookmaker_name  TEXT,
    market_id       INTEGER,
    market_name     TEXT,
    market_type     TEXT,
    side_team       TEXT,
    team_id         INTEGER,
    team_name       TEXT,
    line_value      NUMERIC(8,3),
    market_pt       TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_odds_values_fixture ON odds_values(fixture_id);
CREATE INDEX IF NOT EXISTS idx_odds_values_odd     ON odds_values(odd_value);

-- ─── REFEREES ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS referees (
    referee_id   SERIAL PRIMARY KEY,
    name         VARCHAR(255) UNIQUE NOT NULL,
    created_at   TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW()
);

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

-- ─── LEAGUE ANALYSIS ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS league_analysis (
    id            SERIAL PRIMARY KEY,
    league_id     INTEGER NOT NULL,
    league_name   TEXT,
    season        INTEGER NOT NULL,
    analysis_text TEXT,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE (league_id, season)
);

-- ─── PICKS VIP ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS picks_vip (
    id              SERIAL PRIMARY KEY,
    fixture_id      INTEGER UNIQUE,
    match_date      DATE,
    home_team_id    INTEGER,
    away_team_id    INTEGER,
    home_team_name  TEXT,
    away_team_name  TEXT,
    market          TEXT,
    line            TEXT,
    odd             NUMERIC(8,3),
    bet_house       TEXT,
    market_type     TEXT,
    market_id       INTEGER,
    confidence      NUMERIC(5,4),
    stake           NUMERIC(5,2),
    stake_pct       NUMERIC(5,4),
    ev              NUMERIC(8,4),
    reasoning       TEXT,
    result          TEXT,
    profit          NUMERIC(8,4),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ─── PICKS FREE (dica do dia) ────────────────────────────────
CREATE TABLE IF NOT EXISTS picks_free (
    id           SERIAL PRIMARY KEY,
    fixture_id   INTEGER,
    match_date   DATE UNIQUE,
    home_team    TEXT,
    away_team    TEXT,
    home_team_id INTEGER,
    away_team_id INTEGER,
    league_id    INTEGER,
    league_name  TEXT,
    market       TEXT,
    line         TEXT,
    odd          NUMERIC(8,3),
    bet_house    TEXT,
    confidence   NUMERIC(5,4),
    reasoning    TEXT,
    result       TEXT,
    profit       NUMERIC(8,4),
    created_at   TIMESTAMP DEFAULT NOW()
);

-- ─── PICKS ALAVANCAGEM ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS picks_alavancagem (
    id              SERIAL PRIMARY KEY,
    match_date      DATE UNIQUE,
    tipo            TEXT NOT NULL DEFAULT 'simples',
    fixture_id_1    INTEGER,
    home_team_1     TEXT,
    away_team_1     TEXT,
    market_1        TEXT,
    market_type_1   TEXT,
    line_1          TEXT,
    odd_1           NUMERIC,
    bet_house_1     TEXT,
    fixture_id_2    INTEGER,
    home_team_2     TEXT,
    away_team_2     TEXT,
    market_2        TEXT,
    market_type_2   TEXT,
    line_2          TEXT,
    odd_2           NUMERIC,
    bet_house_2     TEXT,
    odd_combined    NUMERIC,
    stake           NUMERIC,
    confidence      NUMERIC,
    reasoning       TEXT,
    result          TEXT,
    profit          NUMERIC,
    bankroll_after  NUMERIC,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ─── PICKS MÚLTIPLAS ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS picks_multiplas (
    id            SERIAL PRIMARY KEY,
    multipla_name TEXT,
    games         JSONB,
    total_odd     NUMERIC,
    stake         NUMERIC,
    stake_pct     NUMERIC,
    score_combo   NUMERIC,
    match_date    DATE,
    result        TEXT,
    profit        NUMERIC,
    reasoning     TEXT,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- ─── LEAGUE STANDINGS ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS league_standings (
    id                 SERIAL PRIMARY KEY,
    league_id          INTEGER,
    league_name        TEXT,
    country            TEXT,
    season             INTEGER,
    group_name         TEXT,
    team_id            INTEGER,
    team_name          TEXT,
    team_logo          TEXT,
    rank               INTEGER,
    points             INTEGER,
    goals_diff         INTEGER,
    form               TEXT,
    status             TEXT,
    description        TEXT,
    played             INTEGER,
    win                INTEGER,
    draw               INTEGER,
    lose               INTEGER,
    goals_for          INTEGER,
    goals_against      INTEGER,
    home_played        INTEGER,
    home_win           INTEGER,
    home_draw          INTEGER,
    home_lose          INTEGER,
    home_goals_for     INTEGER,
    home_goals_against INTEGER,
    away_played        INTEGER,
    away_win           INTEGER,
    away_draw          INTEGER,
    away_lose          INTEGER,
    away_goals_for     INTEGER,
    away_goals_against INTEGER,
    api_last_update    TIMESTAMP,
    created_at         TIMESTAMP DEFAULT NOW(),
    updated_at         TIMESTAMP DEFAULT NOW()
);

-- ─── USUÁRIO ADMIN PADRÃO (ajuste a senha depois) ────────────
-- Descomente e ajuste se quiser criar um admin de teste:
-- INSERT INTO users (name, email, password_hash, plan)
-- VALUES ('Admin Dev', 'admin@dev.local', '<bcrypt_hash>', 'admin');
