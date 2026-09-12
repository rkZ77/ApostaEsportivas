"""HT_RISK_SCORE e TAIL_RISK -- o risco de a perna do intervalo quebrar.

O QUE A V1 ENXERGAVA DO PRIMEIRO TEMPO
--------------------------------------
Tres coisas, todas medias: a frequencia de Under 2.5 HT, a media de gols no
intervalo e a probabilidade do modelo. Nenhuma delas responde a pergunta que
derruba a pick, que e' de FORMATO da distribuicao, nao de nivel:

    dois primeiros tempos de 2 gols e oito de 0 gol
    dez primeiros tempos de 1 gol

Os dois times tem 10/10 de Under 2.5 HT e media 0,4 contra 1,0 -- e a V1
preferia o PRIMEIRO, porque a media dele e' menor. Mas e' o primeiro que tem
dois jogos encostados na linha e uma cauda que ja' se mostrou capaz de chegar
la'. Under 2.5 HT nao quebra por media alta; quebra por jogo que abre cedo.

DUAS MEDIDAS, PROPOSITALMENTE SEPARADAS
---------------------------------------
  HT_RISK_SCORE  o risco de nivel e de dispersao: projecao alta, 2+ gols
                 frequente, 3+ gols presente, jogos encostados na linha,
                 primeiro tempo irregular. E' o que bloqueia em 80.

  TAIL_RISK      so' a cauda: a concentracao exatamente em 2 gols e a
                 presenca de 3+. Ele existe separado porque e' o unico risco
                 que MELHORA a frequencia enquanto piora a aposta -- um 2 a 0
                 no intervalo conta como acerto do Under 2.5 e e' o aviso de
                 que o mesmo jogo, com um gol a mais, teria sido RED.

ESCALA (a pedida)
-----------------
    0-20 muito baixo · 21-40 baixo · 41-60 moderado · 61-80 alto · 81-100 critico
"""
from __future__ import annotations

from services.pick_engine_boost import config as cfg


def _faixa(valor, inicio: float, fim: float) -> float:
    """0 no inicio, 1 no fim. None -> 0 (ausencia nao inventa risco)."""
    if valor is None or fim == inicio:
        return 0.0
    return max(0.0, min(1.0, (float(valor) - inicio) / (fim - inicio)))


def classificar(score: float) -> str:
    if score >= 81:
        return "CRITICO"
    if score >= 61:
        return "ALTO"
    if score >= 41:
        return "MODERADO"
    if score >= 21:
        return "BAIXO"
    return "MUITO_BAIXO"


def calcular(lambda_ht: float | None, dist_ht: dict) -> dict:
    """HT_RISK_SCORE 0-100, com as parcelas abertas.

    `dist_ht` e' a distribuicao agregada dos dois times, montada em
    `stats_model.distribuicao_ht`: freq_2mais, freq_3mais, freq_exatos_2,
    desvio, n.
    """
    componentes = {
        "projecao_ht": _faixa(lambda_ht, *cfg.FAIXA_LAMBDA_HT) * cfg.PESO_RISCO_LAMBDA_HT,
        "freq_2mais": _faixa(dist_ht.get("freq_2mais"), *cfg.FAIXA_FREQ_2MAIS_HT) * cfg.PESO_RISCO_FREQ_2MAIS,
        "freq_3mais": _faixa(dist_ht.get("freq_3mais"), *cfg.FAIXA_FREQ_3MAIS_HT) * cfg.PESO_RISCO_FREQ_3MAIS,
        "encostados_na_linha": _faixa(dist_ht.get("freq_exatos_2"), *cfg.FAIXA_CONCENTRACAO_2) * cfg.PESO_RISCO_CONCENTRACAO_2,
        # Dispersao RELATIVA (variancia/media). Ver stats_model.distribuicao_ht:
        # o desvio cru pune o primeiro tempo normal por ser normal.
        "dispersao": _faixa(dist_ht.get("dispersao_relativa"), *cfg.FAIXA_DISPERSAO_HT) * cfg.PESO_RISCO_DISPERSAO_HT,
    }
    total = round(sum(componentes.values()), 1)
    return {
        "score": total,
        "classe": classificar(total),
        "componentes": {k: round(v, 2) for k, v in componentes.items()},
        "bloqueia": total >= cfg.HT_RISK_BLOQUEIA,
        "penaliza": total >= cfg.HT_RISK_PENALIZA,
    }


def tail_risk(dist_ht: dict) -> dict:
    """A cauda, isolada. 0-100.

    `concentracao` e' a fatia dos acertos de Under 2.5 HT que parou EXATAMENTE
    em 2 gols -- a pergunta literal do enunciado. Quando nao ha acerto nenhum
    ela nao existe, e nao vira zero: um time sem acerto nao tem cauda boa, tem
    problema maior, e quem responde por ele e' a frequencia.
    """
    acertos = dist_ht.get("acertos_under25") or 0
    exatos_2 = dist_ht.get("jogos_exatos_2") or 0
    concentracao = round(exatos_2 / acertos, 4) if acertos else None

    componentes = {
        "concentracao_em_2": _faixa(concentracao, 0.15, 0.55) * 50,
        "freq_3mais": _faixa(dist_ht.get("freq_3mais"), *cfg.FAIXA_FREQ_3MAIS_HT) * 30,
        "pior_caso": _faixa(dist_ht.get("max_ht"), 2, 5) * 20,
    }
    total = round(sum(componentes.values()), 1)
    return {
        "score": total,
        "concentracao_em_2": concentracao,
        "componentes": {k: round(v, 2) for k, v in componentes.items()},
        "bloqueia": total >= cfg.TAIL_RISK_BLOQUEIA,
    }
