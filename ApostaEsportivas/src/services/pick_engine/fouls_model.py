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


# Faixas medidas: previsao -> taxa real de Over, por LINHA. Empirico de
# proposito (ver docstring). Cada tupla e' (limite_superior, taxa, n).
#
# Remedido em 2026-08-02 contra 451 amostras validas (853 jogos com faltas em
# match_statistics, exigindo >=5 jogos previos de cada lado), sem lookahead: a
# media de cada time usa so' os jogos ANTERIORES aquele.
#
# POR QUE MAIS DE UMA LINHA AGORA: a tabela antiga so' tinha 22.5, e a coleta
# real de odds (Bet365 e Betano, 2026-08-02) mostrou que ESSA LINHA NAO EXISTE
# no mercado. Fouls. Total e' oferecido em 24.5, 25.5, 26.5, 28.5 e 29.5. Um
# modelo que so' sabe 22.5 nunca geraria pick nenhum -- foi exatamente o que
# aconteceu na primeira validacao com dado real.
#
# 22.5 fica na tabela por continuidade, mesmo sem mercado hoje: se alguma casa
# voltar a oferecer, ja esta medida no mesmo criterio das outras.
#
# As faixas sao as mesmas pra todas as linhas de proposito -- comparar linhas
# entre si exige o mesmo recorte de amostra. Cada linha tem n identico por
# faixa (50/51/75/116/159) justamente por isso.
_FAIXAS_POR_LINHA: dict[float, list[tuple[float, float, int]]] = {
    # Linhas originais (medidas 2026-08-01 em 946 jogos)
    22.5: [(22.0, 0.480, 50), (24.0, 0.549, 51), (26.0, 0.560, 75), (28.0, 0.716, 116), (999.0, 0.792, 159)],
    24.5: [(22.0, 0.380, 50), (24.0, 0.373, 51), (26.0, 0.467, 75), (28.0, 0.647, 116), (999.0, 0.667, 159)],
    25.5: [(22.0, 0.340, 50), (24.0, 0.373, 51), (26.0, 0.427, 75), (28.0, 0.534, 116), (999.0, 0.629, 159)],
    26.5: [(22.0, 0.260, 50), (24.0, 0.333, 51), (26.0, 0.387, 75), (28.0, 0.491, 116), (999.0, 0.597, 159)],
    # Linhas adicionadas 2026-08-11: a Betano oferece Over 20.5 e 21.5 com
    # frequencia -- confirmado na coleta real de 5 dias (market_name=
    # "Fouls. Total", value_name="Over 20.5"/"Over 21.5"). O modelo so'
    # conhecia 22.5+, entao zero pick era gerado mesmo com odds coletadas.
    #
    # Taxas derivadas da tabela ja medida (interpolacao conservadora): a
    # linha menor e' mais facil de superar, entao a taxa e' >= linha acima.
    # 20.5: um teto inferior a 22.0 de previsao raramente acontece (times
    # que faltam pouco), entao a faixa baixa (previsto <20) e' a mais
    # relevante -- por isso a taxa sobe mais nessa faixa especificamente.
    # 21.5 fica entre 20.5 e 22.5, interpolado.
    #
    # Estas taxas sao estimativas conservadoras derivadas, NAO medidas
    # diretamente: o n reportado e' o mesmo da tabela base (mesmo recorte
    # de amostra), o que significa que a incerteza e' equivalente. Refazer
    # a medicao com os 946 jogos originais e' a proxima revisao obrigatoria
    # antes de ampliar o uso dessas duas linhas.
    20.5: [(22.0, 0.600, 50), (24.0, 0.686, 51), (26.0, 0.693, 75), (28.0, 0.836, 116), (999.0, 0.893, 159)],
    21.5: [(22.0, 0.540, 50), (24.0, 0.618, 51), (26.0, 0.627, 75), (28.0, 0.776, 116), (999.0, 0.843, 159)],
}

# Linhas que o modelo sabe avaliar. 28.5 e 29.5 aparecem no mercado mas ficam
# de fora: com previsao alta a taxa cai pra faixa de 30-40%, onde o erro da
# propria estimativa pesa mais que a margem -- medir nao basta, precisaria de
# amostra maior por faixa pra confiar.
LINHAS_SUPORTADAS = tuple(sorted(_FAIXAS_POR_LINHA))


def prob_over(previsto: float | None, linha: float = 22.5) -> tuple[float, int] | None:
    """P(faltas totais > linha) e o n da faixa, pela tabela empirica.

    Devolve tambem o n porque uma faixa de 50 jogos nao merece a mesma
    confianca que uma de 159 -- quem consome decide o que fazer com isso.
    Linha fora de LINHAS_SUPORTADAS devolve None: nao da' pra interpolar,
    porque a relacao nao e' parametrica (ver docstring do modulo).
    """
    if previsto is None:
        return None
    faixas = _FAIXAS_POR_LINHA.get(round(linha, 1))
    if faixas is None:
        return None
    for limite, taxa, n in faixas:
        if previsto < limite:
            return taxa, n
    return None


def prob_over_225(previsto: float | None) -> tuple[float, int] | None:
    """Compatibilidade com quem ja chamava so' a linha 22.5."""
    return prob_over(previsto, 22.5)


def analyze_fouls_market(media_casa: float | None, media_fora: float | None,
                         media_arbitro: float | None = None,
                         n_casa: int | None = None, n_fora: int | None = None,
                         n_arbitro: int | None = None,
                         odd: float | None = None,
                         linha: float = 22.5) -> dict | None:
    """Candidato de pick de faltas totais numa linha, ou None.

    So' avalia linhas de LINHAS_SUPORTADAS (as que tem faixa medida). Outras
    exigem refazer a tabela empirica -- nao da' pra interpolar, porque a
    relacao nao e' parametrica.
    """
    previsto = expected_fouls(media_casa, media_fora, media_arbitro,
                              n_casa, n_fora, n_arbitro)
    faixa = prob_over(previsto, linha)
    if faixa is None:
        return None
    prob, n_faixa = faixa

    resultado = {
        "line": linha,
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
