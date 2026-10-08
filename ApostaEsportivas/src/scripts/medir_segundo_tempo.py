"""
medir_segundo_tempo.py · vale ter mercado de 2o TEMPO no motor?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso (da pasta onde esta' o .env.prod):
  python ApostaEsportivas/src/scripts/medir_segundo_tempo.py [desde AAAA-MM-DD]

POR QUE UM BACKTEST E NAO SOMBRA (2026-10-08). Em vez de ligar o 2o tempo no
motor e esperar semanas, este script refaz o passado: `odds_snapshots` guarda
45 dias de cotacao (inclusive dos mercados de 2o tempo, bet 26 gols e 127
escanteios), e `match_statistics` tem o placar do intervalo desde sempre e o
escanteio do 1o tempo desde 27/09. Pra cada jogo ja' disputado:

  1. estima a media do 2o tempo SO' com jogos ANTERIORES a ele (nada do
     futuro entra), pelo que cada time faz e cede;
  2. le a ultima cotacao antes do apito (mediana entre as casas, a mesma odd
     de avaliacao do motor);
  3. "aposta" onde haveria valor (chance x odd >= 1.05, chance >= 55%, odd
     entre 1.40 e 2.60), uma linha por jogo e mercado, a de maior valor;
  4. confere com o 2o tempo que aconteceu (total - 1o tempo).

CONTROLE. O mesmo modelo simples roda no jogo INTEIRO (bet 5 e 45). O motor de
verdade e' mais sofisticado que isto; o controle diz quanto do resultado e' do
mercado e quanto e' do modelo simples. 2o tempo so' vale ir pro motor se render
pelo menos o que o controle rende, com amostra.

Escanteio do 2o tempo: a media do jogo inteiro de cada time vezes a fracao do
2o tempo na liga (medida nos jogos com folha do 1o tempo). Gol do 2o tempo:
direto do historico (gols - gols do intervalo), que existe desde sempre.
"""
from __future__ import annotations

import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402
from services.pick_engine.probability_model import prob_over, prob_under  # noqa: E402

MERCADOS = {
    26:  ("Gols 2o tempo", "gols", "2t"),
    127: ("Escanteios 2o tempo", "escanteios", "2t"),
    5:   ("Gols jogo inteiro (controle)", "gols", "ft"),
    45:  ("Escanteios jogo inteiro (controle)", "escanteios", "ft"),
}
PHI = {"gols": 1.07, "escanteios": 1.82}   # probability_model._DISPERSAO, total
MIN_JOGOS = 5
JANELA = 10
EV_MIN, PROB_MIN, ODD_MIN, ODD_MAX = 0.05, 0.55, 1.40, 2.60


def carregar(desde: date):
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""
        SELECT fixture_id, match_date::date, league_id, home_team_id, away_team_id,
               home_goals, away_goals, home_goals_ht, away_goals_ht,
               home_corners, away_corners, home_corners_1h, away_corners_1h
          FROM match_statistics
         WHERE status IN ('FT','AET','PEN') AND match_date >= %s
    """, (desde - timedelta(days=200),))
    cols = [d[0] for d in cur.description]
    jogos = [dict(zip(cols, r)) for r in cur.fetchall()]

    alvo = [j["fixture_id"] for j in jogos if j["match_date"] >= desde]
    cur.execute("""
        SELECT DISTINCT ON (fixture_id, bookmaker_id, market_id, value_name)
               fixture_id, market_id, value_name, odd_value
          FROM odds_snapshots
         WHERE fixture_id = ANY(%s) AND market_id = ANY(%s)
           AND minutes_to_kickoff >= 0
         ORDER BY fixture_id, bookmaker_id, market_id, value_name, captured_at DESC
    """, (alvo, list(MERCADOS)))
    odds = defaultdict(list)
    for fid, mid, nome, odd in cur.fetchall():
        if odd and float(odd) > 1:
            odds[(fid, mid, (nome or "").strip().lower())].append(float(odd))
    cur.close()
    conn.close()
    return jogos, odds


def _num(j, campo):
    v = j.get(campo)
    return None if v is None else float(v)


def contagem(j, mercado, periodo, lado):
    """O numero do jogo, de um lado, no periodo. None sem dado."""
    if mercado == "gols":
        ft = _num(j, f"{lado}_goals")
        if periodo == "ft":
            return ft
        ht = _num(j, f"{lado}_goals_ht")
        return None if ft is None or ht is None else ft - ht
    ft = _num(j, f"{lado}_corners")
    if periodo == "ft":
        return ft
    h1 = _num(j, f"{lado}_corners_1h")
    return None if ft is None or h1 is None else ft - h1


def media_faz_cede(historico, team_id, mercado, periodo):
    faz, cede = [], []
    for j in historico:
        casa = j["home_team_id"] == team_id
        a = contagem(j, mercado, periodo, "home" if casa else "away")
        b = contagem(j, mercado, periodo, "away" if casa else "home")
        if a is not None and b is not None:
            faz.append(a)
            cede.append(b)
        if len(faz) >= JANELA:
            break
    if len(faz) < MIN_JOGOS:
        return None
    return sum(faz) / len(faz), sum(cede) / len(cede)


class FracaoDoSegundoTempo:
    """Fracao dos escanteios que sai no 2o tempo, na liga (ou geral), so' com
    jogos JA' vistos. Acumulada jogo a jogo: refazer a lista dos anteriores
    pra cada jogo seria quadratico no banco inteiro."""

    def __init__(self):
        self.liga = defaultdict(lambda: [0, 0.0, 0.0])   # n, total, 1o tempo
        self.geral = [0, 0.0, 0.0]

    def somar(self, j):
        if None in (j["home_corners_1h"], j["away_corners_1h"], j["home_corners"], j["away_corners"]):
            return
        tot = j["home_corners"] + j["away_corners"]
        h1 = j["home_corners_1h"] + j["away_corners_1h"]
        for acc in (self.liga[j["league_id"]], self.geral):
            acc[0] += 1
            acc[1] += tot
            acc[2] += h1

    def de(self, league_id):
        for n, tot, h1 in (self.liga.get(league_id, [0, 0, 0]), self.geral):
            if n >= 30 and tot:
                return (tot - h1) / tot
        return 0.53


def main():
    desde = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 9, 28)
    jogos, odds = carregar(desde)
    jogos.sort(key=lambda j: j["match_date"])
    por_time = defaultdict(list)    # team_id -> jogos (mais recente primeiro, montado no laco)
    apostas = defaultdict(list)     # bet_id -> [(prob, acertou, odd)]
    sem_odd = defaultdict(int)
    fracao = FracaoDoSegundoTempo()
    linhas_por_jogo = defaultdict(lambda: defaultdict(set))   # fixture -> bet -> nomes
    for fid, mid, nome in odds:
        linhas_por_jogo[fid][mid].add(nome)
    pendentes_do_dia: list = []   # jogos do mesmo dia so' entram no historico no dia seguinte
    dia_atual = None

    for j in jogos:
        if j["match_date"] != dia_atual:
            for x in pendentes_do_dia:
                fracao.somar(x)
                for t in (x["home_team_id"], x["away_team_id"]):
                    por_time[t].insert(0, x)
            pendentes_do_dia, dia_atual = [], j["match_date"]
        if j["match_date"] >= desde:
            for mid, (_, mercado, periodo) in MERCADOS.items():
                real_h = contagem(j, mercado, periodo, "home")
                real_a = contagem(j, mercado, periodo, "away")
                if real_h is None or real_a is None:
                    continue
                mp = "ft" if mercado == "escanteios" else periodo
                h = media_faz_cede(por_time[j["home_team_id"]], j["home_team_id"], mercado, mp)
                a = media_faz_cede(por_time[j["away_team_id"]], j["away_team_id"], mercado, mp)
                if not h or not a:
                    continue
                lam = (h[0] + a[1]) / 2 + (a[0] + h[1]) / 2
                if mercado == "escanteios" and periodo == "2t":
                    lam *= fracao.de(j["league_id"])
                real = real_h + real_a
                melhor = None
                linhas = linhas_por_jogo[j["fixture_id"]][mid]
                if not linhas:
                    sem_odd[mid] += 1
                for nome in linhas:
                    partes = nome.split()
                    if len(partes) != 2 or partes[0] not in ("over", "under"):
                        continue
                    try:
                        linha = float(partes[1])
                    except ValueError:
                        continue
                    if linha != math.floor(linha) + 0.5:
                        continue   # so' linha .5: sem devolucao pra complicar
                    odd = statistics.median(odds[(j["fixture_id"], mid, nome)])
                    p = (prob_over(linha, lam, PHI[mercado]) if partes[0] == "over"
                         else prob_under(linha, lam, PHI[mercado]))
                    ev = p * odd - 1
                    if ev >= EV_MIN and p >= PROB_MIN and ODD_MIN <= odd <= ODD_MAX:
                        if not melhor or ev > melhor[0]:
                            acertou = real > linha if partes[0] == "over" else real < linha
                            melhor = (ev, p, acertou, odd)
                if melhor:
                    apostas[mid].append(melhor[1:])
        pendentes_do_dia.append(j)

    print(f"Jogos encerrados desde {desde}: {sum(1 for j in jogos if j['match_date'] >= desde)}")
    print(f"Regra de aposta: chance x odd >= {1 + EV_MIN:.2f}, chance >= {PROB_MIN:.0%}, "
          f"odd {ODD_MIN}-{ODD_MAX}, uma linha .5 por jogo e mercado\n")
    print(f"  {'mercado':36} {'apostas':>7} {'prob':>6} {'preco':>6} {'acerto':>7} {'±2ep':>6} {'ROI':>7} {'±2ep':>6}")
    for mid, (rotulo, _, _) in MERCADOS.items():
        ap = apostas[mid]
        if not ap:
            print(f"  {rotulo:36} {0:>7}   (jogos sem odd deste mercado: {sem_odd[mid]})")
            continue
        n = len(ap)
        ac = sum(1 for _, a, _ in ap if a) / n
        rs = [(o - 1) if a else -1 for _, a, o in ap]
        r = sum(rs) / n
        ep_r = math.sqrt(sum((x - r) ** 2 for x in rs) / max(n - 1, 1) / n)
        print(f"  {rotulo:36} {n:>7} {sum(p for p, _, _ in ap) / n:>6.3f} "
              f"{sum(1 / o for _, _, o in ap) / n:>6.3f} {ac:>7.3f} "
              f"{2 * math.sqrt(ac * (1 - ac) / n):>6.3f} {r:>+7.3f} {2 * ep_r:>6.3f}")

    print("\nLeitura: 2o tempo so' vale ir pro motor se o ROI dele for positivo com o")
    print("intervalo (±2ep) longe de zero E nao pior que o do controle do mesmo mercado.")
    print("Com menos de ~150 apostas por mercado, rode de novo daqui a duas semanas.")


if __name__ == "__main__":
    main()
