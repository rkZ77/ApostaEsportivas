"""As contradicoes -- quando duas leituras do mesmo jogo se desmentem.

POR QUE ISTO NAO E' UMA PENALIDADE A MAIS
-----------------------------------------
Um somatorio de evidencias (que e' o que o Score e') nao tem como representar
desacordo: se o historico diz 90% e o modelo diz 65%, as duas parcelas
entregam pontos, a soma fica alta, e o Score sai dizendo "forte" sobre um jogo
em que as duas fontes discordam sobre o que vai acontecer. Media de duas
afirmacoes incompativeis nao e' uma afirmacao intermediaria -- e' a prova de
que pelo menos uma das duas esta' errada, e o motor nao sabe qual.

Por isso contradicao GRAVE bloqueia em vez de descontar.

GRAVE x LEVE
------------
Grave: as duas fontes se contradizem sobre o EVENTO. Leve: uma fonte esta'
fraca, mas nao contra. So' a grave bloqueia; a leve entra no rastro e custa
ponto pelo caminho normal (a fonte fraca ja' pontua menos na parcela dela).

MERCADO CONTRA MODELO NAO E' CONTRADICAO GRAVE AQUI
---------------------------------------------------
A faixa de odd ja' reprova os dois extremos, e a porta de EV ja' reprova o
jogo em que o mercado paga menos do que o modelo pede. Repetir isso como
contradicao grave seria bloquear duas vezes pelo mesmo motivo -- e ainda por
cima com o motor discordando de si mesmo sobre o que a odd significa (a nota
de config.py e' clara: odd alta e' alerta, nao qualidade).
"""
from __future__ import annotations

from services.pick_engine_boost import config as cfg

GRAVE = "GRAVE"
LEVE = "LEVE"


def _c(codigo: str, gravidade: str, texto: str) -> dict:
    return {"codigo": codigo, "gravidade": gravidade, "descricao": texto}


def detectar(confronto: dict, risco_ht: dict, ev: float | None,
             score_estatistico: float | None) -> dict:
    """Lista de contradicoes, com a mais grave primeiro.

    `ev` pode chegar None (jogo que morreu antes de a odd ser avaliada); nesse
    caso a contradicao de valor simplesmente nao e' testada, em vez de ser
    testada contra zero.
    """
    achados = []

    freq_ft = confronto.get("freq_over15")
    modelo_ft = confronto.get("prob_modelo_ft")
    if freq_ft is not None and modelo_ft is not None:
        if freq_ft >= 0.80 and modelo_ft < 0.70:
            achados.append(_c(
                "HISTORICO_FT_CONTRA_MODELO", GRAVE,
                f"Over 1.5 saiu em {freq_ft * 100:.0f}% do histórico, mas a projeção "
                f"de gols dá apenas {modelo_ft * 100:.0f}% para a mesma linha"))

    freq_ht = confronto.get("freq_under25_ht")
    lam_ht = confronto.get("lambda_ht")
    if freq_ht is not None and lam_ht is not None:
        if freq_ht >= 0.85 and float(lam_ht) >= 1.60:
            achados.append(_c(
                "HISTORICO_HT_CONTRA_PROJECAO", GRAVE,
                f"Under 2.5 HT saiu em {freq_ht * 100:.0f}% do histórico, mas o primeiro "
                f"tempo projeta {float(lam_ht):.2f} gol"))

    divergencia = confronto.get("divergencia_modelo_historico")
    if divergencia is not None and abs(float(divergencia)) > cfg.DIVERGENCIA_MAX:
        achados.append(_c(
            "MODELO_DIVERGE_DO_HISTORICO", GRAVE,
            f"modelo e histórico discordam em {abs(float(divergencia)) * 100:.0f} pontos "
            f"de probabilidade na combinação"))

    if ev is not None and ev <= cfg.EV_MINIMO and (score_estatistico or 0) >= cfg.SCORE_MINIMO:
        achados.append(_c(
            "SCORE_ALTO_COM_EV_NEGATIVO", GRAVE,
            f"Score {score_estatistico:.0f} com EV {ev * 100:+.1f}%: o jogo é forte e a "
            f"odd não paga por isso"))

    if risco_ht and risco_ht.get("penaliza") and (freq_ht or 0) >= 0.85:
        achados.append(_c(
            "FREQUENCIA_HT_ESCONDE_RISCO", LEVE,
            f"frequência de Under 2.5 HT alta com risco de primeiro tempo "
            f"{risco_ht.get('score')} ({risco_ht.get('classe')})"))

    tend = (confronto.get("tendencia") or {})
    deltas = [tend.get("over15"), tend.get("under25_ht")]
    deltas = [float(d) for d in deltas if d is not None]
    if deltas and sum(deltas) / len(deltas) <= -0.20:
        achados.append(_c(
            "TENDENCIA_CONTRA_A_BASE", LEVE,
            "os últimos 5 jogos contradizem os últimos 10 nas duas frequências"))

    achados.sort(key=lambda a: 0 if a["gravidade"] == GRAVE else 1)
    return {
        "achados": achados,
        "graves": [a for a in achados if a["gravidade"] == GRAVE],
        "bloqueia": any(a["gravidade"] == GRAVE for a in achados),
    }
