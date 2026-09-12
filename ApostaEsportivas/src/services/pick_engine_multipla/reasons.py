"""Codigos de rejeicao da Multipla V2.

POR QUE CODIGO E NAO FRASE
--------------------------
A pergunta que o usuario faz quando o dia sai sem bilhete nunca e' "o motor
falhou?", e' "por que". Frase livre nao responde isso em escala: nao da' pra
contar quantos dias morreram por odd fora da faixa contra quantos morreram por
correlacao. Codigo da'. E' a mesma escolha ja' feita em `reject_reason` do
motor pre-jogo, e o painel de Auditoria ja' sabe agrupar por ele.

Todo `NO_MULTIPLA_*` responde pelo DIA. Todo `PERNA_*` responde por UM
candidato, e vai pro log de decisao junto com a perna.
"""
from __future__ import annotations

# ---- o dia nao produziu bilhete
NO_MULTIPLA_LOW_SCORE = "NO_MULTIPLA_LOW_SCORE"
NO_MULTIPLA_NEGATIVE_EV = "NO_MULTIPLA_NEGATIVE_EV"
NO_MULTIPLA_NEGATIVE_EDGE = "NO_MULTIPLA_NEGATIVE_EDGE"
NO_MULTIPLA_LOW_PROBABILITY = "NO_MULTIPLA_LOW_PROBABILITY"
NO_MULTIPLA_HIGH_RISK = "NO_MULTIPLA_HIGH_RISK"
NO_MULTIPLA_HIGH_CORRELATION = "NO_MULTIPLA_HIGH_CORRELATION"
NO_MULTIPLA_UNKNOWN_CORRELATION = "NO_MULTIPLA_UNKNOWN_CORRELATION"
NO_MULTIPLA_LOW_DATA_QUALITY = "NO_MULTIPLA_LOW_DATA_QUALITY"
NO_MULTIPLA_LOW_SAMPLE = "NO_MULTIPLA_LOW_SAMPLE"
NO_MULTIPLA_LOW_PROJECTION_MARGIN = "NO_MULTIPLA_LOW_PROJECTION_MARGIN"
NO_MULTIPLA_ODD_BELOW_RANGE = "NO_MULTIPLA_ODD_BELOW_RANGE"
NO_MULTIPLA_ODD_ABOVE_RANGE = "NO_MULTIPLA_ODD_ABOVE_RANGE"
NO_MULTIPLA_HIGH_OVERLAP = "NO_MULTIPLA_HIGH_OVERLAP"
NO_MULTIPLA_WEAK_LEG = "NO_MULTIPLA_WEAK_LEG"
NO_MULTIPLA_INSUFFICIENT_DIVERSIFICATION = "NO_MULTIPLA_INSUFFICIENT_DIVERSIFICATION"

#: Nao ha' nem o que combinar -- menos de duas pernas aprovadas no dia. E'
#: diferente de "as combinacoes eram ruins", e a diferenca importa: uma aponta
#: pro gate da perna, a outra pro gate da combinacao.
NO_MULTIPLA_INSUFFICIENT_CANDIDATES = "NO_MULTIPLA_INSUFFICIENT_CANDIDATES"
NO_MULTIPLA_INSUFFICIENT_COMBINATION_QUALITY = "INSUFFICIENT_COMBINATION_QUALITY"

#: Nenhuma casa cota o bilhete inteiro. Nao e' defeito de qualidade: o bilhete
#: era bom e nao da' pra apostar em lugar nenhum.
NO_MULTIPLA_NO_SINGLE_BOOKMAKER = "NO_MULTIPLA_NO_SINGLE_BOOKMAKER"

# ---- a perna nao entrou no pool
PERNA_EV = "PERNA_EV_NAO_POSITIVO"
PERNA_EDGE = "PERNA_EDGE_ABAIXO_DO_MINIMO"
PERNA_DATA_QUALITY = "PERNA_DATA_QUALITY_BAIXA"
PERNA_SAMPLE = "PERNA_AMOSTRA_INSUFICIENTE"
PERNA_RISCO = "PERNA_RISCO_ALTO"
PERNA_PROB_CALIBRADA = "PERNA_PROB_CALIBRADA_BAIXA"
PERNA_PROJECAO = "PERNA_PROJECAO_SEM_MARGEM"
PERNA_SCORE = "PERNA_SCORE_ABAIXO_DO_MINIMO"

#: Ordem de gravidade, pra quando o dia acumula varios motivos e so' um vai
#: virar a resposta: o primeiro da lista que aparecer manda. Vale o motivo
#: mais ESTRUTURAL (faltou candidato) sobre o mais circunstancial (a odd nao
#: fechou), porque e' esse que diz onde mexer.
ORDEM_DE_GRAVIDADE = (
    NO_MULTIPLA_INSUFFICIENT_CANDIDATES,
    NO_MULTIPLA_HIGH_CORRELATION,
    NO_MULTIPLA_WEAK_LEG,
    NO_MULTIPLA_LOW_SCORE,
    NO_MULTIPLA_NEGATIVE_EV,
    NO_MULTIPLA_LOW_PROBABILITY,
    NO_MULTIPLA_ODD_ABOVE_RANGE,
    NO_MULTIPLA_ODD_BELOW_RANGE,
    NO_MULTIPLA_NO_SINGLE_BOOKMAKER,
    NO_MULTIPLA_HIGH_OVERLAP,
    NO_MULTIPLA_INSUFFICIENT_DIVERSIFICATION,
    NO_MULTIPLA_INSUFFICIENT_COMBINATION_QUALITY,
)


def motivo_dominante(motivos) -> str:
    """O motivo que responde pelo dia, a partir de todos os que apareceram.

    Sem motivo nenhum a resposta e' a generica -- nunca vazio: "nao saiu e nao
    sei dizer por que" e' pior que uma resposta larga.
    """
    vistos = set(motivos or ())
    for codigo in ORDEM_DE_GRAVIDADE:
        if codigo in vistos:
            return codigo
    return NO_MULTIPLA_INSUFFICIENT_COMBINATION_QUALITY
