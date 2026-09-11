from utils.db_utils import get_connection


class LeaguesService:

    def __init__(self):
        pass

    # ----------------------------------------------------------------------
    # BUSCAR UMA LIGA ESPECÍFICA (mantido para compatibilidade)
    # ----------------------------------------------------------------------
    def get_league(self, league_id):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT league_id, name, season
            FROM leagues
            WHERE league_id = %s
            LIMIT 1;
        """, (league_id,))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        return {
            "league_id": row[0],
            "name": row[1],
            "season": row[2]
        }

    # ----------------------------------------------------------------------
    # AS LIGAS QUE O PROJETO ACOMPANHA
    # ----------------------------------------------------------------------
    def get_all_leagues(self):
        """So' as ATIVAS -- e o nome do metodo mentia ate' 2026-09-11.

        Ele varria `leagues` inteira, e quem o chama e' o gerador de perfil de
        liga: uma chamada da Anthropic POR LIGA. Com a tabela inteira, a Copa do
        Mundo (desativada desde a limpeza dos pipelines) e qualquer liga que o
        backfill de historico tivesse descoberto entravam na conta -- credito
        gasto pra descrever competicao que o projeto nao acompanha.

        `COALESCE(ativa, TRUE)` e' a mesma clausula de fixture_collector,
        match_statistics_sync, team_statistics_sync e do gate do motor ao vivo.
        Liga sem a coluna preenchida continua contando como ativa, que e' o
        comportamento de sempre.
        """
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT league_id, name, season
            FROM leagues
            WHERE COALESCE(ativa, TRUE)
            ORDER BY league_id ASC;
        """)

        rows = cur.fetchall()
        cur.close()
        conn.close()

        leagues = []
        for r in rows:
            leagues.append({
                "league_id": r[0],
                "name": r[1],
                "season": r[2]
            })

        return leagues
