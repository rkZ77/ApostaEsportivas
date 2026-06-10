from utils.db_utils import get_connection
import psycopg2.extras
from datetime import datetime, date
from decimal import Decimal


###############################################################################
# Sanitização universal
###############################################################################
def clean_stats(row):
    if not row:
        return None

    clean = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            clean[k] = v.isoformat()
        elif isinstance(v, Decimal):
            clean[k] = float(v)
        else:
            clean[k] = v
    return clean


class TeamStatsService:

    def _query(self, sql, params=None):
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(sql, params or [])
        row = cur.fetchone()

        cur.close()
        conn.close()

        return clean_stats(row)

    ##########################################################################
    # Estatísticas filtrando por LIGA + TEMPORADA + CONTEXTO
    ##########################################################################
    def get_stats(self, team_id, league_id, season, context_type):

        return self._query("""
            SELECT *
            FROM team_statistics
            WHERE team_id = %s
              AND league_id = %s
              AND season = %s
              AND context_type = %s
            LIMIT 1;
        """, (team_id, league_id, season, context_type))
