"""Recalibracao da probabilidade pelo proprio historico · EM SOMBRA (2026-10-08).

O QUE A MEDICAO MOSTROU. `medir_calibracao_dos_picks.py` em PROD, 850 pernas
desde 01/08: na faixa de 70-80% o motor promete 74,0% e acerta 66,8% (±4,9),
com o preco dizendo 64,6%. E' o unico achado fora da margem de erro. O motor
ainda bate o preco ali (ROI +4,3%), mas o valor e' ~2 pontos, nao os ~9 que
ele enxerga -- e a stake sugerida sai do valor enxergado.

POR QUE `calibration.py` NAO PEGA ISSO. Aquele ajuste olha o gap MEDIO por
mercado e so' age acima de 10 pontos. O excesso aqui mora numa faixa de
probabilidade (ele cresce com a confianca), e a media do mercado dilui.

O QUE ESTE MODULO FAZ. Uma curva prometido -> acontecido, por faixa, com o
acerto de cada faixa encolhido na direcao da propria promessa (`K`) e forcada a
crescer junto com a probabilidade (uma promessa maior nunca pode virar uma
probabilidade corrigida menor que a de uma promessa menor). `aplicar` interpola
a curva.

SOMBRA. O motor so' GRAVA `prob_recalibrada_sombra` no rastro; nenhuma
decisao muda. Quem diz se liga e' `scripts/medir_recalibracao.py`, que ajusta a
curva num periodo e testa no seguinte (descoberta x confirmacao por data).

Ao Vivo e Boost ficam fora da curva: tem modelo proprio, e o Ao Vivo saiu
calibrado na mesma medicao -- misturar puxaria a curva do pre-jogo pro lado
errado.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

FAIXAS = (0.50, 0.55, 0.62, 0.70, 0.80, 1.01)
#: Peso, em pernas, da promessa do motor dentro de cada faixa. Com 60, uma
#: faixa de 60 pernas fica no meio do caminho entre o prometido e o
#: acontecido; com 370 (a faixa 70-80 de hoje) o acontecido manda ~86%.
K_ENCOLHIMENTO = 60
MIN_POR_FAIXA = 20
TIPOS_FORA = ("live", "boost")
_CACHE_SEG = 6 * 3600
_cache: dict = {"em": 0.0, "curva": None}


def _prob(v) -> float | None:
    if v is None:
        return None
    p = float(v)
    return p / 100 if p > 1 else p


def ajustar_curva(pares, k: float = K_ENCOLHIMENTO, minimo: int = MIN_POR_FAIXA) -> list:
    """[(prob_prometida, acertou_bool)] -> [(x, y, n)] crescente em x e y.

    x = media prometida da faixa; y = acerto encolhido na direcao de x.
    Faixa com menos de `minimo` pernas fica de fora (a interpolacao cobre).
    """
    faixas = []
    for lo, hi in zip(FAIXAS, FAIXAS[1:]):
        dentro = [(p, a) for p, a in pares if p is not None and lo <= p < hi]
        n = len(dentro)
        if n < minimo:
            continue
        x = sum(p for p, _ in dentro) / n
        acertos = sum(1 for _, a in dentro if a)
        faixas.append([x, (acertos + k * x) / (n + k), n])

    # Pool-adjacent-violators: junta faixas vizinhas que quebrariam a ordem.
    blocos: list = []
    for f in faixas:
        blocos.append(list(f))
        while len(blocos) > 1 and blocos[-2][1] > blocos[-1][1]:
            b2, b1 = blocos.pop(), blocos.pop()
            n = b1[2] + b2[2]
            blocos.append([(b1[0] * b1[2] + b2[0] * b2[2]) / n,
                           (b1[1] * b1[2] + b2[1] * b2[2]) / n, n])
    return [(round(x, 4), round(y, 4), n) for x, y, n in blocos]


def aplicar(p, curva) -> float | None:
    """Probabilidade corrigida pela curva, ou None sem curva/sem p.

    Dentro da curva, interpola; fora das pontas, carrega a correcao da ponta
    mais proxima (deslocamento constante), em vez de inventar inclinacao.
    """
    p = _prob(p)
    if p is None or not curva:
        return None
    pts = sorted((x, y) for x, y, _ in curva)
    if p <= pts[0][0]:
        y = p + (pts[0][1] - pts[0][0])
    elif p >= pts[-1][0]:
        y = p + (pts[-1][1] - pts[-1][0])
    else:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= p <= x1:
                y = y0 + (y1 - y0) * (p - x0) / (x1 - x0) if x1 > x0 else y0
                break
    return round(min(max(y, 0.01), 0.99), 4)


def pares_do_ledger(cur, desde=None, ate=None) -> list:
    """(prob, acertou, odd, data) das pernas pre-jogo decididas do picks_ledger."""
    cur.execute("""
        SELECT probability, result, odd, match_date
          FROM picks_ledger
         WHERE result IN ('GREEN', 'RED') AND probability IS NOT NULL
           AND pick_type <> ALL(%s)
           AND (%s::date IS NULL OR match_date >= %s::date)
           AND (%s::date IS NULL OR match_date <  %s::date)
    """, (list(TIPOS_FORA), desde, desde, ate, ate))
    linhas = cur.fetchall()
    saida = []
    for r in linhas:
        r = r if isinstance(r, dict) else dict(zip(("probability", "result", "odd", "match_date"), r))
        saida.append((_prob(r["probability"]), r["result"] == "GREEN",
                      float(r["odd"]) if r.get("odd") else None, r["match_date"]))
    return saida


def curva_em_cache() -> list:
    """Curva dos ultimos 120 dias, recalculada no maximo a cada 6h. Nunca
    levanta: sombra nao pode derrubar o motor."""
    agora = time.time()
    if _cache["curva"] is not None and agora - _cache["em"] < _CACHE_SEG:
        return _cache["curva"]
    curva: list = []
    try:
        from utils.db_utils import get_connection
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT (NOW() - INTERVAL '120 days')::date")
            desde = cur.fetchone()[0]
            curva = ajustar_curva([(p, a) for p, a, _, _ in pares_do_ledger(cur, desde=desde)])
            cur.close()
        finally:
            conn.close()
    except Exception:
        logger.warning("[RECALIBRACAO] curva indisponivel", exc_info=True)
    _cache.update(em=agora, curva=curva)
    return curva
