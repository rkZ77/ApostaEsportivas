"""A probabilidade do PAR -- Over 1.5 FT E Under 2.5 HT na mesma conta.

POR QUE O PRODUTO ESTAVA ERRADO, E PRA QUE LADO
------------------------------------------------
A V1 fazia `prob_ft * prob_ht` e justificava assim:

    "Independencia e' aproximacao, e ela e' CONSERVADORA aqui: Under no
     primeiro tempo e Over no jogo inteiro sao levemente concordantes (jogo
     que nao abre cedo tende a abrir depois), entao o produto subestima."

A intuicao e' razoavel e a conta desmente. Os dois eventos nao sao dois jogos:
eles dividem os MESMOS gols do primeiro tempo, e com sinal trocado. Cada gol
no intervalo aproxima o Over 1.5 FT e afasta o Under 2.5 HT. Condicionado a
lambda, a dependencia e' NEGATIVA, e o produto SUPERESTIMA o par.

A conta certa nao precisa de correlacao estimada -- ela sai de decompor o jogo
em duas metades independentes, que e' a hipotese padrao de Poisson e a mesma
que o motor ja' aceita quando modela FT e HT com lambdas separados:

    G_ht  ~ Poisson(lambda_ht)
    G_2t  ~ Poisson(lambda_ft - lambda_ht)        independentes

    P(FT >= 2  E  HT <= 2) = SOMA_{h=0..2} P(G_ht = h) * P(G_2t >= 2 - h)

Com lambda_ft 2,60 e lambda_ht 1,10:

    produto .......... 0,7221 x 0,9004 = 0,6502
    decomposicao ..... 0,1472 + 0,2845 + 0,2014 = 0,6330

1,7 ponto de probabilidade que a V1 dava de graca em todo pick -- e que, numa
odd combinada de 1,50, sao 2,6 pontos de EV inventados. (O produto usa a
Gama-Poisson com phi 1,07 no FT, que e' o que o motor faz hoje; a decomposicao
usa Poisson pura nas duas metades. A diferenca entre as duas familias nesta
faixa e' menor que o erro que estamos corrigindo.)

O HISTORICO TAMBEM SABE RESPONDER
---------------------------------
E ele responde melhor: o par nao precisa ser reconstruido a partir de duas
frequencias, porque cada jogo do historico ou teve as duas coisas ou nao teve.
`frequencia_do_par` conta isso direto, e e' essa contagem que vira o lado
historico da probabilidade final.
"""
from __future__ import annotations

from services.pick_engine import probability_model as pm
from services.pick_engine_boost import config as cfg

#: Piso do lambda do segundo tempo. Existe pra um lambda_ht mal estimado (maior
#: que o lambda_ft, o que acontece quando a cobertura de HT e' curta e a de FT
#: nao) nao produzir taxa negativa e explodir a Poisson.
LAMBDA_2T_MINIMO = 0.15


def lambda_segundo_tempo(lambda_ft: float | None, lambda_ht: float | None) -> float | None:
    if lambda_ft is None or lambda_ht is None:
        return None
    return round(max(float(lambda_ft) - float(lambda_ht), LAMBDA_2T_MINIMO), 4)


def probabilidade_do_par(lambda_ft: float | None, lambda_ht: float | None,
                         linha_ft: float = cfg.LINHA_OVER_FT,
                         linha_ht: float = cfg.LINHA_UNDER_HT) -> float | None:
    """P(gols_ft > linha_ft E gols_ht < linha_ht), pela decomposicao.

    As duas linhas sao .5, entao "> 1.5" e' ">= 2" e "< 2.5" e' "<= 2". A
    conversao esta' explicita em vez de constante pra a funcao continuar certa
    se um dia a linha mudar.
    """
    if lambda_ft is None or lambda_ht is None:
        return None
    lam_2t = lambda_segundo_tempo(lambda_ft, lambda_ht)
    minimo_ft = int(linha_ft) + 1          # 1.5 -> 2 gols no jogo
    maximo_ht = int(linha_ht)              # 2.5 -> ate' 2 gols no intervalo

    total = 0.0
    for h in range(0, maximo_ht + 1):
        p_ht = pm.poisson_pmf(h, float(lambda_ht))
        faltam = minimo_ft - h
        if faltam <= 0:
            p_2t = 1.0
        else:
            # P(G_2t >= faltam) = 1 - CDF(faltam - 1)
            p_2t = 1.0 - pm.poisson_cdf(faltam - 1, lam_2t)
        total += p_ht * max(0.0, p_2t)
    return round(min(max(total, 0.0), 1.0), 4)


def frequencia_do_par(jogos_com_ht: list, linha_ft: float = cfg.LINHA_OVER_FT,
                      linha_ht: float = cfg.LINHA_UNDER_HT) -> tuple[int, int]:
    """(acertos, total) do par no historico de UM time.

    So' jogos com os dois placares -- FT e HT. Um jogo sem intervalo publicado
    nao pode responder a pergunta do par, e conta-lo como falha seria repetir
    o erro que `goals_history.com_ht` ja' evita.
    """
    acertos = total = 0
    for j in jogos_com_ht:
        gf_casa, gf_fora = j.get("home_goals"), j.get("away_goals")
        gh_casa, gh_fora = j.get("home_goals_ht"), j.get("away_goals_ht")
        if None in (gf_casa, gf_fora, gh_casa, gh_fora):
            continue
        total += 1
        if (int(gf_casa) + int(gf_fora)) > linha_ft and (int(gh_casa) + int(gh_fora)) < linha_ht:
            acertos += 1
    return acertos, total
