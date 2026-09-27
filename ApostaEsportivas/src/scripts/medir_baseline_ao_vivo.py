"""
medir_baseline_ao_vivo.py · a media-base do motor ao vivo deveria enxergar o
outro mando?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_baseline_ao_vivo.py

O motor ao vivo parte da media do TOTAL do jogo: o mandante nos jogos em casa
e o visitante nos jogos fora (live_pipeline.baseline_do_mando). O pre-jogo
passou a usar o outro mando com peso 0.5 em 27/09, medido. Este script mede a
mesma pergunta pra media-base do ao vivo: com essa media como lambda (Binomial
Negativa, dispersao da familia), qual preve melhor o total do jogo?
Caminhada pra frente, so' jogos anteriores.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402
from services.pick_engine import probability_model as pm  # noqa: E402

LINHAS = {"goals": 2.5, "corners": 9.5, "cards": 4.5, "fouls": 23.5}
PESOS = (0.0, 0.25, 0.5, 1.0)


def total(m, fam):
    if fam == "goals":
        a, b = m["home_goals"], m["away_goals"]
    elif fam == "corners":
        a, b = m["home_corners"], m["away_corners"]
    elif fam == "fouls":
        a, b = m["home_fouls"], m["away_fouls"]
    else:
        ya, yb, ra, rb = (m["home_yellow_cards"], m["away_yellow_cards"],
                          m["home_red_cards"], m["away_red_cards"])
        if None in (ya, yb, ra, rb):
            return None
        return ya + yb + 2 * (ra + rb)
    return None if a is None or b is None else a + b


def main():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""SELECT league_id, home_team_id, away_team_id,
                          COALESCE(home_goals_90, home_goals) AS home_goals,
                          COALESCE(away_goals_90, away_goals) AS away_goals,
                          home_corners, away_corners, home_yellow_cards, away_yellow_cards,
                          home_red_cards, away_red_cards, home_fouls, away_fouls
                     FROM match_statistics WHERE status = 'FT' AND season >= 2025
                    ORDER BY match_date""")
    cols = [d[0] for d in cur.description]
    jogos = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); conn.close()

    hist = defaultdict(list)
    placar = defaultdict(lambda: [0, 0.0, 0.0])
    for m in jogos:
        lg, h, a = m["league_id"], m["home_team_id"], m["away_team_id"]
        hh, ha = hist[(lg, h)][-40:], hist[(lg, a)][-40:]
        h_casa = [x for x in hh if x["home_team_id"] == h]
        h_fora = [x for x in hh if x["away_team_id"] == h]
        a_fora = [x for x in ha if x["away_team_id"] == a]
        a_casa = [x for x in ha if x["home_team_id"] == a]
        if len(h_casa) >= 5 and len(a_fora) >= 5:
            for fam, linha in LINHAS.items():
                t = total(m, fam)
                if t is None:
                    continue
                ocorreu = 1 if t > linha else 0
                for w in PESOS:
                    def media(mando, outro):
                        pares = [(total(x, fam), 1.0) for x in mando] + [(total(x, fam), w) for x in outro]
                        pares = [(v, p) for v, p in pares if v is not None and p > 0]
                        den = sum(p for _, p in pares)
                        return sum(v * p for v, p in pares) / den if den else None
                    mh, ma = media(h_casa, h_fora), media(a_fora, a_casa)
                    if mh is None or ma is None:
                        continue
                    lam = (mh + ma) / 2
                    p = pm.prob_over(linha, lam, pm.dispersao(fam, "total"))
                    p = min(max(p, 0.01), 0.99)
                    x = placar[(fam, w)]
                    x[0] += 1; x[1] += (p - ocorreu) ** 2
                    x[2] += -(math.log(p) if ocorreu else math.log(1 - p))
        hist[(lg, h)].append(m); hist[(lg, a)].append(m)

    print(f"{'familia':8} {'peso do outro mando':>20} {'n':>6} {'brier':>8} {'logloss':>8}")
    for (fam, w), (n, b, l) in sorted(placar.items()):
        print(f"{fam:8} {w:20} {n:6d} {b / n:8.4f} {l / n:8.4f}")


if __name__ == "__main__":
    main()
