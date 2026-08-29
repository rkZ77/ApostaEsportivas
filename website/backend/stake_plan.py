"""Plano de stake do placar publico, em unidades.

A coluna `profit` das seis tabelas de picks e' lucro com stake de 1 unidade
(settlement.py: GREEN -> odd-1, HALF-WIN -> (odd-1)/2, PUSH -> 0, HALF-LOSS ->
-0.5, RED -> -1). Isso e' a BASE de calculo, nao o plano de aposta: ninguem
aposta a mesma coisa numa entrada simples e num bilhete de quatro pernas.

O placar publico entao anuncia um plano fixo, declarado aqui e em nenhum outro
lugar:

    VIP ................................................ 4u
    free, faltas, defesas, player stats, ao vivo ........ 3u
    pick boost ......................................... 2u
    multipla ........................................... 1u
    alavancagem ........................................ nao entra

O VIP fica um degrau acima porque e' o produto de maior convicção do motor: e'
onde o filtro e' mais duro e onde a assinatura e' cobrada. Free, faltas e
defesas sao entrada simples tambem (um jogo, um mercado), mas entram um degrau
abaixo -- sao vitrine, e o placar publico nao deve pesar vitrine igual ao
produto pago.

Combinada leva 1u pelo motivo de sempre: a variancia de um bilhete e' outra
coisa, e igualar a stake inflaria tanto o lucro nos meses bons quanto o buraco
nos ruins.

POR QUE A ALAVANCAGEM VALE ZERO AQUI (decisao do usuario, 2026-08-19)
---------------------------------------------------------------------
Ela nao e' um pick que se liquida em unidade: e' um CAMINHO. O bilhete em
andamento nao e' dinheiro, o resultado so' vira unidade quando o caminho
encerra, e o RED custa so' a entrada -- essa conta ja existe e mora em
`alavancagem_series` (banca.py::_alav_unidades), na banca de quem de fato
apostou. Somar o `profit` dela no placar publico contava a mesma coisa por uma
regra que nao e' a dela.

Peso zero, e nao remocao da fonte, de proposito: a alavancagem CONTINUA
aparecendo no historico publico, com o resultado dela, na quebra por fonte e na
taxa de acerto. O que ela deixa de fazer e' mover o lucro e o ROI em unidades.
Tirar do UNION apagaria o produto da tela.

DUAS REGRAS PRA NAO QUEBRAR O NUMERO:

1. `profit` e `stake` andam JUNTOS. Multiplicar o lucro pelo peso sem
   multiplicar a stake faria o ROI (lucro/stake) saltar pelo mesmo fator, e o
   site passaria a anunciar um ROI que nao existe. Vale pro zero tambem: a
   alavancagem some das DUAS somas, entao o ROI nao e' diluido por uma stake
   que nao rendeu.

2. Este arquivo e' a fonte unica. O mesmo numero alimenta /public/results (Home,
   Resultados, Performance) e /suggestions/stats/quick (tela de Picks); com a
   tabela escrita duas vezes, as duas telas passariam a discordar em silencio
   sobre o lucro da IA -- e uma discordancia dessas e' a coisa que mais
   rapidamente derruba a confianca no placar.

   O front tem um espelho em frontend/src/utils/stakePlan.ts, porque o card de
   pick precisa do numero antes de qualquer resposta do backend. Ele nao e' uma
   segunda fonte: test_unidades_e_odd_2026_08.py compara os dois e quebra se
   divergirem.
"""

STAKE_PADRAO: dict[str, int] = {
    "vip":         4,
    "free":        3,
    "faltas":      3,
    "goleiros":    3,
    # Player Stats (27/08) herda o peso de `goleiros`: e' o mesmo produto, o
    # mesmo formato de entrada (um jogo, um mercado, uma odd) e o mesmo lugar
    # na vitrine. Peso diferente pro sucessor faria o placar dar um degrau no
    # dia da troca, sem nada ter mudado na aposta.
    "player_stats": 3,
    # Ao vivo (29/08). Herda o peso da entrada simples pelo mesmo criterio que
    # rege a tabela inteira: o peso descreve a FORMA da aposta, nao a
    # confianca no motor. Um pick ao vivo e' um jogo, um mercado, uma odd --
    # igual ao free e aos mercados proprios. O VIP fica acima por ser o
    # produto pago, nao por ser o motor melhor.
    #
    # Ate' 28/08 a chave nem existia, e isso era pior do que qualquer peso:
    # `stake_de("live")` caia no STAKE_FALLBACK de 1u, entao o ao vivo teria
    # entrado no placar com um peso que ninguem escolheu, no dia em que
    # aparecesse na primeira consulta.
    "live":        3,
    # Pick Boost publicado em 2026-08-28. Peso 2, entre a multipla (1) e os
    # mercados proprios (3), e o meio nao e' indecisao:
    #
    #   e' um COMBINADO (Over 1.5 FT + Under 2.5 HT), e combinado quebra
    #   inteiro quando uma perna erra -- por isso nao merece o peso de um pick
    #   de perna unica;
    #
    #   mas as duas pernas sao do MESMO jogo e do MESMO evento (gols), com
    #   probabilidade individual alta (piso de 72% e 70%) e faixa de odd curta
    #   (1.30-2.30 no combinado). Nao e' a aposta de 3 pernas independentes que
    #   justifica o peso 1 da multipla.
    #
    # Ate' 27/08 era 0, e o zero era explicito: fase 1 do produto era so' Admin,
    # e sem a chave ele cairia no STAKE_FALLBACK de 1u no dia em que entrasse
    # numa consulta -- entrando no placar por descuido em vez de por decisao.
    "boost":       2,
    "multiplas":   1,
    # Zero = fora do placar de unidades. Ver o bloco no topo deste arquivo.
    "alavancagem": 0,
}

# Fonte desconhecida entra com 1u: subestima, nunca infla.
STAKE_FALLBACK = 1


def stake_de(source: str) -> int:
    return STAKE_PADRAO.get(source, STAKE_FALLBACK)


def conta_em_unidades(source: str) -> bool:
    """Se esta fonte move o lucro em unidades do placar publico.

    Existe pra tela poder dizer "nao conta em unidades" em vez de estampar um
    `+0,0u` que parece defeito. Quem le' o peso pra CALCULAR usa `stake_de`;
    quem le' pra ESCREVER na tela pergunta aqui.
    """
    return stake_de(source) > 0


def rotulo_curto() -> str:
    """'VIP 4u · free e mercados 3u · múltipla 1u' · texto que vai pra tela.

    Sai daqui pra que mudar o plano mude a legenda junto. Uma legenda velha
    grudada num numero novo e' pior do que nao ter legenda.

    A alavancagem nao aparece na legenda porque nao entra na conta que a
    legenda explica -- citar "0u" convidaria a leitura errada de que ela deu
    zero de lucro.
    """
    return (f"VIP {STAKE_PADRAO['vip']}u · free e mercados {STAKE_PADRAO['free']}u"
            f" · múltipla {STAKE_PADRAO['multiplas']}u")
