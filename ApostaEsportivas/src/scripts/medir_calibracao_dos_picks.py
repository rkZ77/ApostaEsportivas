"""
medir_calibracao_dos_picks.py · o motor acerta o que promete NOS PICKS?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_calibracao_dos_picks.py [desde AAAA-MM-DD]

POR QUE ISTO E NAO SO' O validar_motor_antes_depois (2026-10-02)
-----------------------------------------------------------------
O validador mede o Brier em linhas fixas (Over 2.5, 9.5, 4.5) sobre todas as
partidas. Mas o pick nasce exatamente onde o motor DISCORDA do mercado, nas
pontas da distribuicao e em linhas alternativas -- e e' ali que um modelo mais
calibrado na media pode estar pior. Este script olha so' o que virou pick, e
compara tres numeros por faixa de probabilidade:

  prob     o que o motor prometeu
  mercado  1/odd, o que o preco dizia (com a margem da casa dentro)
  acerto   o que aconteceu

Leitura: acerto perto de `prob` = calibrado. Acerto perto de `mercado` e
abaixo de `prob` = o motor acha valor que nao existe (o mercado ja' sabia).
O produto vende o primeiro caso.

No fim, o CLV so' das pernas com fechamento perto do apito
(`closing_min_to_ko`, desde 02/10) -- o de antes media a odd da manha.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

FAIXAS = ((0.0, 0.55), (0.55, 0.62), (0.62, 0.70), (0.70, 0.80), (0.80, 1.01))
MIN_N = 20


def carregar(desde: str):
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""
        SELECT pick_type, market_type, probability, odd, result, clv, closing_min_to_ko
          FROM picks_ledger
         WHERE result IN ('GREEN', 'RED') AND probability IS NOT NULL
           AND odd IS NOT NULL AND odd > 1 AND match_date >= %s
    """, (desde,))
    cols = [d[0] for d in cur.description]
    linhas = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return linhas


def linha_de_faixa(pernas: list) -> dict | None:
    n = len(pernas)
    if n < MIN_N:
        return None
    acerto = sum(1 for p in pernas if p["result"] == "GREEN") / n
    prob = sum(float(p["probability"]) for p in pernas) / n
    mercado = sum(1 / float(p["odd"]) for p in pernas) / n
    lucro = sum((float(p["odd"]) - 1) if p["result"] == "GREEN" else -1 for p in pernas) / n
    ep = math.sqrt(acerto * (1 - acerto) / n)
    return {"n": n, "prob": prob, "mercado": mercado, "acerto": acerto, "ep": ep, "roi": lucro}


def imprimir(titulo: str, pernas: list) -> None:
    print(f"\n=== {titulo} ({len(pernas)} pernas) ===")
    print(f"  {'faixa':11} {'n':>5} {'prob':>6} {'mercado':>8} {'acerto':>7} {'±2ep':>6} {'roi':>7}  leitura")
    for lo, hi in FAIXAS:
        r = linha_de_faixa([p for p in pernas if lo <= float(p["probability"]) < hi])
        if not r:
            continue
        if abs(r["acerto"] - r["prob"]) <= 2 * r["ep"]:
            leitura = "calibrado"
        elif r["acerto"] < r["prob"] and abs(r["acerto"] - r["mercado"]) <= 2 * r["ep"]:
            leitura = "OTIMISTA: acerto e' o do mercado"
        elif r["acerto"] < r["prob"]:
            leitura = "OTIMISTA"
        else:
            leitura = "conservador"
        print(f"  {lo:.2f}-{min(hi, 1):.2f}  {r['n']:5d} {r['prob']:6.3f} {r['mercado']:8.3f} "
              f"{r['acerto']:7.3f} {2 * r['ep']:6.3f} {r['roi']:+7.3f}  {leitura}")


def main():
    desde = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"
    pernas = carregar(desde)
    print(f"Pernas liquidadas desde {desde}: {len(pernas)}")
    imprimir("TODOS OS PRODUTOS", pernas)
    por_produto = defaultdict(list)
    por_familia = defaultdict(list)
    for p in pernas:
        por_produto[p["pick_type"]].append(p)
        por_familia[(p["market_type"] or "?").replace("_1h", "")].append(p)
    for nome, ps in sorted(por_produto.items(), key=lambda kv: -len(kv[1])):
        if len(ps) >= MIN_N:
            imprimir(f"produto {nome}", ps)
    for nome, ps in sorted(por_familia.items(), key=lambda kv: -len(kv[1])):
        if len(ps) >= MIN_N:
            imprimir(f"familia {nome}", ps)

    clvs = [float(p["clv"]) for p in pernas
            if p.get("clv") is not None and p.get("closing_min_to_ko") is not None]
    print("\n=== CLV com fechamento perto do apito ===")
    if len(clvs) < 2:
        print(f"  {len(clvs)} perna(s). Rode `python main.py fechamento loop` nos dias de jogo "
              f"e `python main.py setup` uma vez (migracao do minuto do retrato).")
        return
    media = sum(clvs) / len(clvs)
    ep = math.sqrt(sum((c - media) ** 2 for c in clvs) / (len(clvs) - 1) / len(clvs))
    print(f"  n={len(clvs)}  CLV medio={media:+.3%}  IC95=[{media - 1.96 * ep:+.3%}, "
          f"{media + 1.96 * ep:+.3%}]  "
          f"{'VANTAGEM DEMONSTRADA' if media - 1.96 * ep > 0 else 'ainda nao demonstrada'}")


if __name__ == "__main__":
    main()
