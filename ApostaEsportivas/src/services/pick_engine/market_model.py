"""Modelo 5 (Mercado/EV): probabilidade implicita, no-vig, edge e EV."""


def implied_prob(odd: float) -> float:
    return round(1 / odd, 4) if odd and odd > 0 else 0.0


def no_vig_pair_prob(odd_a: float, odd_b: float):
    if not odd_a or not odd_b or odd_a <= 1.0 or odd_b <= 1.0:
        return None, None
    ia, ib = 1 / odd_a, 1 / odd_b
    total = ia + ib
    return round(ia / total, 4), round(ib / total, 4)


def resolve_prob_baseline(entry: dict, sibling_entry: dict = None) -> dict:
    """Probabilidade implicita de mercado para usar como baseline do edge.
    Usa no-vig quando o par complementar (Over/Under, Yes/No) tem
    cobertura de >=2 bookmakers dos dois lados; caso contrario cai para
    1/best_odd."""
    if (
        sibling_entry
        and entry.get("bookmakers_count", 0) >= 2
        and sibling_entry.get("bookmakers_count", 0) >= 2
    ):
        prob_a, prob_b = no_vig_pair_prob(entry["best_odd"], sibling_entry["best_odd"])
        if prob_a is not None:
            return {"prob": prob_a, "source": "no_vig"}

    return {"prob": implied_prob(entry["best_odd"]), "source": "implied"}


def edge_and_ev(taxa_real: float, odd: float, prob_baseline: float) -> dict:
    edge = round(taxa_real - prob_baseline, 4)
    ev = round(taxa_real * odd - 1, 4)
    return {"edge": edge, "ev": ev}
