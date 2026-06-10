from utils.db_utils import get_connection
import psycopg2.extras


class OddsService:

    ##########################################################################
    # Carrega todas as odds estruturadas da fixture
    ##########################################################################
    def load_odds_by_fixture(self, fixture_id):
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                v.market_row_id,
                v.odd_value,
                v.bookmaker_name,
                v.market_id,
                v.market_name,
                v.market_type,
                v.team_id,
                v.team_name,
                v.line_value
            FROM odds_values v
            WHERE v.fixture_id = %s
            ORDER BY v.market_row_id, v.bookmaker_id;
        """, (fixture_id,))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        structured = []

        for r in rows:
            structured.append({
                "market_id":   r["market_id"],
                "market_type": r["market_type"],
                "market_name": r["market_name"],
                "line": r["line_value"],
                "odd": float(r["odd_value"]),
                "bookmaker": r["bookmaker_name"],
                "team": r["team_name"] if r["team_id"] else None
            })

        return structured