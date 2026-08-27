"""Player Stats -- motor de estatistica INDIVIDUAL de jogador.

Absorve o antigo motor de Defesas de Goleiro como um metodo (`saves`) e abre a
mesma estrutura pra chutes, chutes no alvo, faltas, desarmes e passes. Mercado
novo = uma entrada em methods.METODOS, nao um pipeline novo.

    methods         o catalogo: coluna, mercados, amostra minima, cargo
    player_history  leitura de player_match_stats (com filtro de minutos)
    count_model     probabilidade por Binomial Negativa, com dispersao MEDIDA
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
    count_model,
    explanation,
    methods,
    player_history,
)

__all__ = ["config", "count_model", "explanation", "methods", "player_history"]
