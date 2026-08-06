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

_POISSON_FAMILIES = {"goals", "corners", "cards", "fouls"}


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
    feitos/cedidos indisponiveis -- ver stats_model.expected_value_convergence).

    LINHA REDONDA (sem .5, ex.: "Under 10"): o jogo que empata exato com a
    linha e' PUSH na graduacao real (ai_result_checker_service.evaluate_asian
    devolve a stake, nem GREEN nem RED), entao a probabilidade relevante e'
    condicional a NAO dar push -- P(hit) / (1 - P(X = linha)).

    Sem essa normalizacao, este modulo media uma coisa e stats_model outra:
    weighted_rate() ja EXCLUI o jogo empatado da amostra (correcao de
    2026-07-25), enquanto aqui "Under 10" contava P(X<=10), somando ao acerto
    justamente a massa que na pratica vira devolucao. As duas estimativas
    entao discordavam por construcao numa linha redonda, e o termo M
    (confidence.model_fit_adjustment) cobrava -0.05 de confidence por uma
    divergencia que era artefato de convencao, nao sinal de modelo errado.
    Em linha .5 (o caso comum) P(X = linha) = 0 e nada muda."""
    if lam is None or lam < 0:
        return None
    direction = (direction or "").strip().lower()
    if direction == "over":
        raw = prob_over(line, lam)
    elif direction == "under":
        raw = prob_under(line, lam)
    else:
        return None

    if line % 1 == 0:
        push_mass = poisson_pmf(int(line), lam)
        if direction == "under":
            # prob_under() usa floor(line), que numa linha redonda INCLUI o
            # empate exato -- tira ele antes de renormalizar.
            raw -= push_mass
        if push_mass < 1.0:
            raw = raw / (1.0 - push_mass)

    return round(max(0.0, min(1.0, raw)), 4)


def is_poisson_family(family: str) -> bool:
    return family in _POISSON_FAMILIES


def btts_probability(lambda_home: float | None, lambda_away: float | None) -> float | None:
    """P(ambas marcam) = P(casa marca>=1) x P(fora marca>=1), assumindo os
    dois times marcarem de forma independente -- simplificacao padrao (o
    ritmo do jogo pode correlacionar os dois levemente, mas nao ha dado
    pra medir essa correlacao hoje; assumir independencia e' o modelo
    baseline da industria pra BTTS via Poisson). lambda_home/lambda_away
    vem de stats_model.expected_value_convergence(..., scope='home'/'away')
    -- o valor esperado de CADA time nesta partida especifica (feitos dele
    x cedido pelo adversario), nao um lambda combinado do jogo inteiro
    como goals/corners/cards usam (BTTS pergunta sobre os dois times
    marcarem, nao sobre o total)."""
    if lambda_home is None or lambda_away is None or lambda_home < 0 or lambda_away < 0:
        return None
    p_home_scores = 1.0 - poisson_pmf(0, lambda_home)
    p_away_scores = 1.0 - poisson_pmf(0, lambda_away)
    return round(p_home_scores * p_away_scores, 4)


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
