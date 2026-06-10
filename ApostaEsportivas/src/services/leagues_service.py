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
    # NOVO: BUSCAR TODAS AS LIGAS DO SISTEMA
    # ----------------------------------------------------------------------
    def get_all_leagues(self):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT league_id, name, season
            FROM leagues
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
