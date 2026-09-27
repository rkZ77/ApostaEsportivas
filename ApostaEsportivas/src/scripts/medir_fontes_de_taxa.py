"""
medir_fontes_de_taxa.py · de onde a probabilidade deveria sair?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_fontes_de_taxa.py

POR QUE EXISTE (27/09/2026)
---------------------------
Tres pedidos do usuario, e a regra dele de so' mudar o motor com medicao:

  1. "Minimo de 5 jogos em casa ou fora": hoje o piso de 8 soma os dois lados,
     entao um mercado de total passa com 7 jogos de um time e 1 do outro.
  2. "O motor precisa enxergar o jogo fora tambem, com peso diferente": hoje o
     pool e' SO' do mando (decisao de 08/08, que mediu a mistura inflando a
     taxa). A pergunta e' se o outro mando, com peso MENOR, ajuda.
  3. "Gol nao e' so' gol: chute, chute no gol, pressao; e o mesmo pros
     escanteios": prever pela causa (volume de finalizacao) em vez de pela
     media do proprio contador.

COMO MEDE
---------
Caminhada pra frente em todas as partidas FT das ultimas temporadas: pra cada
jogo, so' com os jogos ANTERIORES dos dois times na mesma liga, cada metodo
da' P(Over linha) e compara com o que aconteceu. Brier (erro quadratico, menor
e' melhor) e log-loss. Todos os metodos veem a mesma partida, entao a
diferenca de Brier entre eles e' a diferenca de previsao, nao de amostra.

Linhas: gols 2.5, escanteios 9.5, cartoes 4.5 (pontos: amarelo 1, vermelho 2).
Sem decaimento temporal em nenhum metodo, pra comparacao ser justa.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402
from services.pick_engine import probability_model as pm  # noqa: E402

LINHAS = {"goals": 2.5, "corners": 9.5, "cards": 4.5}
MIN_POR_LADO_AVALIAR = 3
PESO_OUTRO_MANDO = (0.25, 0.5)


def _cartoes(m, lado):
    a, v = m[f"{lado}_yellow_cards"], m[f"{lado}_red_cards"]
    return None if a is None or v is None else a + 2 * v


def valor(m, fam, lado):
    if fam == "goals":
        return m[f"{lado}_goals"]
    if fam == "corners":
        return m[f"{lado}_corners"]
    return _cartoes(m, lado)


def total(m, fam):
    a, b = valor(m, fam, "home"), valor(m, fam, "away")
    return None if a is None or b is None else a + b


def carregar(cur):
    cur.execute("""
        SELECT fixture_id, league_id, season, match_date, home_team_id, away_team_id,
               COALESCE(home_goals_90, home_goals) AS home_goals,
               COALESCE(away_goals_90, away_goals) AS away_goals,
               home_corners, away_corners,
               home_yellow_cards, away_yellow_cards, home_red_cards, away_red_cards,
               home_shots_on, away_shots_on, home_total_shots, away_total_shots
          FROM match_statistics
         WHERE status = 'FT' AND season >= 2025
         ORDER BY match_date
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def taxa(jogos_pesos, fam, linha):
    """Taxa empirica ponderada de Over (jogos da partida inteira)."""
    num = den = 0.0
    for m, w in jogos_pesos:
        t = total(m, fam)
        if t is None:
            continue
        num += w * (1 if t > linha else 0)
        den += w
    return (num / den, den) if den else (None, 0)


def media_lado(jogos, team_id, fam, feitos=True):
    vals = []
    for m in jogos:
        eu = "home" if m["home_team_id"] == team_id else "away"
        ele = "away" if eu == "home" else "home"
        v = valor(m, fam, eu if feitos else ele)
        if v is not None:
            vals.append(v)
    return sum(vals) / len(vals) if vals else None


def media_campo(jogos, team_id, campo, feitos=True):
    vals = []
    for m in jogos:
        eu = "home" if m["home_team_id"] == team_id else "away"
        ele = "away" if eu == "home" else "home"
        v = m.get(f"{eu if feitos else ele}_{campo}")
        if v is not None:
            vals.append(v)
    return sum(vals) / len(vals) if vals else None


def p_over_nb(lam, linha, fam):
    if lam is None or lam <= 0:
        return None
    return pm.prob_over(linha, lam, pm.dispersao(fam, "total"))


class Placar:
    def __init__(self):
        self.d = defaultdict(lambda: [0, 0.0, 0.0])

    def add(self, chave, p, ocorreu):
        if p is None:
            return
        p = min(max(p, 0.01), 0.99)
        x = self.d[chave]
        x[0] += 1
        x[1] += (p - ocorreu) ** 2
        x[2] += -(math.log(p) if ocorreu else math.log(1 - p))

    def imprimir(self, titulo):
        print(f"\n{titulo}")
        print(f"  {'familia':8} {'metodo':34} {'n':>6} {'brier':>8} {'logloss':>8}")
        for (fam, met), (n, b, l) in sorted(self.d.items()):
            print(f"  {fam:8} {met:34} {n:6d} {b / n:8.4f} {l / n:8.4f}")


def main():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    jogos = carregar(cur)
    cur.close(); conn.close()
    print(f"{len(jogos)} partidas FT desde 2025")

    # Taxa de conversao da liga (gols por chute no alvo, escanteios por chute),
    # acumulada so' com o passado de cada jogo.
    hist_time = defaultdict(list)          # (league, team) -> jogos anteriores
    conv = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])   # league -> gols, alvo, esc, chutes

    mando = Placar()          # pergunta 1 e 2: mesmo conjunto de jogos
    fatores = Placar()        # pergunta 3: contagem x causa
    piso = Placar()           # pergunta 1: com e sem 5 por lado
    escopo = Placar()         # mercado de um time so'
    combo = Placar()          # taxa mista x modelo x os dois

    for m in jogos:
        lg, h, a = m["league_id"], m["home_team_id"], m["away_team_id"]
        hh, ha = hist_time[(lg, h)], hist_time[(lg, a)]
        h_casa = [x for x in hh if x["home_team_id"] == h]
        h_fora = [x for x in hh if x["away_team_id"] == h]
        a_fora = [x for x in ha if x["away_team_id"] == a]
        a_casa = [x for x in ha if x["home_team_id"] == a]

        if len(h_casa) >= MIN_POR_LADO_AVALIAR and len(a_fora) >= MIN_POR_LADO_AVALIAR:
            for fam, linha in LINHAS.items():
                t = total(m, fam)
                if t is None:
                    continue
                ocorreu = 1 if t > linha else 0
                # --- mando: hoje, e com o outro mando pesando menos
                so_mando = [(x, 1.0) for x in h_casa + a_fora]
                p0, _ = taxa(so_mando, fam, linha)
                mando.add((fam, "so' mando (hoje)"), p0, ocorreu)
                for w in PESO_OUTRO_MANDO:
                    mistura = so_mando + [(x, w) for x in h_fora + a_casa]
                    p, _ = taxa(mistura, fam, linha)
                    mando.add((fam, f"mando + outro mando peso {w}"), p, ocorreu)
                todos = [(x, 1.0) for x in hh + ha]
                p, _ = taxa(todos, fam, linha)
                mando.add((fam, "todos os jogos, peso igual"), p, ocorreu)

                # --- piso de 5 por lado, dentro do piso de 8 somado de hoje
                if len(h_casa) + len(a_fora) >= 8:
                    grupo = ("ambos >= 5" if min(len(h_casa), len(a_fora)) >= 5
                             else "algum lado < 5")
                    piso.add((fam, f"so' mando, {grupo}"), p0, ocorreu)

                # --- causa x contagem (Binomial Negativa, mesma estrutura)
                fh = media_lado(h_casa, h, fam, True); ca = media_lado(a_fora, a, fam, False)
                fa = media_lado(a_fora, a, fam, True); ch = media_lado(h_casa, h, fam, False)
                if None not in (fh, ca, fa, ch):
                    lam = (fh + ca) / 2 + (fa + ch) / 2
                    fatores.add((fam, "media do proprio contador"), p_over_nb(lam, linha, fam), ocorreu)
                gols, alvo, esc, chutes = conv[lg]
                if fam == "goals" and alvo > 200:
                    k = gols / alvo
                    sh = media_campo(h_casa, h, "shots_on", True); sa_c = media_campo(a_fora, a, "shots_on", False)
                    sa = media_campo(a_fora, a, "shots_on", True); sh_c = media_campo(h_casa, h, "shots_on", False)
                    if None not in (sh, sa_c, sa, sh_c):
                        lam = k * ((sh + sa_c) / 2 + (sa + sh_c) / 2)
                        fatores.add((fam, "chutes no alvo x conversao da liga"),
                                    p_over_nb(lam, linha, fam), ocorreu)
                        # Meio a meio: a causa corrige o ruido do contador
                        if fh is not None and None not in (ca, fa, ch):
                            lam2 = 0.5 * lam + 0.5 * ((fh + ca) / 2 + (fa + ch) / 2)
                            fatores.add((fam, "meio contador, meio chutes no alvo"),
                                        p_over_nb(lam2, linha, fam), ocorreu)
                if fam == "corners" and chutes > 500:
                    k = esc / chutes
                    sh = media_campo(h_casa, h, "total_shots", True); sa_c = media_campo(a_fora, a, "total_shots", False)
                    sa = media_campo(a_fora, a, "total_shots", True); sh_c = media_campo(h_casa, h, "total_shots", False)
                    if None not in (sh, sa_c, sa, sh_c):
                        lam = k * ((sh + sa_c) / 2 + (sa + sh_c) / 2)
                        fatores.add((fam, "chutes x conversao da liga"),
                                    p_over_nb(lam, linha, fam), ocorreu)
                        if None not in (fh, ca, fa, ch):
                            lam2 = 0.5 * lam + 0.5 * ((fh + ca) / 2 + (fa + ch) / 2)
                            fatores.add((fam, "meio contador, meio chutes"),
                                        p_over_nb(lam2, linha, fam), ocorreu)

        # --- ESCOPO DE UM TIME (o caso de 08/08: "Escanteios Visitante").
        # Mandante no mercado dele, com e sem os jogos fora pesando menos.
        if len(h_casa) >= MIN_POR_LADO_AVALIAR:
            for fam, linha in (("corners", 4.5), ("goals", 1.5)):
                v = valor(m, fam, "home")
                if v is None:
                    continue
                ocorreu = 1 if v > linha else 0

                def taxa_lado(pares):
                    num = den = 0.0
                    for x, w in pares:
                        vv = valor(x, fam, "home" if x["home_team_id"] == h else "away")
                        if vv is None:
                            continue
                        num += w * (1 if vv > linha else 0); den += w
                    return num / den if den else None

                escopo.add((fam, "mandante: so' em casa (hoje)"),
                           taxa_lado([(x, 1.0) for x in h_casa]), ocorreu)
                escopo.add((fam, "mandante: casa + fora peso 0.5"),
                           taxa_lado([(x, 1.0) for x in h_casa] + [(x, 0.5) for x in h_fora]), ocorreu)

        # --- COMBINACAO: taxa (outro mando 0.5) com o modelo por causa
        if len(h_casa) >= MIN_POR_LADO_AVALIAR and len(a_fora) >= MIN_POR_LADO_AVALIAR:
            for fam, linha in LINHAS.items():
                t = total(m, fam)
                if t is None:
                    continue
                ocorreu = 1 if t > linha else 0
                mistura = [(x, 1.0) for x in h_casa + a_fora] + [(x, 0.5) for x in h_fora + a_casa]
                pt, _ = taxa(mistura, fam, linha)
                fh = media_lado(h_casa, h, fam, True); ca = media_lado(a_fora, a, fam, False)
                fa = media_lado(a_fora, a, fam, True); ch = media_lado(h_casa, h, fam, False)
                lam_cont = ((fh + ca) / 2 + (fa + ch) / 2) if None not in (fh, ca, fa, ch) else None
                lam = lam_cont
                gols, alvo, esc, chutes = conv[lg]
                campo, k = (("shots_on", gols / alvo) if fam == "goals" and alvo > 200 else
                            ("total_shots", esc / chutes) if fam == "corners" and chutes > 500 else
                            (None, None))
                if campo:
                    sh = media_campo(h_casa, h, campo, True); sa_c = media_campo(a_fora, a, campo, False)
                    sa = media_campo(a_fora, a, campo, True); sh_c = media_campo(h_casa, h, campo, False)
                    if None not in (sh, sa_c, sa, sh_c):
                        lam_causa = k * ((sh + sa_c) / 2 + (sa + sh_c) / 2)
                        lam = (lam_causa if fam == "goals" or lam_cont is None
                               else 0.5 * lam_causa + 0.5 * lam_cont)
                pm_ = p_over_nb(lam, linha, fam)
                combo.add((fam, "taxa mista"), pt, ocorreu)
                combo.add((fam, "modelo (melhor lambda da familia)"), pm_, ocorreu)
                if pt is not None and pm_ is not None:
                    combo.add((fam, "meio taxa mista, meio modelo"), 0.5 * pt + 0.5 * pm_, ocorreu)

        # atualiza o passado DEPOIS de prever
        hh.append(m); ha.append(m)
        c = conv[lg]
        for lado in ("home", "away"):
            g, s, e, t = (m[f"{lado}_goals"], m[f"{lado}_shots_on"],
                          m[f"{lado}_corners"], m[f"{lado}_total_shots"])
            if g is not None and s is not None:
                c[0] += g; c[1] += s
            if e is not None and t is not None:
                c[2] += e; c[3] += t

    mando.imprimir("1+2. QUAIS JOGOS ENTRAM NO POOL (taxa empirica de Over)")
    piso.imprimir("1. PISO DE 5 POR LADO (so' mando, dentro do piso de 8 somado)")
    fatores.imprimir("3. CONTAGEM x CAUSA (Binomial Negativa, lambda feitos x cedidos)")
    escopo.imprimir("4. MERCADO DE UM TIME (mandante; o caso que criou o 'so' mando')")
    combo.imprimir("5. TAXA MISTA x MODELO POR CAUSA x OS DOIS")


if __name__ == "__main__":
    main()
