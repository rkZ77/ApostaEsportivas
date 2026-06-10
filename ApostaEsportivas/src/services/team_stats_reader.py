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
