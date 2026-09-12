"""Encolhimento: o que 4/4 realmente afirma.

O DEFEITO QUE ISTO FECHA
------------------------
A V1 calculava frequencia como `acertos / total` e entregava o resultado pra
probabilidade final com peso 0,45. Com o piso de amostra em 4 jogos (baixado
em 28/08 pra valer nos cinco pipelines), um time com 4 jogos e 4 acertos
entrava na conta afirmando 100% -- a mesma afirmacao que um time com 40
acertos em 40, e mais forte que a de um time com 36 em 40.

O conserto e' o de sempre em contagem pequena: misturar o observado com o
baseline, dando ao baseline o peso de uma amostra fantasma de tamanho k.

    p = (n * p_observado + k * p_baseline) / (n + k)

Isto NAO e' um redutor pessimista. Um time com 2/10 (20%) contra um baseline
de 75% SOBE pra 41% -- o encolhimento puxa nos dois sentidos, porque o que ele
corrige nao e' otimismo, e' a pretensao de precisao que a amostra nao tem.

POR QUE ISSO NAO PODE VIVER SO' NO SCORE
----------------------------------------
O Score ja' tinha uma parcela de consistencia que olhava amostra. Mas a
probabilidade -- que e' o que vira EV, edge e odd justa -- nao olhava: ela
recebia a fracao crua. Um numero errado na probabilidade contamina a decisao
financeira inteira, e nenhum peso de score conserta isso depois.
"""
from __future__ import annotations

from services.pick_engine_boost import config as cfg


def classe_de_amostra(n: int | None) -> str:
    """INSUFICIENTE / MUITO_FRACA / LIMITADA / RAZOAVEL / BOA / FORTE."""
    total = int(n or 0)
    for piso, rotulo in cfg.CLASSES_DE_AMOSTRA:
        if total >= piso:
            return rotulo
    return "INSUFICIENTE"


def encolher(acertos: int | None, total: int | None, baseline: float | None,
             pseudo_jogos: float) -> float | None:
    """A frequencia ajustada. None quando nao ha nem observacao nem baseline.

    Sem baseline devolve a frequencia crua -- e' pior, mas e' honesto: inventar
    um baseline seria pior ainda.
    """
    n = int(total or 0)
    if baseline is None:
        return round(acertos / n, 4) if n else None
    if n <= 0:
        return round(float(baseline), 4)
    k = float(pseudo_jogos)
    return round((int(acertos or 0) + k * float(baseline)) / (n + k), 4)


def encolher_media(valores_e_pesos, baseline: float | None,
                   pseudo_jogos: float) -> float | None:
    """Encolhe uma MEDIA (nao uma fracao) em direcao ao baseline.

    Usada na media de gols do primeiro tempo: a conta e' a mesma, trocando
    "acertos" pela soma observada.
    """
    soma, n = 0.0, 0
    for valor, quantos in valores_e_pesos:
        if valor is None or not quantos:
            continue
        soma += float(valor) * int(quantos)
        n += int(quantos)
    if baseline is None:
        return round(soma / n, 4) if n else None
    if n <= 0:
        return round(float(baseline), 4)
    k = float(pseudo_jogos)
    return round((soma + k * float(baseline)) / (n + k), 4)


def deslocamento(cru: float | None, encolhido: float | None) -> float | None:
    """Quanto o encolhimento mexeu, com sinal. Vai pro engine_debug.

    Serve pra responder "esta pick depende de uma amostra pequena?" sem ter
    que reabrir a conta: deslocamento grande e' amostra fraca, por definicao.
    """
    if cru is None or encolhido is None:
        return None
    return round(float(encolhido) - float(cru), 4)
