"""Score Estatistico do Pick Boost -- 0 a 100.

O QUE ELE E'
------------
Uma soma de dez parcelas, cada uma valendo entre 0 e o seu peso
(config.PESO_*). Nenhuma parcela e' multiplicativa e nenhuma pode zerar o
Score sozinha: o corte por criterio duro acontece ANTES, no pipeline (amostra
minima, faixa de odd, probabilidade minima). Aqui e' so' ordenacao.

A ODD NAO ENTRA. Foi pedido explicito, e e' o que separa este metodo dos
outros do projeto: o Score responde "quao forte e' este jogo pra esta
combinacao", nao "quao bem pago esta'". Odd, odd justa e EV sao gravados junto
e exibidos, como informacao secundaria.

POR QUE CADA PARCELA E' NORMALIZADA POR FAIXA, E NAO LINEARMENTE
----------------------------------------------------------------
Frequencia de Over 1.5 e' 100% do peso em 9/10 e 0% em 5/10 -- mas 5/10 nao e'
"metade de bom", e' irrelevante, porque 50% de Over 1.5 esta' abaixo da media
de qualquer liga. Escalar linearmente de 0 a 1 daria meio peso a um jogo que
nao tem nada. Cada `_faixa` abaixo comeca no ponto em que o indicador comeca a
querer dizer alguma coisa.

Os pontos de corte sao julgamento declarado, nao medicao -- este metodo nasce
em 27/08/2026 e nao tem historico proprio ainda. Estao todos em UM lugar por
isso: quando houver resultado medido, o ajuste e' aqui.
"""
from __future__ import annotations

from services.pick_engine_boost import config as cfg


def _faixa(valor, piso: float, teto: float) -> float:
    """0 no piso, 1 no teto, linear entre eles. None -> 0.

    Valor abaixo do piso vale zero, e nao negativo: uma parcela nunca tira
    ponto de outra. O Score e' um somatorio de evidencias a favor.
    """
    if valor is None:
        return 0.0
    v = float(valor)
    if teto == piso:
        return 0.0
    return max(0.0, min(1.0, (v - piso) / (teto - piso)))


def _faixa_invertida(valor, teto_bom: float, piso_ruim: float) -> float:
    """1 quando o valor e' BAIXO (bom) e 0 quando e' alto. Ver media de gols HT."""
    if valor is None:
        return 0.0
    v = float(valor)
    if piso_ruim == teto_bom:
        return 0.0
    return max(0.0, min(1.0, (piso_ruim - v) / (piso_ruim - teto_bom)))


def calcular(confronto: dict, perfil_home: dict, perfil_away: dict) -> dict:
    """Score 0-100 com as parcelas abertas.

    Devolve as parcelas junto do total de proposito: sem elas, "Score 87" e'
    um numero sem argumento, e a tela "Por que essa pick?" nao teria o que
    mostrar alem de repetir o proprio score.
    """
    ad = confronto.get("ataque_defesa") or {}
    tend = confronto.get("tendencia") or {}
    cons = confronto.get("consistencia") or {}

    # -- Over 1.5 FT ---------------------------------------------------------
    # 60% dos jogos = piso (media folgada de qualquer liga), 95% = teto.
    p_freq_over = _faixa(confronto.get("freq_over15"), 0.60, 0.95)
    # Media de gols: 2.2 e' jogo comum, 3.4 e' jogo de gol.
    media_gols = (perfil_home.get("media_gols_total"), perfil_away.get("media_gols_total"))
    media_gols = [float(m) for m in media_gols if m is not None]
    p_media = _faixa(sum(media_gols) / len(media_gols) if media_gols else None, 2.2, 3.4)
    # Ataque x defesa: a soma dos quatro numeros e' o gol esperado do jogo por
    # outro caminho. 2.0 piso, 3.6 teto.
    soma_ad = [v for v in ad.values() if v is not None]
    p_ad = _faixa(sum(float(v) for v in soma_ad) if len(soma_ad) == 4 else None, 2.0, 3.6)
    # Desempenho no mando: as duas frequencias de Over 1.5 no mando de hoje.
    mando = [perfil_home.get("freq_over15_mando"), perfil_away.get("freq_over15_mando")]
    mando = [float(m) for m in mando if m is not None]
    p_mando = _faixa(sum(mando) / len(mando) if mando else None, 0.60, 0.95)
    p_modelo_ft = _faixa(confronto.get("prob_modelo_ft"), 0.70, 0.93)

    # -- Under 2.5 HT --------------------------------------------------------
    # 70% e' quase o basal (a maioria dos primeiros tempos tem 2 gols ou
    # menos), entao o piso e' alto: so' pontua quem esta' claramente acima.
    p_freq_under_ht = _faixa(confronto.get("freq_under25_ht"), 0.70, 0.97)
    # Media de gols no primeiro tempo: INVERTIDA -- quanto menos, melhor.
    p_media_ht = _faixa_invertida(confronto.get("lambda_ht"), 0.75, 1.60)
    p_modelo_ht = _faixa(confronto.get("prob_modelo_ht"), 0.70, 0.95)

    # -- Tendencia -----------------------------------------------------------
    # Media dos dois deltas que importam. Zero delta = metade do peso: os
    # ultimos 5 CONFIRMANDO os ultimos 10 e' bom, e o que este termo procura e'
    # a diferenca entre confirmar e contradizer, nao a ausencia de mudanca.
    deltas = [tend.get("over15"), tend.get("under25_ht")]
    deltas = [float(d) for d in deltas if d is not None]
    p_tendencia = _faixa(sum(deltas) / len(deltas) if deltas else 0.0, -0.20, 0.20)

    # -- Consistencia --------------------------------------------------------
    # Duas metades: amostra (o elo mais fraco) e dispersao (invertida).
    p_amostra = (_faixa(cons.get("min_amostra_ft"), cfg.MIN_JOGOS_FT, cfg.JANELA_LONGA) * 0.5
                 + _faixa(cons.get("min_amostra_ht"), cfg.MIN_JOGOS_HT, cfg.JANELA_LONGA) * 0.5)
    p_dispersao = _faixa_invertida(cons.get("desvio_medio_gols"), 1.0, 2.2)
    p_consistencia = p_amostra * 0.6 + p_dispersao * 0.4

    parcelas = {
        "freq_over15":     round(p_freq_over * cfg.PESO_FREQ_OVER15, 2),
        "media_gols":      round(p_media * cfg.PESO_MEDIA_GOLS, 2),
        "ataque_defesa":   round(p_ad * cfg.PESO_ATAQUE_DEFESA, 2),
        "mando":           round(p_mando * cfg.PESO_MANDO, 2),
        "freq_under25_ht": round(p_freq_under_ht * cfg.PESO_FREQ_UNDER25_HT, 2),
        "media_ht":        round(p_media_ht * cfg.PESO_MEDIA_HT, 2),
        "modelo_ft":       round(p_modelo_ft * cfg.PESO_MODELO_FT, 2),
        "modelo_ht":       round(p_modelo_ht * cfg.PESO_MODELO_HT, 2),
        "tendencia":       round(p_tendencia * cfg.PESO_TENDENCIA, 2),
        "consistencia":    round(p_consistencia * cfg.PESO_CONSISTENCIA, 2),
    }
    total = round(sum(parcelas.values()), 1)

    return {
        "score": total,
        "parcelas": parcelas,
        # Onde o jogo perdeu ponto, em ordem. E' o que vira o motivo de
        # descarte legivel -- "Score 64" nao explica nada; "frequencia de
        # Under 2.5 HT abaixo do minimo" explica.
        "pontos_fracos": _pontos_fracos(parcelas),
    }


#: Rotulo humano de cada parcela. Fica junto do calculo pra o motivo de
#: descarte nao ser escrito de novo (e diferente) em cada tela.
ROTULOS = {
    "freq_over15": "frequência de Over 1.5 FT",
    "media_gols": "média de gols dos dois times",
    "ataque_defesa": "ataque contra defesa dos dois lados",
    "mando": "desempenho no mando (casa/fora)",
    "freq_under25_ht": "frequência de Under 2.5 HT",
    "media_ht": "média de gols no primeiro tempo",
    "modelo_ft": "probabilidade do modelo para Over 1.5",
    "modelo_ht": "probabilidade do modelo para Under 2.5 HT",
    "tendencia": "tendência dos últimos 5 jogos",
    "consistencia": "consistência dos dados (amostra e dispersão)",
}

#: Peso maximo de cada parcela, pra medir aproveitamento em vez de valor
#: absoluto -- uma parcela de peso 6 nunca pareceria fraca ao lado de uma de
#: peso 18 se a comparacao fosse pelo numero cru.
_PESOS = {
    "freq_over15": cfg.PESO_FREQ_OVER15, "media_gols": cfg.PESO_MEDIA_GOLS,
    "ataque_defesa": cfg.PESO_ATAQUE_DEFESA, "mando": cfg.PESO_MANDO,
    "freq_under25_ht": cfg.PESO_FREQ_UNDER25_HT, "media_ht": cfg.PESO_MEDIA_HT,
    "modelo_ft": cfg.PESO_MODELO_FT, "modelo_ht": cfg.PESO_MODELO_HT,
    "tendencia": cfg.PESO_TENDENCIA, "consistencia": cfg.PESO_CONSISTENCIA,
}


def _pontos_fracos(parcelas: dict, limite: float = 0.45) -> list:
    """As parcelas que aproveitaram menos de `limite` do peso, piores antes."""
    fracos = []
    for chave, valor in parcelas.items():
        peso = _PESOS.get(chave) or 0
        if not peso:
            continue
        aproveitamento = valor / peso
        if aproveitamento < limite:
            fracos.append({"chave": chave, "rotulo": ROTULOS.get(chave, chave),
                           "aproveitamento": round(aproveitamento, 3)})
    return sorted(fracos, key=lambda f: f["aproveitamento"])


def motivo_do_descarte(resultado: dict) -> str:
    """Frase curta e estavel pro campo `reason` de engine_decisions.

    Estavel porque vira GROUP BY depois ("onde os jogos estao morrendo?"),
    mesma regra das constantes MOTIVO_* do decision_log.
    """
    fracos = resultado.get("pontos_fracos") or []
    if not fracos:
        return f"Score {resultado.get('score')} abaixo do mínimo de {cfg.SCORE_MINIMO}"
    return (f"Score {resultado.get('score')} · {fracos[0]['rotulo']} abaixo do mínimo")
