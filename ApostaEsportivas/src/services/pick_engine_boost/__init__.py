"""Pick Boost -- motor estatistico de UM metodo com DOIS mercados fixos.

    Over 1.5 gols FT  +  Under 2.5 gols HT

O motor NAO escolhe mercado. Ele escolhe JOGO: dado que a combinacao esta'
definida, quais partidas do dia melhor a sustentam. Isso inverte a pergunta
dos outros motores do projeto -- o Pre Live pontua mercados dentro de um jogo,
este pontua jogos dentro de um mercado -- e por isso ele nao reusa
analyze_fixture_markets nem o ranking generico: nao ha' o que ranquear entre
familias quando a familia e' uma so'.

O criterio e' FORCA ESTATISTICA. Odd, odd justa e EV sao gravados e exibidos,
mas nao entram no Score (ver score.py e a nota de config.py sobre por que a
odd alta e' alerta, e nao qualidade).

    goals_history  le gols de FT e de HT do banco, com o recorte por competicao
    stats_model    os indicadores (frequencias, medias, mando, tendencia...)
    score          Score Estatistico 0-100, com as parcelas abertas
    explanation    a justificativa, a partir dos mesmos numeros
    config         limiares, pesos e faixa de odd

O pipeline que amarra tudo e grava o pick fica em
engine_pipelines/pick_boost_pipeline.py.
"""
from services.pick_engine_boost import (  # noqa: F401
    config,
    explanation,
    goals_history,
    score,
    stats_model,
)

__all__ = ["config", "explanation", "goals_history", "score", "stats_model"]
