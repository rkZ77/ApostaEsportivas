"""O caminho de referencia da alavancagem · como ela entra no placar publico.

POR QUE ELA NAO PODIA ENTRAR COMO AS OUTRAS
-------------------------------------------
Todas as outras fontes do placar sao pick independente: cada linha arrisca a
propria stake e o lucro do periodo e' a soma das linhas. Alavancagem nao e'
isso. Ela e' um CAMINHO: o dinheiro entra uma vez, rola de pick em pick, e so'
sai quando o caminho encerra -- batendo a meta de 6 greens seguidos, ou
levando um RED.

Somar o `profit` perna a perna, como o UNION faz com todo o resto, descreve
uma aposta que ninguem fez: seriam 6 entradas independentes de 1u num
produto onde existe UMA entrada. Nos dados de PROD de 04/09 a diferenca e' de
+14,6u pela soma ingenua contra +42,9u pela conta do caminho, e as duas estao
"certas" -- so' que a segunda e' a que descreve o produto.

Por isso ela valeu ZERO no placar de 19/08 ate' 04/09: era melhor nao contar do
que contar pela regra errada. O que faltava era a conta certa, e ela ja'
existia -- na banca de quem apostou (`banca.py::_alav_unidades`,
`alavancagem_series`). Este modulo e' a MESMA conta aplicada aos picks
publicados, como se o proprio site tivesse seguido todos eles desde o primeiro.

A CONTA, EM UNIDADES
--------------------
O caminho arrisca 1u -- uma entrada. E' a mesma escolha da banca, e pelo mesmo
motivo: o valor em reais e' de cada um (R$50, R$200) e nao serve pra comparar
caminho de gente diferente. Com entrada de R$50, 1u = R$50.

    encerrou batendo a meta -> paga (multiplicador - 1)u, onde o
                               multiplicador e' o produto das odds do caminho;
    encerrou em RED         -> custa 1u, a entrada. Nao importa se caiu no
                               primeiro passo ou no sexto: o que se perde e'
                               sempre o que entrou;
    ainda aberto            -> vale 0. Composto em andamento nao e' dinheiro.

ONDE O LUCRO CAI NO TEMPO
-------------------------
No dia em que o caminho ENCERRA, e nao espalhado pelos passos. E' o que faz o
grafico por dia e a quebra por mes dizerem a verdade: o dinheiro nao existiu
durante o caminho, ele apareceu de uma vez quando acabou.

Consequencia aceita: um caminho que comeca em julho e fecha em agosto conta
inteiro em agosto. E' assim que ele foi vivido.

O RECORTE DE DATA VEM DEPOIS, NUNCA DENTRO
------------------------------------------
O caminho e' construido sobre o historico INTEIRO e so' entao filtrado. Fazer
o contrario deixaria o numero dependente do filtro: pedir "agosto" recomecaria
a contagem no dia 1o e inventaria um caminho que nunca existiu.

O QUE ISTO PRODUZIU EM PROD, NO DIA EM QUE ENTROU (2026-09-04)
--------------------------------------------------------------
Fica registrado pra quem for mexer poder conferir se ainda bate. Sobre os 57
picks liquidados desde 26/06:

    14 caminhos fechados · 5 bateram a meta, 9 levaram RED
    +42,8939u no total (R$ 2.144,70 com entrada de R$50)
    stake 14u · ROI do produto +306,4%

E no placar inteiro, que ate' entao ignorava a alavancagem:

    antes  +230,50u sobre 1.640u de stake · ROI 14,1%
    depois +273,39u sobre 1.654u de stake · ROI 16,5%

O ROI de 306% e' real e nao domina o placar porque a stake e' pequena: sao 14
entradas em tres meses, contra 1.048u so' de VIP. Um produto de variancia alta
que arrisca pouco pesa pouco -- que e' exatamente o que se quer que ele faca.
"""
from __future__ import annotations

#: Quantos greens seguidos fecham um caminho.
#:
#: Mora aqui, e nao em banca.py, porque agora ha' DOIS consumidores -- a banca
#: de cada usuario e o placar publico -- e uma meta escrita duas vezes viraria
#: dois produtos diferentes com o mesmo nome no primeiro ajuste.
#:
#: 6 e' escolha do produto, nao da matematica. A matematica diz que o
#: comprimento nao CRIA lucro: a odd de ~1,47 ja' embute ~68% de probabilidade,
#: entao caminho longo multiplica a vantagem por pick se ela existir e
#: multiplica o buraco se nao existir.
META_PADRAO = 6


def _sql_multiplicador(coluna_odd: str, coluna_result: str) -> str:
    """Quanto o dinheiro do caminho e' multiplicado por este passo.

    Espelha `services/settlement.py`, que e' a matematica de resultado do
    projeto: GREEN paga a odd, PUSH devolve, meia vitoria paga metade do lucro,
    meia derrota devolve metade, RED zera. Aqui o zero e' o que ENCERRA o
    caminho -- e' a unica diferenca de leitura entre os dois contextos.
    """
    return f"""
        CASE {coluna_result}
            WHEN 'GREEN'     THEN {coluna_odd}::numeric
            WHEN 'HALF-WIN'  THEN 1 + ({coluna_odd}::numeric - 1) / 2
            WHEN 'HALF-LOSS' THEN 0.5
            WHEN 'PUSH'      THEN 1
            ELSE 0
        END"""


def subquery_dos_caminhos(meta: int = META_PADRAO) -> str:
    """Subconsulta que devolve, por pick liquidado, o que ele rendeu AO CAMINHO.

    Sai `pick_id`, `encerra`, `passos`, `caminho_profit` e `caminho_stake`. Os
    dois ultimos sao zero em todo passo que NAO encerra -- e andam sempre
    juntos, que e' a regra numero 1 de stake_plan.py: mexer no lucro sem mexer
    na stake faz o ROI saltar por um fator que nao existe.

    Recursivo porque o estado do caminho depende do passo anterior e ZERA no
    encerramento -- nao ha' janela de agregacao que reinicie sozinha. Custa
    pouco: sao dezenas de linhas na tabela inteira, nao milhoes.

    SUBCONSULTA COMPLETA, e nao um pedaco de CTE, porque o consumidor e' um
    ramo de UNION ALL (`public.py::_build_union`): `WITH` no meio de um UNION
    e' erro de sintaxe, dentro de um `FROM (...)` e' valido.
    """
    return f"""(
    WITH RECURSIVE ordenado AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY match_date, id) AS n,
               {_sql_multiplicador("odd_combined", "result")} AS mult
          FROM picks_alavancagem
         WHERE result IS NOT NULL
    ),
    caminho AS (
        SELECT n, id, mult, mult AS saldo, 1 AS passos,
               (mult = 0 OR 1 >= {meta}) AS encerra
          FROM ordenado WHERE n = 1
        UNION ALL
        -- `c.encerra` do passo anterior e' o gatilho de reinicio: quando ele e'
        -- verdadeiro, este passo e' o PRIMEIRO de um caminho novo e o saldo
        -- volta a ser so' o multiplicador dele.
        SELECT o.n, o.id, o.mult,
               CASE WHEN c.encerra THEN o.mult ELSE c.saldo * o.mult END,
               CASE WHEN c.encerra THEN 1     ELSE c.passos + 1     END,
               (o.mult = 0
                OR (CASE WHEN c.encerra THEN 1 ELSE c.passos + 1 END) >= {meta})
          FROM caminho c
          JOIN ordenado o ON o.n = c.n + 1
    )
    SELECT id AS pick_id, passos, encerra,
           CASE WHEN encerra THEN ROUND(saldo - 1, 4) ELSE 0 END::numeric
                AS caminho_profit,
           CASE WHEN encerra THEN 1 ELSE 0 END::numeric AS caminho_stake
      FROM caminho
    )"""
