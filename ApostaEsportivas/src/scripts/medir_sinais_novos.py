"""
medir_sinais_novos.py · sinais que o motor ainda nao enxerga tem valor?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_sinais_novos.py

COMO MEDE (2026-09-27)
----------------------
Pra cada partida FT, na ordem das datas, o ESPERADO de cada familia sai do
jeito que o motor ja' calcula (feitos x cedidos, mando com o outro mando a
0.5, so' jogos anteriores). O RESIDUO e' real - esperado. Um sinal tem valor se
o residuo medio muda de forma consistente entre as faixas dele: o motor erra
sempre pro mesmo lado quando o sinal esta' alto.

Imprime, por sinal e faixa: n, residuo medio e erro-padrao. Diferenca entre
faixas maior que ~2 erros-padrao e' sinal pra levar adiante (e medir de novo
pelo validador antes de ligar); menor que isso e' ruido.

SINAIS
------
  descanso        dias desde o jogo anterior de cada time, em QUALQUER
                  competicao (copa no meio da semana entra).
  estilo_posse    posse media do mandante menos a do visitante: quem tem a
                  bola contra quem se fecha.
  bloqueio        chutes bloqueados cedidos: time que defende na area.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

PESO_OUTRO = 0.5
FAMILIAS = ("goals", "corners", "cards")


def carregar():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""SELECT fixture_id, league_id, match_date, home_team_id, away_team_id, status,
                          COALESCE(home_goals_90, home_goals) AS home_goals,
                          COALESCE(away_goals_90, away_goals) AS away_goals,
                          home_corners, away_corners, home_yellow_cards, away_yellow_cards,
                          home_red_cards, away_red_cards, home_possession, away_possession,
                          home_blocked_shots, away_blocked_shots
                     FROM match_statistics
                    WHERE status IN ('FT','AET','PEN') AND season >= 2025
                    ORDER BY match_date""")
    cols = [d[0] for d in cur.description]
    jogos = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); conn.close()
    return jogos


def carregar_calendario():
    """{team_id: [datas]} de calendario_jogos, sem partida adiada/cancelada.
    Vazio se a tabela ainda nao existe (rodar `python main.py calendario`)."""
    conn = get_connection()
    cur = conn.cursor()
    agenda = defaultdict(list)
    try:
        cur.execute("""SELECT home_team_id, away_team_id, match_datetime FROM calendario_jogos
                        WHERE match_datetime IS NOT NULL
                          AND COALESCE(status, '') NOT IN ('PST','CANC','ABD','AWD','WO')""")
        for h, a, d in cur.fetchall():
            agenda[h].append(d); agenda[a].append(d)
    except Exception as e:
        print(f"calendario indisponivel: {e}")
    finally:
        cur.close(); conn.close()
    for t in agenda:
        agenda[t].sort()
    return agenda


def carga(agenda, team, quando):
    """(dias ate o proximo, jogos nos 14 dias anteriores) pelo calendario."""
    from datetime import datetime, timedelta
    datas = agenda.get(team)
    if not datas or quando is None:
        return None, None
    q = quando if isinstance(quando, datetime) else datetime(quando.year, quando.month, quando.day, 12)
    depois = [d for d in datas if d > q + timedelta(hours=12)]
    ult14 = sum(1 for d in datas if q - timedelta(days=14) <= d < q - timedelta(hours=12))
    prox = (depois[0] - q).days if depois else None
    return prox, ult14


def valor(m, fam, lado):
    if fam == "goals":
        return m[f"{lado}_goals"]
    if fam == "corners":
        return m[f"{lado}_corners"]
    a, v = m[f"{lado}_yellow_cards"], m[f"{lado}_red_cards"]
    return None if a is None or v is None else a + 2 * v


def media_pond(pares):
    num = den = 0.0
    for v, w in pares:
        if v is not None:
            num += v * w; den += w
    return num / den if den else None


def esperado(fam, hist_h, hist_a, h, a):
    """Feitos x cedidos, mando pesando 1 e o outro mando 0.5 -- a conta do motor."""
    def lado(hist, team, mando):
        feitos, cedidos = [], []
        for m in hist:
            eu = "home" if m["home_team_id"] == team else "away"
            ele = "away" if eu == "home" else "home"
            w = 1.0 if eu == mando else PESO_OUTRO
            feitos.append((valor(m, fam, eu), w)); cedidos.append((valor(m, fam, ele), w))
        return media_pond(feitos), media_pond(cedidos)
    fh, ch = lado(hist_h, h, "home")
    fa, ca = lado(hist_a, a, "away")
    if None in (fh, ch, fa, ca):
        return None
    return (fh + ca) / 2 + (fa + ch) / 2


def faixa_descanso(dias):
    if dias is None:
        return None
    return "ate 3 dias" if dias <= 3 else "4 a 5 dias" if dias <= 5 else "6 a 9 dias" if dias <= 9 else "10+ dias"


def faixa_num(v, cortes, nomes):
    if v is None:
        return None
    for c, n in zip(cortes, nomes):
        if v < c:
            return n
    return nomes[-1]


def main():
    jogos = carregar()
    agenda = carregar_calendario()
    print(f"{len(jogos)} partidas encerradas desde 2025; calendario de {len(agenda)} times")
    por_liga_time = defaultdict(list)
    ultimo_jogo = {}                     # team -> data (qualquer competicao)
    acum = defaultdict(lambda: defaultdict(list))   # (sinal, fam) -> faixa -> residuos

    for m in jogos:
        h, a, lg = m["home_team_id"], m["away_team_id"], m["league_id"]
        hh, ha = por_liga_time[(lg, h)][-40:], por_liga_time[(lg, a)][-40:]
        if m["status"] == "FT" and len(hh) >= 6 and len(ha) >= 6:
            dh = (m["match_date"] - ultimo_jogo[h]).days if h in ultimo_jogo else None
            da = (m["match_date"] - ultimo_jogo[a]).days if a in ultimo_jogo else None
            menor = min(x for x in (dh, da) if x is not None) if (dh or da) else None

            def media_campo(hist, team, campo, feitos=True):
                vals = []
                for x in hist:
                    eu = "home" if x["home_team_id"] == team else "away"
                    ele = "away" if eu == "home" else "home"
                    v = x.get(f"{eu if feitos else ele}_{campo}")
                    if v is not None:
                        vals.append(float(str(v).replace("%", "")))
                return sum(vals) / len(vals) if vals else None

            pos_h, pos_a = media_campo(hh, h, "possession"), media_campo(ha, a, "possession")
            dif_posse = (pos_h - pos_a) if None not in (pos_h, pos_a) else None
            bloq = media_campo(ha, a, "blocked_shots", feitos=False)   # o visitante bloqueia

            prox_h, c14_h = carga(agenda, h, m["match_date"])
            prox_a, c14_a = carga(agenda, a, m["match_date"])
            proximos = [x for x in (prox_h, prox_a) if x is not None]
            cargas = [x for x in (c14_h, c14_a) if x is not None]
            sinais = {
                "proximo jogo (o mais cedo dos dois)": (
                    None if not proximos else "ate 3 dias" if min(proximos) <= 3
                    else "4 a 5 dias" if min(proximos) <= 5 else "6+ dias"),
                "jogos nos ultimos 14 dias (o mais cansado)": (
                    None if not cargas else "0-2" if max(cargas) <= 2
                    else "3" if max(cargas) == 3 else "4+"),
                "descanso (o menor dos dois)": faixa_descanso(menor),
                "estilo: posse mandante - visitante": faixa_num(
                    dif_posse, (-8, -2, 2, 8), ("<-8", "-8 a -2", "-2 a 2", "2 a 8", ">8")),
                "visitante bloqueia chutes (por jogo)": faixa_num(
                    bloq, (2.5, 3.5, 4.5), ("<2.5", "2.5 a 3.5", "3.5 a 4.5", ">4.5")),
            }
            for fam in FAMILIAS:
                vh, va = valor(m, fam, "home"), valor(m, fam, "away")
                esp = esperado(fam, hh, ha, h, a)
                if vh is None or va is None or esp is None:
                    continue
                res = (vh + va) - esp
                for sinal, faixa in sinais.items():
                    if faixa is not None:
                        acum[(sinal, fam)][faixa].append(res)

        por_liga_time[(lg, h)].append(m); por_liga_time[(lg, a)].append(m)
        ultimo_jogo[h] = m["match_date"]; ultimo_jogo[a] = m["match_date"]

    for (sinal, fam), faixas in acum.items():
        print(f"\n{sinal} | {fam}")
        for faixa, rs in sorted(faixas.items()):
            n = len(rs)
            if n < 30:
                continue
            media = sum(rs) / n
            dp = math.sqrt(sum((r - media) ** 2 for r in rs) / (n - 1))
            print(f"   {faixa:12} n={n:5d} residuo medio={media:+.3f}  (erro-padrao {dp / math.sqrt(n):.3f})")


if __name__ == "__main__":
    main()
