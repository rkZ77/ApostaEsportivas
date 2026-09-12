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
# 4 desde 2026-08-28 · piso unico de amostra pra todos os pipelines (2 em
# casa e 2 fora, entao a 5a rodada ja' produz). O do ARBITRO ja' era 4.
MIN_JOGOS_TIME = 4
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


def prob_over(previsto: float | None, linha: float = 22.5,
              faixas: dict | None = None) -> tuple[float, int] | None:
    """P(faltas totais > linha) e o n da faixa, pela tabela empirica.

    Devolve tambem o n porque uma faixa de 50 jogos nao merece a mesma
    confianca que uma de 159 -- quem consome decide o que fazer com isso.
    Linha fora das linhas da tabela devolve None: nao da' pra interpolar,
    porque a relacao nao e' parametrica (ver docstring do modulo).

    `faixas` permite injetar uma tabela RECALIBRADA no lugar da congelada
    (2026-08-16, ver services/pick_engine/fouls_calibration.py). Mesmo formato:
    {linha: [(limite_superior, taxa, n), ...]}. None usa a congelada, que
    continua sendo o comportamento de quem chama sem saber que isso existe --
    inclusive todos os testes que travam os numeros medidos em 01/08.
    """
    if previsto is None:
        return None
    tabela = _FAIXAS_POR_LINHA if faixas is None else faixas
    faixas_da_linha = tabela.get(round(linha, 1))
    if faixas_da_linha is None:
        return None
    for limite, taxa, n in faixas_da_linha:
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
                         linha: float = 22.5,
                         faixas: dict | None = None) -> dict | None:
    """Candidato de pick de faltas totais numa linha, ou None.

    So' avalia linhas que a tabela conhece (as que tem faixa medida). Outras
    exigem refazer a tabela empirica -- nao da' pra interpolar, porque a
    relacao nao e' parametrica.

    `faixas` injeta uma tabela recalibrada; None usa a congelada. Ver prob_over.
    """
    previsto = expected_fouls(media_casa, media_fora, media_arbitro,
                              n_casa, n_fora, n_arbitro)
    faixa = prob_over(previsto, linha, faixas=faixas)
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


# ---------------------------------------------------------------------------
# RECENCIA (2026-09-11) · media ponderada por quao recente e' o jogo
# ---------------------------------------------------------------------------
# Ate' aqui a media de faltas de um time era media SIMPLES de todo o historico:
# o jogo da primeira rodada pesava igual ao de ontem. Faltas e' justamente o
# mercado onde isso incomoda -- estilo de marcacao, tecnico e escalacao mudam
# dentro da temporada, e o proprio pipeline ja' respeita
# `get_structural_change_date` por reconhecer isso.
#
# Os pesos sao TIERED e nao exponenciais de proposito: exponencial tem uma
# constante de decaimento que ninguem mediu, tier reproduz a pergunta que o
# usuario faz ("ultimos 5 contra ultimos 10 contra o resto") e e' auditavel
# olhando a lista de jogos.
#
# O PESO E' POR JOGO, NAO POR BLOCO -- e essa distincao nao e' estetica, foi
# um bug de verdade na primeira versao disto. Com peso de BLOCO ("ultimos 5
# valem 45%, os 5 anteriores 30%, o resto 25%") um time com 11 jogos dava 25%
# do total ao UNICO jogo mais antigo da serie, enquanto cada jogo recente valia
# 9%. Numa serie crescente (10, 11, ... 20) a media "ponderada por recencia"
# saia 14.5 contra 15.0 da media simples: o peso de recencia estava puxando
# pra TRAS. Peso por jogo nao tem como fazer isso -- cada jogo antigo vale
# exatamente um terco de um recente, independente de quantos existam.
#
# ESTES PESOS NAO SAO DEFINITIVOS. Sao ponto de partida pra medicao (Parte D de
# scripts/medir_faltas_mando_e_pressao.py). Enquanto a medicao nao existir o
# pipeline roda com USAR_RECENCIA=False -- ver o comentario la'.
PESOS_RECENCIA = ((5, 3.0), (10, 2.0), (None, 1.0))


def media_ponderada(valores: list[float]) -> float | None:
    """Media de faltas com os jogos recentes pesando mais.

    `valores` vem em ordem CRONOLOGICA (mais antigo primeiro) -- e' a ordem que
    tanto o historico do pipeline quanto a calibragem produzem. Cada um dos 5
    jogos mais recentes pesa 3, cada um dos 5 anteriores pesa 2 e cada jogo mais
    antigo pesa 1. Ver o comentario de PESOS_RECENCIA pro motivo de o peso ser
    por jogo e nao por bloco.

    Com 10 jogos ou menos nenhum jogo cai no terceiro tier, entao a diferenca
    pra media simples vem so' da separacao 5/5 -- que e' o comportamento certo:
    um time com pouco historico nao tem passado remoto pra descontar.
    """
    if not valores:
        return None
    recentes = list(reversed(valores))  # mais novo primeiro
    soma = peso_total = 0.0
    inicio = 0
    for corte, peso in PESOS_RECENCIA:
        fim = len(recentes) if corte is None else min(corte, len(recentes))
        for v in recentes[inicio:fim]:
            soma += v * peso
            peso_total += peso
        inicio = fim
    if not peso_total:
        return None
    return round(soma / peso_total, 3)


# ---------------------------------------------------------------------------
# QUALIDADE DA AMOSTRA E DA EVIDENCIA (2026-09-11)
# ---------------------------------------------------------------------------
# O motor gravava `confidence` = probabilidade CRUA da tabela empirica. Duas
# coisas erradas nisso:
#
#   1. a taxa da faixa foi medida em 50 a 159 jogos -- 0.716 medido em 116
#      jogos tem erro padrao de ~4pp, e isso nunca aparecia em lugar nenhum;
#   2. um pick com 10 jogos de historico por time saia com a MESMA confianca
#      de um com 25, embora o erro da projecao seja quase o dobro (ver
#      _ERRO_POR_AMOSTRA em faltas_pipeline).
#
# `pick_score` ja' usava o n da faixa pra ORDENAR, mas a confianca publicada e o
# stake continuavam lendo a taxa crua. Aqui a evidencia fraca encolhe a
# probabilidade em direcao a' taxa base da linha (a media de todas as faixas
# daquela linha), que e' o que sobra quando a previsao nao merece credito.
QUALIDADE_AMOSTRA = ((5, "insuficiente"), (8, "baixa"), (13, "moderada"),
                     (21, "boa"), (None, "forte"))


def qualidade_da_amostra(n: int) -> str:
    for corte, rotulo in QUALIDADE_AMOSTRA:
        if corte is None or n < corte:
            return rotulo
    return "forte"


def taxa_base(linha: float, faixas: dict | None = None) -> float | None:
    """Taxa media da linha entre todas as faixas, ponderada pelo n de cada uma.

    E' o alvo do encolhimento: a resposta honesta pra "Over nesta linha bate
    com que frequencia?" quando a previsao especifica do jogo nao e' confiavel.
    """
    tabela = _FAIXAS_POR_LINHA if faixas is None else faixas
    celulas = tabela.get(round(linha, 1))
    if not celulas:
        return None
    total = sum(n for _, _, n in celulas)
    if not total:
        return None
    return sum(taxa * n for _, taxa, n in celulas) / total


def probabilidade_calibrada(prob: float, linha: float, n_time: int,
                            n_faixa: int, margem: float, exigido: float,
                            faixas: dict | None = None) -> tuple[float, dict]:
    """Probabilidade encolhida pela qualidade da evidencia, e o porque.

    Tres fatores, todos em [0,1], multiplicados -- basta um ser fraco pra o
    pick perder confianca, que e' a regra de "um unico indicador nao libera
    aposta":

        amostra  historico dos times. Satura em 20 jogos (onde o erro da
                 projecao ja' caiu pra ~0.6 falta) e vale 0.5 no piso de 10.
        faixa    n da celula da tabela empirica. Satura no maior n medido.
        margem   quanto a projecao passa do minimo exigido pelo proprio erro
                 de amostragem. Colado no limite (margem == exigido) vale 0.6;
                 dobro da folga vale 1.0. Projecao encostada na linha e' moeda
                 ao ar mesmo com EV positivo.

    O encolhimento e' em direcao a `taxa_base`, nunca em direcao a zero: a
    linha continua tendo a frequencia historica dela.
    """
    base = taxa_base(linha, faixas)
    if base is None:
        return round(prob, 4), {"peso": 1.0, "base": None}

    f_amostra = min(1.0, 0.5 + 0.5 * max(0, n_time - 10) / 10)
    f_faixa = min(1.0, (n_faixa or 0) / 159)
    folga = (margem - exigido) / exigido if exigido > 0 else 1.0
    f_margem = max(0.6, min(1.0, 0.6 + 0.4 * folga))

    peso = round(f_amostra * f_faixa * f_margem, 4)
    calibrada = round(base + (prob - base) * peso, 4)
    return calibrada, {
        "peso": peso, "base": round(base, 4),
        "fator_amostra": round(f_amostra, 3),
        "fator_faixa": round(f_faixa, 3),
        "fator_margem": round(f_margem, 3),
    }


def data_quality_score(n_casa: int, n_fora: int, n_faixa: int,
                       usou_arbitro: bool, n_arbitro: int | None) -> int:
    """0-100. Quantidade e procedencia do que alimentou a decisao.

    Nao inclui odd nem edge de proposito: preco nao e' dado de entrada do
    modelo, e misturar os dois faria odd generosa parecer dado bom.
    """
    n_time = min(n_casa or 0, n_fora or 0)
    score = 40 * min(1.0, max(0, n_time - 4) / 16)          # 4 -> 0, 20 -> 40
    # A escala comeca em 4 (MIN_JOGOS_TIME) e nao no piso de 10 do pipeline de
    # proposito: este score descreve o dado, nao repete o gate. Um pick no piso
    # tira 50 aqui, e 50 e' uma descricao honesta de "10 jogos por time, sem
    # arbitro" -- nao e' nota de reprovacao.
    score += 35 * min(1.0, (n_faixa or 0) / 159)
    score += 15 if usou_arbitro else 0
    score += 10 * min(1.0, (n_arbitro or 0) / 12)
    return int(round(score))
