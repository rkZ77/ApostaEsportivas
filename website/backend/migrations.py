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
        # Onboarding interativo. 'pending' e' o unico estado que faz o tour
        # abrir sozinho; 'completed' e 'skipped' sao iguais pra essa decisao --
        # a diferenca so' existe pra saber depois quantos chegaram ao fim.
        #
        # O bloco DO existe por causa do backfill, e nao por gosto: a coluna
        # nasce com DEFAULT 'pending', entao a base inteira (contas antigas,
        # que ja' sabem usar o site) acordaria com o tour na cara no proximo
        # login. O UPDATE tem que rodar UMA vez, junto do ALTER, e nunca mais.
        # Solto ao lado de um ADD COLUMN IF NOT EXISTS ele reapagaria o estado
        # de quem ja' esta' no meio do tour toda vez que o servidor subisse.
        #
        # `'users'::regclass` em vez de information_schema: resolve pelo mesmo
        # search_path que as linhas acima usam, sem chance de achar um `users`
        # de outro schema.
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_attribute
                     WHERE attrelid = 'users'::regclass
                       AND attname  = 'tutorial_status'
                       AND NOT attisdropped
                ) THEN
                    ALTER TABLE users ADD COLUMN tutorial_status VARCHAR(12) NOT NULL DEFAULT 'pending';
                    UPDATE users SET tutorial_status = 'completed';
                END IF;
            END $$;
        """)
        # Passo em que a pessoa parou. E' o que faz recarregar a pagina (ou
        # abrir no celular depois de comecar no desktop) continuar de onde
        # parou em vez de voltar pro "Bem-vindo".
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tutorial_step SMALLINT NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tutorial_finished_at TIMESTAMP;")
        # Segundo roteiro: o tour de boas-vindas ao VIP, que mostra o que a
        # assinatura abriu. Mesmo desenho do de cima -- estado, passo e carimbo.
        #
        # O BACKFILL AQUI E' DIFERENTE, e a diferenca importa. La em cima todo
        # mundo virou 'completed', porque ninguem devia receber o tour de
        # boas-vindas retroativamente. Aqui so' quem JA' TEM VIP e' marcado como
        # visto: free e trial ficam 'pending' de proposito, e e' isso que faz o
        # tour aparecer no dia em que eles assinarem. Marcar a base inteira como
        # 'completed' entregaria a assinatura sem nenhuma tela explicando o que
        # mudou, que e' exatamente o buraco que este tour veio tapar.
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_attribute
                     WHERE attrelid = 'users'::regclass
                       AND attname  = 'vip_tour_status'
                       AND NOT attisdropped
                ) THEN
                    ALTER TABLE users ADD COLUMN vip_tour_status VARCHAR(12) NOT NULL DEFAULT 'pending';
                    UPDATE users SET vip_tour_status = 'completed' WHERE plan IN ('vip', 'admin');
                END IF;
            END $$;
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_tour_step SMALLINT NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_tour_finished_at TIMESTAMP;")
        cur.execute("ALTER TABLE picks_alavancagem DROP COLUMN IF EXISTS bankroll_after;")

        # O ID DO TIME NA TABELA DO PICK, igual `picks_free` e `picks_vip`
        # (2026-08-28).
        #
        # A alavancagem era a unica que guardava so' o NOME dos times, e o
        # escudo era descoberto na hora da leitura: JOIN com `fixtures` pelo
        # fixture_id, e um plano B que casava `fixtures.away_team` pelo nome
        # solto, sem data, com LIMIT 1.
        #
        # As duas pontas falhavam. `fixtures` guarda so' a janela corrente,
        # entao o jogo some da tabela depois de liquidado e o pick de ontem
        # perdia o id · era por isso que o escudo sumia justamente quando saia
        # o GREEN. E o plano B por nome trazia o time ERRADO: "Athletic Club"
        # e' o mineiro (13975) e tambem o Bilbao (531), e La Liga esta entre as
        # ligas acompanhadas, entao os dois moram no banco. Um pick de Serie B
        # apareceu com o brasao do Bilbao no card e na imagem de story.
        #
        # Guardado na linha do pick, o escudo passa a ser um FATO GRAVADO no
        # momento em que o pick nasceu, e nao uma reconsulta que depende do que
        # sobrou em `fixtures` · mesma decisao que a amostra do motor.
        for _n in (1, 2, 3):
            cur.execute(f"ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS home_team_id_{_n} INTEGER;")
            cur.execute(f"ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS away_team_id_{_n} INTEGER;")

        # Backfill 1 · pelo fixture_id, que so' as pernas 1 e 2 guardam e so'
        # enquanto o jogo esta na janela. E' a fonte exata; as outras duas sao
        # reconstrucao.
        for _n in (1, 2):
            cur.execute(f"""
                UPDATE picks_alavancagem pa
                SET home_team_id_{_n} = f.home_team_id,
                    away_team_id_{_n} = f.away_team_id
                FROM fixtures f
                WHERE f.fixture_id = pa.fixture_id_{_n}
                  AND pa.home_team_id_{_n} IS NULL
                  AND f.home_team_id IS NOT NULL;
            """)

        # Backfill 2 · pelo PAR de nomes mais a data. Identifica a PARTIDA e
        # nao um time: dois clubes homonimos nao enfrentam o mesmo adversario
        # no mesmo dia. E' o unico caminho da perna 3, que nao tem fixture_id.
        for _n in (1, 2, 3):
            cur.execute(f"""
                UPDATE picks_alavancagem pa
                SET home_team_id_{_n} = f.home_team_id,
                    away_team_id_{_n} = f.away_team_id
                FROM fixtures f
                WHERE f.home_team = pa.home_team_{_n}
                  AND f.away_team = pa.away_team_{_n}
                  AND f.match_datetime::date = pa.match_date
                  AND pa.home_team_id_{_n} IS NULL
                  AND f.home_team_id IS NOT NULL;
            """)

        # Backfill 3 · `teams`, que nao e' podada por data, DESEMPATADA PELO
        # ADVERSARIO: os dois times de uma partida disputam a mesma
        # competicao, entao o time procurado tem que aparecer em alguma liga
        # onde o adversario tambem aparece. "Nautico Recife" e' unico e esta na
        # liga 72; so' um dos dois "Athletic Club" esta la.
        #
        # O HAVING recusa o que continua ambiguo depois do desempate: NULL
        # desenha o card sem escudo, e sem escudo e' melhor que com o escudo
        # errado.
        for _n in (1, 2, 3):
            for _lado, _outro in (("home", "away"), ("away", "home")):
                cur.execute(f"""
                    UPDATE picks_alavancagem pa
                    SET {_lado}_team_id_{_n} = (
                        SELECT MIN(t.team_id) FROM teams t
                        WHERE t.name = pa.{_lado}_team_{_n}
                          AND t.league_id IN (SELECT adv.league_id FROM teams adv
                                               WHERE adv.name = pa.{_outro}_team_{_n})
                        HAVING COUNT(DISTINCT t.team_id) = 1
                    )
                    WHERE pa.{_lado}_team_id_{_n} IS NULL
                      AND pa.{_lado}_team_{_n} IS NOT NULL;
                """)
        cur.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;")
        cur.execute("ALTER TABLE user_followed_picks ADD COLUMN IF NOT EXISTS actual_odd DECIMAL(6,2);")
        cur.execute("ALTER TABLE user_followed_picks ADD COLUMN IF NOT EXISTS bet_house VARCHAR(100);")
        cur.execute("ALTER TABLE user_followed_picks ADD COLUMN IF NOT EXISTS cashout_amount NUMERIC(10,2);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_token VARCHAR(64);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_device VARCHAR(60);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP;")
        cur.execute("ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS home_goals_ht INTEGER;")
        cur.execute("ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS away_goals_ht INTEGER;")
        # PROCEDENCIA do numero digitado a mao no /admin (aba Dados).
        #
        # Numero preenchido a mao fica indistinguivel do coletado assim que
        # entra na coluna, e o motor le as duas do mesmo jeito. Como a regra da
        # casa e que zero fabricado vira pick errado (invariante 1 de
        # services/settlement.py), a linha precisa dizer QUAL valor veio de
        # gente: {"escanteios": {"casa": 5, "fora": 3, "por": "...", "em": "..."}}.
        cur.execute("ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS manual_stats JSONB;")
        # JOGOS APITADOS, ao lado dos que sustentam a media do arbitro.
        #
        # Quem cria a coluna de verdade e o coletor (_ensure_columns), porque e
        # ele que escreve nela. Aqui ela e repetida pra a ABA nao depender de
        # alguem ter rodado uma coleta antes: sem a coluna, a lista de arbitros
        # do /admin some inteira, com um erro que nao explica que so falta
        # rodar o motor uma vez.
        cur.execute("ALTER TABLE referee_stats ADD COLUMN IF NOT EXISTS games_total INTEGER;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_password_hash VARCHAR(100);")
        # Marca "esta pessoa foi pro MercadoPago". Sem isso nao da pra saber em
        # quem vale a pena gastar consulta a API no login: e' o que permite
        # ativar o VIP de quem pagou por boleto/Pix e so' voltou dias depois,
        # sem varrer a base inteira nem depender do webhook.
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS checkout_started_at TIMESTAMP;")
        cur.execute("UPDATE users SET reset_token=NULL, reset_token_expires_at=NULL WHERE reset_token IS NOT NULL AND LENGTH(reset_token) < 64")
        cur.execute("UPDATE users SET email_verification_token=NULL WHERE email_verification_token IS NOT NULL AND LENGTH(email_verification_token) < 64")
        cur.execute("UPDATE users SET phone = '+55' || regexp_replace(phone, '[^0-9]', '', 'g') WHERE phone IS NOT NULL AND phone NOT LIKE '+%' AND length(regexp_replace(phone, '[^0-9]', '', 'g')) BETWEEN 10 AND 11")
        # Telefone provado (hoje so' pelo codigo do WhatsApp, quando a WABA
        # sair). Junto com email_verified e' o que paga o trial desde que o
        # CPF saiu do cadastro -- ver _ativar_trial_se_elegivel em auth.py.
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN DEFAULT FALSE;")
        # Numero unico = 1 conta por chip, que e' o que substituiu o "1 conta
        # por CPF". Vem DEPOIS da normalizacao E.164 acima, senao o mesmo
        # numero em dois formatos passaria batido pelo indice.
        #
        # A criacao e' condicional porque `phone` nunca foi unico: se a base
        # ja tiver duplicata, um CREATE UNIQUE INDEX cru estoura e o except
        # geral la embaixo faz rollback de TODAS as migrations deste arquivo.
        # O cadastro ja checa duplicata em query separada, entao sem o indice
        # o que se perde e' so' a protecao contra corrida.
        cur.execute("""
            SELECT COUNT(*) AS n FROM (
                SELECT phone FROM users
                WHERE phone IS NOT NULL
                GROUP BY phone HAVING COUNT(*) > 1
            ) d
        """)
        dup = cur.fetchone()
        dup_n = (dup["n"] if isinstance(dup, dict) or hasattr(dup, "keys") else dup[0]) or 0
        if dup_n:
            logger.warning(
                "[MIGRATION] %s telefone(s) repetido(s) em users - indice unico de phone NAO criado. "
                "Resolver os duplicados e rodar o setup de novo.", dup_n
            )
        else:
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS users_phone_uniq
                ON users (phone) WHERE phone IS NOT NULL
            """)
        # Codigos de verificacao de telefone (OTP por SMS).
        #
        # Guarda o HASH do codigo, nunca o codigo: quem ler a tabela nao pode
        # verificar telefone dos outros. `attempts` existe porque 6 digitos sao
        # 1 milhao de combinacoes -- sem teto de tentativa, forca bruta acha em
        # minutos. `phone` fica gravado junto porque o codigo vale pro numero
        # que estava la na hora do pedido: trocar o telefone e usar o codigo
        # antigo verificaria o numero errado.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS phone_verification_codes (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                phone       VARCHAR(30) NOT NULL,
                code_hash   VARCHAR(64) NOT NULL,
                expires_at  TIMESTAMP NOT NULL,
                attempts    INTEGER NOT NULL DEFAULT 0,
                consumed_at TIMESTAMP,
                created_at  TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_phone_codes_user
            ON phone_verification_codes (user_id, created_at DESC)
        """)
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
        # Resultado do caminho em UNIDADES, do lado do resultado em reais.
        # O caminho arrisca 1u e paga (multiplicador - 1)u ao bater a meta; RED
        # custa exatamente -1u. E' assim que ele entra em Meus Picks e na banca,
        # na mesma unidade do resto do site -- reais dependem do valor de
        # unidade de cada usuario e nao servem pro placar comum.
        cur.execute("ALTER TABLE alavancagem_series ADD COLUMN IF NOT EXISTS realized_units NUMERIC(10,4);")
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
        # Estado do acompanhamento continuo do Motor Ao Vivo.
        #
        # POR QUE PRECISA DE TABELA. O estado vivia so' na memoria do processo.
        # Toda morte DENTRO do processo grava um motivo (disjuntor de falhas,
        # cancelamento, desligar no painel), mas o processo morrer inteiro nao
        # grava nada: o modulo recarrega zerado e o painel volta dizendo
        # "desligado, 0 rodadas, sem motivo". O Railway recicla container por
        # conta propria, entao o operador ligava e via cair "sozinho", sem
        # bilhete. Uma linha no banco e' o que sobrevive ao restart.
        #
        # `boot_id` e' quem responde a pergunta: se o dono da linha nao e' este
        # processo, o laco morreu com o anterior. Sem ele nao da' pra separar
        # "reiniciou" de "alguem desligou".
        cur.execute("""
            CREATE TABLE IF NOT EXISTS live_watch_state (
                id             SMALLINT PRIMARY KEY DEFAULT 1,
                ativo          BOOLEAN   NOT NULL DEFAULT FALSE,
                boot_id        VARCHAR(40),
                iniciado_em    TIMESTAMP,
                ultimo_sinal   TIMESTAMP,
                rodadas        INTEGER   NOT NULL DEFAULT 0,
                intervalo_min  INTEGER,
                dry_run        BOOLEAN,
                max_partidas   INTEGER,
                motivo_parada  TEXT,
                CONSTRAINT live_watch_state_uma_linha CHECK (id = 1)
            );
        """)

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

        # ── Arquitetura de motores · Engine Audit (2026-08-27) ───────────────
        #
        # POR QUE ESTAS TABELAS ESTAO AQUI E NAO SO' NO MOTOR
        #
        # Elas sao criadas pelo motor (main.py::run_migrations e
        # services/engine_audit/audit.py) -- mas o SITE as LE, e o motor roda
        # na mao. A aba Auditoria dos Motores nao pode depender de alguem ter
        # rodado um pipeline pra existir: sem isto, um deploy num banco novo
        # abre a aba em erro em vez de abrir vazia.
        #
        # E' a mesma assimetria que ja' mordeu em `engine_decisions`: o painel
        # precisou de um `_sem_tabela()` pra nao devolver 500 num ambiente que
        # nunca rodou pipeline. Criar aqui e' resolver a causa, e o
        # `_sem_tabela` continua como rede.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS engine_runs (
                run_id          TEXT PRIMARY KEY,
                engine          TEXT NOT NULL,
                method          TEXT NOT NULL,
                engine_version  TEXT NOT NULL,
                match_date      DATE NOT NULL,
                started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
                finished_at     TIMESTAMP,
                status          TEXT NOT NULL,
                analisados      INTEGER NOT NULL DEFAULT 0,
                selecionados    INTEGER NOT NULL DEFAULT 0,
                descartados     INTEGER NOT NULL DEFAULT 0,
                erros           INTEGER NOT NULL DEFAULT 0,
                resumo          JSONB
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_runs_recentes ON engine_runs (started_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_runs_motor ON engine_runs (engine, method, match_date DESC);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS engine_errors (
                id          BIGSERIAL PRIMARY KEY,
                run_id      TEXT,
                engine      TEXT,
                method      TEXT,
                fixture_id  INTEGER,
                contexto    TEXT,
                erro        TEXT NOT NULL,
                traceback   TEXT,
                created_at  TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_errors_run ON engine_errors (run_id, created_at DESC);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS engine_decisions (
                id          BIGSERIAL PRIMARY KEY,
                match_date  DATE NOT NULL,
                pipeline    TEXT NOT NULL,
                fixture_id  INTEGER,
                home_team   TEXT,
                away_team   TEXT,
                status      TEXT NOT NULL,
                reason      TEXT,
                candidates  JSONB NOT NULL DEFAULT '[]'::jsonb,
                matchup     JSONB,
                context     JSONB,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        # As colunas que promovem engine_decisions de "log de decisao" a camada
        # de analise da auditoria. Uma por ALTER, mesma razao do resto deste
        # arquivo: um IF NOT EXISTS que falhe nao pode arrastar os seguintes.
        for _coluna, _tipo in (
            ("run_id", "TEXT"), ("engine", "TEXT"), ("method", "TEXT"),
            ("engine_version", "TEXT"), ("score", "NUMERIC"),
            ("probability", "NUMERIC"), ("odd", "NUMERIC"),
            ("pick_table", "TEXT"), ("pick_id", "BIGINT"),
        ):
            cur.execute(f"ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS {_coluna} {_tipo}")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_engine_decisions_run ON engine_decisions (run_id);")

        # ── Picks dos motores novos ─────────────────────────────────────────
        # Mesma DDL de main.py::run_migrations, pelo mesmo motivo das tabelas
        # de auditoria acima: o site le, e o site nao pode esperar o motor.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS picks_boost (
                id            SERIAL PRIMARY KEY,
                fixture_id    INTEGER,
                match_date    DATE,
                home_team     TEXT,
                away_team     TEXT,
                home_team_id  INTEGER,
                away_team_id  INTEGER,
                league_id     INTEGER,
                league_name   TEXT,
                market        TEXT,
                market_type   VARCHAR(40) DEFAULT 'boost_over15_under25ht',
                line          TEXT,
                odd           NUMERIC,
                odd_ft        NUMERIC,
                odd_ht        NUMERIC,
                bet_house_ft  TEXT,
                bet_house_ht  TEXT,
                market_id_ft  INTEGER,
                market_id_ht  INTEGER,
                score         NUMERIC,
                confidence    NUMERIC,
                prob_real     NUMERIC,
                prob_ft       NUMERIC,
                prob_ht       NUMERIC,
                fair_odd      NUMERIC,
                ev            NUMERIC,
                edge          NUMERIC,
                reasoning     TEXT,
                stake_pct     NUMERIC,
                stake_units   INTEGER,
                engine_debug  JSONB,
                result_ft     TEXT,
                result_ht     TEXT,
                result        TEXT,
                profit        NUMERIC,
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_boost_dia_jogo ON picks_boost (match_date, fixture_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_boost_pendentes ON picks_boost (match_date) WHERE result IS NULL;")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS picks_player_stats (
                id            SERIAL PRIMARY KEY,
                fixture_id    INTEGER,
                match_date    DATE,
                home_team     TEXT,
                away_team     TEXT,
                home_team_id  INTEGER,
                away_team_id  INTEGER,
                league_id     INTEGER,
                league_name   TEXT,
                player_id     BIGINT,
                player_name   TEXT,
                team_id       INTEGER,
                team_name     TEXT,
                position      TEXT,
                method        VARCHAR(40),
                stat_column   VARCHAR(40),
                market        TEXT,
                market_type   VARCHAR(40),
                line          TEXT,
                line_value    NUMERIC,
                odd           NUMERIC,
                bet_house     TEXT,
                market_id     INTEGER,
                score         NUMERIC,
                confidence    NUMERIC,
                prob_real     NUMERIC,
                fair_odd      NUMERIC,
                edge          NUMERIC,
                ev            NUMERIC,
                reasoning     TEXT,
                stake_pct     NUMERIC,
                stake_units   INTEGER,
                engine_debug  JSONB,
                result        TEXT,
                profit        NUMERIC,
                created_at    TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_player_stats_unico ON picks_player_stats (match_date, fixture_id, player_id, method);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_player_stats_pendentes ON picks_player_stats (match_date) WHERE result IS NULL;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_player_stats_metodo ON picks_player_stats (method, match_date DESC);")

        conn.commit()
        return True
    except Exception as e:
        logger.error("[MIGRATION] Erro: %s", e)
        conn.rollback()
        return True
    finally:
        cur.close()
        conn.close()
