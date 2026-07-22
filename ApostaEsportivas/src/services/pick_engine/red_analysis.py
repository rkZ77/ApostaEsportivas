"""Classifica o motivo de uma pick RED antes dela alimentar a calibracao
(services/pick_engine/calibration.py) -- distingue "erro real" (o motor tinha
os dados e errou de forma sistematica, deve puxar a calibracao pra baixo) de
"nao tinha o que fazer" (evento em campo que nenhuma analise pre-jogo
capturaria, ou risco que o proprio motor ja tinha sinalizado antes do jogo).
Sem essa distincao, a calibracao aprenderia com ruido (variancia normal do
esporte) tanto quanto com sinal real (vies sistematico do modelo), degradando
em vez de melhorar o proprio motor -- pedido explicito do usuario."""

_CATEGORIES = ("erro_real", "evento_atipico", "variancia_esperada", "sem_dado")


def classify_miss(engine_debug: dict | None, red_cards_in_match: int | None) -> dict:
    """Categoriza uma pick RED:

    - sem_dado: pick anterior a esta feature, sem retrato salvo no momento
      da escolha (services/pick_engine/homologation.py::build_score_breakdown_section) --
      nao da pra saber o que o motor sabia, entao nao classifica.
    - evento_atipico: o jogo teve cartao(oes) vermelho(s) -- divisor de aguas
      bem estabelecido (muda posse/intensidade/contagens pro resto do jogo),
      e o unico sinal concreto de "evento em campo que o modelo pre-jogo nao
      tinha como prever" que o sistema coleta hoje. NAO sabemos o minuto do
      cartao (so a contagem final) -- um vermelho aos 88' quase nao muda
      nada, mas essa distincao exigiria coletar eventos de partida, fora de
      escopo aqui.
    - variancia_esperada: o motor ja tinha descontado confidence por
      dispersao historica alta (variancia.penalidade_aplicada > 0 no
      retrato) -- a perda ja era um risco assumido e sinalizado antes do
      jogo, nao e' um sinal NOVO de erro sistematico.
    - erro_real: nenhum dos sinais acima -- o motor declarou confianca sem
      ressalva de variancia e o jogo nao teve evento disruptivo conhecido;
      esse SIM deve contar contra a calibracao do mercado.
    """
    if not engine_debug:
        return {"category": "sem_dado", "reasons": ["pick sem engine_debug salvo (anterior a esta feature)"]}

    if red_cards_in_match:
        return {
            "category": "evento_atipico",
            "reasons": [f"{red_cards_in_match} cartão(ões) vermelho(s) no jogo (minuto não rastreado)"],
        }

    penalidade = (engine_debug.get("variancia") or {}).get("penalidade_aplicada") or 0
    if penalidade > 0:
        return {
            "category": "variancia_esperada",
            "reasons": [f"motor já descontava confidence por dispersão histórica alta (penalidade={penalidade})"],
        }

    return {"category": "erro_real", "reasons": ["sem sinal de evento atípico ou variância já sinalizada"]}
