"""Modelo de probabilidade real via distribuicao de Poisson -- complementa
a taxa empirica bruta (stats_model.compute_taxa, "quantas vezes aconteceu
nos ultimos N jogos") com um valor esperado (lambda) combinando ataque dos
dois times, e P(X<=k)/P(X>=k) derivado da distribuicao, nao so contagem
historica direta.

Por que Poisson: contagens de eventos discretos por partida (gols,
escanteios, cartoes) sao classicamente bem aproximadas por Poisson quando
a media (lambda) e conhecida -- e o modelo padrao da industria de apostas
esportivas pra esses mercados. So se aplica as familias que ja tem
estimativa de feitos/cedidos em stats_model (goals/corners/cards, ver
_SCORED_CONCEDED_FIELDS) -- nao a mercados binarios (BTTS/resultado/
handicap) nem a familias sem essa decomposicao (shots/shots_on_target/
offsides).

Toda a matematica roda em Python puro (math.exp/factorial) -- contagens
por partida raramente passam de ~20, entao isso e trivial sem precisar de
scipy/numpy (nenhuma das duas e dependencia hoje do projeto)."""
import math

_POISSON_FAMILIES = {"goals", "corners", "cards"}


def poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) para X ~ Poisson(lam)."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) para X ~ Poisson(lam). k negativo -> 0 (nunca acontece)."""
    if k < 0:
        return 0.0
    return sum(poisson_pmf(i, lam) for i in range(0, k + 1))


def prob_under(line: float, lam: float) -> float:
    """P(X < line) -- linhas de aposta sao sempre .5 (ex.: Under 2.5 == X<=2)."""
    return poisson_cdf(math.floor(line), lam)


def prob_over(line: float, lam: float) -> float:
    """P(X > line) = 1 - P(X <= floor(line))."""
    return round(1.0 - prob_under(line, lam), 6)


def poisson_prob_for_line(lam: float | None, line: float, direction: str) -> float | None:
    """P(hit) segundo o modelo Poisson pra uma linha Over/Under especifica.
    Retorna None se nao houver lambda valido (familia fora de escopo ou
    feitos/cedidos indisponiveis -- ver stats_model.expected_value_convergence)."""
    if lam is None or lam < 0:
        return None
    direction = (direction or "").strip().lower()
    if direction == "over":
        return round(prob_over(line, lam), 4)
    if direction == "under":
        return round(prob_under(line, lam), 4)
    return None


def is_poisson_family(family: str) -> bool:
    return family in _POISSON_FAMILIES


def model_fit(taxa_empirica: float | None, prob_poisson: float | None) -> float | None:
    """Convergencia entre a taxa empirica (stats_model, contagem direta
    nos ultimos jogos) e a probabilidade do modelo Poisson pra MESMA linha
    -- duas estimativas independentes concordando e sinal de que o modelo
    realmente descreve o padrao observado (nao so ajuste por acaso).
    Retorna a diferenca absoluta (0=concordancia total, 1=maxima
    divergencia); None se qualquer uma das duas nao existir."""
    if taxa_empirica is None or prob_poisson is None:
        return None
    return round(abs(taxa_empirica - prob_poisson), 4)
