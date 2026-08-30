"""Limiares do Pick Boost.

O CRITERIO E' FORCA ESTATISTICA, NAO ODD -- e isso tem consequencia
------------------------------------------------------------------
O metodo tem dois mercados FIXOS (Over 1.5 FT e Under 2.5 HT) e escolhe JOGO.
Como a odd nao seleciona, ela nao pode entrar no Score. Ela entra depois, como
faixa de sanidade: um Over 1.5 pagando 1.05 nao e' pick porque nao sobra
margem nenhuma, e um pagando 2.40 nao e' um jogo de Over 1.5 forte -- e' o
mercado dizendo que o jogo e' fraco de gol, contra o que o modelo estaria
afirmando. Nos dois extremos o problema e' o mesmo: a odd esta' contando outra
historia, e a resposta certa e' nao apostar, nao "confiar mais no modelo".

Mesma licao que ja' esta' escrita nos pipelines de faltas e goleiros, e a
mesma da memoria do projeto: edge alto e' alerta, nao qualidade.

AMOSTRA MINIMA
--------------
Under 2.5 HT depende do placar do INTERVALO, cuja cobertura e' menor que a do
placar final. Por isso ha' dois minimos separados -- exigir o mesmo numero nos
dois zeraria o metodo em ligas onde o provedor publica pouco HT, e afrouxar o
de FT pra compensar pioraria o lado que tem dado bom.
"""
from __future__ import annotations

# -- Amostra -----------------------------------------------------------------
#: Jogos com placar final, por time. Abaixo disso o jogo nem e' avaliado.
#:
#: 4 desde 2026-08-28 (era 6): piso unico de amostra pra todos os pipelines,
#: decisao do usuario -- 2 em casa e 2 fora, entao a 5a rodada ja' produz.
MIN_JOGOS_FT = 4
#: Jogos com placar de intervalo, por time.
#:
#: MESMO numero que o de FT desde 28/08. Os dois eram separados porque a
#: cobertura de HT e' menor que a de FT, e exigir 6 nos dois zerava o metodo em
#: liga onde o provedor publica pouco intervalo. Com o piso em 4 essa distincao
#: perde funcao: ela existia pra nao afrouxar o lado bom compensando o ruim, e
#: agora os dois estao no mesmo chao.
MIN_JOGOS_HT = 4
#: Recortes que o metodo declara analisar. O de 10 e' a base; o de 5 mede
#: TENDENCIA contra ela (ver stats_model.tendencia).
JANELA_LONGA = 10
JANELA_CURTA = 5

# -- Mercados fixos ----------------------------------------------------------
LINHA_OVER_FT = 1.5
LINHA_UNDER_HT = 2.5

#: Nomes do mercado de gols totais como as casas publicam. Mesmo padrao de
#: casamento por nome que faltas/goleiros usam -- o market_id varia por casa.
NOMES_MERCADO_FT = frozenset({
    "goals over/under", "over/under", "match goals", "total goals",
    "goals over/under full time",
})
#: Gols totais do PRIMEIRO TEMPO. Nome diferente por casa; todos em minusculo.
NOMES_MERCADO_HT = frozenset({
    "goals over/under first half", "first half goals", "over/under first half",
    "total goals first half", "half time goals", "1st half goals",
})

# -- Faixa de odd (sanidade, nao selecao) ------------------------------------
ODD_MIN_FT, ODD_MAX_FT = 1.12, 1.55

#: O PISO DO HT ERA MAIOR QUE O QUE O MERCADO PAGA (medido em 2026-08-29).
#:
#: Era 1.10, e o produto quase nao publicava. A leitura de `engine_decisions`
#: mostrou o mesmo motivo repetido em quase todo jogo -- "odd fora da faixa de
#: sanidade" -- sempre com a perna do HT em 1.07 ou 1.08:
#:
#:     FT 1.35, HT 1.08, par 1.458
#:     FT 1.38, HT 1.08, par 1.49
#:     FT 1.42, HT 1.07, par 1.519
#:
#: E' o mercado, nao a coleta. Menos de 2.5 gols no PRIMEIRO TEMPO e' um evento
#: quase certo (a media de gols no HT fica perto de 1), entao a casa paga
#: 1.05-1.10 nele. Medido nas odds coletadas: mediana 1.09, minimo 1.05, p90
#: 1.39. Um piso de 1.10 reprovava mais da metade dos jogos por nao alcancar um
#: numero que o mercado raramente produz.
#:
#: O ERRO CONCEITUAL, e ele importa mais que o numero: o piso existe pra
#: garantir que sobre margem, e essa garantia nao e' desta perna. O Under 2.5
#: HT e' ANCORA -- ele nao carrega o bilhete, ele reduz a variancia do que o
#: Over 1.5 afirma. Quem garante margem no Pick Boost e' a odd COMBINADA, que
#: tem piso proprio (ODD_MIN_COMBINADA) e ja estava sendo aplicada: os pares
#: reprovados acima estavam em 1.458, 1.49 e 1.519, ou seja, DENTRO da faixa
#: que de fato protege o produto.
#:
#: O TETO NAO MUDA, e ele continua sendo a metade util da regra aqui: Under 2.5
#: HT pagando mais de 1.60 e' o mercado dizendo que espera gol cedo -- contra o
#: que o modelo estaria afirmando -- e ai a resposta certa continua sendo nao
#: apostar.
ODD_MIN_HT, ODD_MAX_HT = 1.03, 1.60
#: A combinacao dos dois mercados. Existe porque o produto e' o par, e o par
#: e' o que o usuario vai apostar.
ODD_MIN_COMBINADA, ODD_MAX_COMBINADA = 1.30, 2.30

# -- Corte de publicacao -----------------------------------------------------
#: Score minimo pra virar pick. O metodo devolve VARIAS oportunidades por dia
#: (era pedido explicito), entao o corte e' de qualidade, nao de quantidade.
SCORE_MINIMO = 70
#: Probabilidade minima de cada perna, ja' combinada modelo+historico.
PROB_MINIMA_FT = 0.72
PROB_MINIMA_HT = 0.70
#: Teto de picks por rodada. Nao e' limite de qualidade: e' pra uma falha de
#: calibragem nao publicar o dia inteiro de uma vez.
MAX_PICKS_POR_RODADA = 8

# -- Pesos do Score Estatistico (somam 100) ----------------------------------
#
# A divisao entre os dois mercados e' proposital e desigual: Over 1.5 FT tem
# amostra maior (todo jogo tem placar final) e e' o lado que carrega o
# bilhete. Under 2.5 HT tem cobertura menor e variancia maior, entao pesa
# menos -- mas nao pouco, senao o Score aprovaria jogo de gol cedo, que e'
# exatamente o que quebra a perna do HT.
PESO_FREQ_OVER15 = 18      # frequencia historica de Over 1.5 (10 jogos)
PESO_MEDIA_GOLS = 12       # media de gols totais dos dois times
PESO_ATAQUE_DEFESA = 12    # ataque de um contra defesa do outro, dos dois lados
PESO_MANDO = 10            # mandante em casa / visitante fora
PESO_FREQ_UNDER25_HT = 16  # frequencia historica de Under 2.5 HT
PESO_MEDIA_HT = 10         # media de gols no primeiro tempo
PESO_MODELO_FT = 8         # probabilidade do modelo pra Over 1.5
PESO_MODELO_HT = 6         # probabilidade do modelo pra Under 2.5 HT
PESO_TENDENCIA = 8         # ultimos 5 confirmam os ultimos 10?
PESO_CONSISTENCIA = 10     # amostra + dispersao dos dois times

#: Dispersao de gols totais. Medida em 2026-08-20 junto com as outras
#: familias: gol e' o unico contador do projeto em que Poisson se sustenta
#: (variancia/media = 1.07), por isso este motor usa Poisson e nao a Binomial
#: Negativa que escanteios e faltas exigem.
PHI_GOLS_TOTAL = 1.07
#: Gols do primeiro tempo especificamente -- media baixa, e nessa faixa a
#: Gama-Poisson nao se distingue de Poisson.
PHI_GOLS_HT = 1.0
