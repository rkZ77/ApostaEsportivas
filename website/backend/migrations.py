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
        # A liga ainda e' coletada? FALSE = so' historico.
        #
        # Existe porque REMOVER a linha quebra o nome em todo lugar que faz
        # JOIN em `leagues`: a Copa do Mundo 2026 saiu da tabela em 2026-08-11
        # (competicao encerrada, so' volta em 2030) e os picks dela passaram a
        # aparecer como "LIGA 1" nos Resultados da IA. Os 104 jogos continuam em
        # match_statistics sustentando 77% do ledger de calibracao -- o que
        # sumiu foi so' o nome.
        cur.execute("ALTER TABLE leagues ADD COLUMN IF NOT EXISTS ativa BOOLEAN NOT NULL DEFAULT TRUE;")
        # Restaura a Copa do Mundo como historico. ON CONFLICT protege quem
        # nunca deletou, e o nome vem fixo porque a API nao e' consultada aqui.
        cur.execute("""
            INSERT INTO leagues (league_id, name, season, ativa)
            VALUES (1, 'Copa do Mundo', 2026, FALSE)
            ON CONFLICT (league_id) DO NOTHING
        """)

        # Temporada da liga ja comecou? NULL = ninguem marcou ainda.
        #
        # Tres estados de proposito: quem cadastra pode nao saber, e assumir
        # "sim" faria o botao Coletar disparar o backfill de temporada (uma
        # requisicao por jogo) numa liga que pode nao ter jogo nenhum
        # finalizado. NULL cai no comportamento completo, que e' o seguro.
        cur.execute("ALTER TABLE leagues ADD COLUMN IF NOT EXISTS temporada_iniciada BOOLEAN;")
        cur.execute("ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS home_team_id INTEGER;")
        cur.execute("ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS away_team_id INTEGER;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);")
        # client_id do GA, capturado no checkout. Sem ele a receita chega no GA
        # como sessao nova e direta, e a unica pergunta que o GA responde melhor
        # que a tabela payments -- de qual canal veio quem paga -- fica sem
        # resposta. Ver analytics.py.
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ga_client_id VARCHAR(50);")
        # Consentimento pra WhatsApp. Separado do telefone de proposito: o
        # `phone` foi coletado no cadastro pra CONTA, nao pra marketing, e
        # disparar pra base inteira sem opt-in explicito e o caminho mais curto
        # pro numero ser denunciado e banido. Ver website/scripts/whatsapp/.
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_opt_in BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_opt_in_at TIMESTAMP;")
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
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_password_hash VARCHAR(100);")
        # Marca "esta pessoa foi pro MercadoPago". Sem isso nao da pra saber em
        # quem vale a pena gastar consulta a API no login: e' o que permite
        # ativar o VIP de quem pagou por boleto/Pix e so' voltou dias depois,
        # sem varrer a base inteira nem depender do webhook.
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS checkout_started_at TIMESTAMP;")
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
        # Trilha de tentativas de processar pagamento (webhook, retorno do
        # checkout, botao do admin). Nao guarda corpo de requisicao: o webhook
        # e' publico, entao aqui so' entra campo curto e ja' validado.
        #
        # Existe por causa da falha de agosto/2026: o webhook rejeitava a
        # notificacao do MercadoPago por assinatura e nao sobrava rastro
        # nenhum -- o comprador seguia free e a venda nao aparecia no
        # relatorio. Sem essa tabela, a pergunta "o MercadoPago chegou a
        # chamar?" nao tinha como ser respondida.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payment_events (
                id             SERIAL PRIMARY KEY,
                source         VARCHAR(20)  NOT NULL,
                status         VARCHAR(30)  NOT NULL,
                mp_payment_id  VARCHAR(50),
                detail         VARCHAR(300),
                created_at     TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_payment_events_created ON payment_events(created_at DESC);")
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
        cur.execute("ALTER TABLE user_banca ADD COLUMN IF NOT EXISTS last_manual_setup_month VARCHAR(7);")
        # Caminhos de alavancagem. Cada linha e' UM caminho: comeca com
        # initial_amount, os GREENs vao compondo em cima e ele so' vira dinheiro
        # de verdade quando fecha -- na mao (o usuario decide sacar) ou no RED
        # (perde o inicial e nada mais, porque o composto nunca foi sacado).
        # Enquanto ended_at e' NULL o caminho esta' rodando e NAO entra na banca.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alavancagem_series (
                id             SERIAL PRIMARY KEY,
                user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                initial_amount NUMERIC(12,2) NOT NULL,
                started_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                ended_at       TIMESTAMP,
                end_reason     VARCHAR(10),
                final_amount   NUMERIC(12,2),
                realized_pnl   NUMERIC(12,2)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alav_series_user ON alavancagem_series(user_id, started_at);")
        # Um caminho aberto por usuario. E' o que impede duas abas (ou dois
        # cliques) criarem caminhos paralelos e a replay ficar ambigua.
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_alav_series_um_aberto
            ON alavancagem_series(user_id) WHERE ended_at IS NULL
        """)
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS banca_monthly_closes (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                month_key       VARCHAR(7) NOT NULL,
                bankroll_start  NUMERIC(10,2) NOT NULL,
                bankroll_end    NUMERIC(10,2) NOT NULL,
                total_pnl       NUMERIC(10,2) NOT NULL DEFAULT 0,
                greens          INTEGER NOT NULL DEFAULT 0,
                reds            INTEGER NOT NULL DEFAULT 0,
                push            INTEGER NOT NULL DEFAULT 0,
                half_wins       INTEGER NOT NULL DEFAULT 0,
                half_loss       INTEGER NOT NULL DEFAULT 0,
                total_resolved  INTEGER NOT NULL DEFAULT 0,
                total_followed  INTEGER NOT NULL DEFAULT 0,
                unit_value      NUMERIC(10,2),
                closed_at       TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, month_key)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_banca_monthly_closes_user ON banca_monthly_closes(user_id, closed_at DESC);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS banca_withdrawals (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount          NUMERIC(10,2) NOT NULL,
                bankroll_before NUMERIC(10,2) NOT NULL,
                bankroll_after  NUMERIC(10,2) NOT NULL,
                created_at      TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_banca_withdrawals_user ON banca_withdrawals(user_id, created_at DESC);")
        # Central de notificacoes in-app (o sino da navbar). dedupe_key e' o que
        # impede o mesmo evento de virar duas linhas quando o gerador roda de
        # novo -- resultado corrigido por revisao tardia do provedor, poll de
        # /live/my-picks batendo a cada 60s, fechamento mensal recalculado a
        # cada request. Sempre criar via create_notification() em
        # routers/notifications.py, nunca com INSERT solto.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                type        VARCHAR(30)  NOT NULL,
                title       VARCHAR(160) NOT NULL,
                body        TEXT,
                url         VARCHAR(200),
                payload     JSONB,
                dedupe_key  VARCHAR(120) NOT NULL,
                read_at     TIMESTAMP,
                created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, dedupe_key)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id) WHERE read_at IS NULL;")

        # ── Favoritos ────────────────────────────────────────────────────────
        # Uma tabela pra todos os tipos (liga, time, mercado, pick) em vez de
        # quatro: o que muda entre eles é só o significado de ref_id, e a tela
        # sempre lê "os favoritos do usuário" de uma vez. `kind` é texto livre
        # com CHECK pra não virar tabela de dominio pra 4 valores.
        #
        # ref_id é TEXT e não INTEGER de propósito: liga e time são id numérico
        # da API-Football, mas mercado é chave textual ('faltas', 'goleiros').
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_favorites (
                id         SERIAL PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind       VARCHAR(20) NOT NULL CHECK (kind IN ('league','team','market','pick')),
                ref_id     VARCHAR(60) NOT NULL,
                label      VARCHAR(120),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, kind, ref_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_favorites_user ON user_favorites(user_id, kind);")

        # ── Alertas ──────────────────────────────────────────────────────────
        # Preferência do usuário, não fila de disparo: quem dispara é o gerador
        # de notificação já existente, que consulta isto antes de criar a linha
        # em `notifications`.
        #
        # min_confidence e min_ev ficam como NUMERIC nullable: NULL = "não me
        # importo com esse critério", que é diferente de 0.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_alerts (
                id             SERIAL PRIMARY KEY,
                user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind           VARCHAR(30) NOT NULL CHECK (kind IN ('new_value_bet','confidence','favorite_team')),
                enabled        BOOLEAN NOT NULL DEFAULT TRUE,
                min_confidence NUMERIC,
                min_ev         NUMERIC,
                created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, kind)
            )
        """)

        # ── Conquistas ───────────────────────────────────────────────────────
        # Só o registro de "quando desbloqueou". O catálogo (nome, descrição,
        # meta) vive no código, em routers/personal.py: é conteúdo de produto,
        # muda junto com a copy e não precisa de deploy de banco pra ajustar.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code         VARCHAR(40) NOT NULL,
                unlocked_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, code)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_achievements_user ON user_achievements(user_id);")

        # Fila da Home (GET /api/public/next-fixtures): "proximos jogos ainda
        # nao iniciados, em ordem de horario". Sem indice isso e' varredura da
        # tabela inteira a cada visita anonima -- e `fixtures` so' cresce, o
        # coletor nunca apaga o passado, entao a conta piora com o tempo.
        # Parcial no status porque a consulta so' olha jogo por comecar: o
        # indice fica do tamanho da janela util, nao do historico.
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_fixtures_proximos
            ON fixtures (match_datetime)
            WHERE status IN ('NS', 'TBD')
        """)

        # ── Casas de aposta ──────────────────────────────────────────────────
        # Tabela de bookmakers gerenciavel pelo admin. Antes o ID e o nome
        # viviam so' em odds_values (repetidos em cada linha de odd) e nao
        # havia como ativar/desativar uma casa sem mexer no codigo do coletor.
        # Com esta tabela o admin consegue cadastrar, renomear e desativar
        # casas pela tela, sem deploy.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookmakers (
                bookmaker_id   INTEGER PRIMARY KEY,
                bookmaker_name VARCHAR(100) NOT NULL,
                ativo          BOOLEAN NOT NULL DEFAULT TRUE,
                created_at     TIMESTAMP DEFAULT NOW()
            )
        """)
        # Popula com as casas que ja estao sendo coletadas, sem sobrescrever
        # nenhuma que o admin ja tenha editado (ON CONFLICT DO NOTHING).
        cur.execute("""
            INSERT INTO bookmakers (bookmaker_id, bookmaker_name)
            SELECT DISTINCT bookmaker_id, bookmaker_name
            FROM odds_values
            WHERE bookmaker_id IS NOT NULL
            ON CONFLICT (bookmaker_id) DO NOTHING
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
