"""Modelo de probabilidade real via distribuicao de Poisson -- complementa
a taxa empirica bruta (stats_model.compute_taxa, "quantas vezes aconteceu
nos ultimos N jogos") com um valor esperado (lambda) combinando ataque dos
dois times, e P(X<=k)/P(X>=k) derivado da distribuicao, nao so contagem
historica direta.

Por que Poisson: contagens de eventos discretos por partida sao
classicamente bem aproximadas por Poisson quando a media (lambda) e
conhecida -- e o modelo padrao da industria. So se aplica as familias que ja
tem estimativa de feitos/cedidos em stats_model (goals/corners/cards, ver
_SCORED_CONCEDED_FIELDS) -- nao a mercados binarios (BTTS/resultado/
handicap) nem a familias sem essa decomposicao (shots/shots_on_target/
offsides).

POISSON SO' VALE PRA GOLS -- MEDIDO EM 2026-08-20
--------------------------------------------------
Poisson impoe variancia = media. Isso e' uma AFIRMACAO sobre o dado, nao uma
conveniencia, e ela foi testada nos ~1.690 jogos FT da base ajustando a MESMA
estrutura que o motor usa (lambda_ij = mu x ataque_i x defesa_j) e medindo a
dispersao de Pearson que sobra:

    contagem                 phi residual
    gols (mandante)              1.05      <- Poisson esta' certo
    gols (visitante)             0.98      <- Poisson esta' certo
    gols (total)                 1.07      <- Poisson esta' certo
    cartoes (mandante)           1.24
    impedimentos (total)         1.37
    chutes no gol (total)        1.61
    escanteios (mandante)        1.82
    escanteios (visitante)       1.86
    faltas (mandante)            2.15
    cartoes (total)              2.28
    faltas (total)               3.12
    chutes (total)               3.20

O phi e' RESIDUAL: a variacao entre times ja' foi removida pelo ajuste, entao
o que sobra e' a superdispersao que o lambda do motor NAO explica.

A consequencia tem uma direcao so'. Superdispersao empurra massa pras duas
caudas, e as linhas de aposta ficam perto da media -- entao o Poisson INFLA
tanto o Over quanto o Under em toda familia superdispersa:

    escanteios visitante Over 2.5    72.1% -> 62.9%   (-9.2pp)
    faltas mandante      Over 9.5    77.9% -> 70.3%   (-7.6pp)
    escanteios mandante  Over 3.5    74.2% -> 67.3%   (-6.9pp)
    escanteios total     Under 11.5  82.3% -> 77.4%   (-4.9pp)
    gols total           Over 1.5    72.1% -> 70.9%   (-1.2pp)

E isso explica o desempenho medido por mercado sem precisar de mais nada: o
unico mercado em que o motor bate o mercado e' gols, e gols e' o unico em que
a distribuicao assumida esta' certa. Escanteios anunciava 71,9% e realizava
50,0% em agosto de 2026.

A correcao e' trocar Poisson por Binomial Negativa (Gama-Poisson) com a
dispersao MEDIDA de cada familia. Gols fica praticamente identico (phi ~ 1
devolve Poisson), entao o mercado que funciona nao e' tocado.

Toda a matematica roda em Python puro (math.exp/factorial) -- contagens
por partida raramente passam de ~20, entao isso e trivial sem precisar de
scipy/numpy (nenhuma das duas e dependencia hoje do projeto)."""
import math

_POISSON_FAMILIES = {"goals", "corners", "cards", "fouls"}

#: Dispersao residual medida por (familia, escopo) -- ver o cabecalho.
#: phi = variancia / media depois de remover o efeito de time dos dois lados.
#: Nao ha nenhum numero escolhido aqui: cada um saiu do ajuste sobre a base de
#: PROD em 2026-08-20, e mexer num deles exige refazer a medicao.
_DISPERSAO: dict[tuple[str, str], float] = {
    # Gols e' o caso de controle: phi ~ 1 devolve Poisson e o mercado que
    # funciona continua exatamente como estava.
    ("goals", "home"): 1.05,
    ("goals", "away"): 1.00,   # medido 0.98 -- subdispersao nao e' representavel
    ("goals", "total"): 1.07,  # na Gama-Poisson, entao trunca em Poisson
    ("corners", "home"): 1.82,
    ("corners", "away"): 1.86,
    ("corners", "total"): 1.82,
    # So' o lado mandante de cartoes tem amostra propria (n=1.187); o
    # visitante herda em vez de ganhar um numero inventado. O total tem o seu,
    # e ele e' MAIOR que a soma dos lados porque cartao dos dois times anda
    # junto (jogo pegado castiga os dois) -- correlacao positiva infla a
    # variancia do total. Mesmo motivo em faltas e chutes.
    ("cards", "home"): 1.24,
    ("cards", "away"): 1.24,
    ("cards", "total"): 2.28,
    ("fouls", "home"): 2.15,
    ("fouls", "away"): 2.16,
    ("fouls", "total"): 3.12,
    ("shots", "home"): 2.61,
    ("shots", "away"): 2.61,
    ("shots", "total"): 3.20,
    ("shots_on_target", "home"): 1.38,
    ("shots_on_target", "away"): 1.41,
    ("shots_on_target", "total"): 1.61,
    ("offsides", "home"): 1.24,
    ("offsides", "away"): 1.24,
    ("offsides", "total"): 1.37,
}

#: Abaixo disso a Gama-Poisson nao se distingue de Poisson e so' custaria
#: precisao numerica -- inclui todo caso em que a familia nao foi medida.
_PHI_MINIMO = 1.02


def dispersao(family: str | None, scope: str | None) -> float:
    """phi da familia/escopo, ou 1.0 (= Poisson) quando nao foi medido.

    O default e' Poisson de proposito: familia sem medicao continua se
    comportando exatamente como antes desta mudanca, entao a Binomial Negativa
    nunca altera um mercado sobre o qual nao ha evidencia.
    """
    if not family:
        return 1.0
    escopo = scope or "total"
    return (_DISPERSAO.get((family, escopo))
            or _DISPERSAO.get((family, "total"))
            or 1.0)


def nb_pmf(k: int, mu: float, phi: float) -> float:
    """P(X = k) na Gama-Poisson de media `mu` e variancia `phi * mu`.

    Parametrizada por (media, dispersao) e nao por (r, p) porque phi e' a
    quantidade que a medicao produz e que nao depende da escala: escanteio tem
    phi 1.82 com lambda 4 ou com lambda 6, enquanto o r equivalente mudaria
    junto. r = mu / (phi - 1) e' derivado aqui dentro.

    Em log-gama pra nao estourar em contagem alta (faltas passa de 30).
    """
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    if phi <= _PHI_MINIMO:
        return poisson_pmf(k, mu)
    r = mu / (phi - 1.0)
    log_p = (
        math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
        + r * math.log(r / (r + mu))
        + k * math.log(mu / (r + mu))
    )
    return math.exp(log_p)


def nb_cdf(k: int, mu: float, phi: float) -> float:
    """P(X <= k). k negativo -> 0 (nunca acontece)."""
    if k < 0:
        return 0.0
    return sum(nb_pmf(i, mu, phi) for i in range(0, k + 1))


def poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) para X ~ Poisson(lam).

    Em log-gama e nao com factorial(): `math.factorial(171)` ja' nao cabe num
    float e a versao anterior levantava OverflowError. Nao dava pra chegar la'
    somando contagem de partida, mas quem soma uma cauda inteira chega -- e um
    erro de estouro numa funcao de probabilidade e' o tipo de coisa que
    aparece em producao num jogo estranho, nao em teste."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    if k < 0:
        return 0.0
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))


def poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) para X ~ Poisson(lam). k negativo -> 0 (nunca acontece)."""
    if k < 0:
        return 0.0
    return sum(poisson_pmf(i, lam) for i in range(0, k + 1))


def prob_under(line: float, lam: float, phi: float = 1.0) -> float:
    """P(X < line) -- linhas de aposta sao sempre .5 (ex.: Under 2.5 == X<=2).

    phi=1.0 e' Poisson exato e e' o default: quem chama sem dispersao continua
    vendo o comportamento anterior a 2026-08-20."""
    return nb_cdf(math.floor(line), lam, phi)


def prob_over(line: float, lam: float, phi: float = 1.0) -> float:
    """P(X > line) = 1 - P(X <= floor(line))."""
    return round(1.0 - prob_under(line, lam, phi), 6)


def poisson_prob_for_line(lam: float | None, line: float, direction: str,
                          family: str | None = None,
                          scope: str | None = None) -> float | None:
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
    Em linha .5 (o caso comum) P(X = linha) = 0 e nada muda.

    `family`/`scope` selecionam a dispersao medida (ver _DISPERSAO). Sem eles a
    conta e' Poisson pura, identica a de antes. O nome continua "poisson_" por
    isso: Poisson e' o caso particular phi=1, e renomear quebraria todo
    chamador sem mudar comportamento nenhum."""
    if lam is None or lam < 0:
        return None
    phi = dispersao(family, scope)
    direction = (direction or "").strip().lower()
    if direction == "over":
        raw = prob_over(line, lam, phi)
    elif direction == "under":
        raw = prob_under(line, lam, phi)
    else:
        return None

    if line % 1 == 0:
        push_mass = nb_pmf(int(line), lam, phi)
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
