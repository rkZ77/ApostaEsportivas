"""Plano de stake do placar publico, em unidades.

A coluna `profit` das seis tabelas de picks e' lucro com stake de 1 unidade
(settlement.py: GREEN -> odd-1, HALF-WIN -> (odd-1)/2, PUSH -> 0, HALF-LOSS ->
-0.5, RED -> -1). Isso e' a BASE de calculo, nao o plano de aposta: ninguem
aposta a mesma coisa numa entrada simples e num bilhete de quatro pernas.

O placar publico entao anuncia um plano fixo, declarado aqui e em nenhum outro
lugar:

    ao vivo ............................................ 4u
    VIP ................................................ 4u
    free, faltas, defesas, player stats, pick boost .... 3u
    multipla ........................................... 1u
    alavancagem ........... 1u POR CAMINHO, nao por pick (ver abaixo)

O VIP fica um degrau acima porque e' o produto de maior convicção do motor: e'
onde o filtro e' mais duro e onde a assinatura e' cobrada. Free, faltas e
defesas sao entrada simples tambem (um jogo, um mercado), mas entram um degrau
abaixo -- sao vitrine, e o placar publico nao deve pesar vitrine igual ao
produto pago.

Combinada leva 1u pelo motivo de sempre: a variancia de um bilhete e' outra
coisa, e igualar a stake inflaria tanto o lucro nos meses bons quanto o buraco
nos ruins.

POR QUE A ALAVANCAGEM NAO TEM PESO POR PICK
-------------------------------------------
Ela nao e' um pick que se liquida em unidade: e' um CAMINHO. O bilhete em
andamento nao e' dinheiro, o resultado so' vira unidade quando o caminho
encerra, e o RED custa so' a entrada.

Entre 19/08 e 04/09 isso a deixou valendo ZERO no placar. O zero nunca foi
desprezo pelo produto -- era a falta da conta certa: somar o `profit` perna a
perna descreve seis entradas independentes de 1u num produto onde existe UMA,
e contar errado e' pior que nao contar. Nos dados de PROD de 04/09 a soma
ingenua daria +14,6u contra os +42,9u que o caminho de fato rendeu.

Desde 04/09 (pedido do usuario) ela CONTA, pela conta dela: 1u de entrada por
caminho, (multiplicador - 1)u quando bate a meta de 6, -1u no RED, e zero
enquanto esta' aberta. Quem faz isso e' `alavancagem_caminho.py`, que aplica
aos picks publicados a mesma conta que `alavancagem_series`
(banca.py::_alav_unidades) ja' usava na banca de quem apostou.

A ENTRADA DE VERDADE: 1u = uma entrada. Com os R$50 que o produto sugere como
padrao, 1u = R$50 e o placar em unidades vira reais multiplicando. O valor em
reais nao entra aqui de proposito -- ele e' escolha de cada usuario, e o placar
tem que ser comparavel entre gente que aposta valores diferentes.

`STAKE_PADRAO["alavancagem"]` continua 0, e continua certo: ele responde
"quanto vale UM pick de alavancagem sozinho", e a resposta e' nada. O peso por
linha e a participacao no placar sao duas perguntas diferentes, e so' agora
elas tem respostas diferentes.

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
    # Ao vivo: 4u desde 29/08, no mesmo degrau do VIP (decisao do usuario).
    #
    # A regra anterior era "o peso descreve a FORMA da aposta", e por ela o ao
    # vivo entrou com 3 -- um jogo, um mercado, uma odd, igual ao free. O
    # criterio agora e' o do PRODUTO: o ao vivo e' exclusivo de assinante, e
    # entra no placar publico com o peso do produto pago.
    #
    # Peso do PLACAR, nao da aposta de ninguem. O que o assinante ve' no card
    # continua saindo da banca dele (suggestions::_compute_suggested_stake_
    # units), com o teto de 4u de banca.STAKE_LIMITS -- que por coincidencia
    # e' o mesmo numero, e coincidencia e' tudo o que e'.
    "live":        4,
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
    #
    # 29/08: subiu de 2 pra 3, igualando os mercados proprios (decisao do
    # usuario). O argumento do combinado continua de pe' e continua escrito
    # acima -- ele e' o que mantem o boost ABAIXO do VIP e do ao vivo, nao
    # abaixo do free.
    "boost":       3,
    "multiplas":   1,
    # Zero = NAO tem peso por pick. Isso nao significa mais "fora do placar":
    # desde 04/09 a alavancagem entra por caminho, em alavancagem_caminho.py.
    # Ver o bloco no topo deste arquivo.
    "alavancagem": 0,
}

# Fonte desconhecida entra com 1u: subestima, nunca infla.
STAKE_FALLBACK = 1


def stake_de(source: str) -> int:
    return STAKE_PADRAO.get(source, STAKE_FALLBACK)


def conta_em_unidades(source: str) -> bool:
    """Se UM PICK desta fonte tem lucro proprio em unidades.

    Existe pra tela poder dizer "nao conta em unidades" em vez de estampar um
    `+0,0u` que parece defeito. Quem le' o peso pra CALCULAR usa `stake_de`;
    quem le' pra ESCREVER na tela pergunta aqui.

    NAO E' "a fonte entra no placar" -- as duas coisas se separaram em 04/09.
    Alavancagem responde False aqui, e com razao: o card de um passo de caminho
    nao pode anunciar lucro proprio, porque ele nao tem. Ainda assim ela move o
    placar, pelo caminho fechado (ver alavancagem_caminho.py). Quem quiser
    saber se a FONTE conta olha o placar, nao esta funcao.
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
    return (f"VIP e ao vivo {STAKE_PADRAO['vip']}u · free e mercados "
            f"{STAKE_PADRAO['free']}u · múltipla {STAKE_PADRAO['multiplas']}u")
