import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from database import get_connection
from auth_utils import get_current_user
from routers.payments import PLANS

router = APIRouter(prefix="/api/banca", tags=["banca"])

BR_TZ = ZoneInfo("America/Sao_Paulo")

# Rate limit por usuario nas mutacoes de banca (setup/saque/seguir/cashout) --
# nao existiam limites aqui antes, so em login/cadastro/chat. Generoso o
# bastante pra nunca ser atingido por uso real (a UI nao dispara isso em
# loop), so barra automacao/spam roteirizado.
_banca_mutation_rate: dict[int, list[float]] = defaultdict(list)
_BANCA_MUTATION_LIMIT  = 20
_BANCA_MUTATION_WINDOW = 60


def _check_banca_rate(user_id: int) -> None:
    now = time.time()
    _banca_mutation_rate[user_id] = [t for t in _banca_mutation_rate[user_id] if now - t < _BANCA_MUTATION_WINDOW]
    if len(_banca_mutation_rate[user_id]) >= _BANCA_MUTATION_LIMIT:
        raise HTTPException(429, "Muitas requisições. Aguarde um momento e tente novamente.")
    _banca_mutation_rate[user_id].append(now)


class BancaSetup(BaseModel):
    bankroll_start: float
    bankroll_goal: Optional[float] = None
    unit_value: Optional[float] = None  # R$ por unidade; None = manter atual
    monthly_close_month_key: Optional[str] = None  # 'YYYY-MM'; presente quando vem do fechamento mensal


class BancaWithdraw(BaseModel):
    amount: float


class FollowPick(BaseModel):
    pick_id: int
    pick_type: str
    stake_units: float = 1.0
    actual_odd: Optional[float] = Field(default=None, gt=1, le=1000)
    bet_house: Optional[str] = None


class CashoutBody(BaseModel):
    cashout_amount: float  # valor recebido de volta em R$


# Picks de mercado proprio (faltas, defesas de goleiro). Estrutura identica a
# de picks_free -- um jogo, um mercado, uma odd -- entao entram no calculo da
# banca pelo mesmo caminho, sem tratamento especial.
#
# O helper existe porque o type_map e' montado em 4 lugares diferentes deste
# modulo. Um tipo esquecido em qualquer um deles nao da erro: o pick
# simplesmente some do somatorio (type_map.get devolve {} e o loop faz
# `continue`), e a banca do usuario fica errada em silencio.
_TABELAS_MERCADO = {"faltas": "picks_faltas", "goleiros": "picks_goleiros"}


def _mercado_maps(cur, followed: list, colunas: str = "id, result, odd") -> dict:
    maps: dict = {}
    for tipo, tabela in _TABELAS_MERCADO.items():
        ids = [f["pick_id"] for f in followed if f["pick_type"] == tipo]
        m: dict = {}
        if ids:
            try:
                cur.execute(f"SELECT {colunas} FROM {tabela} WHERE id = ANY(%s)", (ids,))
                for r in cur.fetchall():
                    m[r["id"]] = dict(r)
            except Exception:
                # Instancia sem a migracao das tabelas novas: segue sem elas
                # em vez de derrubar a banca inteira.
                cur.connection.rollback()
        maps[tipo] = m
    return maps


def _resolve_pick(cur, pick_id: int, pick_type: str) -> Optional[dict]:
    if pick_type == "vip":
        cur.execute("""
            SELECT pv.result, pv.profit,
                   pv.home_team_name, pv.away_team_name,
                   pv.home_team_id, pv.away_team_id,
                   pv.market, pv.line, pv.odd,
                   f.match_datetime
            FROM picks_vip pv
            LEFT JOIN fixtures f ON f.fixture_id = pv.fixture_id
            WHERE pv.id = %s
        """, (pick_id,))
    elif pick_type == "free":
        cur.execute("""
            SELECT pf.result, pf.profit, 1 AS stake,
                   pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                   pf.market, pf.line, pf.odd,
                   f.match_datetime
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            WHERE pf.id = %s
        """, (pick_id,))
    elif pick_type == "multipla":
        cur.execute("""
            SELECT result, profit, 1 AS stake,
                   NULL AS home_team_name, NULL AS away_team_name,
                   NULL AS home_team_id, NULL AS away_team_id,
                   NULL AS market, NULL AS line,
                   total_odd AS odd,
                   games AS legs_json,
                   COALESCE(prob_combinada, score_combo) AS confidence,
                   NULL AS match_datetime
            FROM picks_multiplas WHERE id = %s
        """, (pick_id,))
    elif pick_type == "alavancagem":
        cur.execute("""
            SELECT pa.result, pa.profit,
                   pa.home_team_1 AS home_team_name, pa.away_team_1 AS away_team_name,
                   f1.home_team_id, f1.away_team_id,
                   pa.market_1 AS market, pa.line_1 AS line,
                   pa.odd_combined AS odd,
                   f1.match_datetime
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            WHERE pa.id = %s
        """, (pick_id,))
    elif pick_type == "faltas":
        cur.execute("""
            SELECT pf.result, pf.profit, 1 AS stake,
                   pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                   pf.market, pf.line, pf.odd,
                   f.match_datetime
            FROM picks_faltas pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            WHERE pf.id = %s
        """, (pick_id,))
    elif pick_type == "goleiros":
        # A "linha" ja vem pronta do pipeline no formato "<goleiro> · N ou
        # mais defesas" -- e' prop de jogador, entao o nome do goleiro faz
        # parte da aposta e nao pode ficar so' no campo player_name.
        cur.execute("""
            SELECT pg.result, pg.profit, 1 AS stake,
                   pg.home_team AS home_team_name, pg.away_team AS away_team_name,
                   COALESCE(pg.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pg.away_team_id, f.away_team_id) AS away_team_id,
                   pg.market, pg.line, pg.odd,
                   f.match_datetime
            FROM picks_goleiros pg
            LEFT JOIN fixtures f ON f.fixture_id = pg.fixture_id
            WHERE pg.id = %s
        """, (pick_id,))
    else:
        return None
    row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    # Para múltipla: extrai primeiro time dos legs + kickoff mais cedo entre as pernas
    if pick_type == "multipla" and d.get("legs_json"):
        import json as _json
        try:
            legs = _json.loads(d["legs_json"]) if isinstance(d["legs_json"], str) else (d["legs_json"] or [])
        except Exception:
            legs = []
        if legs:
            first = legs[0]
            d["home_team_name"] = first.get("home") or first.get("home_team")
            d["away_team_name"] = first.get("away") or first.get("away_team")
            d["home_team_id"]   = first.get("home_team_id")
            d["away_team_id"]   = first.get("away_team_id")
            fixture_ids = [leg["fixture_id"] for leg in legs if leg.get("fixture_id")]
            if fixture_ids:
                cur.execute("SELECT MIN(match_datetime) AS md FROM fixtures WHERE fixture_id = ANY(%s)", (fixture_ids,))
                md_row = cur.fetchone()
                d["match_datetime"] = md_row["md"] if md_row else None
        d["market"] = f"Múltipla · {len(legs)} seleções"
        del d["legs_json"]
    return d


def _compute_streak(resolved: list) -> dict:
    """Calcula streak atual e melhor streak."""
    streak = 0
    streak_type = None
    for e in reversed(resolved):
        r = e.get("result")
        if r not in ("GREEN", "RED"):
            continue
        t = "green" if r == "GREEN" else "red"
        if streak_type is None:
            streak_type = t; streak = 1
        elif streak_type == t:
            streak += 1
        else:
            break

    best = 0
    temp = 0
    for e in resolved:
        r = e.get("result")
        if r == "GREEN":
            temp += 1
            if temp > best: best = temp
        else:
            temp = 0

    return {"streak": streak, "streak_type": streak_type, "best_streak": best}


def _compute_follow_pnl(pick: dict, follow: dict, unit_value: float):
    """
    P&L de um pick seguido, em unidades e em R$. Cashout sempre sobrepõe o
    resultado oficial. Usa actual_odd (odd que o usuário realmente pegou) se
    informado, senão cai pra odd oficial do pick.
    Retorna (result_label, profit_units, pnl_reais) ou (None, None, None)
    se ainda não resolvido e sem cashout.
    """
    cashout_amount = float(follow["cashout_amount"]) if follow.get("cashout_amount") is not None else None
    stake_units = float(follow["stake_units"])

    if cashout_amount is not None:
        stake_r = stake_units * unit_value
        pnl_r = cashout_amount - stake_r
        profit_u = pnl_r / unit_value if unit_value else 0.0
        return "CASHOUT", profit_u, pnl_r

    result = pick.get("result")
    if result not in ("GREEN", "RED", "PUSH", "HALF-WIN", "HALF-LOSS"):
        return None, None, None

    actual_odd = float(follow["actual_odd"]) if follow.get("actual_odd") else None
    odd = actual_odd or float(pick.get("odd") or 1)

    if result == "GREEN":
        profit_u = odd - 1
    elif result == "RED":
        profit_u = -1.0
    elif result == "PUSH":
        profit_u = 0.0
    elif result == "HALF-WIN":
        profit_u = (odd - 1) / 2
    else:  # HALF-LOSS
        profit_u = -0.5

    pnl_r = profit_u * stake_units * unit_value
    return result, profit_u, pnl_r


def _get_bankroll_epoch(cur, user_id: int) -> Optional[str]:
    """
    Data-limite (exclusiva, 'YYYY-MM-DD') até onde o P&L do usuário já foi
    "rolado" pro bankroll_start no último fechamento mensal · ou None se nunca
    fechou (nesse caso a banca conta desde o início, comportamento anterior).

    Usa o fim do mês fechado (month_key), não o instante em que o usuário
    confirmou (closed_at): o usuário pode confirmar o fechamento de junho já em
    julho, e picks seguidos nesse intervalo (ex: 1-2 de julho, antes da
    confirmação) são de julho e não podem ficar de fora da banca atual até o
    fechamento seguinte.
    """
    cur.execute("SELECT MAX(month_key) AS last_month FROM banca_monthly_closes WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    last_month = row["last_month"] if row else None
    if not last_month:
        return None
    _, _, _, month_end = _month_bounds(last_month)
    return month_end


def _current_month_key() -> str:
    """Mês corrente 'YYYY-MM' no fuso de Brasília (não o do servidor)."""
    now = datetime.now(BR_TZ)
    return f"{now.year:04d}-{now.month:02d}"


def _month_bounds(month_key: str):
    """A partir de 'YYYY-MM', retorna (year, mo, month_start, month_end) como strings YYYY-MM-DD."""
    try:
        year, mo = int(month_key[:4]), int(month_key[5:7])
    except Exception:
        raise HTTPException(400, "Formato de mês inválido. Use YYYY-MM.")
    if not (1 <= mo <= 12):
        raise HTTPException(400, "Mês inválido. Use um valor entre 01 e 12.")
    month_start = f"{year:04d}-{mo:02d}-01"
    month_end = f"{year+1:04d}-01-01" if mo == 12 else f"{year:04d}-{mo+1:02d}-01"
    return year, mo, month_start, month_end


def _compute_bankroll_current(cur, user_id: int, bankroll_start: float, unit_value: float) -> float:
    """Banca atual "de verdade": bankroll_start (banca no ultimo fechamento mensal,
    ou desde sempre se nunca fechou) + PNL de tudo que segue dali pra frente.

    Sempre roda sobre TODO o historico desde o epoch, independente de qualquer
    filtro de periodo (days/from_date/to_date) que a tela esteja usando pra
    listar as entries -- serve de fonte unica de verdade pro "banca total" e
    a barra de progresso da meta em Banca.tsx. Bug real encontrado validando o
    fechamento mensal: GET /banca sempre usava bankroll_start (valor de HOJE,
    ja rolado pelos fechamentos) como base pro `running`, mas so somava o PNL
    do periodo filtrado -- ao navegar "Mes passado"/"Este mes"/dias apos algum
    fechamento ja ter empurrado bankroll_start pra frente, o numero exibido
    nao era nem a banca real de hoje, nem a banca real no fim daquele periodo.
    """
    epoch = _get_bankroll_epoch(cur, user_id)
    cond = " AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo') >= %s" if epoch is not None else ""
    params: list = [user_id] + ([epoch] if epoch is not None else [])
    cur.execute(f"""
        SELECT uf.pick_id, uf.pick_type, uf.stake_units, uf.actual_odd, uf.cashout_amount
        FROM user_followed_picks uf
        WHERE uf.user_id = %s AND uf.pick_type != 'alavancagem' {cond}
    """, params)
    followed = [dict(r) for r in cur.fetchall()]
    if not followed:
        return round(bankroll_start, 2)

    vip_ids      = [f["pick_id"] for f in followed if f["pick_type"] == "vip"]
    free_ids     = [f["pick_id"] for f in followed if f["pick_type"] == "free"]
    multipla_ids = [f["pick_id"] for f in followed if f["pick_type"] == "multipla"]

    vip_map: dict = {}
    if vip_ids:
        cur.execute("SELECT id, result, odd FROM picks_vip WHERE id = ANY(%s)", (vip_ids,))
        for r in cur.fetchall(): vip_map[r["id"]] = dict(r)
    free_map: dict = {}
    if free_ids:
        cur.execute("SELECT id, result, odd FROM picks_free WHERE id = ANY(%s)", (free_ids,))
        for r in cur.fetchall(): free_map[r["id"]] = dict(r)
    multipla_map: dict = {}
    if multipla_ids:
        cur.execute("SELECT id, result, total_odd AS odd FROM picks_multiplas WHERE id = ANY(%s)", (multipla_ids,))
        for r in cur.fetchall(): multipla_map[r["id"]] = dict(r)
    type_map = {"vip": vip_map, "free": free_map, "multipla": multipla_map,
                **_mercado_maps(cur, followed)}

    total = bankroll_start
    for f in followed:
        pick = type_map.get(f["pick_type"], {}).get(f["pick_id"])
        if not pick:
            continue
        _, _, pnl_r = _compute_follow_pnl(pick, f, unit_value)
        if pnl_r is not None:
            total += pnl_r
    return round(total, 2)


def _compute_month_stats(cur, user_id: int, month_start: str, month_end: str, unit_value: float) -> dict:
    """P&L e contagem de resultados (vip/free/multipla) de um usuário dentro de [month_start, month_end)."""
    cur.execute("""
        SELECT uf.id, uf.pick_id, uf.pick_type, uf.stake_units,
               uf.actual_odd, uf.cashout_amount
        FROM user_followed_picks uf
        WHERE uf.user_id = %s
          AND uf.pick_type != 'alavancagem'
          AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo') >= %s
          AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo') <  %s
        ORDER BY uf.followed_at ASC
    """, (user_id, month_start, month_end))
    followed = [dict(r) for r in cur.fetchall()]

    stats = {
        "total_pnl": 0.0, "greens": 0, "reds": 0, "push": 0,
        "half_wins": 0, "half_loss": 0, "total_resolved": 0,
        "total_followed": len(followed),
    }
    if not followed:
        return stats

    vip_ids      = [f["pick_id"] for f in followed if f["pick_type"] == "vip"]
    free_ids     = [f["pick_id"] for f in followed if f["pick_type"] == "free"]
    multipla_ids = [f["pick_id"] for f in followed if f["pick_type"] == "multipla"]

    vip_map: dict = {}
    if vip_ids:
        cur.execute("SELECT id, result, odd FROM picks_vip WHERE id = ANY(%s)", (vip_ids,))
        for r in cur.fetchall(): vip_map[r["id"]] = dict(r)

    free_map: dict = {}
    if free_ids:
        cur.execute("SELECT id, result, odd FROM picks_free WHERE id = ANY(%s)", (free_ids,))
        for r in cur.fetchall(): free_map[r["id"]] = dict(r)

    multipla_map: dict = {}
    if multipla_ids:
        cur.execute("SELECT id, result, total_odd AS odd FROM picks_multiplas WHERE id = ANY(%s)", (multipla_ids,))
        for r in cur.fetchall(): multipla_map[r["id"]] = dict(r)

    type_map = {"vip": vip_map, "free": free_map, "multipla": multipla_map,
                **_mercado_maps(cur, followed)}

    for f in followed:
        pick = type_map.get(f["pick_type"], {}).get(f["pick_id"])
        if not pick:
            continue
        result, _profit_u, pnl_r = _compute_follow_pnl(pick, f, unit_value)
        if result is None:
            continue
        stats["total_pnl"] += pnl_r
        stats["total_resolved"] += 1
        if result == "GREEN": stats["greens"] += 1
        elif result == "RED": stats["reds"] += 1
        elif result == "PUSH": stats["push"] += 1
        elif result == "HALF-WIN": stats["half_wins"] += 1
        elif result == "HALF-LOSS": stats["half_loss"] += 1

    stats["total_pnl"] = round(stats["total_pnl"], 2)
    return stats


@router.get("")
def get_banca(
    current_user: dict = Depends(get_current_user),
    days: int = Query(0, ge=0),        # 0 = tudo
    from_date: Optional[str] = Query(None),  # YYYY-MM-DD
    to_date:   Optional[str] = Query(None),  # YYYY-MM-DD
    resolved_offset: int = Query(0, ge=0),
    resolved_limit:  int = Query(100, ge=1, le=500),
):
    import json as _json
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT bankroll_start, bankroll_goal, unit_value, last_manual_setup_month FROM user_banca WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        bankroll_start = float(row["bankroll_start"]) if row else 100.0
        bankroll_goal  = float(row["bankroll_goal"]) if row and row["bankroll_goal"] else None
        unit_value = float(row["unit_value"]) if row and row["unit_value"] else 1.0
        can_configure = not (row and row["last_manual_setup_month"] == _current_month_key())

        date_cond = ""
        date_params: list = [user_id]
        if from_date and to_date:
            date_cond = " AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN %s AND %s"
            date_params += [from_date, to_date]
        elif from_date:
            date_cond = " AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s"
            date_params.append(from_date)
        elif days > 0:
            date_cond = " AND uf.followed_at >= NOW() - (%s * INTERVAL '1 day')"
            date_params.append(days)
        else:
            # "Tudo" sem filtro explícito = desde o último fechamento mensal (se houver).
            # Evita contar de novo o P&L de meses já fechados/rolados pro bankroll_start.
            epoch = _get_bankroll_epoch(cur, user_id)
            if epoch is not None:
                date_cond = " AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo') >= %s"
                date_params.append(epoch)

        cur.execute(f"""
            SELECT uf.id, uf.pick_id, uf.pick_type, uf.stake_units, uf.followed_at,
                   uf.actual_odd, uf.cashout_amount
            FROM user_followed_picks uf
            WHERE uf.user_id = %s AND uf.pick_type != 'alavancagem' {date_cond}
            ORDER BY uf.followed_at ASC
        """, date_params)
        followed = [dict(r) for r in cur.fetchall()]

        running = bankroll_start
        if not followed:
            entries = []
        else:
            # Batch: separa ids por tipo para buscar tudo de uma vez
            vip_ids      = [f["pick_id"] for f in followed if f["pick_type"] == "vip"]
            free_ids     = [f["pick_id"] for f in followed if f["pick_type"] == "free"]
            multipla_ids = [f["pick_id"] for f in followed if f["pick_type"] == "multipla"]

            vip_map: dict = {}
            if vip_ids:
                cur.execute("""
                    SELECT id, result, profit, home_team_name, away_team_name,
                           home_team_id, away_team_id, market, line, odd
                    FROM picks_vip WHERE id = ANY(%s)
                """, (vip_ids,))
                for r in cur.fetchall():
                    vip_map[r["id"]] = dict(r)

            free_map: dict = {}
            if free_ids:
                cur.execute("""
                    SELECT pf.id, pf.result, pf.profit,
                           pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                           COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                           COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                           pf.market, pf.line, pf.odd
                    FROM picks_free pf
                    LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
                    WHERE pf.id = ANY(%s)
                """, (free_ids,))
                for r in cur.fetchall():
                    free_map[r["id"]] = dict(r)

            multipla_map: dict = {}
            if multipla_ids:
                cur.execute("""
                    SELECT id, result, profit, total_odd AS odd, games AS legs_json
                    FROM picks_multiplas WHERE id = ANY(%s)
                """, (multipla_ids,))
                for r in cur.fetchall():
                    d = dict(r)
                    legs = []
                    try:
                        legs = _json.loads(d["legs_json"]) if isinstance(d.get("legs_json"), str) else (d.get("legs_json") or [])
                    except Exception:
                        pass
                    first = legs[0] if legs else {}
                    d["home_team_name"] = first.get("home") or first.get("home_team")
                    d["away_team_name"] = first.get("away") or first.get("away_team")
                    d["home_team_id"]   = first.get("home_team_id")
                    d["away_team_id"]   = first.get("away_team_id")
                    d["market"]         = f"Múltipla · {len(legs)} seleções"
                    del d["legs_json"]
                    multipla_map[d["id"]] = d

            # Aqui a lista e' exibida, nao so' somada: precisa das mesmas
            # colunas de display que vip_map/free_map trazem acima, senao o
            # pick de mercado apareceria sem time e sem mercado na tela.
            type_map = {"vip": vip_map, "free": free_map, "multipla": multipla_map,
                        **_mercado_maps(cur, followed,
                                        "id, result, profit, "
                                        "home_team AS home_team_name, "
                                        "away_team AS away_team_name, "
                                        "home_team_id, away_team_id, "
                                        "market, line, odd")}

            entries = []
            for f in followed:
                pick = type_map.get(f["pick_type"], {}).get(f["pick_id"])
                if not pick:
                    continue
                actual_odd = float(f["actual_odd"]) if f.get("actual_odd") else None
                result, profit_u, pnl_r = _compute_follow_pnl(pick, f, unit_value)
                if pnl_r is not None:
                    running += pnl_r

                entries.append({
                    "id":             f["id"],
                    "pick_id":        f["pick_id"],
                    "pick_type":      f["pick_type"],
                    "stake_units":    float(f["stake_units"]),
                    "followed_at":    f["followed_at"].isoformat() if f["followed_at"] else None,
                    "home_team_name": pick.get("home_team_name"),
                    "away_team_name": pick.get("away_team_name"),
                    "home_team_id":   pick.get("home_team_id"),
                    "away_team_id":   pick.get("away_team_id"),
                    "market":         pick.get("market"),
                    "line":           pick.get("line"),
                    "odd":            float(pick["odd"]) if pick.get("odd") is not None else None,
                    "actual_odd":     actual_odd,
                    "result":         result,
                    "profit_units":   profit_u,
                    "pnl":            round(pnl_r, 2) if pnl_r is not None else None,
                    "bankroll_after": round(running, 2) if pnl_r is not None else None,
                })

        resolved  = [e for e in entries if e["result"]]
        greens    = sum(1 for e in resolved if e["result"] == "GREEN")
        reds      = sum(1 for e in resolved if e["result"] == "RED")
        push      = sum(1 for e in resolved if e["result"] == "PUSH")
        half_wins = sum(1 for e in resolved if e["result"] == "HALF-WIN")
        half_loss = sum(1 for e in resolved if e["result"] == "HALF-LOSS")
        total_pnl = sum(e["pnl"] for e in resolved if e["pnl"] is not None)
        win_rate  = round(greens / len(resolved) * 100) if resolved else 0
        # ROI de crescimento: ganho sobre banca inicial em R$
        roi = round(total_pnl / bankroll_start * 100, 1) if bankroll_start else 0
        # Yield tipster: lucro em unidades / unidades apostadas × 100
        total_profit_units  = sum(e["pnl"] / unit_value for e in resolved if e["pnl"] is not None)
        total_staked_units  = sum(e["stake_units"] for e in resolved)
        yield_roi = round(total_profit_units / total_staked_units * 100, 1) if total_staked_units > 0 else 0

        # Streak pessoal
        streak_info = _compute_streak(resolved)

        # Melhor e pior pick
        pnl_entries = [e for e in resolved if e["pnl"] is not None]
        best_pick  = max(pnl_entries, key=lambda e: e["pnl"]) if pnl_entries else None
        worst_pick = min(pnl_entries, key=lambda e: e["pnl"]) if pnl_entries else None

        # ROI geral da IA para comparação
        ia_roi = None
        try:
            cur.execute("""
                SELECT COALESCE(SUM(profit), 0) AS p, COUNT(*) AS s
                FROM picks_vip WHERE result IS NOT NULL
            """)
            ia_row = cur.fetchone()
            if ia_row and float(ia_row["s"]) > 0:
                ia_roi = round(float(ia_row["p"]) / float(ia_row["s"]) * 100, 1)
        except Exception:
            pass

        # Gráfico (usa running que já acumula com unit_value)
        chart: list[dict] = []
        running2 = bankroll_start
        for e in entries:
            if e["pnl"] is not None:
                running2 += e["pnl"]
                chart.append({
                    "date": (e["followed_at"] or "")[:10],
                    "bankroll": round(running2, 2),
                })

        # Banca atual sempre "de verdade" (todo o historico desde o ultimo
        # fechamento), nao presa ao periodo filtrado acima -- ver docstring
        # de _compute_bankroll_current. Pra "Tudo" (sem filtro) da o mesmo
        # valor que `running` ja dava; so muda o resultado quando days/
        # from_date/to_date estao filtrando uma janela diferente do epoch.
        bankroll_current_real = _compute_bankroll_current(cur, user_id, bankroll_start, unit_value)

        # Pendentes sempre completos (autolimitado -- resolve em poucos dias);
        # so os resolvidos sao paginados, ja que crescem sem limite com o
        # tempo. Stats/chart/bankroll acima usam `entries`/`resolved` inteiros
        # -- so o payload de entradas devolvido ao cliente e que e recortado.
        pending_entries = [e for e in entries if not e["result"]]
        resolved_sorted_desc = sorted(resolved, key=lambda e: e["followed_at"] or "", reverse=True)
        resolved_page = resolved_sorted_desc[resolved_offset:resolved_offset + resolved_limit]
        page_entries = sorted(pending_entries + resolved_page, key=lambda e: e["followed_at"] or "")

        return {
            "bankroll_start":       bankroll_start,
            "bankroll_goal":        bankroll_goal,
            "bankroll_current":     bankroll_current_real,
            "unit_value":           unit_value,
            "can_configure":        can_configure,
            "total_followed":       len(followed),
            "total_resolved":       len(resolved),
            "greens":               greens,
            "reds":                 reds,
            "push":                 push,
            "half_wins":            half_wins,
            "half_loss":            half_loss,
            "win_rate":             win_rate,
            "roi":                  roi,
            "yield_roi":            yield_roi,
            "ia_roi":               ia_roi,
            "total_pnl":            round(total_pnl, 2),
            "streak":               streak_info["streak"],
            "streak_type":          streak_info["streak_type"],
            "best_streak":          streak_info["best_streak"],
            "best_pick":            best_pick,
            "worst_pick":           worst_pick,
            "entries":              page_entries,
            "resolved_total":       len(resolved),
            "has_more_resolved":    resolved_offset + resolved_limit < len(resolved),
            "chart":                chart,
        }
    finally:
        cur.close()
        conn.close()


@router.post("/setup")
def setup_banca(body: BancaSetup, current_user: dict = Depends(get_current_user)):
    _check_banca_rate(current_user["id"])
    if body.bankroll_start <= 0:
        raise HTTPException(400, "Banca deve ser maior que zero.")
    if body.bankroll_goal is not None and body.bankroll_goal <= body.bankroll_start:
        raise HTTPException(400, "Meta deve ser maior que a banca inicial.")
    if body.unit_value is not None and body.unit_value <= 0:
        raise HTTPException(400, "Valor da unidade deve ser maior que zero.")
    if body.unit_value is not None:
        total_units = body.bankroll_start / body.unit_value
        if total_units < 20:
            max_unit = round(body.bankroll_start / 20, 2)
            raise HTTPException(
                400,
                f"Unidade muito alta para sua banca. "
                f"Com R${body.bankroll_start:.2f} de banca e R${body.unit_value:.2f} por unidade "
                f"você teria apenas {total_units:.0f} unidades · alto risco de ruína. "
                f"Reduza a unidade para no máximo R${max_unit:.2f} (20 unidades mínimas)."
            )
    user_id = current_user["id"]
    manual_setup = body.monthly_close_month_key is None
    conn = get_connection()
    cur = conn.cursor()
    try:
        if manual_setup:
            # Trava: 1 configuração manual por mês, pra não dar pra ficar mudando
            # banca/unidade no meio do mês pra manipular o cálculo de stake e o
            # histórico de risco. O fechamento mensal automático (que chama esse
            # mesmo endpoint com monthly_close_month_key) sempre passa direto.
            cur.execute("SELECT last_manual_setup_month FROM user_banca WHERE user_id = %s", (user_id,))
            prev_row = cur.fetchone()
            if prev_row and prev_row["last_manual_setup_month"] == _current_month_key():
                raise HTTPException(
                    400,
                    "Você já configurou sua banca este mês. Isso evita mudar os números no "
                    "meio do mês e distorcer o histórico de risco. Pra tirar dinheiro agora, "
                    "use o botão \"Sacar\" · pra reconfigurar de novo, espera o fechamento "
                    "mensal automático."
                )

        if body.monthly_close_month_key:
            # Registra o fechamento (banca antes -> depois + estatísticas do mês) antes
            # de sobrescrever o bankroll_start. É esse registro que marca o "epoch" pra
            # não somar de novo o P&L desse mês nos cálculos futuros de banca atual.
            cur.execute("SELECT bankroll_start, unit_value FROM user_banca WHERE user_id = %s", (user_id,))
            prev = cur.fetchone()
            prev_start = float(prev["bankroll_start"]) if prev else 100.0
            prev_unit  = float(prev["unit_value"]) if prev and prev["unit_value"] else 1.0

            _year, _mo, month_start, month_end = _month_bounds(body.monthly_close_month_key)
            stats = _compute_month_stats(cur, user_id, month_start, month_end, prev_unit)

            cur.execute("""
                INSERT INTO banca_monthly_closes
                    (user_id, month_key, bankroll_start, bankroll_end, total_pnl,
                     greens, reds, push, half_wins, half_loss, total_resolved, total_followed, unit_value)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, month_key) DO UPDATE
                    -- bankroll_start NAO entra aqui de proposito: e o valor historico de
                    -- "banca no inicio desse mes", nao pode mudar numa reconfirmacao (ex:
                    -- usuario ja fechou no celular e o popup reaparece em outro aparelho).
                    SET bankroll_end   = EXCLUDED.bankroll_end,
                        total_pnl      = EXCLUDED.total_pnl,
                        greens         = EXCLUDED.greens,
                        reds           = EXCLUDED.reds,
                        push           = EXCLUDED.push,
                        half_wins      = EXCLUDED.half_wins,
                        half_loss      = EXCLUDED.half_loss,
                        total_resolved = EXCLUDED.total_resolved,
                        total_followed = EXCLUDED.total_followed,
                        unit_value     = EXCLUDED.unit_value,
                        closed_at      = NOW()
            """, (
                user_id, body.monthly_close_month_key, prev_start, body.bankroll_start, stats["total_pnl"],
                stats["greens"], stats["reds"], stats["push"], stats["half_wins"], stats["half_loss"],
                stats["total_resolved"], stats["total_followed"], prev_unit,
            ))

            # Fechamento resolvido: o item do sino vira histórico (lido) e para
            # de reabrir o popup em qualquer aparelho.
            cur.execute("""
                UPDATE notifications SET read_at = COALESCE(read_at, NOW())
                WHERE user_id = %s AND dedupe_key = %s
            """, (user_id, f"monthly_close:{body.monthly_close_month_key}"))

        new_last_manual_month = _current_month_key() if manual_setup else None
        cur.execute("""
            INSERT INTO user_banca (user_id, bankroll_start, bankroll_goal, unit_value, last_manual_setup_month)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET bankroll_start = EXCLUDED.bankroll_start,
                    bankroll_goal  = EXCLUDED.bankroll_goal,
                    unit_value     = COALESCE(EXCLUDED.unit_value, user_banca.unit_value),
                    last_manual_setup_month = COALESCE(EXCLUDED.last_manual_setup_month, user_banca.last_manual_setup_month),
                    updated_at     = NOW()
        """, (user_id, body.bankroll_start, body.bankroll_goal, body.unit_value, new_last_manual_month))
        conn.commit()
        return {"ok": True}
    finally:
        cur.close()
        conn.close()


@router.post("/withdraw")
def withdraw_banca(body: BancaWithdraw, current_user: dict = Depends(get_current_user)):
    """Desconta um valor da banca atual e registra o saque pra ter historico
    (data, valor, banca antes/depois) -- diferente do /setup, que so troca o
    numero sem deixar rastro de por que mudou."""
    _check_banca_rate(current_user["id"])
    if body.amount <= 0:
        raise HTTPException(400, "Valor do saque deve ser maior que zero.")

    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Trava consultivo por usuario (mesmo sem linha existente em user_banca)
        # -- sem isso, dois saques concorrentes leem o mesmo bankroll_current
        # antes de qualquer commit e ambos passam na checagem, deixando a banca
        # negativa (numero virtual, mas exibido/usado pra calculos futuros).
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))

        cur.execute("SELECT bankroll_start, bankroll_goal, unit_value FROM user_banca WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        bankroll_start = float(row["bankroll_start"]) if row else 100.0
        bankroll_goal  = float(row["bankroll_goal"]) if row and row["bankroll_goal"] else None
        unit_value     = float(row["unit_value"])     if row and row["unit_value"] else 1.0

        bankroll_current = _compute_bankroll_current(cur, user_id, bankroll_start, unit_value)
        if body.amount > bankroll_current:
            raise HTTPException(400, f"Você não pode sacar mais do que tem na banca (R${bankroll_current:.2f}).")

        new_start = bankroll_current - body.amount

        cur.execute("""
            INSERT INTO banca_withdrawals (user_id, amount, bankroll_before, bankroll_after)
            VALUES (%s, %s, %s, %s)
        """, (user_id, body.amount, bankroll_current, new_start))

        cur.execute("""
            INSERT INTO user_banca (user_id, bankroll_start, bankroll_goal, unit_value)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET bankroll_start = EXCLUDED.bankroll_start,
                    updated_at     = NOW()
        """, (user_id, new_start, bankroll_goal, unit_value))
        conn.commit()
        return {"ok": True, "bankroll_start": new_start}
    finally:
        cur.close()
        conn.close()


@router.get("/withdrawals")
def get_withdrawals(current_user: dict = Depends(get_current_user), limit: int = Query(20, ge=1, le=100)):
    """Historico de saques da banca do usuario, mais recente primeiro."""
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, amount, bankroll_before, bankroll_after, created_at
            FROM banca_withdrawals
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, limit))
        rows = cur.fetchall()
        return [
            {
                "id": r["id"],
                "amount": float(r["amount"]),
                "bankroll_before": float(r["bankroll_before"]),
                "bankroll_after": float(r["bankroll_after"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


STAKE_LIMITS = {
    "vip":        (1, 20),
    "free":       (1, 6),
    "multipla":   (1, 5),
    "alavancagem":(1, 9999),  # sem limite fixo · banca composta progressiva
    # Mercados de modelo proprio. Teto igual ao do Free e nao ao do VIP: sao
    # mercados com amostra historica menor (defesas aparece em menos de 1% dos
    # jogos), entao a incerteza da estimativa e maior mesmo quando a margem
    # calculada e boa.
    "faltas":     (1, 6),
    "goleiros":   (1, 6),
}

STAKE_LABELS = {
    "vip": "VIP", "free": "Free", "multipla": "Múltipla",
    "alavancagem": "Alavancagem", "faltas": "de Faltas", "goleiros": "de Defesas",
}

@router.post("/follow")
def follow_pick(body: FollowPick, current_user: dict = Depends(get_current_user)):
    _check_banca_rate(current_user["id"])
    # A fonte da verdade e STAKE_LIMITS: a lista estava escrita duas vezes e
    # foi por isso que faltas/goleiros ficaram de fora do follow mesmo com o
    # resto da banca (resolve, P&L, historico) ja sabendo lidar com eles.
    if body.pick_type not in STAKE_LIMITS:
        raise HTTPException(400, "Tipo inválido.")
    min_u, max_u = STAKE_LIMITS[body.pick_type]
    if not (min_u <= body.stake_units <= max_u):
        label = STAKE_LABELS.get(body.pick_type, body.pick_type)
        raise HTTPException(400, f"Stake para picks {label} deve ser entre {min_u} e {max_u} unidades.")
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        pick = _resolve_pick(cur, body.pick_id, body.pick_type)
        if not pick:
            raise HTTPException(404, "Pick não encontrado.")
        if pick.get("result"):
            raise HTTPException(400, "Não é possível registrar aposta após o resultado.")
        # Decisao do usuario (2026-07-17): permitir registrar aposta mesmo
        # depois do jogo ja ter comecado (odd atualizada na hora via
        # GET /api/live/pick-odd, buscada pelo frontend antes de abrir o
        # modal) -- so bloqueia quando ja existe resultado (acima).
        cur.execute(
            "SELECT id FROM user_followed_picks WHERE user_id=%s AND pick_id=%s AND pick_type=%s",
            (user_id, body.pick_id, body.pick_type),
        )
        if cur.fetchone():
            return {"ok": True, "already_followed": True}
        cur.execute("""
            INSERT INTO user_followed_picks (user_id, pick_id, pick_type, stake_units, actual_odd, bet_house)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, pick_id, pick_type) DO NOTHING
        """, (user_id, body.pick_id, body.pick_type, body.stake_units, body.actual_odd, body.bet_house))
        conn.commit()
        return {"ok": True, "already_followed": False}
    finally:
        cur.close()
        conn.close()


@router.get("/alavancagem-serie")
def get_alavancagem_serie(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT alav_bankroll_init
            FROM user_banca
            WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()

        if not row or row["alav_bankroll_init"] is None:
            return {"configured": False, "current_bankroll": 0.0, "initial_bankroll": 0.0}

        initial = float(row["alav_bankroll_init"])
        bankroll = initial

        cur.execute("""
            SELECT pa.result, pa.odd_combined
            FROM user_followed_picks uf
            JOIN picks_alavancagem pa ON pa.id = uf.pick_id
            WHERE uf.user_id = %s AND uf.pick_type = 'alavancagem' AND pa.result IS NOT NULL
            ORDER BY pa.match_date ASC
        """, (user_id,))

        for pick in cur.fetchall():
            result = pick["result"]
            odd = float(pick["odd_combined"] or 1)
            if result == "GREEN":
                bankroll = round(bankroll * odd, 2)
            elif result == "RED":
                bankroll = initial

        return {
            "configured": True,
            "current_bankroll": round(bankroll, 2),
            "initial_bankroll": initial,
        }
    finally:
        cur.close()
        conn.close()


class AlavancagemInit(BaseModel):
    bankroll_init: float


@router.put("/alavancagem-init")
def set_alavancagem_init(body: AlavancagemInit, current_user: dict = Depends(get_current_user)):
    _check_banca_rate(current_user["id"])
    if body.bankroll_init <= 0:
        raise HTTPException(400, "Valor deve ser maior que zero.")
    bankroll_init = body.bankroll_init
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO user_banca (user_id, bankroll_start, alav_bankroll_init)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET alav_bankroll_init = EXCLUDED.alav_bankroll_init,
                    updated_at = NOW()
        """, (user_id, float(bankroll_init), float(bankroll_init)))
        conn.commit()
        return {"ok": True, "initial_bankroll": float(bankroll_init)}
    finally:
        cur.close()
        conn.close()


@router.get("/summary")
def get_banca_summary(current_user: dict = Depends(get_current_user)):
    """Retorna dados mínimos da banca para sugestão de stake nos picks."""
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT bankroll_start, unit_value FROM user_banca WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"has_banca": False, "bankroll_current": 0.0, "unit_value": 1.0}

        bankroll_start = float(row["bankroll_start"])
        unit_value = float(row["unit_value"]) if row["unit_value"] else 1.0

        # "Tudo" = desde o último fechamento mensal (se houver), senão desde o início ·
        # mesmo criterio usado em GET /banca e /monthly-close (evita contar 2x o P&L
        # de meses já fechados/rolados pro bankroll_start).
        epoch = _get_bankroll_epoch(cur, user_id)
        date_cond = " AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo') >= %s" if epoch is not None else ""
        params = [user_id] + ([epoch] if epoch is not None else [])

        cur.execute(f"""
            SELECT uf.pick_id, uf.pick_type, uf.stake_units, uf.actual_odd, uf.cashout_amount
            FROM user_followed_picks uf
            WHERE uf.user_id = %s AND uf.pick_type != 'alavancagem' {date_cond}
        """, params)
        followed = [dict(r) for r in cur.fetchall()]

        pnl = 0.0
        if followed:
            vip_ids      = [f["pick_id"] for f in followed if f["pick_type"] == "vip"]
            free_ids     = [f["pick_id"] for f in followed if f["pick_type"] == "free"]
            multipla_ids = [f["pick_id"] for f in followed if f["pick_type"] == "multipla"]

            vip_map: dict = {}
            if vip_ids:
                cur.execute("SELECT id, result, odd FROM picks_vip WHERE id = ANY(%s)", (vip_ids,))
                for r in cur.fetchall(): vip_map[r["id"]] = dict(r)

            free_map: dict = {}
            if free_ids:
                cur.execute("SELECT id, result, odd FROM picks_free WHERE id = ANY(%s)", (free_ids,))
                for r in cur.fetchall(): free_map[r["id"]] = dict(r)

            multipla_map: dict = {}
            if multipla_ids:
                cur.execute("SELECT id, result, total_odd AS odd FROM picks_multiplas WHERE id = ANY(%s)", (multipla_ids,))
                for r in cur.fetchall(): multipla_map[r["id"]] = dict(r)

            type_map = {"vip": vip_map, "free": free_map, "multipla": multipla_map,
                **_mercado_maps(cur, followed)}
            for f in followed:
                pick = type_map.get(f["pick_type"], {}).get(f["pick_id"])
                if not pick:
                    continue
                _result, _profit_u, pnl_r = _compute_follow_pnl(pick, f, unit_value)
                if pnl_r is not None:
                    pnl += pnl_r

        return {
            "has_banca": True,
            "bankroll_current": round(bankroll_start + pnl, 2),
            "unit_value": unit_value,
        }
    finally:
        cur.close()
        conn.close()


@router.post("/cashout/{pick_id}/{pick_type}")
def cashout_pick(pick_id: int, pick_type: str, body: CashoutBody, current_user: dict = Depends(get_current_user)):
    _check_banca_rate(current_user["id"])
    if body.cashout_amount < 0:
        raise HTTPException(400, "Valor de cashout não pode ser negativo.")
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, stake_units, actual_odd, cashout_amount FROM user_followed_picks "
            "WHERE user_id=%s AND pick_id=%s AND pick_type=%s",
            (user_id, pick_id, pick_type),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Aposta não encontrada.")
        if row["cashout_amount"] is not None:
            raise HTTPException(400, "Cashout já registrado para esta aposta.")

        pick = _resolve_pick(cur, pick_id, pick_type)
        cur.execute("SELECT unit_value FROM user_banca WHERE user_id = %s", (user_id,))
        banca_row  = cur.fetchone()
        unit_value = float(banca_row["unit_value"]) if banca_row and banca_row["unit_value"] else 1.0
        odd        = float(row["actual_odd"] or (pick or {}).get("odd") or 1)
        stake_r    = float(row["stake_units"]) * unit_value
        max_payout = stake_r * odd
        if body.cashout_amount > max_payout:
            raise HTTPException(
                400,
                f"Valor de cashout (R${body.cashout_amount:.2f}) excede o retorno máximo possível "
                f"da aposta (R${max_payout:.2f}). Verifique o valor digitado.",
            )

        cur.execute(
            "UPDATE user_followed_picks SET cashout_amount=%s WHERE user_id=%s AND pick_id=%s AND pick_type=%s",
            (body.cashout_amount, user_id, pick_id, pick_type),
        )
        conn.commit()
        return {"ok": True, "cashout_amount": body.cashout_amount}
    finally:
        cur.close()
        conn.close()


MONTH_NAMES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
               "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]


# Usuários cujo mês anterior já foi checado. Sem isso, cada listagem de
# notificações · e o sino faz poll de 60s · refaria as queries de estatística do
# mês inteiro pra quem não seguiu pick nenhum (esse caso nunca cria linha, então
# nunca sairia pelo caminho barato). Memória do processo: reinício custa no
# máximo uma recontagem por usuário. Zera na virada do mês pra não crescer.
_monthly_close_checked: set[tuple[int, str]] = set()
_monthly_close_checked_month = ""


def _last_month_key() -> str:
    """Mês anterior 'YYYY-MM' no fuso de Brasília · o mês que o fechamento cobre."""
    today = datetime.now(BR_TZ).date()
    last = today.replace(day=1) - timedelta(days=1)
    return f"{last.year:04d}-{last.month:02d}"


def sync_monthly_close_notification(cur, user_id: int) -> None:
    """
    Garante o item "fechamento do mês passado" no sino do usuário.

    Fonte de verdade do fechamento passou a ser esta notificação, não mais um
    localStorage por navegador: antes, fechar o popup gravava a marca só naquele
    aparelho (reaparecia no outro, sumia pra sempre se limpasse o navegador) e
    qualquer erro de rede na abertura queimava o mês inteiro.

    Chamada a cada listagem de notificações, então sai cedo pelo caminho barato
    (dois SELECTs em índice único) sempre que já existe ou já foi resolvido · o
    cálculo do mês só roda uma vez por usuário por mês.
    """
    from routers.notifications import TYPE_MONTHLY_CLOSE, create_notification, fmt_brl

    global _monthly_close_checked_month

    month_key  = _last_month_key()
    dedupe_key = f"monthly_close:{month_key}"

    if month_key != _monthly_close_checked_month:
        _monthly_close_checked.clear()
        _monthly_close_checked_month = month_key
    elif (user_id, month_key) in _monthly_close_checked:
        return

    cur.execute(
        "SELECT 1 FROM notifications WHERE user_id = %s AND dedupe_key = %s",
        (user_id, dedupe_key),
    )
    if cur.fetchone():
        _monthly_close_checked.add((user_id, month_key))
        return

    cur.execute(
        "SELECT 1 FROM banca_monthly_closes WHERE user_id = %s AND month_key = %s",
        (user_id, month_key),
    )
    if cur.fetchone():
        _monthly_close_checked.add((user_id, month_key))
        return

    cur.execute("SELECT unit_value FROM user_banca WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        _monthly_close_checked.add((user_id, month_key))
        return  # nunca configurou banca · não tem fechamento pra mostrar
    unit_value = float(row["unit_value"]) if row["unit_value"] else 1.0

    year, mo, month_start, month_end = _month_bounds(month_key)
    stats = _compute_month_stats(cur, user_id, month_start, month_end, unit_value)
    alav  = _get_alavancagem_month_stats(cur, user_id, month_start, month_end)
    has_alav_activity = bool(alav) and (alav["greens_this_month"] > 0 or alav["reds_this_month"] > 0)
    if stats["total_followed"] == 0 and not has_alav_activity:
        _monthly_close_checked.add((user_id, month_key))
        return  # mês sem movimento nenhum

    pnl   = stats["total_pnl"]
    sign  = "+" if pnl >= 0 else ""
    label = f"{MONTH_NAMES[mo-1]} {year}"
    create_notification(
        cur, user_id, TYPE_MONTHLY_CLOSE,
        title=f"Fechamento de {label}",
        dedupe_key=dedupe_key,
        body=f"{sign}{fmt_brl(pnl)} no mês · {stats['greens']}G/{stats['reds']}R. "
             f"Confirme sua banca pra começar o mês novo.",
        url="/banca",
        payload={"month_key": month_key, "month_label": label, "total_pnl": pnl},
    )
    _monthly_close_checked.add((user_id, month_key))


def _get_alavancagem_month_stats(cur, user_id: int, month_start: str, month_end: str) -> Optional[dict]:
    """Progressão completa da série de alavancagem (banca atual da série) + quantos
    passos GREEN/RED aconteceram dentro do mês alvo. None se o usuário nunca configurou."""
    cur.execute("SELECT alav_bankroll_init FROM user_banca WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row or row["alav_bankroll_init"] is None:
        return None

    initial = float(row["alav_bankroll_init"])
    bankroll = initial

    cur.execute("""
        SELECT pa.result, pa.odd_combined,
               ((uf.followed_at AT TIME ZONE 'America/Sao_Paulo') >= %s
                AND (uf.followed_at AT TIME ZONE 'America/Sao_Paulo') < %s) AS in_month
        FROM user_followed_picks uf
        JOIN picks_alavancagem pa ON pa.id = uf.pick_id
        WHERE uf.user_id = %s AND uf.pick_type = 'alavancagem' AND pa.result IS NOT NULL
        ORDER BY pa.match_date ASC
    """, (month_start, month_end, user_id))

    month_greens = month_reds = 0
    busted_this_month = False
    for pick in cur.fetchall():
        result = pick["result"]
        odd = float(pick["odd_combined"] or 1)
        if result == "GREEN":
            bankroll = round(bankroll * odd, 2)
            if pick["in_month"]: month_greens += 1
        elif result == "RED":
            bankroll = initial
            if pick["in_month"]:
                month_reds += 1
                busted_this_month = True

    return {
        "configured":         True,
        "current_bankroll":   round(bankroll, 2),
        "initial_bankroll":   initial,
        "greens_this_month":  month_greens,
        "reds_this_month":    month_reds,
        "busted_this_month":  busted_this_month,
    }


@router.get("/monthly-close")
def get_monthly_close(
    current_user: dict = Depends(get_current_user),
    month: str = Query(None),  # YYYY-MM, defaults to last calendar month
):
    """
    Retorna P&L do mês anterior (ou do mês especificado) para o fechamento mensal.
    """
    if month:
        year, mo, month_start, month_end = _month_bounds(month)
    else:
        # Fuso de Brasília, não o do servidor · evita a virada de mês ficar
        # ~3h fora de sincronia se o processo rodar em UTC.
        today = datetime.now(BR_TZ).date()
        last_month_last = today.replace(day=1) - timedelta(days=1)
        year, mo = last_month_last.year, last_month_last.month
        month_start = f"{year:04d}-{mo:02d}-01"
        month_end = f"{year+1:04d}-01-01" if mo == 12 else f"{year:04d}-{mo+1:02d}-01"

    month_label = f"{MONTH_NAMES[mo-1]} {year}"
    month_key   = f"{year:04d}-{mo:02d}"

    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT bankroll_start, unit_value FROM user_banca WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        bankroll_start = float(row["bankroll_start"]) if row else 100.0
        unit_value     = float(row["unit_value"])     if row and row["unit_value"] else 1.0

        # Banca atual = bankroll_start + P&L desde o último fechamento mensal (ou desde
        # sempre, se nunca fechou). Sem esse corte, todo fechamento aceito soma de novo
        # o lucro/prejuízo de meses que já foram "rolados" pro bankroll_start.
        # Usa o mesmo helper de GET /banca (_compute_follow_pnl por pick, via Python)
        # em vez de reimplementar em SQL puro -- a versão antiga em CASE/SQL ignorava
        # uf.actual_odd (odd real que o usuário registrou) e sempre usava o profit
        # pré-calculado com a odd oficial do pick, divergindo do resto do sistema
        # sempre que o usuário tivesse pego uma odd diferente da oficial.
        bankroll_current = _compute_bankroll_current(cur, user_id, bankroll_start, unit_value)

        stats = _compute_month_stats(cur, user_id, month_start, month_end, unit_value)
        alav = _get_alavancagem_month_stats(cur, user_id, month_start, month_end)
        plan_price = PLANS["mensal"]["price"]

        # Já fechado (em qualquer dispositivo)? Evita reabrir o popup e sobrescrever
        # o registro histórico se o usuário já confirmou em outro aparelho no mesmo mês.
        cur.execute(
            "SELECT 1 FROM banca_monthly_closes WHERE user_id = %s AND month_key = %s",
            (user_id, month_key),
        )
        already_closed = cur.fetchone() is not None

        return {
            "month_label":      month_label,
            "month_key":        month_key,
            "total_pnl":        stats["total_pnl"],
            "greens":           stats["greens"],
            "reds":             stats["reds"],
            "push":             stats["push"],
            "half_wins":        stats["half_wins"],
            "half_loss":        stats["half_loss"],
            "total_resolved":   stats["total_resolved"],
            "total_followed":   stats["total_followed"],
            "bankroll_start":   bankroll_start,
            "bankroll_current": bankroll_current,
            "unit_value":       unit_value,
            "paid_plan":        stats["total_pnl"] >= plan_price,
            "alavancagem":      alav,
            "already_closed":   already_closed,
        }
    finally:
        cur.close()
        conn.close()


@router.get("/monthly-closes")
def list_monthly_closes(current_user: dict = Depends(get_current_user), limit: int = Query(24, ge=1, le=60)):
    """
    Histórico de fechamentos já confirmados, do mais recente pro mais antigo.
    A tabela guardava isso desde sempre e nenhuma tela lia · é o que dá pro
    usuário a evolução mês a mês da banca dele.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT month_key, bankroll_start, bankroll_end, total_pnl,
                   greens, reds, push, half_wins, half_loss,
                   total_resolved, total_followed, unit_value, closed_at
            FROM banca_monthly_closes
            WHERE user_id = %s
            ORDER BY month_key DESC
            LIMIT %s
        """, (current_user["id"], limit))
        out = []
        for r in cur.fetchall():
            d = dict(r)
            year, mo = int(d["month_key"][:4]), int(d["month_key"][5:7])
            unit = float(d["unit_value"]) if d["unit_value"] else 0.0
            pnl  = float(d["total_pnl"])
            out.append({
                "month_key":      d["month_key"],
                "month_label":    f"{MONTH_NAMES[mo-1]} {year}",
                "bankroll_start": float(d["bankroll_start"]),
                "bankroll_end":   float(d["bankroll_end"]),
                "total_pnl":      pnl,
                "profit_units":   round(pnl / unit, 2) if unit else None,
                "greens":         d["greens"],
                "reds":           d["reds"],
                "push":           d["push"],
                "half_wins":      d["half_wins"],
                "half_loss":      d["half_loss"],
                "total_resolved": d["total_resolved"],
                "total_followed": d["total_followed"],
                "unit_value":     unit,
                "closed_at":      d["closed_at"].isoformat() if d["closed_at"] else None,
            })
        return out
    finally:
        cur.close()
        conn.close()


@router.delete("/follow/{pick_id}/{pick_type}")
def unfollow_pick(pick_id: int, pick_type: str, current_user: dict = Depends(get_current_user)):
    _check_banca_rate(current_user["id"])
    user_id = current_user["id"]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM user_followed_picks WHERE user_id=%s AND pick_id=%s AND pick_type=%s",
            (user_id, pick_id, pick_type),
        )
        conn.commit()
        return {"ok": True}
    finally:
        cur.close()
        conn.close()
