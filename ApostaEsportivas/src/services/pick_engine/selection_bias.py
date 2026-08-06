"""Correcao da maldicao do vencedor no candidato selecionado.

O PROBLEMA
----------
`orchestrator.analyze_fixture_markets()` avalia dezenas de mercados por
partida. `ranking.select_smart_safe_line()` escolhe a melhor LINHA de cada
mercado, e `rank_all_candidates()` escolhe o melhor MERCADO. Ou seja: o pick
final e' o MAXIMO de muitas estimativas ruidosas.

O maximo de N estimativas ruidosas e' enviesado pra cima mesmo quando todas
tem edge verdadeiro zero. Nao e' um defeito do estimador de nenhum mercado
individual -- cada um pode ser perfeitamente nao-enviesado -- e' consequencia
de SELECIONAR pelo maior. Quanto mais mercados avaliados, maior o edge
aparente do vencedor, e a reacao intuitiva (cobrir mais mercados pra achar
mais valor) piora o problema.

Nada no motor reconhecia isso ate 2026-08-06.

A CORRECAO
----------
Para N amostras independentes de uma normal(0, sigma), a esperanca do maximo
cresce com sigma * sqrt(2*ln(N)). Isso da a escala do vies otimo a descontar.
Duas rotas, e o modulo usa a que o dado sustentar:

1. `desconto_por_contagem`: usa so' N e o desvio das estimativas. E' a formula
   fechada acima, aplicavel sempre que houver mais de um candidato.

2. `desconto_por_destaque`: mede quantos desvios o vencedor esta' acima dos
   DEMAIS candidatos. Se esse destaque e' compativel com o que o puro acaso
   produziria (sqrt(2*ln(N)) desvios), o desconto vale inteiro; se o vencedor
   esta' muito alem disso, parte da vantagem e' sinal real e o desconto
   encolhe proporcionalmente.

O desvio e' sempre estimado EXCLUINDO o vencedor. Incluir o proprio extremo
selecionado infla o desvio e, por consequencia, o desconto -- o vencedor
acabaria justificando a propria penalidade.

POR QUE NAO E' UMA REGRA FIXA
-----------------------------
O desconto e' calculado a partir da dispersao MEDIDA dos candidatos daquela
partida, nao de uma constante. Partida com 3 candidatos parecidos recebe
desconto pequeno; partida com 40 candidatos dos quais um disparou recebe
desconto grande. E' o mesmo espirito do encolhimento bayesiano ja' usado no
motor: a correcao e' proporcional a quanta evidencia existe.
"""
from __future__ import annotations

import math

# Teto do desconto, em pontos de probabilidade. Sem teto, uma partida com
# muitos candidatos e dispersao alta poderia zerar qualquer edge -- o objetivo
# e' corrigir o vies, nao proibir aposta.
DESCONTO_MAX = 0.12

# Abaixo de 2 candidatos nao existe selecao, logo nao existe vies de selecao.
MIN_CANDIDATOS = 2


def _desvio_amostral(valores: list[float]) -> float | None:
    n = len(valores)
    if n < 2:
        return None
    media = sum(valores) / n
    return math.sqrt(sum((v - media) ** 2 for v in valores) / (n - 1))


def desconto_por_contagem(n_candidatos: int, desvio: float | None) -> float:
    """Vies esperado do maximo de `n_candidatos` estimativas com desvio dado.

    E[max] - media ~= desvio * sqrt(2 * ln(n)) para n moderado. Cresce devagar
    (logaritmo), o que e' a propriedade certa: dobrar o numero de mercados nao
    dobra o vies, mas o aumenta de forma real.
    """
    if n_candidatos < MIN_CANDIDATOS or not desvio or desvio <= 0:
        return 0.0
    bruto = desvio * math.sqrt(2 * math.log(n_candidatos))
    return round(min(bruto, DESCONTO_MAX), 4)


def desconto_por_destaque(vencedor: float, resto: list[float]) -> float:
    """Desconto lendo quantos desvios o vencedor esta' acima dos demais.

    Sob puro acaso, o maximo de N estimativas fica cerca de sqrt(2*ln(N))
    desvios acima da media. Entao:

      z <= esperado_sob_acaso  -> o destaque e' o que o ruido produziria
                                  sozinho; desconta o vies inteiro.
      z >> esperado_sob_acaso  -> o vencedor esta' alem do que o acaso
                                  explica; a diferenca e' sinal real e o
                                  desconto encolhe na proporcao.

    O encolhimento e' `esperado / z`, que vale 1 no limite do acaso e tende a
    zero conforme o vencedor se destaca -- monotono na direcao certa, que era
    exatamente o que a primeira versao deste calculo errava (ela punia MAIS o
    vencedor destacado que o vencedor colado).
    """
    n_resto = len(resto)
    if n_resto < 1:
        return 0.0
    n_total = n_resto + 1
    if n_total < MIN_CANDIDATOS:
        return 0.0

    desvio_resto = _desvio_amostral(resto)
    if not desvio_resto or desvio_resto <= 0:
        # Todos os perdedores identicos: nao ha ruido medivel entre eles,
        # logo nao ha vies de selecao a estimar por este caminho.
        return 0.0

    media_resto = sum(resto) / n_resto
    esperado = math.sqrt(2 * math.log(n_total))
    z = (vencedor - media_resto) / desvio_resto
    if z <= 0:
        return 0.0

    vies_bruto = desvio_resto * esperado
    encolhimento = min(1.0, esperado / z)
    return round(min(vies_bruto * encolhimento, DESCONTO_MAX), 4)


def corrigir(candidatos: list, campo: str = "edge") -> dict:
    """Desconto a aplicar no `campo` do candidato vencedor.

    `candidatos` e' a lista completa AVALIADA naquela partida (nao so' os
    aprovados) -- o vies vem de quantos competiram, e filtrar antes de contar
    subestimaria o problema.

    Devolve o desconto e os componentes, sempre expostos: um numero que reduz
    edge precisa ser auditavel, e a explicacao da pick tem que poder dizer
    "descontei X por ter avaliado N mercados".
    """
    valores = [
        float(c[campo]) for c in candidatos
        if c.get(campo) is not None
    ]
    n = len(valores)
    if n < MIN_CANDIDATOS:
        return {"desconto": 0.0, "n_candidatos": n, "metodo": "sem_selecao",
                "desvio": None, "folga": None}

    ordenados = sorted(valores, reverse=True)
    vencedor, segundo = ordenados[0], ordenados[1]
    resto = ordenados[1:]

    # Desvio SEM o vencedor: incluir o extremo selecionado infla o desvio e
    # faria o proprio vencedor justificar a penalidade que recebe.
    desvio_resto = _desvio_amostral(resto)

    por_contagem = desconto_por_contagem(n, desvio_resto)
    por_destaque = desconto_por_destaque(vencedor, resto)

    # Usa o MENOR dos dois. Os dois medem o mesmo vies por caminhos
    # diferentes; pegar o menor mantem a correcao conservadora, que e' a
    # postura certa pra uma penalidade que reduz aposta -- errar pro lado de
    # descontar de menos custa menos que matar picks boas.
    desconto = min(por_contagem, por_destaque)

    return {
        "desconto": round(desconto, 4),
        "n_candidatos": n,
        # `is not None` e nao truthiness: desvio ZERO e' um resultado legitimo
        # e informativo (todos os perdedores identicos, nao ha ruido a
        # descontar), enquanto None significa amostra insuficiente pra medir.
        # Colapsar os dois esconderia justamente o caso em que o desconto e'
        # corretamente nulo.
        "desvio": round(desvio_resto, 4) if desvio_resto is not None else None,
        "folga_1o_2o": round(vencedor - segundo, 4),
        "por_contagem": por_contagem,
        "por_destaque": por_destaque,
        "metodo": "contagem" if desconto == por_contagem else "destaque",
    }
