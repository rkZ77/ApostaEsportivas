"""
EV Calculator — Cálculo de probabilidade no-vig para mercados de apostas.

Princípio:
  Os bookmakers embute uma margem (vig/overround) nas odds para garantir lucro.
  Remover essa margem revela a "probabilidade de mercado" — o consenso real
  sobre a chance do evento ocorrer.

  EV real = (prob_no_vig * melhor_odd) - 1
  Se EV > 0: o mercado está subestimando o evento → valor encontrado.
  Se EV < 0: o mercado precifica corretamente ou superestima → sem valor.

Uso típico:
  calculator = EVCalculator()
  resultado = calculator.build_market_consensus(odds_rows, fixture_id)
  # resultado é uma lista estruturada com no_vig_prob e best_ev por mercado/linha
"""

from __future__ import annotations
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES MATEMÁTICAS FUNDAMENTAIS
# ─────────────────────────────────────────────────────────────────────────────

def remove_vig(implied_probs: list[float]) -> list[float]:
    """
    Remove a margem do bookmaker usando normalização multiplicativa.

    Exemplo:
      Over 2.5 @ 1.85 → implied 54.05%
      Under 2.5 @ 2.00 → implied 50.00%
      Total = 104.05% (vig = 4.05%)
      No-vig Over  = 54.05 / 104.05 = 51.95%
      No-vig Under = 50.00 / 104.05 = 48.05%
    """
    total = sum(implied_probs)
    if total <= 0:
        return implied_probs
    return [round(p / total, 6) for p in implied_probs]


def no_vig_prob_for_side(side_odd: float, counterpart_odds: list[float]) -> Optional[float]:
    """
    Calcula a probabilidade no-vig de um lado específico de um mercado.

    side_odd: odd do lado que queremos a probabilidade (ex: Over)
    counterpart_odds: odds dos outros lados do mesmo mercado no mesmo bookmaker
                      (ex: [Under_odd] para Over/Under; [Away_odd, Draw_odd] para 1X2)
    """
    if not side_odd or side_odd <= 1.0:
        return None

    valid_counterparts = [o for o in counterpart_odds if o and o > 1.0]
    if not valid_counterparts:
        return None

    all_odds = [side_odd] + valid_counterparts
    implied = [1.0 / o for o in all_odds]
    no_vig = remove_vig(implied)
    return round(no_vig[0], 4)


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class EVCalculator:

    # -------------------------------------------------------------------------
    # AGRUPA ODDS POR (market_id, line_value, bookmaker_id) → outcomes
    # -------------------------------------------------------------------------
    def _group_by_market_bookmaker(
        self, odds_rows: list[dict]
    ) -> dict[tuple, dict[int, list[dict]]]:
        """
        Retorna:
          {(market_id, line_value): {bookmaker_id: [row, row, ...]}}

        Cada "row" contém value_name (Over/Under/Home/Away/Yes/No) + odd_value.
        """
        grouped: dict[tuple, dict[int, list[dict]]] = {}

        for row in odds_rows:
            market_id  = row.get("market_id")
            line_value = str(row.get("line_value") or "").strip()
            bk_id      = row.get("bookmaker_id")

            if not market_id or not bk_id:
                continue

            key = (market_id, line_value)
            if key not in grouped:
                grouped[key] = {}
            if bk_id not in grouped[key]:
                grouped[key][bk_id] = []
            grouped[key][bk_id].append(row)

        return grouped

    # -------------------------------------------------------------------------
    # CALCULA NO-VIG PROBABILITY PARA UM LADO ESPECÍFICO EM UM BOOKMAKER
    # -------------------------------------------------------------------------
    def _calc_no_vig_for_value(
        self,
        target_value: str,
        bk_rows: list[dict],
    ) -> Optional[float]:
        """
        Para um bookmaker e mercado/linha específicos, calcula a prob no-vig
        do valor alvo (ex: "Over").
        """
        target_row = next(
            (r for r in bk_rows if r.get("value_name", "").lower() == target_value.lower()),
            None,
        )
        if not target_row:
            return None

        counterpart = [
            r["odd_value"]
            for r in bk_rows
            if r.get("value_name", "").lower() != target_value.lower()
            and r.get("odd_value") and r["odd_value"] > 1.0
        ]

        return no_vig_prob_for_side(target_row.get("odd_value", 0), counterpart)

    # -------------------------------------------------------------------------
    # CALCULA CONSENSO NO-VIG ENTRE TODOS OS BOOKMAKERS DISPONÍVEIS
    # -------------------------------------------------------------------------
    def consensus_no_vig(
        self,
        target_value: str,
        bookmaker_map: dict[int, list[dict]],
    ) -> Optional[float]:
        """
        Calcula a probabilidade no-vig média entre todos os bookmakers
        disponíveis para um mercado/linha/lado.

        Quanto mais bookmakers, mais confiável o consenso.
        """
        probs = []

        for bk_id, bk_rows in bookmaker_map.items():
            prob = self._calc_no_vig_for_value(target_value, bk_rows)
            if prob is not None:
                probs.append(prob)

        if not probs:
            return None

        return round(sum(probs) / len(probs), 4)

    # -------------------------------------------------------------------------
    # MONTA ESTRUTURA COMPLETA DE ODDS COM CONSENSO POR MERCADO/LINHA/LADO
    # -------------------------------------------------------------------------
    def build_market_consensus(
        self,
        odds_rows: list[dict],
    ) -> list[dict]:
        """
        A partir de todas as linhas de odds de um fixture, retorna uma lista
        de mercados estruturados com:

          - market_id, market_name, market_type, market_pt
          - line_value
          - value_name (Over / Under / Home / Away / Yes / No)
          - best_odd (melhor odd disponível entre bookmakers)
          - best_bookmaker (casa que oferece a melhor odd)
          - no_vig_prob (probabilidade real de mercado, sem margem)
          - best_ev (EV calculado com best_odd × no_vig_prob)
          - bookmakers_count (quantos bookmakers têm esse mercado)
          - odds_range {"min": x, "max": y} (dispersão entre casas)
          - bookmaker_odds [{"bookmaker": name, "odd": x}, ...]

        Quanto menor a dispersão, mais eficiente/líquido o mercado.
        Alta dispersão = possível ineficiência = oportunidade.
        """
        grouped = self._group_by_market_bookmaker(odds_rows)

        results: list[dict] = []

        for (market_id, line_value), bookmaker_map in grouped.items():
            # Coleta referência de metadados do mercado (qualquer linha serve)
            sample_row = next(
                (r for bk_rows in bookmaker_map.values() for r in bk_rows),
                None,
            )
            if not sample_row:
                continue

            # Coleta todos os value_names distintos neste (market_id, line_value)
            all_values = set()
            for bk_rows in bookmaker_map.values():
                for r in bk_rows:
                    vn = r.get("value_name", "").strip()
                    if vn:
                        all_values.add(vn)

            for target_value in sorted(all_values):
                # No-vig consensus
                no_vig = self.consensus_no_vig(target_value, bookmaker_map)

                # Melhor odd disponível (entre bookmakers) para este value
                best_odd  = 0.0
                best_bk   = ""
                all_odds_for_value: list[float] = []

                for bk_id, bk_rows in bookmaker_map.items():
                    row = next(
                        (r for r in bk_rows if r.get("value_name", "").lower() == target_value.lower()),
                        None,
                    )
                    if not row:
                        continue
                    odd = row.get("odd_value", 0)
                    if odd and odd > 1.0:
                        all_odds_for_value.append(odd)
                        if odd > best_odd:
                            best_odd = odd
                            best_bk  = row.get("bookmaker_name", "")

                if not best_odd:
                    continue

                best_ev = round((no_vig * best_odd) - 1, 4) if no_vig else None

                # Odds por bookmaker para exibição à IA
                bk_odds = []
                for bk_id, bk_rows in bookmaker_map.items():
                    row = next(
                        (r for r in bk_rows if r.get("value_name", "").lower() == target_value.lower()),
                        None,
                    )
                    if row and row.get("odd_value", 0) > 1.0:
                        bk_odds.append({
                            "bookmaker": row.get("bookmaker_name", ""),
                            "odd": row["odd_value"],
                        })

                results.append({
                    "market_id":        market_id,
                    "market_name":      sample_row.get("market_name", ""),
                    "market_type":      sample_row.get("market_type", ""),
                    "market_pt":        sample_row.get("market_pt"),
                    "line":             line_value,
                    "value":            target_value,
                    "best_odd":         round(best_odd, 2),
                    "best_bookmaker":   best_bk,
                    "no_vig_prob":      no_vig,
                    "best_ev":          best_ev,
                    "bookmakers_count": len(bk_odds),
                    "odds_range":       {
                        "min": round(min(all_odds_for_value), 2),
                        "max": round(max(all_odds_for_value), 2),
                    } if len(all_odds_for_value) > 1 else None,
                    "bookmaker_odds":   sorted(bk_odds, key=lambda x: x["odd"], reverse=True),
                })

        return results

    # -------------------------------------------------------------------------
    # CÁLCULO AVULSO DE EV
    # -------------------------------------------------------------------------
    @staticmethod
    def market_ev(no_vig_prob: float, best_odd: float) -> float:
        """EV = (prob_no_vig × melhor_odd) - 1"""
        return round((no_vig_prob * best_odd) - 1, 4)

    # -------------------------------------------------------------------------
    # RESUMO PARA DEBUG / LOG
    # -------------------------------------------------------------------------
    @staticmethod
    def summarize(markets: list[dict]) -> str:
        lines = []
        for m in markets:
            ev_str = f"EV={round(m['best_ev']*100,1)}%" if m.get("best_ev") is not None else "EV=n/a"
            nv_str = f"no-vig={round(m['no_vig_prob']*100,1)}%" if m.get("no_vig_prob") else "no-vig=n/a"
            lines.append(
                f"  {m['market_name']} | {m['value']} {m['line']} "
                f"| best={m['best_odd']}@{m['best_bookmaker']} "
                f"| {nv_str} | {ev_str} | {m['bookmakers_count']} casas"
            )
        return "\n".join(lines)
