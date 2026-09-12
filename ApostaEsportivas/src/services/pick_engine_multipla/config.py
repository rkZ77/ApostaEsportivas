"""Limiares, pesos e faixas da Multipla V2.

TUDO QUE DECIDE ESTA AQUI, e nada aqui decide sozinho: os numeros sao
PONTO DE PARTIDA declarado, nao verdade medida. Cada um existe pra poder ser
movido por backtest sem abrir o motor -- e pra que, quando um dia for movido,
o commit mostre UM numero mudando e nao uma regra escondida dentro de um `if`.

O QUE A V2 MUDA EM RELACAO AO QUE ESTAVA AQUI ANTES
---------------------------------------------------
A V1 nao tinha config: tinha duas constantes no topo do pipeline
(ODD_TOTAL_MIN/MAX) e um teto de bilhetes por dia. O criterio de escolha era
`prob_combinada` com desempate por media de final_score, e o teto de bilhetes
era um numero fixo -- 8 num dia de 3 jogos e 8 num dia de 40.

Na V2 o teto passa a ser FUNCAO DA OFERTA (TETO_POR_JOGOS_ELEGIVEIS) e o
criterio passa a ser um score composto com peso declarado (PESOS_COMPONENTE,
PESOS_COMBINACAO). Maximo nao e' meta: o teto diz quantos bilhetes o dia PODE
publicar, nunca quantos ele DEVE.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------- FAIXA DE ODD
#
# 2.00-3.00 e' a faixa PADRAO pedida em 11/09/2026, e ela APERTA o que estava
# em producao (2.00-4.00 desde 21/07). O motivo do teto largo esta registrado
# no pipeline e continua real: num dia magro, o menor produto possivel entre
# duas pernas de jogos diferentes ja' passava de 3.00 (1.82 x 1.85 = 3.37) e a
# multipla nao saia. A V2 pode apertar sem repetir aquele dia inteiro sem
# bilhete por uma razao concreta: o pool nao e' mais "uma linha por jogo" --
# cada fixture contribui com o elegivel inteiro, entao existem pernas baratas
# (1.40-1.55) que a V1 daquela epoca nem via. Se a medicao mostrar que a faixa
# apertada zera dias demais, o teto volta pra 3.50/4.00 AQUI, numa linha.
ODD_TOTAL_MIN = 2.00
ODD_TOTAL_MAX = 3.00

#: Modo agressivo: so' existe pra ser ligado de fora, e por padrao nao esta'.
#: Odd acima da faixa nao e' qualidade -- e' a mesma aposta com menos chance.
ODD_TOTAL_MAX_AGRESSIVO = 4.00

#: Sub-faixas usadas SO' pra relatorio/backtest (nao filtram nada).
FAIXAS_DE_ODD = ((2.00, 2.20), (2.20, 2.40), (2.40, 2.60), (2.60, 2.80), (2.80, 3.00))


# ------------------------------------------------------- QUANTOS BILHETES O DIA
#
# O teto cresce com a OFERTA, nao com a vontade de publicar. Jogo elegivel e'
# jogo que entregou pelo menos uma perna aprovada no gate individual -- nao e'
# jogo do dia, nem jogo lido: um dia de 40 partidas sem perna aprovada tem
# teto 1 igual a um dia de 3.
TETO_POR_JOGOS_ELEGIVEIS = (
    (31, 5),
    (21, 4),
    (11, 3),
    (6,  2),
    (1,  1),
)

#: Rede de seguranca, identica em espirito a MAX_PICKS_POR_RODADA do Player
#: Stats: uma falha de calibragem nao pode publicar o dia inteiro de uma vez.
TETO_ABSOLUTO_POR_DIA = 5


# ------------------------------------------------------------ PERNAS POR BILHETE
TAMANHOS_PERMITIDOS = (2, 3)      # 4+ so' em modo especial, ver TAMANHO_MAXIMO_ESPECIAL
TAMANHO_MAXIMO_ESPECIAL = 4

#: Bilhete de 3 pernas so' concorre quando TODAS as pernas sao fortes. Duas
#: pernas boas e uma mediana e' o desenho classico de bilhete que perde: a
#: multipla so' paga se todas baterem, entao a perna fraca e' que manda.
MIN_LEG_SCORE_PARA_TRIPLA = 0.70


# ----------------------------------------------------------- GATE DA PERNA (S11)
#
# Estes gates vem DEPOIS dos gates do motor (rank_all_candidates ja' cobrou
# taxa>=0.60, edge>=0.05, EV>0, confidence>=0.55, amostra>=4 de todo candidato
# que chega aqui). O que se cobra a mais e' o que a multipla precisa e a pick
# simples nao: uma perna de bilhete erra por TODAS as outras juntas.
MIN_EV_PERNA = 0.0                # estritamente positivo
MIN_EDGE_PERNA = 0.05
MIN_DATA_QUALITY = 0.50
MIN_SAMPLE_QUALITY = 0.30
MIN_PROB_CALIBRADA = 0.58         # abaixo do piso cru (0.60) de proposito: a
                                  # calibracao so' DESCE, e cobrar 0.60 depois
                                  # dela seria cobrar 0.60 duas vezes.
RISCO_MAXIMO_PERNA = "MEDIO"      # ALTO fica fora. Ordem: BAIXO < MEDIO < ALTO
MIN_LEG_SCORE = 0.60              # regra do elo mais fraco

#: Projecao em cima da linha (ou contra ela) nao vira perna de bilhete. Nas
#: familias sem projecao (btts, resultado, handicap) o campo e' None e isso e'
#: NEUTRO -- ausencia de dado nunca vira confirmacao.
CLASSES_DE_PROJECAO_REPROVADAS = ("contra_a_linha", "em_cima_da_linha")
CLASSE_DE_PROJECAO_PENALIZADA = "apertada"


# ------------------------------------------------------------------- AMOSTRA
#
# (piso, rotulo, fator de qualidade 0-1). O fator e' o que entra no score; o
# rotulo e' o que o log mostra.
CLASSES_DE_AMOSTRA = (
    (30, "FORTE",        1.00),
    (20, "BOA",          0.85),
    (10, "RAZOAVEL",     0.65),
    (5,  "LIMITADA",     0.40),
    (0,  "INSUFICIENTE", 0.15),
)

#: Peso do encolhimento em direcao ao limite inferior de Wilson, por classe de
#: amostra. Amostra forte quase nao encolhe; amostra limitada encolhe metade
#: do caminho ate' o pior caso que o intervalo admite.
ENCOLHIMENTO_POR_CLASSE = {
    "FORTE": 0.05,
    "BOA": 0.15,
    "RAZOAVEL": 0.30,
    "LIMITADA": 0.50,
    "INSUFICIENTE": 0.70,
}

#: Quando nao ha' intervalo de Wilson (familia que nao nasce de contagem
#: binomial), o encolhimento vira um desconto chapado sobre a probabilidade,
#: proporcional a classe. Menor que o de Wilson de proposito: sem intervalo
#: nao se sabe o quanto descontar, e chutar alto tambem e' chutar.
DESCONTO_SEM_WILSON = {
    "FORTE": 0.00,
    "BOA": 0.01,
    "RAZOAVEL": 0.02,
    "LIMITADA": 0.04,
    "INSUFICIENTE": 0.06,
}


# -------------------------------------------------------- SCORE DA PERNA
PESOS_COMPONENTE = {
    "prob_calibrada": 0.25,
    "ev":             0.20,
    "edge":           0.15,
    "data_quality":   0.15,
    "sample_quality": 0.10,
    "convergence":    0.10,
    "risco":          0.05,
}

#: Normalizadores das parcelas que nao nascem em 0-1. EV de +25% e edge de
#: +20pp saturam o topo: acima disso o numero costuma ser erro de estimativa,
#: nao qualidade (ver a regra "valor estatistico, nao odd desalinhada").
EV_SATURA_EM = 0.25
EDGE_SATURA_EM = 0.20

#: Probabilidade calibrada normalizada entre estes dois pontos. 0.50 e' moeda
#: jogada pro alto; 0.85 e' o teto pratico de qualquer perna do motor.
PROB_PISO_ESCALA = 0.50
PROB_TETO_ESCALA = 0.85

RISCO_PARA_NOTA = {"BAIXO": 1.0, "MEDIO": 0.5, "ALTO": 0.0}


# ---------------------------------------------------- SCORE DA COMBINACAO
PESOS_COMBINACAO = {
    "elo_mais_fraco":   0.30,   # a perna pior manda no bilhete
    "media_das_pernas": 0.25,
    "prob_combinada":   0.20,
    "diversificacao":   0.15,
    "correlacao":       0.10,
}

MIN_COMBINATION_SCORE = 0.65

#: Probabilidade combinada normalizada. 0.35 e' o piso pratico de um bilhete
#: de 2 pernas na faixa 2.00-3.00 (0.59 x 0.59); 0.60 e' um bilhete excelente.
PROB_COMBINADA_PISO_ESCALA = 0.35
PROB_COMBINADA_TETO_ESCALA = 0.60

FAIXAS_DE_SCORE = (
    (0.80, "EXCELENTE"),
    (0.75, "MUITO_BOA"),
    (0.70, "BOA"),
    (0.65, "ACEITAVEL"),
)


# ------------------------------------------------------------ CORRELACAO
#
# Penalidade aplicada a probabilidade do PRODUTO, em fracao. O produto assume
# independencia; quando ha' dependencia positiva na direcao "o mesmo jogo
# abriu", o produto e' CONSERVADOR e nao ha' o que descontar. O desconto
# existe pro caso anti-conservador e pro desconhecido.
PENALIDADE_CORRELACAO = {
    "LOW": 0.00,
    "MEDIUM": 0.03,
    "UNKNOWN": 0.05,
    "HIGH": 1.00,   # bloqueia: combo com HIGH nem chega a ser pontuado
}

NOTA_CORRELACAO = {"LOW": 1.0, "MEDIUM": 0.6, "UNKNOWN": 0.35, "HIGH": 0.0}

#: Duas pernas do mesmo jogo continuam tecnicamente possiveis (familias
#: diferentes), mas UMA por jogo e' o padrao pedido em 11/09: o bilhete de
#: mesmo jogo multiplica duas odds que nao sao independentes.
MAX_PERNAS_MESMO_JOGO = 1
MAX_PERNAS_MESMO_TIME = 1


# ------------------------------------------------------------- PORTFOLIO
#
# Perna usada num bilhete sai do pool do proximo. Reuso e' EXCECAO: dois
# bilhetes que dividem uma perna nao sao duas apostas, sao uma aposta com o
# dobro da exposicao -- o RED daquela perna derruba os dois juntos.
MAX_REUSO_DA_PERNA_NO_DIA = 1
MAX_REUSO_EXCEPCIONAL = 2
SCORE_PARA_REUSO_EXCEPCIONAL = 0.85
PENALIDADE_DE_REUSO = 0.10

#: Quantos bilhetes do dia podem tocar o MESMO jogo. Acima disso o dia inteiro
#: passa a depender de uma partida so'.
LIMITE_DE_EXPOSICAO_POR_JOGO = 2

#: Quantos bilhetes do dia podem ser dominados pela MESMA familia de mercado
#: (bilhete "so' de gols" tres vezes). Nao proibe: limita.
LIMITE_DE_EXPOSICAO_POR_FAMILIA = 2


@dataclass(frozen=True)
class MultiplaConfig:
    """A configuracao de UMA execucao. `padrao()` e' o que a producao usa.

    Existe como dataclass (e nao so' como constantes de modulo) porque o
    backtest precisa rodar varias configuracoes na mesma sessao -- comparar
    faixa de odd, teto de bilhetes e piso de score sem reimportar o modulo.
    """
    odd_total_min: float = ODD_TOTAL_MIN
    odd_total_max: float = ODD_TOTAL_MAX
    modo_agressivo: bool = False

    tamanhos: tuple = TAMANHOS_PERMITIDOS
    permitir_quatro_pernas: bool = False

    min_ev_perna: float = MIN_EV_PERNA
    min_edge_perna: float = MIN_EDGE_PERNA
    min_data_quality: float = MIN_DATA_QUALITY
    min_sample_quality: float = MIN_SAMPLE_QUALITY
    min_prob_calibrada: float = MIN_PROB_CALIBRADA
    min_leg_score: float = MIN_LEG_SCORE
    risco_maximo: str = RISCO_MAXIMO_PERNA

    min_combination_score: float = MIN_COMBINATION_SCORE
    teto_absoluto: int = TETO_ABSOLUTO_POR_DIA
    max_reuso_da_perna: int = MAX_REUSO_DA_PERNA_NO_DIA
    max_pernas_mesmo_jogo: int = MAX_PERNAS_MESMO_JOGO
    max_pernas_mesmo_time: int = MAX_PERNAS_MESMO_TIME
    limite_exposicao_por_jogo: int = LIMITE_DE_EXPOSICAO_POR_JOGO
    limite_exposicao_por_familia: int = LIMITE_DE_EXPOSICAO_POR_FAMILIA

    pesos_componente: dict = field(default_factory=lambda: dict(PESOS_COMPONENTE))
    pesos_combinacao: dict = field(default_factory=lambda: dict(PESOS_COMBINACAO))

    @property
    def teto_de_odd(self) -> float:
        return ODD_TOTAL_MAX_AGRESSIVO if self.modo_agressivo else self.odd_total_max

    @property
    def tamanhos_permitidos(self) -> tuple:
        if self.permitir_quatro_pernas:
            return tuple(self.tamanhos) + (TAMANHO_MAXIMO_ESPECIAL,)
        return tuple(self.tamanhos)


def padrao() -> MultiplaConfig:
    return MultiplaConfig()


def teto_de_multiplas(jogos_elegiveis: int, cfg: MultiplaConfig | None = None) -> int:
    """Quantos bilhetes o dia PODE publicar -- nunca quantos deve.

    Jogo elegivel e' jogo com pelo menos uma perna aprovada no gate individual.
    """
    cfg = cfg or padrao()
    if jogos_elegiveis <= 0:
        return 0
    for piso, teto in TETO_POR_JOGOS_ELEGIVEIS:
        if jogos_elegiveis >= piso:
            return min(teto, cfg.teto_absoluto)
    return 0


def faixa_de_score(score: float) -> str:
    for piso, rotulo in FAIXAS_DE_SCORE:
        if score >= piso:
            return rotulo
    return "REJEITADA"
