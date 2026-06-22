from utils.db_utils import get_connection
from services.ev_calculator import EVCalculator
import psycopg2.extras


class OddsService:

    def __init__(self):
        self._ev_calc = EVCalculator()

    ##########################################################################
    # Carrega odds brutas da fixture (compatibilidade com código existente)
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
                "market_id":    r["market_id"],
                "market_type":  r["market_type"],
                "market_name":  r["market_name"],
                "market_pt":    r["market_pt"],
                "line":         r["line_value"],
                "line_value":   r["line_value"],
                "value_name":   r["value_name"],
                "odd":          float(r["odd_value"]),
                "odd_value":    float(r["odd_value"]),
                "bookmaker_id": r["bookmaker_id"],
                "bookmaker":    r["bookmaker_name"],
                "bookmaker_name": r["bookmaker_name"],
                "team":         r["team_name"] if r["team_id"] else None,
            })

        return structured

    ##########################################################################
    # Carrega odds com consenso no-vig calculado pelo EVCalculator
    #
    # Retorna lista de mercados estruturados com:
    #   - no_vig_prob  → probabilidade real de mercado (sem margem do bookmaker)
    #   - best_ev      → EV assumindo que a prob do mercado está correta
    #   - best_odd     → melhor odd disponível entre os bookmakers coletados
    #   - bookmakers_count → número de casas que têm esse mercado
    #   - odds_range   → dispersão entre casas (alta dispersão = mercado ineficiente)
    #
    # A IA usa no_vig_prob como baseline: se sua estimativa estatística for
    # maior que no_vig_prob, há edge positivo real.
    ##########################################################################
    def load_odds_structured(self, fixture_id) -> list[dict]:
        raw = self.load_odds_by_fixture(fixture_id)
        if not raw:
            return []
        return self._ev_calc.build_market_consensus(raw)

    ##########################################################################
    # Retorna apenas os mercados com EV potencialmente positivo
    # (no_vig_prob disponível e best_ev > limiar)
    ##########################################################################
    def load_value_markets(
        self,
        fixture_id: int,
        min_ev: float = -0.05,
        min_odd: float = 1.05,
        max_odd: float = 1.80,
    ) -> list[dict]:
        """
        Filtra os mercados estruturados retornando apenas candidatos válidos
        para análise pela IA:
          - Odd dentro do range permitido (1.05–1.80)
          - EV de mercado acima do mínimo (por padrão > -5%)
          - No-vig probability disponível (pelo menos 2 bookmakers)
        """
        markets = self.load_odds_structured(fixture_id)
        filtered = []

        for m in markets:
            best_odd = m.get("best_odd", 0)
            best_ev  = m.get("best_ev")
            no_vig   = m.get("no_vig_prob")
            n_books  = m.get("bookmakers_count", 0)

            if not (min_odd <= best_odd <= max_odd):
                continue
            if no_vig is None:
                continue
            if n_books < 1:
                continue
            if best_ev is not None and best_ev < min_ev:
                continue

            filtered.append(m)

        return filtered