"""Probabilidade calibrada -- e por que ela esta' DESLIGADA.

O PEDIDO
--------
"Se o motor produz 70-75% e essas picks acertam 60%, a probabilidade esta'
inflada; aplique CALIBRATED_PROBABILITY." A conta e' trivial. O que nao e'
trivial e' ter o direito de aplica-la.

A POSICAO DO PROJETO, QUE JA' CUSTOU UMA MEDICAO
------------------------------------------------
Este projeto ja' construiu uma camada probabilistica (isotonica e correcao de
vies de selecao) e a REPROVOU por medicao: ligada, ela piorou. A licao ficou
escrita -- camada probabilistica entra MEDIDA, nunca por argumento.

O Pick Boost publica desde 27/08 e nao tem picks liquidados suficientes por
faixa. Ligar uma calibracao agora seria escolher os numeros a dedo e chamar de
correcao.

ENTAO O QUE ESTE MODULO FAZ
---------------------------
Tres coisas, e nenhuma delas e' inventar numero:

  1. com `cfg.CALIBRACAO_MEDIDA` vazia, devolve a propria probabilidade e diz
     `fonte = "sem_medicao"`. A porta de calibracao (Gate 8) nao reprova
     ninguem nesse estado, e isso esta' declarado em vez de escondido;
  2. com a tabela preenchida pelo backtest, aplica a correcao pela METADE
     (cfg.FATOR_CALIBRACAO) -- o resto do caminho e' passado, e ir 100% nele
     e' ajustar o motor ao proprio teste;
  3. separa PROBABILIDADE de CONFIANCA, que era o outro pedido. Sao coisas
     diferentes: probabilidade e' a chance estimada do evento, confianca e' a
     qualidade da evidencia que produziu a estimativa. 76% de probabilidade
     com 58% de confianca e' uma frase coerente, e ate' 11/09 este motor
     gravava o MESMO numero nas duas colunas (`confidence` e `prob_real` do
     INSERT recebiam `prob`).
"""
from __future__ import annotations

from services.pick_engine_boost import config as cfg


def faixa_medida(prob: float) -> dict | None:
    """A linha da tabela de calibracao que cobre esta probabilidade."""
    for piso, teto, taxa_real, n in cfg.CALIBRACAO_MEDIDA or ():
        if piso <= prob < teto and n >= cfg.MIN_AMOSTRA_CALIBRACAO:
            return {"piso": piso, "teto": teto, "taxa_real": taxa_real, "n": n}
    return None


def calibrar(prob: float | None) -> dict:
    """{'prob': ..., 'fonte': ..., 'deslocamento': ...}."""
    if prob is None:
        return {"prob": None, "fonte": "sem_probabilidade", "deslocamento": None}
    faixa = faixa_medida(float(prob))
    if not faixa:
        return {"prob": round(float(prob), 4), "fonte": "sem_medicao",
                "deslocamento": 0.0, "faixa": None}
    alvo = float(faixa["taxa_real"])
    corrigida = float(prob) + (alvo - float(prob)) * cfg.FATOR_CALIBRACAO
    corrigida = max(0.0, min(1.0, corrigida))
    return {"prob": round(corrigida, 4), "fonte": "medida",
            "deslocamento": round(corrigida - float(prob), 4), "faixa": faixa}


def confianca(prob: float | None, qualidade: dict, convergencia: dict,
              amostra_classe: str, divergencia: float | None) -> float | None:
    """A CONFIANCA -- qualidade da evidencia, nao chance do evento.

    Comeca na probabilidade e e' descontada por tudo que enfraquece a
    evidencia. Nunca sobe acima da probabilidade: evidencia boa confirma a
    estimativa, nao a melhora.
    """
    if prob is None:
        return None
    fator = 1.0
    fator *= 0.6 + 0.4 * ((qualidade.get("score") or 0) / 100)
    frac = convergencia.get("fracao")
    fator *= 0.7 + 0.3 * (float(frac) if frac is not None else 0.0)
    fator *= {"FORTE": 1.0, "BOA": 0.97, "RAZOAVEL": 0.93,
              "LIMITADA": 0.86, "MUITO_FRACA": 0.78}.get(amostra_classe, 0.70)
    if divergencia is not None:
        excesso = max(0.0, abs(float(divergencia)) - cfg.DIVERGENCIA_PENALIZA)
        fator *= max(0.70, 1.0 - excesso * 2)
    return round(float(prob) * max(0.0, min(1.0, fator)), 4)
