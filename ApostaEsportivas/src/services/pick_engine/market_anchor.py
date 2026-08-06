"""Ancoragem de mercado: combina a probabilidade do motor com a do mercado,
em espaco de log-odds, com peso aprendido por mercado a partir do CLV.

POR QUE ANCORAR
---------------
A odd de fechamento de um mercado liquido incorpora escalacao, lesao, clima,
dinheiro informado e centenas de modelos concorrentes. E' o melhor estimador
publico de probabilidade que existe. O motor hoje trata a odd como ADVERSARIO
(edge = minha taxa menos a odd) em vez de tratar como INFORMACAO.

Tratar como informacao nao significa se render ao mercado: significa que
divergir dele passa a ter um custo proporcional ao quanto o motor ja' provou
que sabe divergir naquele mercado especifico.

O EFEITO PRATICO
----------------
Elimina de uma vez a classe inteira de falso positivo em que uma amostra
pequena produz taxa extrema num mercado ilíquido: se o mercado precifica 45% e
o motor diz 80%, a combinacao so' fica perto de 80% se o historico daquele
mercado sustentar essa ousadia. Sem historico, a combinacao fica perto do
mercado -- que e' a atitude correta diante de ignorancia.

POR QUE LOG-ODDS E NAO MEDIA SIMPLES
------------------------------------
Media aritmetica de probabilidade e' mal comportada nas pontas: 0.02 e 0.98
tem a mesma "distancia" de 0.50 na escala linear, mas em termos de aposta a
diferenca entre 0.02 e 0.04 (dobro do risco) e' enorme e entre 0.50 e 0.52 e'
quase nada. Log-odds e' a escala em que a evidencia se soma linearmente -- e'
por isso que ela e' a escala natural pra combinar duas opinioes
probabilisticas, e nao uma preferencia de gosto.

    logit(p) = ln(p / (1-p))
    logit(p_final) = w * logit(p_modelo) + (1-w) * logit(p_mercado)

COMO O PESO E' APRENDIDO
------------------------
w sai do CLV realizado daquele mercado, nao de um numero escolhido. CLV
positivo e significativo quer dizer "quando este motor discordou do mercado,
ele estava certo antes do fechamento" -- e' exatamente a licenca pra confiar
mais nele. CLV nao significativo mantem w baixo. Mercado com CLV negativo
significativo tem w empurrado pro piso: o motor demonstrou que discorda pro
lado errado.
"""
from __future__ import annotations

import math

# Peso do modelo quando nao ha evidencia nenhuma sobre o mercado. Comeca
# BAIXO de proposito: sem historico, a hipotese default e' que o mercado sabe
# mais que o motor. Subir isso sem evidencia seria exatamente o excesso de
# confianca que a auditoria encontrou em varios lugares.
W_INICIAL = 0.35

# Limites de w. O teto abaixo de 1.0 mantem o mercado sempre com alguma voz --
# nenhum modelo interno deveria poder ignorar completamente o preco de
# fechamento. O piso acima de 0 evita que um mercado ruim vire replica pura da
# odd (nesse caso o certo e' suspender o mercado, nao gerar pick sem opiniao).
W_MIN = 0.10
W_MAX = 0.85

# CLV medio que corresponde ao teto de confianca. 3% de CLV medio sustentado
# e' desempenho forte pra mercado esportivo -- acima disso o ganho de w satura
# em vez de crescer sem limite.
CLV_PARA_W_MAX = 0.03

# Amostra minima de pernas COM odd de fechamento pra o peso sair do default.
# Abaixo disso, w fica em W_INICIAL: nao ha evidencia pra mover.
MIN_AMOSTRA_CLV = 20


def logit(p: float) -> float:
    """ln(p/(1-p)), com recorte pra evitar infinito nas pontas."""
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def expit(x: float) -> float:
    """Inversa do logit. Implementada nos dois ramos pra nao estourar
    exp() com argumento grande."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def blend(p_modelo: float | None, p_mercado: float | None, w: float) -> float | None:
    """Combina as duas probabilidades em log-odds.

    None quando falta qualquer um dos lados: sem preco de mercado nao ha o que
    ancorar, e o chamador deve usar p_modelo puro sabendo disso -- nunca
    fingir que o mercado concordou.
    """
    if p_modelo is None or p_mercado is None:
        return None
    peso = min(max(float(w), 0.0), 1.0)
    combinado = peso * logit(p_modelo) + (1 - peso) * logit(p_mercado)
    return round(expit(combinado), 4)


def peso_por_clv(clv_medio: float | None, amostra: int,
                 significativo: bool = False) -> float:
    """Peso do modelo a partir do CLV demonstrado naquele mercado.

    Amostra insuficiente devolve W_INICIAL. CLV positivo aumenta w
    proporcionalmente ate' o teto; CLV negativo derruba w em direcao ao piso.

    `significativo` (intervalo de confianca do CLV nao cruza zero, ver
    attribution.is_significant) e' exigido pra SUBIR o peso, mas nao pra
    baixar. A assimetria e' deliberada e conservadora: aumentar a confianca no
    modelo com base em ruido e' o erro caro; reduzi-la com base em ruido custa
    apenas oportunidade.
    """
    if amostra < MIN_AMOSTRA_CLV or clv_medio is None:
        return W_INICIAL

    if clv_medio >= 0:
        if not significativo:
            return W_INICIAL
        fracao = min(clv_medio / CLV_PARA_W_MAX, 1.0)
        return round(W_INICIAL + fracao * (W_MAX - W_INICIAL), 4)

    fracao = min(abs(clv_medio) / CLV_PARA_W_MAX, 1.0)
    return round(W_INICIAL - fracao * (W_INICIAL - W_MIN), 4)


def divergencia(p_modelo: float | None, p_mercado: float | None) -> float | None:
    """Distancia entre as duas opinioes, em log-odds.

    E' o sinal de edge de verdade: nao "minha taxa menos a odd", e sim "o
    quanto eu discordo do consenso". Exposto separado pra poder ser explicado
    ao usuario e usado como gate -- divergencia enorme com w baixo e' o
    retrato exato do falso positivo que se quer barrar.
    """
    if p_modelo is None or p_mercado is None:
        return None
    return round(logit(p_modelo) - logit(p_mercado), 4)


def anchor(p_modelo: float | None, p_mercado: float | None,
           clv_medio: float | None = None, amostra_clv: int = 0,
           clv_significativo: bool = False) -> dict:
    """Resultado completo da ancoragem, com todos os componentes expostos.

    Nunca devolve so' o numero final: quem explica a pick precisa poder dizer
    de onde ele veio, e quem audita precisa poder refazer a conta.
    """
    w = peso_por_clv(clv_medio, amostra_clv, clv_significativo)
    return {
        "p_modelo": p_modelo,
        "p_mercado": p_mercado,
        "peso_modelo": w,
        "p_final": blend(p_modelo, p_mercado, w),
        "divergencia_logit": divergencia(p_modelo, p_mercado),
        "clv_medio": clv_medio,
        "clv_amostra": amostra_clv,
        "clv_significativo": clv_significativo,
    }
