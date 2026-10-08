"""
medir_primeiro_tempo.py · o 1o tempo esta' derrubando o acerto do site?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso (da pasta onde esta' o .env.prod):
  python ApostaEsportivas/src/scripts/medir_primeiro_tempo.py [desde AAAA-MM-DD]

POR QUE ESTE SCRIPT (2026-10-08). O usuario viu queda de acerto nos ultimos
dias, com muito pick de 1o tempo em todos os produtos. O 1o tempo entrou no
motor em 27/09 sem medicao, e o medir_calibracao_dos_picks.py nao tinha como
mostrar: ele junta "corners_1h" em "corners" (`replace("_1h", "")`), entao o
desempenho do 1o tempo ficava escondido dentro do jogo inteiro.

Aqui o 1o tempo e' separado do resto, pelo market_type (_1h) ou pelo texto do
mercado. O Boost fica a parte: a perna de intervalo dele e' outro modelo
(pick_boost_pipeline) e nao passa pela chave MOTOR_1T.

Se o 1o tempo perde dinheiro e o resto nao, a acao e' imediata e sem deploy:
MOTOR_1T=off no ambiente onde o motor roda (ver orchestrator.modo_1t).
"""
from __future__ import annotations

import math
import os
import re
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

_TEXTO_1T = re.compile(r"1[ºo°]\s*tempo|primeiro tempo|1st half|first half|\(ht\)|\bht\b", re.I)


def e_primeiro_tempo(perna: dict) -> bool:
    if (perna.get("market_type") or "").endswith(("_1h", "_ht")):
        return True
    return bool(_TEXTO_1T.search(perna.get("market") or ""))


def carregar(desde: date) -> list:
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""
        SELECT pick_type, market, market_type, line, probability, odd, result, match_date
          FROM picks_ledger
         WHERE match_date >= %s
    """, (desde,))
    cols = [d[0] for d in cur.description]
    linhas = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return linhas


def resumo(pernas: list) -> dict | None:
    dec = [p for p in pernas if p["result"] in ("GREEN", "RED") and p.get("odd") and float(p["odd"]) > 1]
    n = len(dec)
    if not n:
        return None
    ac = sum(1 for p in dec if p["result"] == "GREEN") / n
    rs = [(float(p["odd"]) - 1) if p["result"] == "GREEN" else -1.0 for p in dec]
    r = sum(rs) / n
    ep_r = math.sqrt(sum((x - r) ** 2 for x in rs) / max(n - 1, 1) / n) if n > 1 else 0.0
    probs = [float(p["probability"]) for p in dec if p.get("probability") is not None]
    probs = [x / 100 if x > 1 else x for x in probs]
    return {
        "n": n, "acerto": ac, "ep": math.sqrt(ac * (1 - ac) / n), "roi": r, "ep_roi": ep_r,
        "prob": sum(probs) / len(probs) if probs else None,
        "preco": sum(1 / float(p["odd"]) for p in dec) / n,
    }


def linha(rotulo: str, pernas: list) -> None:
    s = resumo(pernas)
    if not s:
        print(f"  {rotulo:30} {'-':>5}")
        return
    prob = "-" if s["prob"] is None else f"{s['prob']:.3f}"
    print(f"  {rotulo:30} {s['n']:>5} {prob:>6} {s['preco']:>6.3f} {s['acerto']:>7.3f} "
          f"{2 * s['ep']:>6.3f} {s['roi']:>+7.3f} {2 * s['ep_roi']:>6.3f}")


def cabecalho():
    print(f"  {'':30} {'n':>5} {'prob':>6} {'preco':>6} {'acerto':>7} {'±2ep':>6} {'ROI':>7} {'±2ep':>6}")


def main():
    desde = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 9, 20)
    todas = carregar(desde)
    if not todas:
        print("Nada no ledger desde", desde)
        return
    sem_boost = [p for p in todas if p["pick_type"] != "boost"]
    um_t = [p for p in sem_boost if e_primeiro_tempo(p)]
    resto = [p for p in sem_boost if not e_primeiro_tempo(p)]

    print(f"Pernas no ledger desde {desde}: {len(todas)} "
          f"(1o tempo: {len(um_t)}, resto: {len(resto)}, boost a parte: {len(todas) - len(sem_boost)})")

    print("\n=== 1. Volume por dia (todas as pernas, decididas ou nao) ===")
    por_dia = defaultdict(lambda: [0, 0])
    for p in sem_boost:
        por_dia[p["match_date"]][1 if e_primeiro_tempo(p) else 0] += 1
    print(f"  {'dia':12} {'resto':>6} {'1o tempo':>9} {'% 1T':>6}")
    for d in sorted(por_dia):
        r, u = por_dia[d]
        print(f"  {str(d):12} {r:>6} {u:>9} {u / (r + u):>6.0%}")

    print("\n=== 2. Resultado: 1o tempo x resto ===")
    cabecalho()
    linha("1o tempo", um_t)
    linha("resto (jogo inteiro etc.)", resto)
    linha("boost (perna HT propria)", [p for p in todas if p["pick_type"] == "boost"])

    print("\n=== 3. Por semana ===")
    cabecalho()
    semanas = sorted({p["match_date"].isocalendar()[:2] for p in sem_boost})
    for ano, sem in semanas:
        da_semana = [p for p in sem_boost if p["match_date"].isocalendar()[:2] == (ano, sem)]
        linha(f"S{sem} 1o tempo", [p for p in da_semana if e_primeiro_tempo(p)])
        linha(f"S{sem} resto", [p for p in da_semana if not e_primeiro_tempo(p)])

    print("\n=== 4. 1o tempo por produto ===")
    cabecalho()
    for tipo in sorted({p["pick_type"] for p in um_t}):
        linha(tipo, [p for p in um_t if p["pick_type"] == tipo])

    print("\n=== 5. 1o tempo por mercado e direcao ===")
    cabecalho()
    grupos = defaultdict(list)
    for p in um_t:
        direcao = "over" if re.match(r"\s*(over|mais)", p.get("line") or "", re.I) else \
                  "under" if re.match(r"\s*(under|menos)", p.get("line") or "", re.I) else "outro"
        grupos[(p.get("market_type") or "?", direcao)].append(p)
    for (mt, dr), ps in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
        linha(f"{mt} {dr}", ps)

    print("\n=== Leitura ===")
    u, r = resumo(um_t), resumo(resto)
    if not u or u["n"] < 30:
        print("  Menos de 30 pernas de 1o tempo decididas: ainda nao da' pra culpar nem absolver.")
    elif u["roi"] + 2 * u["ep_roi"] < 0:
        print("  1o tempo PERDE dinheiro com margem: desligar (MOTOR_1T=off).")
    elif r and u["roi"] < r["roi"] - 2 * u["ep_roi"]:
        print("  1o tempo rende claramente PIOR que o resto: desligar (MOTOR_1T=off) e medir de novo.")
    elif u["roi"] < 0:
        print("  1o tempo esta' negativo, mas dentro do ruido: candidato a desligar; "
              "rode de novo em uma semana ou desligue por precaucao.")
    else:
        print("  1o tempo nao e' o problema: a queda vem de outro lugar (veja a secao 3, 'resto').")


if __name__ == "__main__":
    main()
