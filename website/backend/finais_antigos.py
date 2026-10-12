"""O "Final" das pernas que fecharam ANTES de ele ser gravado (12/10/2026).

Desde 11/10 a liquidacao grava o numero que decidiu cada perna de Multipla,
Bingo, Alavancagem e Boost, e o card mostra "Final: 18 escanteios". O que ja'
tinha fechado antes ficou sem o numero -- e a Alavancagem, sem saber nem qual
perna caiu.

Aqui ele e' preenchido pela folha que JA' ESTA no banco (`match_statistics`):
nenhuma chamada a' API. O numero sai pela mesma leitura que decide o
resultado (`routers.live._stat_for_market`) sobre a mesma folha convertida
pelo mesmo adaptador do card (`market_form.folha_do_jogo`), entao ele nao tem
como discordar do que liquidou -- e, quando a folha nao responde (contador
ausente, 2o tempo, prorrogacao), fica sem numero em vez de inventar um.

Cartao: so' a contagem VALIDADA (banco e comissao fora), a que liquida desde
10/09. Sem ela, sem numero.

Idempotente e com teto por passada: so' toca perna que ainda nao tem o numero.
"""
from __future__ import annotations

import json
import logging

import market_form
from settlement_bridge import settlement

logger = logging.getLogger(__name__)

#: Bilhetes de no maximo tantos dias atras. O card antigo some da tela antes.
JANELA_DIAS = 60
TETO_POR_TABELA = 300


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def valor_final(market: str | None, market_type: str | None, line: str | None,
                ms: dict | None) -> float | None:
    """O contador que decidiu a perna, lido da folha gravada. None = nao sei."""
    if not ms or ms.get("status") not in ("FT", "AET", "PEN"):
        return None
    if market_form.e_mercado_de_segundo_tempo(market):
        return None
    from routers import live
    primeiro = market_form.e_mercado_de_primeiro_tempo(market, market_type)
    if market_form.e_mercado_de_cartoes(market, market_type):
        if primeiro:
            return None
        cols = ("valid_yellow_home", "valid_yellow_away", "valid_red_home", "valid_red_away")
        hy, ay, hr, ar = (ms.get(c) for c in cols)
        if any(v is None for v in (hy, ay, hr, ar)):
            return None
        escopo = market_form.escopo_do_mercado((market or "").lower())
        if escopo == "home":
            return float(hy + 2 * hr)
        if escopo == "away":
            return float(ay + 2 * ar)
        return float(hy + 2 * hr + ay + 2 * ar)
    if ms.get("status") in ("AET", "PEN") and not primeiro:
        # Folha de prorrogacao soma 120 min; so' gol tem o recorte dos 90.
        hg, ag = ms.get("home_goals_90"), ms.get("away_goals_90")
        if hg is None or ag is None:
            return None
        casa, fora = {}, {}
    else:
        casa, fora = market_form.folha_do_jogo(ms, primeiro_tempo=primeiro)
        hg = ms.get("home_goals_ht") if primeiro else ms.get("home_goals")
        ag = ms.get("away_goals_ht") if primeiro else ms.get("away_goals")
    if hg is None or ag is None:
        return None
    valor, _, _ = live._stat_for_market(market or "", line or "", casa, fora,
                                        int(hg), int(ag), market_type)
    return _num(valor)


def _folhas(cur, fids: set) -> dict:
    if not fids:
        return {}
    cur.execute("SELECT * FROM match_statistics WHERE fixture_id = ANY(%s)",
                (sorted(int(f) for f in fids),))
    return {int(r["fixture_id"]): dict(r) for r in cur.fetchall()}


def _cartelas(cur, tabela: str) -> int:
    cur.execute(f"""SELECT id, games FROM {tabela}
                     WHERE result IS NOT NULL AND games IS NOT NULL
                       AND match_date >= CURRENT_DATE - %s
                     ORDER BY match_date DESC LIMIT %s""", (JANELA_DIAS, TETO_POR_TABELA))
    linhas = []
    for r in cur.fetchall():
        pernas = r["games"]
        if isinstance(pernas, str):
            try:
                pernas = json.loads(pernas)
            except Exception:
                continue
        if isinstance(pernas, list) and any(
                isinstance(g, dict) and g.get("result") in settlement.RESULT_LABELS
                and g.get("settled_value") is None and g.get("fixture_id") for g in pernas):
            linhas.append((r["id"], pernas))
    folhas = _folhas(cur, {g["fixture_id"] for _, ps in linhas for g in ps
                           if isinstance(g, dict) and g.get("fixture_id")})
    feitas = 0
    for pid, pernas in linhas:
        mudou = False
        for g in pernas:
            if not isinstance(g, dict) or g.get("settled_value") is not None:
                continue
            if g.get("result") not in settlement.RESULT_LABELS or not g.get("fixture_id"):
                continue
            v = valor_final(g.get("market"), g.get("market_type"), g.get("line"),
                            folhas.get(int(g["fixture_id"])))
            if v is not None:
                g["settled_value"] = v
                mudou = True
        if mudou:
            cur.execute(f"UPDATE {tabela} SET games = %s WHERE id = %s",
                        (json.dumps(pernas, default=str), pid))
            feitas += 1
    return feitas


def _alavancagens(cur) -> int:
    cur.execute("""SELECT pa.*, to_jsonb(pa) -> 'pernas_final' AS pf
                     FROM picks_alavancagem pa
                    WHERE pa.result IS NOT NULL
                      AND (to_jsonb(pa) -> 'pernas_final') IS NULL
                      AND pa.match_date >= CURRENT_DATE - %s
                    ORDER BY pa.match_date DESC LIMIT %s""", (JANELA_DIAS, TETO_POR_TABELA))
    linhas = [dict(r) for r in cur.fetchall()]
    folhas = _folhas(cur, {r.get(f"fixture_id_{i}") for r in linhas for i in (1, 2, 3)
                           if r.get(f"fixture_id_{i}")})
    from routers import live
    feitas = 0
    for r in linhas:
        pernas = []
        for i in (1, 2, 3):
            fid = r.get(f"fixture_id_{i}")
            if not fid:
                continue
            ms = folhas.get(int(fid))
            market, mtype, line = r.get(f"market_{i}"), r.get(f"market_type_{i}"), r.get(f"line_{i}")
            v = valor_final(market, mtype, line, ms)
            res = None
            if ms and ms.get("status") == "FT":
                primeiro = market_form.e_mercado_de_primeiro_tempo(market, mtype)
                casa, fora = market_form.folha_do_jogo(ms, primeiro_tempo=primeiro)
                hg = ms.get("home_goals_ht") if primeiro else ms.get("home_goals")
                ag = ms.get("away_goals_ht") if primeiro else ms.get("away_goals")
                if hg is not None and ag is not None:
                    # Cartao: o contador validado (v) e' o unico que liquida.
                    cartao = market_form.e_mercado_de_cartoes(market, mtype)
                    if not cartao or v is not None:
                        res = live._calc_result(
                            market or "", line or "", v, int(hg), int(ag), market_type=mtype,
                            home_team=r.get(f"home_team_{i}"), away_team=r.get(f"away_team_{i}"),
                            home_stats=casa, away_stats=fora)
            # GREEN no bilhete implica todas as pernas GREEN · deducao, nao conta.
            if r.get("result") == "GREEN":
                res = "GREEN"
            pernas.append((i, res, v))
        if pernas and any(res or v is not None for _, res, v in pernas):
            cur.execute("UPDATE picks_alavancagem SET pernas_final = %s WHERE id = %s",
                        (live._pernas_final(pernas), r["id"]))
            feitas += 1
    return feitas


def _boosts(cur) -> int:
    cur.execute("""SELECT pb.id, pb.fixture_id, pb.result_ft, pb.result_ht,
                          ms.home_goals, ms.away_goals, ms.home_goals_ht, ms.away_goals_ht,
                          ms.home_goals_90, ms.away_goals_90, ms.status
                     FROM picks_boost pb
                     JOIN match_statistics ms ON ms.fixture_id = pb.fixture_id
                    WHERE pb.result IS NOT NULL
                      AND (to_jsonb(pb) -> 'pernas_final') IS NULL
                      AND pb.match_date >= CURRENT_DATE - %s
                    LIMIT %s""", (JANELA_DIAS, TETO_POR_TABELA))
    from routers import live
    feitas = 0
    for r in cur.fetchall():
        prorrogou = r["status"] in ("AET", "PEN")
        hg = r["home_goals_90"] if prorrogou else r["home_goals"]
        ag = r["away_goals_90"] if prorrogou else r["away_goals"]
        ft = float(hg + ag) if hg is not None and ag is not None else None
        ht = (float(r["home_goals_ht"] + r["away_goals_ht"])
              if r["home_goals_ht"] is not None and r["away_goals_ht"] is not None else None)
        if ft is None and ht is None:
            continue
        cur.execute("UPDATE picks_boost SET pernas_final = %s WHERE id = %s",
                    (live._pernas_final([(1, r["result_ft"], ft if r["result_ft"] else None),
                                         (2, r["result_ht"], ht if r["result_ht"] else None)]),
                     r["id"]))
        feitas += 1
    return feitas


def preencher(conn) -> dict:
    """Uma passada. Cada parte em savepoint: uma tabela ausente nao derruba as outras."""
    cur = conn.cursor()
    feitas: dict = {}
    for nome, fn in (("multipla", lambda: _cartelas(cur, "picks_multiplas")),
                     ("bingo", lambda: _cartelas(cur, "picks_bingo")),
                     ("alavancagem", lambda: _alavancagens(cur)),
                     ("boost", lambda: _boosts(cur))):
        try:
            cur.execute("SAVEPOINT finais")
            feitas[nome] = fn()
            cur.execute("RELEASE SAVEPOINT finais")
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT finais")
            logger.warning("[FINAIS] %s: %s", nome, e)
    conn.commit()
    cur.close()
    return feitas
