"""Modelo de faltas (mercados Fouls. Total / Home / Away, bet_id 170/171/173).

Medido contra 946 jogos de PROD (1892 atuacoes de time), 2026-08-01.

POR QUE ESTE MODELO NAO E' PARAMETRICO
--------------------------------------
Diferente de defesas de goleiro, faltas NAO tem distribuicao parametrica que
sirva. Medido na linha Over 22.5 do total do jogo:

    real 57.9%  |  Poisson 51.0% (-7.0pp)  |  BinNegativa 45.6% (-12.3pp)

A Binomial Negativa erra MAIS que o Poisson aqui -- o oposto do que acontece
com defesas. O motivo esta na razao variancia/media: 3.01 por time e 4.82 no
total do jogo, contra 1.80 das defesas. Essa variancia nao e' aleatoriedade
dentro do jogo, e' heterogeneidade ENTRE times e arbitros. Ajustar uma
distribuicao global e' o erro conceitual: a dispersao que ela tenta capturar
e' justamente o que o preditor deveria explicar.

Por isso aqui a estimativa e' da MEDIA condicional (times + arbitro), e a
probabilidade sai da distribuicao empirica condicional, nao de formula
fechada.

O QUE O BACKTEST SUSTENTA (sem lookahead, media so' com jogos anteriores)
-------------------------------------------------------------------------
Total do jogo, agrupado pela previsao (soma da media dos dois times):

    previsto <20    n= 99  reais 19.3  Over 22.5 acerta 43.4%
    previsto 20-22  n= 51  reais 19.9  Over 22.5 acerta 35.3%
    previsto 22-24  n= 60  reais 23.2  Over 22.5 acerta 56.7%
    previsto 24+    n=301  reais 27.0  Over 22.5 acerta 73.4%

A faixa util (24+) cobre 62% dos jogos -- frequencia muito melhor que a de
defesas, onde o recorte bom pegava 0.86% das atuacoes.

CUIDADO COM A CORRELACAO -- DOIS NUMEROS DIFERENTES, NAO COMPARAVEIS
--------------------------------------------------------------------
    0.418  amostra ampla, so' historico dos times
    0.155  subconjunto com historico de arbitro (n=167), so' times
    0.133  mesmo subconjunto, so' arbitro
    0.195  mesmo subconjunto, combinado 60/40

O 0.418 NAO e' o mesmo numero que o 0.155: amostras diferentes. Exigir que o
arbitro ja tenha historico reduz pra 167 jogos e seleciona arbitros
frequentes, um conjunto mais homogeneo, o que comprime a correlacao. O que se
pode afirmar com honestidade e' so' o que foi medido no MESMO recorte: o
arbitro soma sobre os times (0.155 -> 0.195). O nivel absoluto de
previsibilidade e' modesto, e a evidencia mais util pra decisao e' a tabela
de faixas acima, nao a correlacao.

Nao trocar essa tabela por um numero de correlacao ao avaliar o modelo.
"""
from __future__ import annotations

# Peso do historico dos times contra o do arbitro. 60/40 foi o que mediu
# melhor entre as combinacoes testadas; nao e' otimizacao fina, e' a
# proporcao que sustentou o ganho de 0.155 -> 0.195.
PESO_TIMES = 0.60
PESO_ARBITRO = 0.40

# Medias da base, usadas como prior quando falta um dos lados.
MEDIA_FALTAS_TIME = 11.39
MEDIA_FALTAS_JOGO = 22.78

# Minimo de jogos pra confiar em cada historico. O de arbitro e' menor
# porque arbitro apita menos que time joga -- exigir 5 descartaria quase
# todos (so' 30 arbitros passam de 6 jogos na base atual).
MIN_JOGOS_TIME = 5
MIN_JOGOS_ARBITRO = 4


def expected_fouls(media_casa: float | None,
                   media_fora: float | None,
                   media_arbitro: float | None = None,
                   n_casa: int | None = None,
                   n_fora: int | None = None,
                   n_arbitro: int | None = None) -> float | None:
    """Faltas esperadas no jogo inteiro.

    media_casa/media_fora: faltas por jogo que cada time comete, no
    historico. media_arbitro: total de faltas por jogo nos jogos que esse
    arbitro apitou.

    Retorna None se nenhum lado tiver amostra suficiente -- nunca chuta a
    media da liga como se fosse previsao.
    """
    times_ok = (media_casa is not None and media_fora is not None
                and (n_casa or 0) >= MIN_JOGOS_TIME and (n_fora or 0) >= MIN_JOGOS_TIME)
    arbitro_ok = media_arbitro is not None and (n_arbitro or 0) >= MIN_JOGOS_ARBITRO

    if not times_ok and not arbitro_ok:
        return None
    if times_ok and not arbitro_ok:
        return round(media_casa + media_fora, 2)
    if arbitro_ok and not times_ok:
        return round(media_arbitro, 2)
    return round((media_casa + media_fora) * PESO_TIMES + media_arbitro * PESO_ARBITRO, 2)


# Faixas medidas no backtest: previsao -> taxa real de Over 22.5.
# Empirico de proposito (ver docstring). Cada tupla e' (limite_superior,
# taxa, n) -- o n fica pra quem for reavaliar saber o peso de cada faixa.
_FAIXAS_OVER_225 = [
    (20.0, 0.434,  99),
    (22.0, 0.353,  51),
    (24.0, 0.567,  60),
    (999.0, 0.734, 301),
]


def prob_over_225(previsto: float | None) -> tuple[float, int] | None:
    """P(faltas totais > 22.5) e o n da faixa, pela tabela empirica.

    Devolve tambem o n porque uma faixa de 51 jogos nao merece a mesma
    confianca que uma de 301 -- quem consome decide o que fazer com isso.
    """
    if previsto is None:
        return None
    for limite, taxa, n in _FAIXAS_OVER_225:
        if previsto < limite:
            return taxa, n
    return None


def analyze_fouls_market(media_casa: float | None, media_fora: float | None,
                         media_arbitro: float | None = None,
                         n_casa: int | None = None, n_fora: int | None = None,
                         n_arbitro: int | None = None,
                         odd: float | None = None) -> dict | None:
    """Candidato de pick de faltas totais na linha 22.5, ou None.

    So' cobre Over 22.5 por enquanto: e' a unica linha com faixa medida no
    backtest. Outras linhas exigem refazer a tabela empirica pra cada uma --
    nao da' pra interpolar, porque a relacao nao e' parametrica.
    """
    previsto = expected_fouls(media_casa, media_fora, media_arbitro,
                              n_casa, n_fora, n_arbitro)
    faixa = prob_over_225(previsto)
    if faixa is None:
        return None
    prob, n_faixa = faixa

    resultado = {
        "line": 22.5,
        "expected_fouls": previsto,
        "probability": prob,
        "fair_odd": round(1 / prob, 3),
        "faixa_amostra": n_faixa,
        "usou_arbitro": media_arbitro is not None and (n_arbitro or 0) >= MIN_JOGOS_ARBITRO,
    }
    if odd is not None and odd > 1:
        resultado["odd"] = float(odd)
        resultado["edge"] = round(prob - 1 / float(odd), 4)
        resultado["ev"] = round(prob * (float(odd) - 1) - (1 - prob), 4)
    return resultado
