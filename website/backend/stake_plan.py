"""Plano de stake do placar publico, em unidades.

A coluna `profit` das seis tabelas de picks e' lucro com stake de 1 unidade
(settlement.py: GREEN -> odd-1, HALF-WIN -> (odd-1)/2, PUSH -> 0, HALF-LOSS ->
-0.5, RED -> -1). Isso e' a BASE de calculo, nao o plano de aposta: ninguem
aposta a mesma coisa numa entrada simples e num bilhete de quatro pernas.

O placar publico entao anuncia um plano fixo, declarado aqui e em nenhum outro
lugar:

    pick simples (VIP, free, faltas, defesas) ......... 4u
    bilhete combinado (multipla, alavancagem) ......... 1u

Combinada leva 1u pelo motivo de sempre: a variancia de um bilhete e' outra
coisa, e igualar a stake inflaria tanto o lucro nos meses bons quanto o buraco
nos ruins. Faltas e defesas seguem os simples porque sao isso -- uma entrada,
um jogo, um mercado.

DUAS REGRAS PRA NAO QUEBRAR O NUMERO:

1. `profit` e `stake` andam JUNTOS. Multiplicar o lucro pelo peso sem
   multiplicar a stake faria o ROI (lucro/stake) saltar pelo mesmo fator, e o
   site passaria a anunciar um ROI que nao existe.

2. Este arquivo e' a fonte unica. O mesmo numero alimenta /public/results (Home,
   Resultados, Performance) e /suggestions/stats/quick (tela de Picks); com a
   tabela escrita duas vezes, as duas telas passariam a discordar em silencio
   sobre o lucro da IA -- e uma discordancia dessas e' a coisa que mais
   rapidamente derruba a confianca no placar.
"""

STAKE_PADRAO: dict[str, int] = {
    "vip":         4,
    "free":        4,
    "faltas":      4,
    "goleiros":    4,
    "multiplas":   1,
    "alavancagem": 1,
}

# Fonte desconhecida entra com 1u: subestima, nunca infla.
STAKE_FALLBACK = 1


def stake_de(source: str) -> int:
    return STAKE_PADRAO.get(source, STAKE_FALLBACK)


def rotulo_curto() -> str:
    """'4u em picks simples · 1u em múltiplas' · texto que vai pra tela.

    Sai daqui pra que mudar o plano mude a legenda junto. Uma legenda velha
    grudada num numero novo e' pior do que nao ter legenda.
    """
    simples = STAKE_PADRAO["vip"]
    bilhete = STAKE_PADRAO["multiplas"]
    return f"{simples}u em picks simples · {bilhete}u em múltiplas"
