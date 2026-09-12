"""Cobertura de dados: quanto do que o motor precisa existia de verdade.

O DEFEITO QUE ISTO FECHA (auditado em 2026-09-11)
-------------------------------------------------
O motor ao vivo trata ausencia com cuidado em tres lugares -- e em nenhum
deles ela CUSTA alguma coisa:

  pressure_model   componente nao publicado sai da conta e os pesos dos que
                   sobraram sao RENORMALIZADOS. Uma pressao feita de 2 dos 7
                   componentes sai com a mesma cara e a mesma escala de uma
                   feita de 7. O rastro registra `sinais_disponiveis`, e nada
                   le' esse numero depois.

  signal_score     sinal indisponivel sai de `soma_pesos`. Com 4 dos 7 sinais
                   ausentes, os 3 que sobraram definem 100% da convergencia --
                   e um score de 0.9 feito de 3 sinais e' publicado como igual
                   a um score de 0.9 feito de 7.

  tendencia        INDEFINIDA ("nao ha evidencia") devolvia None, que e' o
                   MESMO caminho de "o provedor nao publicou". Os dois viravam
                   renormalizacao, e "nao sei" acabava valendo tanto quanto
                   "nao se aplica".

Renormalizar e' a conta certa -- preencher com zero seria pior, porque
afirmaria que o time nao atacou. O erro nao esta' na renormalizacao, esta' em
ela ser DE GRACA. Este modulo cobra o preco: mede a cobertura, desconta a
confianca proporcionalmente e, abaixo de um minimo, recusa o pick.

A ESCALA, QUE E' A PEDIDA
-------------------------
    >= 0.90  excelente     0.80-0.89  boa
    0.70-0.79 limitada     < 0.70     insuficiente -> NO_PICK

O QUE ELE NAO FAZ
-----------------
Nao le banco nem API. Recebe a analise pronta e devolve numeros.
"""
from __future__ import annotations

from services.pick_engine_live import rhythm_model as rit
from services.pick_engine_live.live_state import DELAYED, FRESH, STALE, UNKNOWN

#: Peso de cada insumo na cobertura. A ordem e' quanto o motor DEPENDE dele:
#: sem o contador da familia nao existe estimativa nenhuma, enquanto a
#: qualidade da chance so' refina.
#:
#: Declarados, nao medidos. Ficam aqui pra serem calibrados contra resultado
#: quando houver amostra por faixa de cobertura -- que e' a medicao que o
#: proprio numero torna possivel, porque ate' hoje ela nao era gravada.
PESOS = {
    "contador_da_familia": 0.22,
    "pressao": 0.18,
    "historico_contextual": 0.18,
    "janela_recente": 0.14,
    "tendencia": 0.12,
    "freshness": 0.10,
    "prob_mercado": 0.06,
}

FATOR_FRESHNESS = {FRESH: 1.0, DELAYED: 0.55, UNKNOWN: 0.25, STALE: 0.0}

EXCELENTE, BOA, LIMITADA, INSUFICIENTE = "EXCELENTE", "BOA", "LIMITADA", "INSUFICIENTE"


def _classificar(cobertura: float) -> str:
    if cobertura >= 0.90:
        return EXCELENTE
    if cobertura >= 0.80:
        return BOA
    if cobertura >= 0.70:
        return LIMITADA
    return INSUFICIENTE


def cobertura(info_familia: dict, pressao: dict | None, fresh: dict | None,
              historico: dict | None = None,
              prob_mercado: float | None = None) -> dict:
    """Fracao [0,1] do que o motor precisava e tinha, com o que faltou nomeado.

    Cada insumo entra com um valor PARCIAL quando ele existe pela metade --
    pressao com 3 dos 7 componentes entra com a fracao de peso coberta, nao
    com 1.0. E' isso que distingue este numero de um checklist de presenca.
    """
    parciais: dict[str, float] = {}
    faltando: list[str] = []

    parciais["contador_da_familia"] = 1.0 if info_familia.get("disponivel") else 0.0
    if not info_familia.get("disponivel"):
        faltando.append(f"contador da familia ({info_familia.get('motivo')})")

    lados = [(pressao or {}).get("home") or {}, (pressao or {}).get("away") or {}]
    cobertos = [l.get("peso_coberto") for l in lados if l.get("peso_coberto")]
    if (pressao or {}).get("total") is None or not cobertos:
        parciais["pressao"] = 0.0
        faltando.append("pressao ofensiva (folha sem contador ofensivo)")
    else:
        parciais["pressao"] = round(min(1.0, sum(cobertos) / len(cobertos)), 4)
        if parciais["pressao"] < 0.7:
            faltando.append(
                f"pressao parcial ({parciais['pressao']:.0%} dos componentes)")

    hist_cob = (historico or {}).get("cobertura")
    if hist_cob is None:
        parciais["historico_contextual"] = 0.0
        faltando.append("historico por mando (sem amostra nos dois lados)")
    else:
        parciais["historico_contextual"] = round(float(hist_cob), 4)
        if hist_cob < 0.7:
            faltando.append(f"historico parcial ({hist_cob:.0%} dos componentes)")

    janela = (info_familia.get("janelas") or {}).get("principal")
    parciais["janela_recente"] = 1.0 if janela else 0.0
    if not janela:
        faltando.append("janela recente (falta observacao anterior desta partida)")

    # TENDENCIA INDEFINIDA NAO E' NEUTRA -- e' ausencia de evidencia, e aqui
    # ela custa o peso inteiro em vez de sumir do denominador.
    rotulo = (info_familia.get("tendencia") or {}).get("rotulo")
    if rotulo in (rit.ACELERANDO, rit.DESACELERANDO, rit.ESTAVEL):
        parciais["tendencia"] = 1.0
    else:
        parciais["tendencia"] = 0.0
        faltando.append("tendencia INDEFINIDA (sem duas leituras comparaveis)")

    nivel = (fresh or {}).get("nivel")
    parciais["freshness"] = FATOR_FRESHNESS.get(nivel, 0.25)
    if parciais["freshness"] < 1.0:
        faltando.append(f"qualidade do feed {nivel}")

    parciais["prob_mercado"] = 1.0 if prob_mercado is not None else 0.0
    if prob_mercado is None:
        faltando.append("probabilidade no-vig do mercado (linha sem par cotado)")

    total = sum(PESOS[nome] * valor for nome, valor in parciais.items())
    total = round(total / sum(PESOS.values()), 4)
    return {
        "coverage": total,
        "classe": _classificar(total),
        "missing": faltando,
        "parciais": {n: round(v, 4) for n, v in parciais.items()},
        "pesos": dict(PESOS),
    }


#: Piso e teto do desconto de confianca por cobertura. Cobertura 1.0 nao
#: PREMIA (fator 1.0 e' o maximo) -- dado completo e' o esperado, nao um bonus.
#: Cobertura 0.70, que e' o minimo aceitavel, ja' custa 12% da confianca.
FATOR_MINIMO = 0.55


def fator_de_confianca(coverage: float) -> float:
    """Multiplicador de confianca pela cobertura.

    Linear entre FATOR_MINIMO (cobertura 0) e 1.0 (cobertura 1), porque nao
    ha' medicao que justifique uma curva -- e uma curva inventada aqui seria
    um segundo parametro nao medido escondido dentro do primeiro.
    """
    c = max(0.0, min(1.0, float(coverage or 0.0)))
    return round(FATOR_MINIMO + (1.0 - FATOR_MINIMO) * c, 4)
