"""Motor de Picks Ao Vivo (V1).

Sistema PARALELO ao motor pre-jogo (services/pick_engine), nao um ramo dele.
Tabela propria, configuracao propria, estatistica propria. O precedente
arquitetural sao os pipelines de faltas e defesas de goleiro, que ja usam
modelo proprio e gravam na propria tabela sem passar pelo caminho generico.

A FILOSOFIA, QUE E' O QUE SEPARA OS DOIS MOTORES
------------------------------------------------
    O pre-jogo tenta PREVER a partida.  Olha o que normalmente acontece.
    O Live tenta ENTENDER a partida.    Olha o que esta acontecendo agora.

O historico pre-jogo entra como BASELINE, nao como resposta. O que decide e' o
comportamento observado: pressao mostra quem esta dominando, ritmo mostra se o
jogo acelera ou desacelera, os eventos mostram mudanca de estado, o tempo
restante define o espaco pra novos eventos, a linha mostra o que o mercado
oferece e a odd diz se ha valor.

OS MODULOS
----------
    live_feed        transporte + ORCAMENTO RIGIDO de requisicao
    live_state       estado completo, eventos e freshness (FRESH/DELAYED/STALE)
    pressure_model   pressao ofensiva por equipe
    rhythm_model     ritmo, janelas recentes e tendencia
    need_model       quem precisa do resultado AGORA (agregado ao vivo, tabela)
    residual_model   lambda do que ainda falta acontecer
    signal_score     convergencia de sinais e confianca Live
    live_odds        leitura de /odds/live e pares sem vig
    orchestrator     analisar -> triagem -> avaliar

O CONTEXTO PRE-JOGO E' REGRA, NAO RESPOSTA (2026-08-14)
------------------------------------------------------
`analisar` aceita `contexto_pre_jogo` (saida de context_gate.build_for_fixture)
e o usa apenas pra saber o REGULAMENTO da partida: qual o agregado da ida,
quem se classifica com o que, quanto cada lado precisava de pontos na tabela.
Quem responde "e o que esta' acontecendo" continua sendo o campo -- need_model
recalcula a necessidade contra o placar de agora a cada passada, e
`confirma_o_contexto` DESCONTA a leitura quando quem deveria estar pressionando
nao esta'. Contexto que o jogo desmente vale menos que contexto nenhum.

O que e' COMPARTILHADO com o pre-jogo, e por que:
  - services/settlement.py         a matematica de resultado do projeto e' uma
                                   so'. Duas divergem, e essa licao ja foi paga.
  - pick_engine/probability_model  Poisson e' Poisson.
  - pick_engine/market_model       no-vig, edge e EV nao mudam ao vivo.
"""
from services.pick_engine_live.config import (  # noqa: F401
    DEFAULT_LIVE_CONFIG, ENGINE_VERSION, AmbienteInvalido, LiveEngineConfig,
    exigir_ambiente_dev,
)
from services.pick_engine_live.orchestrator import (  # noqa: F401
    analisar, avaliar, melhor_candidato, observado_da_familia, triagem,
)

__all__ = [
    "DEFAULT_LIVE_CONFIG", "ENGINE_VERSION", "AmbienteInvalido",
    "LiveEngineConfig", "exigir_ambiente_dev",
    "analisar", "avaliar", "melhor_candidato", "observado_da_familia", "triagem",
]
