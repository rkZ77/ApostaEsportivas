"""Multipla V2 -- portfolio diario de bilhetes, nao "a multipla do dia".

A PERGUNTA QUE O MOTOR PASSA A FAZER
------------------------------------
    V1: "preciso gerar uma multipla."
    V2: "quantas multiplas de qualidade existem hoje?"

A resposta pode ser 0. Zero e' resposta valida: nao existe cota de publicacao
a cumprir, e um bilhete forcado custa dinheiro real.

O que muda em relacao ao que rodava antes:

  * o TETO DE BILHETES vem da oferta (jogos com perna aprovada), nao de uma
    constante -- 1 num dia de 5 jogos, ate' 5 num dia de 31+;
  * a PERNA passa a ter probabilidade CALIBRADA (encolhida pelo que a amostra
    sustenta), score proprio e gate proprio, em vez de entrar crua;
  * a COMBINACAO e' ordenada por um score composto cujo maior peso e' o ELO
    MAIS FRACO -- nunca por EV, porque dentro de uma faixa de odd fixa
    maximizar EV e' maximizar odd;
  * a CORRELACAO deixa de ser presumida: mesmo jogo e mesma equipe viram
    HIGH e nao combinam, desconhecido paga penalidade;
  * o DIA e' visto como conjunto: sobreposicao, exposicao por jogo e
    concentracao por familia de mercado limitam o portfolio inteiro.

    config        limiares, pesos, faixa de odd e o teto por oferta
    component     a perna: calibracao, risco, amostra, score e gate
    correlation   CORRELATION_SCORE e a probabilidade ajustada
    combination   monta, precifica (casa unica) e pontua um bilhete
    portfolio     escolhe QUAIS bilhetes o dia publica
    reasons       os codigos de rejeicao

O pipeline que amarra tudo e grava fica em
engine_pipelines/multipla_pipeline.py.
"""
from services.pick_engine_multipla import (  # noqa: F401
    combination,
    component,
    config,
    correlation,
    portfolio,
    reasons,
)

__all__ = ["combination", "component", "config", "correlation", "portfolio", "reasons"]
