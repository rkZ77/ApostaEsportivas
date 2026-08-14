"""Modelo 5 (Mercado/EV): probabilidade implicita, no-vig, edge e EV."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG


def implied_prob(odd: float) -> float:
    return round(1 / odd, 4) if odd and odd > 0 else 0.0


def evaluation_odd(entry: dict, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """Odd que o motor usa pra JULGAR a linha (edge, EV, faixa de odd) --
    diferente da odd que o site publica, que continua sendo a da melhor casa.

    Com config.odd_evaluation="consensus" (padrao desde 2026-08-14) julga pela
    mediana das casas; "best" restaura o comportamento anterior, em que a casa
    mais generosa definia sozinha quanto valor existia. Cai pra best_odd
    quando o chamador nao trouxe consenso (odds antigas, fixtures de teste)."""
    if config.odd_evaluation == "consensus":
        consensus = entry.get("consensus_odd")
        if consensus:
            return float(consensus)
    return float(entry.get("best_odd") or 0)


def no_vig_pair_prob(odd_a: float, odd_b: float):
    if not odd_a or not odd_b or odd_a <= 1.0 or odd_b <= 1.0:
        return None, None
    ia, ib = 1 / odd_a, 1 / odd_b
    total = ia + ib
    return round(ia / total, 4), round(ib / total, 4)


def resolve_prob_baseline(entry: dict, sibling_entry: dict = None,
                          config: PickEngineConfig = DEFAULT_CONFIG) -> dict:
    """Probabilidade implicita de mercado para usar como baseline do edge.
    Usa no-vig quando o par complementar (Over/Under, Yes/No) tem
    cobertura de >=2 bookmakers dos dois lados; caso contrario cai para
    1/odd_de_avaliacao.

    Os dois lados entram pela MESMA regra de preco (ver evaluation_odd). Com a
    melhor odd dos dois lados o no-vig tirava mais que a margem: cada lado
    podia vir de uma casa diferente, a soma das implicitas caia abaixo de 1 e
    o mercado parecia mais barato do que qualquer casa realmente oferecia --
    o que inflava o edge dos DOIS lados ao mesmo tempo. Medido em 2026-08-14
    sobre 1.267 pares reais: em 63,9% deles o motor subestimava o mercado,
    +0,39 ponto de probabilidade em media (ate +4,2 no pior caso). E' efeito
    menor que o da odd de avaliacao, mas na mesma direcao."""
    odd_a = evaluation_odd(entry, config)
    if (
        sibling_entry
        and entry.get("bookmakers_count", 0) >= 2
        and sibling_entry.get("bookmakers_count", 0) >= 2
    ):
        prob_a, prob_b = no_vig_pair_prob(odd_a, evaluation_odd(sibling_entry, config))
        if prob_a is not None:
            return {"prob": prob_a, "source": "no_vig"}

    return {"prob": implied_prob(odd_a), "source": "implied"}


def edge_and_ev(taxa_real: float, odd: float, prob_baseline: float) -> dict:
    edge = round(taxa_real - prob_baseline, 4)
    ev = round(taxa_real * odd - 1, 4)
    return {"edge": edge, "ev": ev}
