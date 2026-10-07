"""
medir_dixon_coles.py · o Dixon-Coles merece substituir o Poisson em gols?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_dixon_coles.py

DUAS PERGUNTAS, NESTA ORDEM
---------------------------
1. QUAL O RHO DAQUI? Estima o rho por maxima verossimilhanca nos placares de
   `match_statistics`, com o lambda de cada lado = media da liga como mandante
   e como visitante na temporada. E' um ajuste grosseiro (nao separa forca de
   time), mas o rho mede so' o excesso de placares baixos, que e' justamente o
   que a media da liga nao explica. Se o rho medido ficar perto de 0, a
   correcao nao tem o que corrigir e a resposta ja' e' "nao".

2. ELE ACERTA MAIS NOS PICKS? Cruza `engine_decisions.candidates`
   (`poisson_probability` e `dixon_coles_sombra`, gravados desde 07/10) com
   `picks_ledger` por (fixture, mercado, linha) e compara Brier e log-loss dos
   dois. Metade mais antiga = descoberta, metade mais nova = confirmacao: so'
   vale ligar se o Dixon-Coles ganhar NAS DUAS, com MIN_PERNAS em cada.

O que este script NAO decide: CLV. A probabilidade do modelo muda a escolha da
linha e o EV, e o teste final de valor continua sendo o CLV dos picks depois de
ligar (medir_calibracao_dos_picks.py + picks_ledger.clv). Isto aqui so' diz se
vale fazer esse teste.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402
from services.pick_engine.probability_model import placares_dixon_coles  # noqa: E402

MIN_PERNAS = 60
_MERCADOS = ("goals", "btts")


def estimar_rho(cur) -> tuple[float | None, int]:
    cur.execute("""
        SELECT league_id, season, home_goals, away_goals
          FROM match_statistics
         WHERE status IN ('FT','AET','PEN')
           AND home_goals IS NOT NULL AND away_goals IS NOT NULL
    """)
    jogos = cur.fetchall()
    if not jogos:
        return None, 0
    medias = defaultdict(lambda: [0, 0, 0])
    for liga, temp, hg, ag in jogos:
        m = medias[(liga, temp)]
        m[0] += hg; m[1] += ag; m[2] += 1
    lam = {k: (v[0] / v[2], v[1] / v[2]) for k, v in medias.items() if v[2] >= 30}
    amostra = [(lam[(l, t)], hg, ag) for l, t, hg, ag in jogos if (l, t) in lam and hg <= 10 and ag <= 10]

    # Cache da matriz por (lh, la, rho) arredondado: ha' poucas ligas.
    cache: dict = {}

    def loglik(rho: float) -> float:
        total = 0.0
        for (lh, la), hg, ag in amostra:
            k = (round(lh, 3), round(la, 3), rho)
            if k not in cache:
                cache[k] = placares_dixon_coles(lh, la, rho)
            total += math.log(max(cache[k][hg][ag], 1e-12))
        return total

    grade = [x / 100 for x in range(-30, 11)]
    melhor = max(grade, key=loglik)
    return melhor, len(amostra)


def metricas(pares: list) -> dict:
    n = len(pares)
    if not n:
        return {"n": 0}
    brier = sum((p - o) ** 2 for p, o in pares) / n
    ll = -sum(o * math.log(max(p, 1e-6)) + (1 - o) * math.log(max(1 - p, 1e-6)) for p, o in pares) / n
    return {"n": n, "brier": brier, "logloss": ll}


def main():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()

    rho, n_jogos = estimar_rho(cur)
    print(f"\n1. RHO MEDIDO: {rho} em {n_jogos} jogos (sombra usa -0.10; 0 = Poisson ja' basta)")

    cur.execute("""
        SELECT fixture_id, candidates FROM engine_decisions
         WHERE fixture_id IS NOT NULL AND created_at >= '2026-10-07'
    """)
    sombra: dict = {}
    for fixture_id, candidatos in cur.fetchall():
        if isinstance(candidatos, str):
            candidatos = json.loads(candidatos)
        for c in candidatos or []:
            if c.get("market_type") not in _MERCADOS:
                continue
            dc, po = c.get("dixon_coles_sombra"), c.get("poisson_probability")
            if dc is None or po is None:
                continue
            sombra[(fixture_id, c.get("market_type"), c.get("line"))] = (float(po), float(dc))

    cur.execute("""
        SELECT fixture_id, market_type, line, result, match_date
          FROM picks_ledger
         WHERE result IN ('GREEN','RED') AND market_type = ANY(%s)
           AND match_date >= '2026-10-07'
         ORDER BY match_date
    """, (list(_MERCADOS),))
    linhas = [(f, m, l, r) for f, m, l, r, _d in cur.fetchall() if (f, m, l) in sombra]
    cur.close()
    conn.close()

    meio = len(linhas) // 2
    print(f"\n2. PICKS COM AS DUAS PROBABILIDADES: {len(linhas)}")
    vence_nas_duas = True
    for nome, fatia in (("descoberta (mais antigos)", linhas[:meio]), ("confirmacao (mais novos)", linhas[meio:])):
        po = metricas([(sombra[(f, m, l)][0], 1 if r == "GREEN" else 0) for f, m, l, r in fatia])
        dc = metricas([(sombra[(f, m, l)][1], 1 if r == "GREEN" else 0) for f, m, l, r in fatia])
        if not po["n"]:
            print(f"   {nome}: sem dado")
            vence_nas_duas = False
            continue
        print(f"   {nome}: n={po['n']}  Brier Poisson={po['brier']:.4f}  DC={dc['brier']:.4f}  "
              f"| logloss Poisson={po['logloss']:.4f}  DC={dc['logloss']:.4f}")
        if not (dc["brier"] < po["brier"] and dc["logloss"] < po["logloss"]):
            vence_nas_duas = False

    if len(linhas) < 2 * MIN_PERNAS:
        print(f"\nVEREDITO: AMOSTRA INSUFICIENTE (precisa {2 * MIN_PERNAS}, tem {len(linhas)}). Manter em sombra.")
    elif vence_nas_duas:
        print("\nVEREDITO: DIXON-COLES MELHOR NAS DUAS METADES. Proximo passo: ligar com o rho medido "
              "e acompanhar o CLV dos picks de gols antes/depois (medir_mudancas_por_fase.py).")
    else:
        print("\nVEREDITO: SEM GANHO CONSISTENTE. Manter Poisson.")


if __name__ == "__main__":
    main()
