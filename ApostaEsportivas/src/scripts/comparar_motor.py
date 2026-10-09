"""
comparar_motor.py · o motor ATUAL contra cada variante, nas MESMAS partidas,
so' com o que se sabia antes do apito.

SOMENTE LEITURA. Uso:
  python src/scripts/comparar_motor.py --prod [--minutos-antes 120] [--limit N]

A REGRA (pedido do usuario, 09/10): nenhuma mudanca vira "melhoria" porque e'
mais sofisticada ou porque meia duzia de picks deu GREEN. Ela so' passa se,
reexecutando o motor atual e a variante NAS MESMAS PARTIDAS, com a mesma
odd e o mesmo historico disponiveis antes do jogo, a variante ganhar com
margem maior que o ruido -- e nas duas metades do periodo.

O QUE E' "SEM DADO FUTURO"
--------------------------
  odd       odds_snapshots, a ultima cotacao pelo menos N minutos antes do
            apito (SnapshotOddsService). Padrao 120: o preco de quem rodaria o
            motor de manha, nao o de fechamento.
  historico MatchStatsService com before_date = data do jogo.
  conversao conversao da liga so' com jogos anteriores (_conversao_ate).
  contexto  escalacoes e calendario so' de jogos anteriores; tecnico SO' pelas
            escalacoes (o cache e a /coachs sabem o tecnico de hoje). Desfalque
            NAO entra: /injuries nao guarda o que se sabia num dia passado.
  tatico    coeficientes reestimados SO' com partidas anteriores ao inicio da
            janela testada (a tabela gravada usa a base inteira).
  CLV       a mesma linha no retrato mais proximo do apito (mediana das casas).

AS VARIANTES (todas contra `atual`)
-----------------------------------
  atual                o motor como publica hoje (contexto e tatico desligados,
                       melhor do jogo pelo final_score, stake de hoje)
  seletor_valor        mesmos candidatos; publica o de maior EV no limite
                       inferior da probabilidade (ranking.escolher_por_valor)
  seletor_ev           idem, EV puro (z=0)
  stake_probabilidade  mesmos picks; stake com o Kelly lendo a probabilidade
  contexto_on          MOTOR_CONTEXTO=on (sem desfalques -- ver acima)
  tatico_on            MOTOR_TATICO=on com coeficientes de antes da janela

O QUE SAI
---------
Por variante: picks, acerto, ROI (1u) com erro-padrao, Brier, log-loss e ECE da
probabilidade publicada, CLV, lucro com stake e drawdown maximo, por mercado e
competicao. Contra `atual`, PAREADO por partida (sem pick = 0): diferenca de
lucro por jogo com erro-padrao, no periodo todo e em cada metade, e diferenca
de CLV nas partidas em que as duas tem fechamento.

VEREDITO: "MELHOR" so' com diferenca de lucro > 2 erros-padrao no periodo, o
mesmo sinal nas duas metades e CLV que nao piora. Fora disso: manter o atual.
"""
from __future__ import annotations

import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time as dtime
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MOTOR_CONTEXTO_COACHS"] = "off"     # replay nunca pergunta o presente

# Reaproveita a carga do backtest (ambiente --prod, historico, conversao, nota).
from scripts import backtest_pick_engine_full as bt  # noqa: E402
from services.pick_engine import analyze_fixture_markets, ranking  # noqa: E402
from services.pick_engine import efeito_tatico, contexto_atual  # noqa: E402
from services.pick_engine.config import VIP_CONFIG  # noqa: E402
from services.pick_engine.staking import (  # noqa: E402
    calculate_stake, calculate_stake_por_probabilidade)

VARIANTES = ("atual", "seletor_valor", "seletor_ev", "stake_probabilidade",
             "contexto_on", "tatico_on")
#: Configuracao do motor por variante: (MOTOR_CONTEXTO, MOTOR_TATICO).
_MOTOR = {"atual": ("off", "off"), "contexto_on": ("on", "off"), "tatico_on": ("off", "on")}
MIN_GRUPO = 20


# ---------------------------------------------------------------------------
# Selecao e stake (puras -- o teste cobre)
# ---------------------------------------------------------------------------
def escolher(picks: list, seletor: str) -> dict | None:
    """O pick que cada seletor publicaria entre os aprovados do jogo."""
    if not picks:
        return None
    if seletor == "valor":
        return ranking.escolher_por_valor(picks, z=1.0)
    if seletor == "ev":
        return ranking.escolher_por_valor(picks, z=0.0)
    return next((p for p in picks if p.get("is_best_pick")), picks[0])


def unidades(pick: dict, regua: str) -> int:
    if regua == "probabilidade":
        return calculate_stake_por_probabilidade(
            pick["taxa_real"], pick["confidence"], pick["odd"], pick["ev"], "vip")[1]
    return calculate_stake(confidence=pick["confidence"], odd=pick["odd"],
                           ev=pick["ev"], pick_type="vip")[1]


# ---------------------------------------------------------------------------
# Metricas (puras)
# ---------------------------------------------------------------------------
def media_ep(v: list) -> tuple:
    n = len(v)
    if n == 0:
        return None, None
    m = sum(v) / n
    if n < 2:
        return m, None
    return m, math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) / math.sqrt(n)


def drawdown(lucros_em_ordem: list) -> float:
    pico = acum = pior = 0.0
    for x in lucros_em_ordem:
        acum += x
        pico = max(pico, acum)
        pior = min(pior, acum - pico)
    return round(pior, 2)


def resumo(linhas: list) -> dict:
    """linhas: dicts com prob, result, profit, units, clv, data."""
    dec = [l for l in linhas if l["result"] in ("GREEN", "RED")]
    if not linhas:
        return {"n": 0}
    roi, ep = media_ep([l["profit"] for l in linhas])
    pares = [(l["prob"], 1 if l["result"] == "GREEN" else 0) for l in dec]
    brier = (sum((p - o) ** 2 for p, o in pares) / len(pares)) if pares else None
    ll = (-sum(o * math.log(max(p, 1e-6)) + (1 - o) * math.log(max(1 - p, 1e-6))
               for p, o in pares) / len(pares)) if pares else None
    clvs = [l["clv"] for l in linhas if l.get("clv") is not None]
    em_ordem = sorted(linhas, key=lambda l: l["data"])
    return {"n": len(linhas), "acerto": (sum(o for _, o in pares) / len(pares)) if pares else None,
            "roi": roi, "ep_roi": ep, "brier": brier, "logloss": ll,
            "ece": bt.pe_metrics.expected_calibration_error(bt.pe_metrics.reliability_curve(
                [{"confidence": p, "result": "GREEN" if o else "RED"} for p, o in pares])),
            "clv": media_ep(clvs)[0], "n_clv": len(clvs),
            "lucro_stake": round(sum(l["profit"] * l["units"] for l in linhas), 2),
            "drawdown_stake": drawdown([l["profit"] * l["units"] for l in em_ordem])}


def pareado(atual: dict, variante: dict, campo: str = "profit") -> dict:
    """Por partida (fixture_id -> linha ou None). Sem pick conta 0 de lucro."""
    ids = sorted(set(atual) | set(variante), key=lambda f: (atual.get(f) or variante.get(f))["data"])
    if not ids:
        return {"n": 0}
    dif = [((variante.get(f) or {}).get(campo) or 0.0) - ((atual.get(f) or {}).get(campo) or 0.0)
           for f in ids]
    meio = len(ids) // 2
    m, ep = media_ep(dif)
    m1, ep1 = media_ep(dif[:meio])
    m2, ep2 = media_ep(dif[meio:])
    clv = [variante[f]["clv"] - atual[f]["clv"] for f in ids
           if atual.get(f) and variante.get(f)
           and atual[f].get("clv") is not None and variante[f].get("clv") is not None]
    mc, ec = media_ep(clv)
    return {"n": len(ids), "diferente": sum(1 for f in ids if _chave(atual.get(f)) != _chave(variante.get(f))),
            "d": m, "ep": ep, "d_1a_metade": m1, "ep_1a": ep1, "d_2a_metade": m2, "ep_2a": ep2,
            "d_clv": mc, "ep_clv": ec, "n_clv": len(clv)}


def _chave(l):
    return None if not l else (l["market_type"], l["linha"])


def veredito(p: dict) -> str:
    if not p.get("n") or p.get("ep") is None or p.get("ep_1a") is None or p.get("ep_2a") is None:
        return "AMOSTRA INSUFICIENTE: manter o atual."
    if not p["diferente"]:
        return "IDENTICA ao atual nestas partidas: nada a decidir."
    ganha = p["d"] > 2 * p["ep"]
    estavel = p["d_1a_metade"] > 0 and p["d_2a_metade"] > 0
    clv_ok = p.get("d_clv") is None or p["d_clv"] >= -(p.get("ep_clv") or 0)
    if ganha and estavel and clv_ok:
        return (f"MELHOR: {p['d']:+.3f}u por jogo ({p['d'] / p['ep']:.1f} EP), positivo nas duas "
                f"metades, CLV {'sem dado' if p.get('d_clv') is None else f'{p['d_clv']:+.3f}'}.")
    motivos = []
    if not ganha:
        motivos.append(f"diferenca {p['d']:+.3f}u/jogo nao passa de 2 EP ({2 * p['ep']:.3f})")
    if not estavel:
        motivos.append(f"metades com sinais diferentes ({p['d_1a_metade']:+.3f} / {p['d_2a_metade']:+.3f})")
    if not clv_ok:
        motivos.append(f"CLV pior ({p['d_clv']:+.3f})")
    return "SEM EVIDENCIA, manter o atual: " + "; ".join(motivos)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def _kickoff(d):
    return d if isinstance(d, datetime) else datetime.combine(d, dtime(12, 0))


def _fechamento(cur, fixture_id, market_id, linha) -> float | None:
    cur.execute("""
        SELECT DISTINCT ON (bookmaker_id) odd_value FROM odds_snapshots
         WHERE fixture_id = %s AND market_id = %s AND LOWER(value_name) = LOWER(%s)
           AND minutes_to_kickoff BETWEEN 0 AND 90
         ORDER BY bookmaker_id, minutes_to_kickoff ASC
    """, (fixture_id, market_id, linha))
    odds = [float(r[0]) for r in cur.fetchall() if r[0] and float(r[0]) > 1]
    return median(odds) if odds else None


def _contexto_replay(cur, fx) -> dict | None:
    from collectors.calendario_service import carga_do_time
    quando = _kickoff(fx["match_date"])
    cal = {}
    for t in (fx["home_team_id"], fx["away_team_id"]):
        try:
            c = carga_do_time(cur, t, quando)
            if c:
                cal[t] = c
        except Exception:
            cur.connection.rollback()
    try:
        return contexto_atual.coletar(cur, fx["fixture_id"], fx["home_team_id"], fx["away_team_id"],
                                      quando, {}, cal, league_id=fx["league_id"],
                                      season=fx["season"], replay=True)
    except Exception:
        cur.connection.rollback()
        return None


def _tabela_antes_de(inicio) -> dict:
    """Coeficientes taticos estimados SO' com partidas anteriores a `inicio`."""
    from scripts import medir_efeito_tatico as med
    from utils.db_utils import get_connection
    conn = get_connection()
    cur = conn.cursor()
    try:
        jogos, escal, pos, clima = med.carregar(cur)
    finally:
        cur.close()
        conn.close()
    linhas = [l for l in med.montar_linhas([j for j in jogos if j["match_date"] < inicio],
                                           escal, pos, clima)]
    tabela = {}
    for est in efeito_tatico.ESTATISTICAS:
        e = med.estimar(linhas, est)
        if e and e["coefs"]:
            tabela[est] = {"coefs": e["coefs"], "medias": e["medias"], "desvios": e["desvios"],
                           "aprovado": True}
    return tabela


def rodar_partida(fx, ctx, ms, odds_service, checker, calibracao, cur) -> dict:
    """{variante: linha ou None} pra UMA partida."""
    odds = odds_service.load_odds_structured(fx["fixture_id"])
    if not odds:
        return {}
    hc = bt._load_history(ms, fx["home_team_id"], fx["season"], fx["league_id"], fx["match_date"])
    hf = bt._load_history(ms, fx["away_team_id"], fx["season"], fx["league_id"], fx["match_date"])
    if not hc or not hf:
        return {}
    vh, va = bt.dv.validate_history(hc), bt.dv.validate_history(hf)
    if not vh["passed"] or not va["passed"]:
        return {}
    context_data, matchup, strength = bt._build_signals(
        hc, hf, fx["home_team_id"], fx["away_team_id"], fx["league_id"], fx["match_date"])
    cov = bt.dv.validate_coverage(structured_odds=odds, last10_home=hc, last10_away=hf,
                                  context_data=context_data)
    q = bt.dv.data_quality_score({"Q": min(vh["Q"], va["Q"])}, cov)
    stats = checker.get_fixture_result(fx["fixture_id"], cur)
    if not stats:
        return {}
    picks_por_motor = {}
    for nome, (mc, mt) in _MOTOR.items():
        os.environ["MOTOR_CONTEXTO"], os.environ["MOTOR_TATICO"] = mc, mt
        cands = analyze_fixture_markets(
            odds, hc, hf, reference_date=fx["match_date"], config=VIP_CONFIG,
            calibration_data=calibracao, context_data=context_data, matchup_data=matchup,
            team_strength_data=strength, data_quality_score=q["score"],
            home_team_id=fx["home_team_id"], away_team_id=fx["away_team_id"],
            league_baseline=bt._conversao_ate(cur, fx["league_id"], fx["match_date"]),
            contexto_partida=ctx if mc == "on" else None)
        picks_por_motor[nome] = ranking.select_final_picks(
            ranking.rank_all_candidates(cands, VIP_CONFIG))
    plano = {"atual": ("atual", "score", "confidence"),
             "seletor_valor": ("atual", "valor", "confidence"),
             "seletor_ev": ("atual", "ev", "confidence"),
             "stake_probabilidade": ("atual", "score", "probabilidade"),
             "contexto_on": ("contexto_on", "score", "confidence"),
             "tatico_on": ("tatico_on", "score", "confidence")}
    saida = {}
    for var, (motor, seletor, regua) in plano.items():
        p = escolher(picks_por_motor[motor], seletor)
        if not p:
            saida[var] = None
            continue
        g = bt._grade(checker, stats, p)
        if not g:
            saida[var] = None
            continue
        fech = _fechamento(cur, fx["fixture_id"], p.get("market_id"), p.get("value_label"))
        saida[var] = {"data": fx["match_date"], "league_id": fx["league_id"],
                      "market_type": p["market_type"], "linha": p.get("value_label"),
                      "prob": float(p["taxa_real"]), "odd": float(p["odd"]),
                      "result": g["result"], "profit": float(g["profit"]),
                      "units": unidades(p, regua),
                      "clv": (round(float(p["odd"]) / fech - 1, 4) if fech else None)}
    return saida


def imprimir(por_var: dict) -> list:
    base = por_var["atual"]
    melhores = []
    print(f"\n{'variante':22} {'n':>4} {'acerto':>7} {'ROI/1u':>8} {'±':>6} {'Brier':>6} "
          f"{'logloss':>7} {'ECE':>5} {'CLV':>7} {'lucro stake':>11} {'drawdown':>9}")
    for var in VARIANTES:
        r = resumo([l for l in por_var[var].values() if l])
        if not r["n"]:
            print(f"{var:22} sem picks")
            continue
        f = lambda v, d=3: "-" if v is None else f"{v:+.{d}f}"
        print(f"{var:22} {r['n']:4d} {r['acerto'] or 0:7.1%} {f(r['roi'])} {r['ep_roi'] or 0:6.3f} "
              f"{r['brier'] or 0:6.3f} {r['logloss'] or 0:7.3f} {r['ece'] or 0:5.3f} "
              f"{f(r['clv'])} ({r['n_clv']}) {r['lucro_stake']:+11.2f} {r['drawdown_stake']:+9.2f}")
    print("\nCONTRA O ATUAL, nas mesmas partidas (sem pick = 0):")
    for var in VARIANTES[1:]:
        p = pareado(base, por_var[var], "profit")
        if var == "stake_probabilidade":
            for d in (base, por_var[var]):
                for l in d.values():
                    if l:
                        l["lucro_stake"] = l["profit"] * l["units"]
            p = pareado(base, por_var[var], "lucro_stake")
        v = veredito(p)
        print(f"  {var:22} partidas={p.get('n', 0)} diferentes={p.get('diferente', 0)}  {v}")
        if v.startswith("MELHOR"):
            melhores.append(var)
    print("\nPOR MERCADO E COMPETICAO (atual x seletor_valor, n >= %d):" % MIN_GRUPO)
    for chave in ("market_type", "league_id"):
        grupos = defaultdict(lambda: {"atual": [], "seletor_valor": []})
        for var in ("atual", "seletor_valor"):
            for l in por_var[var].values():
                if l:
                    grupos[l[chave]][var].append(l)
        for k, g in sorted(grupos.items(), key=lambda kv: str(kv[0])):
            if len(g["atual"]) < MIN_GRUPO:
                continue
            a, s = resumo(g["atual"]), resumo(g["seletor_valor"])
            print(f"  {chave}={k}: atual n={a['n']} ROI {a['roi']:+.3f}±{a['ep_roi'] or 0:.3f} | "
                  f"valor n={s.get('n', 0)} ROI {(s.get('roi') or 0):+.3f}±{(s.get('ep_roi') or 0):.3f}")
    return melhores


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--minutos-antes", type=int, default=120)
    # As N partidas MAIS RECENTES (o agendador usa isto pra caber no limite de
    # 15 minutos). --limit corta as mais antigas, como no backtest.
    ap.add_argument("--ultimas", type=int, default=None)
    args = ap.parse_args()
    from services.odds_snapshot_service import SnapshotOddsService
    odds_service = SnapshotOddsService(minutos_antes=args.minutos_antes)
    fixtures = odds_service.fixtures_com_snapshot(limit=args.limit)
    if args.ultimas:
        fixtures = fixtures[-args.ultimas:]
    if not fixtures:
        print("Nenhuma partida encerrada com odd arquivada antes do apito.")
        return
    inicio = min(f["match_date"] for f in fixtures)
    print(f"{len(fixtures)} partidas com odd >= {args.minutos_antes} min antes do apito, "
          f"de {inicio} a {max(f['match_date'] for f in fixtures)}")
    tabela = _tabela_antes_de(inicio)
    print(f"tatico: coeficientes estimados antes de {inicio} em {len(tabela)} mercado(s)")
    efeito_tatico.tabela_em_cache = lambda: tabela      # replay le' so' o passado
    ms, checker = bt.MatchStatsService(), bt.AIResultCheckerService()
    calibracao = bt.get_market_calibration()
    conn = bt.get_connection()
    cur = conn.cursor()
    por_var = {v: {} for v in VARIANTES}
    feitas = 0
    for fx in fixtures:
        try:
            ctx = _contexto_replay(cur, fx)
            r = rodar_partida(fx, ctx, ms, odds_service, checker, calibracao, cur)
        except Exception as e:
            cur.connection.rollback()
            print(f"  fixture {fx['fixture_id']}: {e}")
            continue
        if r:
            feitas += 1
            for v in VARIANTES:
                if r.get(v):
                    por_var[v][fx["fixture_id"]] = r[v]
    cur.close()
    conn.close()
    print(f"{feitas} partidas reexecutadas")
    melhores = imprimir(por_var)
    print("\n=== Leitura ===")
    print(("Variantes que ganham do atual com margem e estabilidade: " + ", ".join(melhores))
          if melhores else "Nenhuma variante ganha do motor atual com margem fora do ruido. Manter o atual.")


if __name__ == "__main__":
    main()
