import logging


def run_startup_migrations(logger: logging.Logger) -> bool:
    """Run legacy startup migrations.

    These statements are kept here to preserve the existing deployment behavior.
    The next step should be moving them into versioned SQL/Alembic migrations.
    """
    from database import get_connection

    try:
        conn = get_connection()
    except Exception as e:
        logger.error("[MIGRATION] DB indisponivel no startup: %s - pulando migration", e)
        return False

    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS home_team_id INTEGER;")
        cur.execute("ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS away_team_id INTEGER;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(30) UNIQUE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cpf VARCHAR(14) UNIQUE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(10) UNIQUE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token VARCHAR(100);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(100);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_ip VARCHAR(45);")
        cur.execute("ALTER TABLE picks_alavancagem DROP COLUMN IF EXISTS bankroll_after;")
        cur.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;")
        cur.execute("ALTER TABLE user_followed_picks ADD COLUMN IF NOT EXISTS actual_odd DECIMAL(6,2);")
        cur.execute("ALTER TABLE user_followed_picks ADD COLUMN IF NOT EXISTS bet_house VARCHAR(100);")
        cur.execute("ALTER TABLE user_followed_picks ADD COLUMN IF NOT EXISTS cashout_amount NUMERIC(10,2);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_token VARCHAR(64);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_device VARCHAR(60);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP;")
        cur.execute("ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS home_goals_ht INTEGER;")
        cur.execute("ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS away_goals_ht INTEGER;")
        cur.execute("UPDATE users SET reset_token=NULL, reset_token_expires_at=NULL WHERE reset_token IS NOT NULL AND LENGTH(reset_token) < 64")
        cur.execute("UPDATE users SET email_verification_token=NULL WHERE email_verification_token IS NOT NULL AND LENGTH(email_verification_token) < 64")
        cur.execute("UPDATE users SET phone = '+55' || regexp_replace(phone, '[^0-9]', '', 'g') WHERE phone IS NOT NULL AND phone NOT LIKE '+%' AND length(regexp_replace(phone, '[^0-9]', '', 'g')) BETWEEN 10 AND 11")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id                SERIAL PRIMARY KEY,
                user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                mp_payment_id     VARCHAR(50) UNIQUE NOT NULL,
                plan_key          VARCHAR(20) NOT NULL,
                amount            NUMERIC(10,2) NOT NULL,
                status            VARCHAR(20) NOT NULL DEFAULT 'approved',
                expires_at        TIMESTAMP NOT NULL,
                payment_method    VARCHAR(50),
                created_at        TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_banca (
                user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                bankroll_start NUMERIC(10,2) NOT NULL DEFAULT 100,
                bankroll_goal  NUMERIC(10,2),
                updated_at     TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("ALTER TABLE user_banca ADD COLUMN IF NOT EXISTS bankroll_goal NUMERIC(10,2);")
        cur.execute("ALTER TABLE user_banca ADD COLUMN IF NOT EXISTS unit_value NUMERIC(10,2);")
        cur.execute("ALTER TABLE user_banca ADD COLUMN IF NOT EXISTS alav_bankroll_init NUMERIC(10,2);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_followed_picks (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pick_id     INTEGER NOT NULL,
                pick_type   VARCHAR(20) NOT NULL,
                stake_units NUMERIC(5,2) NOT NULL DEFAULT 1,
                followed_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (user_id, pick_id, pick_type)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pick_reactions (
                id         SERIAL PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pick_id    INTEGER NOT NULL,
                pick_type  VARCHAR(20) NOT NULL,
                reaction   VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (user_id, pick_id, pick_type, reaction)
            )
        """)
        cur.execute("""
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
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                user_name       TEXT NOT NULL,
                user_plan       TEXT NOT NULL DEFAULT 'free',
                user_avatar_url TEXT,
                content         TEXT NOT NULL,
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            UPDATE picks_free pf
            SET home_team_id = f.home_team_id,
                away_team_id = f.away_team_id
            FROM fixtures f
            WHERE f.fixture_id = pf.fixture_id
              AND pf.home_team_id IS NULL
              AND f.home_team_id IS NOT NULL;
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_push_subscriptions (
                id         SERIAL PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                endpoint   TEXT NOT NULL,
                p256dh     TEXT NOT NULL,
                auth       TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (user_id, endpoint)
            )
        """)
        cur.execute("ALTER TABLE picks_vip ADD COLUMN IF NOT EXISTS probability NUMERIC(5,4);")
        cur.execute("ALTER TABLE picks_vip ADD COLUMN IF NOT EXISTS stake_pct NUMERIC(5,4);")
        cur.execute("ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS market_type VARCHAR(20);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_vip_date ON picks_vip(match_date DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_free_date ON picks_free(match_date DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_alav_date ON picks_alavancagem(match_date DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_multi_date ON picks_multiplas(match_date DESC);")
        cur.execute("ALTER TABLE user_followed_picks ADD COLUMN IF NOT EXISTS result VARCHAR(20);")
        cur.execute("""
            UPDATE user_followed_picks uf SET result = pv.result
            FROM picks_vip pv
            WHERE uf.pick_type = 'vip' AND uf.pick_id = pv.id
              AND pv.result IS NOT NULL AND uf.result IS NULL
        """)
        cur.execute("""
            UPDATE user_followed_picks uf SET result = pf.result
            FROM picks_free pf
            WHERE uf.pick_type = 'free' AND uf.pick_id = pf.id
              AND pf.result IS NOT NULL AND uf.result IS NULL
        """)
        cur.execute("""
            UPDATE user_followed_picks uf SET result = pm.result
            FROM picks_multiplas pm
            WHERE uf.pick_type = 'multipla' AND uf.pick_id = pm.id
              AND pm.result IS NOT NULL AND uf.result IS NULL
        """)
        cur.execute("""
            UPDATE user_followed_picks uf SET result = pa.result
            FROM picks_alavancagem pa
            WHERE uf.pick_type = 'alavancagem' AND uf.pick_id = pa.id
              AND pa.result IS NOT NULL AND uf.result IS NULL
        """)
        conn.commit()
        return True
    except Exception as e:
        logger.error("[MIGRATION] Erro: %s", e)
        conn.rollback()
        return True
    finally:
        cur.close()
        conn.close()
