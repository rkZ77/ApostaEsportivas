from utils.db_utils import get_connection


class TeamStatsReader:

    ##########################################################################
    # Retorna estatísticas consolidadas do time POR CONTEXTO
    ##########################################################################
    def get_team_stats(self, team_id, league_id, season, context_type):

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM team_statistics
            WHERE team_id = %s
              AND league_id = %s
              AND season = %s
              AND context_type = %s
            LIMIT 1;
        """, (team_id, league_id, season, context_type))

        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return None

        columns = [desc[0] for desc in cur.description]

        return {
            col: float(val) if isinstance(val, (int, float)) else val
            for col, val in zip(columns, row)
        }

    ##########################################################################
    # Busca todos os times da tabela teams
    ##########################################################################
    def get_all_teams(self):

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT DISTINCT team_id, league_id, season
            FROM teams;
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return [
            {"team_id": r[0], "league_id": r[1], "season": r[2]}
            for r in rows
        ]

    ##########################################################################
    # Retorna times distintos que tiveram fixture atualizada recentemente
    ##########################################################################
    def get_teams_with_recent_fixtures(self, days=3):
        from datetime import datetime, timedelta, timezone
        conn = get_connection()
        cur = conn.cursor()
        limit_date = datetime.now(timezone.utc) - timedelta(days=days)
        cur.execute("""
            SELECT DISTINCT ms.home_team_id, ms.league_id, ms.season
            FROM match_statistics ms
            INNER JOIN teams t
                ON t.team_id = ms.home_team_id
               AND t.league_id = ms.league_id
               AND t.season = ms.season
            WHERE ms.last_updated >= %s
            UNION
            SELECT DISTINCT ms.away_team_id, ms.league_id, ms.season
            FROM match_statistics ms
            INNER JOIN teams t
                ON t.team_id = ms.away_team_id
               AND t.league_id = ms.league_id
               AND t.season = ms.season
            WHERE ms.last_updated >= %s
        """, (limit_date, limit_date))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"team_id": r[0], "league_id": r[1], "season": r[2]} for r in rows]

    ##########################################################################
    # DELETA TODAS AS ESTATÍSTICAS
    ##########################################################################
    def delete_all_team_statistics(self):

        conn = get_connection()
        cur = conn.cursor()

        print("[TeamStatsReader] Deletando todas as estatísticas...")

        cur.execute("DELETE FROM team_statistics;")

        conn.commit()
        cur.close()
        conn.close()

        print("✔ team_statistics limpa.\n")

    ##########################################################################
    # UPSERT na team_statistics COM CONTEXT_TYPE
    ##########################################################################
    def get_teams_with_stale_statistics(self, limite: int = 0):
        """Times cuja MEDIA esta' mais velha que a ultima partida deles.

        POR QUE ISTO EXISTE (2026-08-27)

        As duas formas que havia eram grossas demais nas duas pontas:

          update_full_season_statistics()      APAGA `team_statistics` inteira
                                               e reprocessa todo time do banco;
          update_recent_teams_statistics(3)    reprocessa todo time que teve
                                               jogo nos ultimos 3 dias.

        A segunda e' a que a varredura automatica usava, e ela refaz a conta de
        um time mesmo quando NADA daquele time mudou na passada -- basta ele ter
        jogado. Numa janela de tres dias cheia sao dezenas de times, cada um
        custando duas leituras da temporada inteira e dois upserts com conexao
        propria. O trabalho e' quase todo desperdicio, e ele acontece no
        caminho de uma VISITA ao site.

        Aqui a pergunta e' a exata: existe partida daquele time gravada DEPOIS
        da ultima vez que a media dele foi escrita? Se nao existe, refazer a
        conta produz o mesmo numero.

        Custa zero requisicao de API -- e' comparacao de `last_updated` entre
        duas tabelas que ja' tem a coluna.

        Time SEM linha em `team_statistics` entra: media que nunca foi
        calculada e' o caso mais desatualizado que existe, e o LEFT JOIN
        devolveria NULL, que nao e' "menor que" nada em SQL.
        """
        conn = get_connection()
        cur = conn.cursor()
        # `team_statistics` tem uma linha por contexto (HOME/AWAY); a media do
        # time so' esta' em dia quando A MAIS VELHA delas for mais nova que a
        # ultima partida. MIN, portanto, e nao MAX.
        cur.execute(f"""
            WITH ultima_partida AS (
                SELECT lado.team_id, ms.league_id, ms.season,
                       MAX(ms.last_updated) AS gravada_em
                  FROM match_statistics ms
                  CROSS JOIN LATERAL (VALUES (ms.home_team_id), (ms.away_team_id))
                       AS lado(team_id)
                 WHERE lado.team_id IS NOT NULL
                 GROUP BY lado.team_id, ms.league_id, ms.season
            ),
            media AS (
                SELECT team_id, league_id, season, MIN(last_updated) AS calculada_em
                  FROM team_statistics
                 GROUP BY team_id, league_id, season
            )
            SELECT u.team_id, u.league_id, u.season
              FROM ultima_partida u
              -- INNER JOIN em `teams`: o mesmo recorte de
              -- get_teams_with_recent_fixtures. Time nao cadastrado naquela
              -- liga/temporada nao tem media pra atualizar.
              JOIN teams t ON t.team_id = u.team_id
                          AND t.league_id = u.league_id
                          AND t.season = u.season
              LEFT JOIN media m ON m.team_id = u.team_id
                               AND m.league_id = u.league_id
                               AND m.season = u.season
             WHERE m.calculada_em IS NULL OR m.calculada_em < u.gravada_em
             ORDER BY u.gravada_em DESC
             {"LIMIT %s" if limite else ""}
        """, (limite,) if limite else ())
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"team_id": r[0], "league_id": r[1], "season": r[2]} for r in rows]

    def upsert_team_statistics(self, team_id, league_id, season, stats):

        conn = get_connection()
        cur = conn.cursor()

        context_type = stats["context_type"]

        # Remove context_type do dicionário de colunas dinâmicas
        data_columns = {k: v for k, v in stats.items() if k != "context_type"}

        columns = ", ".join(data_columns.keys())
        values_placeholders = ", ".join(["%s"] * len(data_columns))
        update_set = ", ".join(
            [f"{k} = EXCLUDED.{k}" for k in data_columns.keys()]
        )

        sql = f"""
            INSERT INTO team_statistics (
                team_id,
                league_id,
                season,
                context_type,
                {columns},
                last_updated
            )
            VALUES (%s, %s, %s, %s, {values_placeholders}, NOW())
            ON CONFLICT (team_id, league_id, season, context_type)
            DO UPDATE SET
                {update_set},
                last_updated = NOW();
        """

        cur.execute(
            sql,
            [team_id, league_id, season, context_type] +
            list(data_columns.values())
        )

        conn.commit()
        cur.close()
        conn.close()
