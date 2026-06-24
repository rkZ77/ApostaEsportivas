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
        odd disponível entre os bookmakers coletados.

        Valida pares Over/Under por bookmaker: a soma das probabilidades implícitas
        deve estar entre 85% e 130%. Pares fora desse range indicam line_value errado
        na API (ex: Superbet retornando Under 0.5 rotulado como Under 1.5) e são
        descartados antes de calcular o best_odd.
        """
        import re as _re

        raw = self.load_odds_by_fixture(fixture_id)
        if not raw:
            return []

        _LINE_RE = _re.compile(
            r'^(Over|Under)\s+([\d.]+)$', _re.IGNORECASE
        )

        def _parse_over_under(vn: str):
            """Retorna (direction, line_num) para 'Over 1.5' → ('over','1.5'); None se não bater."""
            m = _LINE_RE.match(vn.strip())
            if m:
                return m.group(1).lower(), m.group(2)
            return None

        # Detecta pares Over/Under corrompidos por bookmaker
        # (probabilidade implícita fora de 85-130% → dado inválido da API)
        pair_groups: dict[tuple, dict] = {}
        for r in raw:
            parsed = _parse_over_under(r.get("value_name", ""))
            if not parsed:
                continue
            direction, line_num = parsed
            bk  = r.get("bookmaker") or r.get("bookmaker_name", "")
            key = (bk, r["market_id"], line_num)
            pair_groups.setdefault(key, {})[direction] = float(r.get("odd") or r.get("odd_value") or 0)

        corrupt_pairs: set[tuple] = set()
        for key, pair in pair_groups.items():
            o = pair.get("over", 0)
            u = pair.get("under", 0)
            if o > 1.0 and u > 1.0:
                implied_sum = 1 / o + 1 / u
                if implied_sum < 0.85 or implied_sum > 1.30:
                    corrupt_pairs.add(key)
                    bk, mid, lv = key
                    print(f"[ODDS] Par corrompido descartado: {bk} market={mid} line={lv} "
                          f"Over={o} Under={u} impl_sum={implied_sum:.2%}")

        # Agrupa por (market_id, value_name) — value_name já inclui a linha ("Over 1.5")
        groups: dict[tuple, list[dict]] = {}
        for r in raw:
            vn     = r.get("value_name", "")
            parsed = _parse_over_under(vn)
            if parsed:
                direction, line_num = parsed
                bk      = r.get("bookmaker") or r.get("bookmaker_name", "")
                pair_key = (bk, r["market_id"], line_num)
                if pair_key in corrupt_pairs:
                    continue
            key = (r["market_id"], vn)
            groups.setdefault(key, []).append(r)

        results: list[dict] = []
        for (market_id, value_name), rows in groups.items():
            sample = rows[0]

            # Extrai direction e linha do value_name ("Over 1.5" → direction="Over", line="1.5")
            parsed   = _parse_over_under(value_name)
            direction = parsed[0].capitalize() if parsed else value_name
            line_out  = parsed[1] if parsed else (sample.get("line_value") or sample.get("line") or "")

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

            # Over/Under com apenas 1 bookmaker → dado suspeito, descarta
            # (linha pode estar errada se só uma fonte reporta aquele valor)
            is_over_under = parsed is not None  # só True quando value_name é "Over X" / "Under X"
            if is_over_under and len(bk_odds) < 2:
                continue

            results.append({
                "market_id":        market_id,
                "market_name":      sample.get("market_name", ""),
                "market_type":      sample.get("market_type", ""),
                "market_pt":        sample.get("market_pt"),
                "line":             line_out,
                "value":            direction,
                "value_label":      value_name,   # label completo ex: "Over 1.5"
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
