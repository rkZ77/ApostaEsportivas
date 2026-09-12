"""Player Stats -- motor de estatistica INDIVIDUAL de jogador.

Absorve o antigo motor de Defesas de Goleiro como um metodo (`saves`) e abre a
mesma estrutura pra chutes, chutes no alvo, faltas, desarmes e passes. Mercado
novo = uma entrada em methods.METODOS, nao um pipeline novo.

    methods         o catalogo: coluna, mercados, amostra minima, cargo
    player_history  leitura de player_match_stats (com filtro de minutos)
    minutes_model   minutos esperados, titularidade e risco de funcao
    opponent_model  o quanto o adversario de hoje desloca a expectativa
    count_model     probabilidade por Binomial Negativa, com dispersao MEDIDA
    quality         dispersao, margem de projecao e qualidade do dado
    contradiction   quando dois sinais apontam pra lados opostos
    selection       a escolha entre candidatos -- 100% estatistica
    decision        a auditoria final (as vinte perguntas) e o rastro
    explanation     a justificativa, a partir dos mesmos numeros
    config          faixa de odd, probabilidade minima, tetos

O calculo do metodo `saves` continua sendo o de services/pick_engine/
goalkeeper_model.py -- ele foi MEDIDO contra jogo real (correlacao 0.88 com
chutes no alvo sofridos) e nao seria melhorado por ser reescrito de forma
generica. O motor generico entra onde nao ha' medicao especifica.

O pipeline que amarra tudo fica em engine_pipelines/player_stats_pipeline.py.
"""
from services.player_stats_engine import (  # noqa: F401
    config,
    contradiction,
    count_model,
    decision,
    explanation,
    methods,
    minutes_model,
    opponent_model,
    player_history,
    quality,
    selection,
)

__all__ = ["config", "contradiction", "count_model", "decision", "explanation",
           "methods", "minutes_model", "opponent_model", "player_history",
           "quality", "selection"]
