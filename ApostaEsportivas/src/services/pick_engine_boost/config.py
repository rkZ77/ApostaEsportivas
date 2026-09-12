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


# ===========================================================================
# V2 -- 2026-09-11
# ===========================================================================
# O que a V2 muda, em uma frase: o Pick Boost deixa de ser um motor que ORDENA
# jogos e passa a ser um motor que RECUSA jogos. Tudo abaixo e' porta ou
# insumo de porta; nada aqui existe pra melhorar a posicao de um jogo no
# ranking.
#
# TRES DEFEITOS DA V1, e o que cada um produzia:
#
#   1. EV NUNCA REPROVOU. `ev` e `edge` eram calculados DEPOIS de
#      `aprovado = True` e gravados como "informacao secundaria". Um jogo com
#      probabilidade 0,63 e odd combinada 1,45 (EV -8,6%) virava pick com
#      Score 80. Ver EV_MINIMO.
#
#   2. A PROBABILIDADE DO PAR ESTAVA INFLADA, e a V1 afirmava o contrario. O
#      comentario de `analisar_confronto` dizia que o produto prob_ft x prob_ht
#      SUBESTIMA o par, "porque Under no 1o tempo e Over no jogo inteiro sao
#      levemente concordantes". Sob o proprio modelo do motor (Poisson) vale o
#      inverso: os dois eventos dividem os gols do primeiro tempo COM SINAL
#      TROCADO -- o Under 2.5 HT quer poucos, o Over 1.5 FT quer muitos -- e o
#      produto SUPERESTIMA. Com lambda_ft 2,60 e lambda_ht 1,10, nas mesmas
#      distribuicoes que o motor ja' usa, o produto da' 0,650 e a conta certa
#      da' 0,633: 1,7 ponto de probabilidade por pick, que numa odd combinada
#      de 1,50 sao 2,6 pontos de EV inventados. Ver joint.py.
#
#   3. 4/4 VALIA 100%. `_freq` dividia acertos por total sem ajuste nenhum, e
#      `_combinar` levava essa fracao com peso 0,45 pra probabilidade final.
#      Com o piso de amostra em 4, um time de 4 jogos entrava afirmando
#      certeza. Ver shrinkage.py.

# -- Amostra: a classificacao ------------------------------------------------
#: (piso, rotulo), do maior pro menor.
CLASSES_DE_AMOSTRA = (
    (30, "FORTE"), (20, "BOA"), (10, "RAZOAVEL"), (6, "LIMITADA"),
    (4, "MUITO_FRACA"), (0, "INSUFICIENTE"),
)

# -- Encolhimento (shrinkage) ------------------------------------------------
#: Jogos-fantasma do baseline. A frequencia observada e' misturada com a da
#: liga como se o baseline fosse um time com este tanto de jogos:
#:
#:     p = (n * p_observado + k * p_baseline) / (n + k)
#:
#: Com k = 6, um 4/4 (100%) contra baseline 75% sai 85%, e um 9/10 (90%) sai
#: 84%. E' o efeito procurado: a amostra pequena perde quase toda a distancia
#: ate' o baseline, a grande perde pouco.
#:
#: DECLARADO, nao medido. O k honesto sai do backtest
#: (src/scripts/boost_backtest_v2.py, secao `amostra`).
PSEUDO_JOGOS_FT = 6
PSEUDO_JOGOS_HT = 6

#: Baseline global, pra quando a liga nao tem amostra pra ter o proprio.
BASELINE_OVER15_FT = 0.75
BASELINE_UNDER25_HT = 0.88
BASELINE_PAR = 0.63
BASELINE_GOLS_HT = 1.10
#: Jogos minimos na liga pra o baseline dela substituir o global.
MIN_JOGOS_BASELINE_LIGA = 30

# -- Risco do primeiro tempo -------------------------------------------------
#: Pesos do HT_RISK_SCORE (somam 100). O primeiro pesa mais porque e' o unico
#: que olha a projecao; os outros olham o que ja' aconteceu.
PESO_RISCO_LAMBDA_HT = 30
PESO_RISCO_FREQ_2MAIS = 25
PESO_RISCO_FREQ_3MAIS = 20
PESO_RISCO_CONCENTRACAO_2 = 15
PESO_RISCO_DISPERSAO_HT = 10

#: (valor onde o risco comeca, valor onde satura).
FAIXA_LAMBDA_HT = (0.90, 1.90)
FAIXA_FREQ_2MAIS_HT = (0.20, 0.60)
FAIXA_FREQ_3MAIS_HT = (0.00, 0.25)
FAIXA_CONCENTRACAO_2 = (0.15, 0.45)
#: Dispersao RELATIVA do primeiro tempo (variancia/media), nao desvio cru: em
#: Poisson o desvio vale a raiz da media, entao desvio 1,0 num HT de media 1,0
#: e' o esperado, nao risco. A escala e' a mesma do phi que o projeto ja' mede
#: nas outras familias -- 1,0 e' Poisson puro, acima disso e' cauda.
FAIXA_DISPERSAO_HT = (1.00, 2.20)

HT_RISK_BLOQUEIA = 80     # >= isto e' NO_PICK
HT_RISK_PENALIZA = 65     # >= isto custa ponto no score final
#: Teto da penalidade, em pontos de score final, entre PENALIZA e BLOQUEIA.
PENALIDADE_MAX_HT_RISK = 12.0

#: TAIL_RISK: a concentracao perigosa DENTRO do acerto. Um Under 2.5 HT de
#: 10/10 com sete jogos parando exatamente em 2 gols nao e' o mesmo 10/10 de
#: um com sete jogos parando em 0.
TAIL_RISK_BLOQUEIA = 85

# -- Projecao contra a linha -------------------------------------------------
#: lambda_ft - 1.5. Abaixo do minimo o modelo esta' dizendo "tem gol
#: suficiente por pouco", que e' a definicao de pick sem folga.
MARGEM_MIN_FT = 0.55
FAIXA_MARGEM_FT = (0.30, 1.30)
#: 2.5 - lambda_ht. Os dois numeros na ordem pedida: 2.25 bloqueia, 2.00
#: penaliza.
LAMBDA_HT_BLOQUEIA = 2.25
LAMBDA_HT_PENALIZA = 2.00
FAIXA_MARGEM_HT = (1.00, 1.80)
PENALIDADE_MAX_MARGEM = 8.0

# -- Divergencia modelo x historico ------------------------------------------
#: |modelo - historico| no PAR. Acima disto os dois nao descrevem o mesmo
#: jogo, e a media ponderada deixa de ser resposta: vira a media de duas
#: afirmacoes incompativeis.
DIVERGENCIA_MAX = 0.18
DIVERGENCIA_PENALIZA = 0.10
PENALIDADE_MAX_DIVERGENCIA = 8.0

# -- Qualidade de dado -------------------------------------------------------
PESOS_QUALIDADE = {
    "amostra_ft": 0.24,
    "amostra_ht": 0.24,
    "cobertura_ht": 0.18,   # quantos dos jogos lidos tem placar de intervalo
    "amostra_mando": 0.14,  # jogos no mando de hoje
    "recencia": 0.12,       # o jogo mais recente e' de quando?
    "completude": 0.08,     # indicadores que nasceram None
}
DATA_QUALITY_MINIMO = 70.0
#: Dias desde o ultimo jogo lido. Ate' o primeiro valor a recencia e' cheia;
#: no segundo, zero. Parada de temporada cabe no meio.
FAIXA_RECENCIA_DIAS = (21, 75)

# -- Convergencia ------------------------------------------------------------
#: Fracao minima dos sinais independentes que precisam concordar. Sao oito
#: sinais (ver quality.convergencia); 0.55 exige cinco.
CONVERGENCIA_MINIMA = 0.55

# -- Portas de valor ---------------------------------------------------------
#: EV e edge da COMBINACAO, contra a odd combinada. Estritamente maior: EV
#: zero e' aposta sem razao pra existir.
EV_MINIMO = 0.0
EDGE_MINIMO = 0.0
#: Abaixo deste edge a pick passa mas perde ponto. Nao bloqueia porque edge
#: pequeno com evidencia forte continua sendo aposta valida.
EDGE_BAIXO = 0.03

# -- Score final -------------------------------------------------------------
#: Pesos do SCORE FINAL, normalizados pela soma -- mexer num nao exige
#: reajustar os outros.
#:
#: `valor` ESTA' EM ZERO DE PROPOSITO, e e' a unica divergencia deliberada em
#: relacao ao pedido da V2 (que sugeria 15%). A regra do projeto e' que preco
#: ELIMINA nas portas e NUNCA ordena: se pesar, um jogo fraco e bem pago sobe
#: no ranking, que e' o defeito oposto ao que a V2 veio corrigir. O EV
#: continua porta obrigatoria (EV_MINIMO) e continua gravado e exibido -- ele
#: so' nao decide quem vem antes. Pra ligar, basta pôr 0.15 aqui.
PESOS_SCORE_FINAL = {
    "estatistico": 0.30,
    "modelo": 0.20,
    "valor": 0.00,
    "mando": 0.10,
    "seguranca_ht": 0.10,
    "amostra": 0.05,
    "qualidade_dado": 0.05,
    "convergencia": 0.05,
}

# -- Calibracao --------------------------------------------------------------
#: Faixas medidas: (piso, teto, taxa_real, n). VAZIA enquanto nao houver
#: medicao, e isso e' posicao, nao pendencia esquecida -- a camada
#: probabilistica deste projeto ja' reprovou por medicao uma isotonica ligada
#: no palpite. O backtest (secao `calibracao`) produz exatamente esta tabela;
#: enquanto estiver vazia, `calibration.calibrar` devolve a propria
#: probabilidade e diz que nao ha medicao.
CALIBRACAO_MEDIDA: tuple = ()
#: Picks liquidados minimos por faixa pra a faixa valer alguma coisa.
MIN_AMOSTRA_CALIBRACAO = 25
#: Quanto da correcao medida e' aplicada. Meio caminho: a tabela e' passado, e
#: aplicar 100% dela e' ajustar o motor ao proprio teste.
FATOR_CALIBRACAO = 0.5
