from utils.db_utils import get_connection
import psycopg2.extras


class OddsService:

    ##########################################################################
    # Carrega odds brutas da fixture
    ##########################################################################
    def load_odds_by_fixture(self, fixture_id):
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                v.market_row_id,
                v.odd_value,
                v.bookmaker_id,
                v.bookmaker_name,
                v.market_id,
                v.market_name,
                v.market_type,
                v.market_pt,
                v.team_id,
                v.team_name,
                v.value_name,
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
                "market_id":      r["market_id"],
                "market_type":    r["market_type"],
                "market_name":    r["market_name"],
                "market_pt":      r["market_pt"],
                "line":           r["line_value"],
                "line_value":     r["line_value"],
                "value_name":     r["value_name"],
                "odd":            float(r["odd_value"]),
                "odd_value":      float(r["odd_value"]),
                "bookmaker_id":   r["bookmaker_id"],
                "bookmaker":      r["bookmaker_name"],
                "bookmaker_name": r["bookmaker_name"],
                "team":           r["team_name"] if r["team_id"] else None,
            })

        return structured

    ##########################################################################
    # Agrega odds por mercado+linha+side — retorna melhor odd entre bookmakers
    ##########################################################################
    def load_odds_structured(self, fixture_id) -> list[dict]:
        """Agrupa odds por (market_id, line_value, value_name) e retorna a melhor
        odd disponível entre os bookmakers coletados."""
        raw = self.load_odds_by_fixture(fixture_id)
        if not raw:
            return []

        groups: dict[tuple, list[dict]] = {}
        for r in raw:
            key = (r["market_id"], r.get("line", ""), r.get("value_name", ""))
            groups.setdefault(key, []).append(r)

        results: list[dict] = []
        for (market_id, line_value, value_name), rows in groups.items():
            sample = rows[0]

            best_odd = 0.0
            best_bk  = ""
            all_odds: list[float] = []
            bk_odds:  list[dict]  = []

            for r in rows:
                odd = float(r.get("odd") or r.get("odd_value") or 0)
                if odd > 1.0:
                    bk_name = r.get("bookmaker") or r.get("bookmaker_name", "")
                    all_odds.append(odd)
                    bk_odds.append({"bookmaker": bk_name, "odd": odd})
                    if odd > best_odd:
                        best_odd = odd
                        best_bk  = bk_name

            if not best_odd:
                continue

            results.append({
                "market_id":        market_id,
                "market_name":      sample.get("market_name", ""),
                "market_type":      sample.get("market_type", ""),
                "market_pt":        sample.get("market_pt"),
                "line":             line_value,
                "value":            value_name,
                "best_odd":         round(best_odd, 2),
                "best_bookmaker":   best_bk,
                "bookmakers_count": len(bk_odds),
                "odds_range": {
                    "min": round(min(all_odds), 2),
                    "max": round(max(all_odds), 2),
                } if len(all_odds) > 1 else None,
                "bookmaker_odds": sorted(bk_odds, key=lambda x: x["odd"], reverse=True),
            })

        return results
