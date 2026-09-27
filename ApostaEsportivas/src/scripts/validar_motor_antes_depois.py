"""
validar_motor_antes_depois.py · a configuracao nova do motor preve melhor?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/validar_motor_antes_depois.py

`medir_fontes_de_taxa.py` mede IDEIAS com codigo proprio. Este mede o MOTOR:
chama as funcoes de producao (stats_model.compute_taxa, expected_value_
convergence, probability_model) com a configuracao anterior a 27/09 e com a
atual, sobre as mesmas partidas, numa caminhada pra frente (so' jogos
anteriores de cada time, conversao da liga acumulada so' com o passado).

Nao tem odd historica (odds_values e' snapshot), entao o encolhimento pro
mercado fica de fora -- e fica de fora dos DOIS lados, igual. O que se compara
e' a probabilidade que entra no encolhimento.

Uma mudanca so' fica ligada se o Brier da configuracao atual for menor.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402
from services.pick_engine import stats_model, probability_model  # noqa: E402
from services.pick_engine.config import DEFAULT_CONFIG  # noqa: E402

NOVA = DEFAULT_CONFIG
ANTIGA = replace(DEFAULT_CONFIG, peso_outro_mando=0.0, peso_modelo_na_taxa=0.0,
                 min_jogos_mando_por_lado=0)
MERCADOS = (("goals", "total", 2.5), ("corners", "total", 9.5), ("cards", "total", 4.5),
            ("goals", "home", 1.5), ("corners", "home", 4.5), ("corners", "away", 4.5))


def carregar():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""SELECT * FROM match_statistics WHERE status = 'FT' AND season >= 2025
                    ORDER BY match_date""")
    cols = [d[0] for d in cur.description]
    jogos = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); conn.close()
    return jogos


def prob(cfg, fam, escopo, linha, lh, la, m, baseline):
    h, a = m["home_team_id"], m["away_team_id"]
    team = h if escopo == "home" else a if escopo == "away" else None
    taxa = stats_model.compute_taxa(fam, escopo, "Over", str(linha), lh, la, m["match_date"], cfg,
                                    team_id=team, home_team_id=h, away_team_id=a)
    if not taxa or taxa["taxa_ponderada"] is None or taxa["amostra"] < cfg.min_amostra:
        return None
    lado = taxa.get("amostra_mando_min_lado")
    if cfg.min_jogos_mando_por_lado and lado is not None and lado < cfg.min_jogos_mando_por_lado:
        return None
    p = taxa["taxa_ponderada"]
    if cfg.peso_modelo_na_taxa:
        conv = stats_model.expected_value_convergence(
            lh, la, fam, escopo, home_team_id=h, away_team_id=a, league_baseline=baseline)
        if conv:
            pm_ = probability_model.poisson_prob_for_line(
                conv["expected_value"], linha, "over", family=fam, scope=escopo)
            if pm_ is not None:
                p = (1 - cfg.peso_modelo_na_taxa) * p + cfg.peso_modelo_na_taxa * pm_
    return p


def valor(m, fam, escopo):
    if fam == "cards":
        a = [m.get(f"{l}_yellow_cards") for l in ("home", "away")]
        v = [m.get(f"{l}_red_cards") for l in ("home", "away")]
        if None in a + v:
            return None
        return a[0] + a[1] + 2 * (v[0] + v[1])
    col = {"goals": "goals", "corners": "corners"}[fam]
    if escopo in ("home", "away"):
        return m.get(f"{escopo}_{col}")
    x, y = m.get(f"home_{col}"), m.get(f"away_{col}")
    return None if x is None or y is None else x + y


def main():
    jogos = carregar()
    print(f"{len(jogos)} partidas FT desde 2025")
    hist = defaultdict(list)
    conv = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    placar = defaultdict(lambda: [0, 0.0, 0.0])     # (mercado, cfg) -> n, brier, logloss
    so_nova = defaultdict(int)
    so_antiga = defaultdict(int)
    for m in jogos:
        lg, h, a = m["league_id"], m["home_team_id"], m["away_team_id"]
        lh, la = list(reversed(hist[(lg, h)][-60:])), list(reversed(hist[(lg, a)][-60:]))
        g, s, e, c = conv[lg]
        baseline = ({"conv_gols_por_chute_no_alvo": g / s, "conv_escanteios_por_chute": e / c}
                    if s > 200 and c > 500 else None)
        for fam, escopo, linha in MERCADOS:
            v = valor(m, fam, escopo)
            if v is None or len(lh) < 3 or len(la) < 3:
                continue
            ocorreu = 1 if v > linha else 0
            p_ant = prob(ANTIGA, fam, escopo, linha, lh, la, m, None)
            p_nov = prob(NOVA, fam, escopo, linha, lh, la, m, baseline)
            chave = f"{fam} {escopo} {linha}"
            if p_ant is not None and p_nov is None:
                so_antiga[chave] += 1
                x = placar[(chave, "antiga, jogos que a nova corta")]
                q = min(max(p_ant, 0.01), 0.99); x[0] += 1; x[1] += (q - ocorreu) ** 2
                x[2] += -(math.log(q) if ocorreu else math.log(1 - q))
            if p_nov is not None and p_ant is None:
                so_nova[chave] += 1
                x = placar[(chave, "nova, jogos que so' ela aceita")]
                q = min(max(p_nov, 0.01), 0.99); x[0] += 1; x[1] += (q - ocorreu) ** 2
                x[2] += -(math.log(q) if ocorreu else math.log(1 - q))
            if p_ant is None or p_nov is None:
                continue
            for nome, p in (("antiga", p_ant), ("nova", p_nov)):
                p = min(max(p, 0.01), 0.99)
                x = placar[(chave, nome)]
                x[0] += 1; x[1] += (p - ocorreu) ** 2
                x[2] += -(math.log(p) if ocorreu else math.log(1 - p))
        hist[(lg, h)].append(m); hist[(lg, a)].append(m)
        cc = conv[lg]
        for lado in ("home", "away"):
            gg, ss = m.get(f"{lado}_goals"), m.get(f"{lado}_shots_on")
            ee, tt = m.get(f"{lado}_corners"), m.get(f"{lado}_total_shots")
            if gg is not None and ss is not None:
                cc[0] += gg; cc[1] += ss
            if ee is not None and tt is not None:
                cc[2] += ee; cc[3] += tt

    print(f"\n{'mercado':22} {'config':7} {'n':>6} {'brier':>8} {'logloss':>8}")
    for fam, escopo, linha in MERCADOS:
        chave = f"{fam} {escopo} {linha}"
        for nome in ("antiga", "nova", "antiga, jogos que a nova corta",
                     "nova, jogos que so' ela aceita"):
            n, b, l = placar[(chave, nome)]
            if n:
                print(f"{chave:22} {nome:32} {n:6d} {b / n:8.4f} {l / n:8.4f}")
        print(f"{'':22} so' a antiga aprovaria: {so_antiga[chave]}  so' a nova: {so_nova[chave]}")


if __name__ == "__main__":
    main()
