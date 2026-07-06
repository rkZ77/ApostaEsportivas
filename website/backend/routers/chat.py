import json
import asyncio
import logging
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from auth_utils import get_current_user
from database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

# Rate limit: máx 10 msgs por usuário por 60 segundos (evita spam caro na API Anthropic)
_chat_rate: dict[str, list[float]] = defaultdict(list)
_CHAT_LIMIT  = 10
_CHAT_WINDOW = 60

# Importação direta do pacote futebol_agent
try:
    from futebol_agent.agent import run_agent
    _AGENT_OK = True
    logger.info("futebol_agent carregado com sucesso.")
except Exception as _e:
    _AGENT_OK = False
    run_agent = None  # type: ignore
    logger.warning(f"futebol_agent não carregado: {_e}")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


def _get_site_context(user_id: int) -> str:
    """Busca contexto completo do site: picks, banca, alavancagem e desempenho histórico."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT plan FROM users WHERE id = %s", (user_id,))
            plan_row = cur.fetchone()
            plan = plan_row["plan"] if plan_row else "free"
            is_vip = plan in ("vip", "admin", "trial")

            lines = ["=== CONTEXTO PICKIA ==="]

            # ── Banca principal do usuário ──────────────────────────────────
            cur.execute("SELECT bankroll_start, unit_value FROM user_banca WHERE user_id = %s", (user_id,))
            banca = cur.fetchone()
            if banca:
                banca = dict(banca)
                lines.append(f"Banca principal: R${banca['bankroll_start']:.2f} | Unidade: R${banca['unit_value']:.2f}")

            # ── Série de alavancagem do usuário ─────────────────────────────
            cur.execute("SELECT alav_bankroll_init FROM user_banca WHERE user_id = %s", (user_id,))
            alav_row = cur.fetchone()
            if alav_row and alav_row["alav_bankroll_init"] is not None:
                alav_initial = float(alav_row["alav_bankroll_init"])
                alav_current = alav_initial
                cur.execute("""
                    SELECT pa.result, pa.odd_combined
                    FROM user_followed_picks uf
                    JOIN picks_alavancagem pa ON pa.id = uf.pick_id
                    WHERE uf.user_id = %s AND uf.pick_type = 'alavancagem' AND pa.result IS NOT NULL
                    ORDER BY pa.match_date ASC
                """, (user_id,))
                for pick in cur.fetchall():
                    if pick["result"] == "GREEN":
                        alav_current = round(alav_current * float(pick["odd_combined"] or 1), 2)
                    elif pick["result"] == "RED":
                        alav_current = alav_initial
                gain = alav_current - alav_initial
                sign = "+" if gain >= 0 else ""
                lines.append(f"Banca alavancagem: R${alav_current:.2f} (inicial: R${alav_initial:.2f} | ganho: {sign}R${gain:.2f})")

            # ── Desempenho VIP: mês atual + últimos 7 dias ──────────────────
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE result IS NOT NULL)     AS total,
                    COUNT(*) FILTER (WHERE result = 'GREEN')       AS greens,
                    COUNT(*) FILTER (WHERE result = 'RED')         AS reds,
                    COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit
                FROM picks_vip
                WHERE DATE_TRUNC('month', match_date) = DATE_TRUNC('month', CURRENT_DATE)
            """)
            m = dict(cur.fetchone() or {})
            total_m, greens_m = m.get("total", 0) or 0, m.get("greens", 0) or 0
            wr_m = round(greens_m / total_m * 100, 1) if total_m > 0 else 0.0

            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE result IS NOT NULL)     AS total,
                    COUNT(*) FILTER (WHERE result = 'GREEN')       AS greens,
                    COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit
                FROM picks_vip
                WHERE match_date >= CURRENT_DATE - INTERVAL '7 days' AND result IS NOT NULL
            """)
            s7 = dict(cur.fetchone() or {})
            total_7, greens_7 = s7.get("total", 0) or 0, s7.get("greens", 0) or 0
            wr_7 = round(greens_7 / total_7 * 100, 1) if total_7 > 0 else 0.0

            lines.append(f"\n--- DESEMPENHO VIP ---")
            lines.append(f"Mês atual: {greens_m}/{total_m} greens ({wr_m}% win rate) | Lucro: {float(m.get('profit', 0)):.2f}u")
            lines.append(f"Últimos 7 dias: {greens_7}/{total_7} greens ({wr_7}% win rate) | Lucro: {float(s7.get('profit', 0)):.2f}u")

            # ── Desempenho alavancagem ──────────────────────────────────────
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE result IS NOT NULL) AS total,
                    COUNT(*) FILTER (WHERE result = 'GREEN')   AS greens,
                    COUNT(*) FILTER (WHERE result = 'RED')     AS reds
                FROM picks_alavancagem
                WHERE DATE_TRUNC('month', match_date) = DATE_TRUNC('month', CURRENT_DATE)
            """)
            am = dict(cur.fetchone() or {})
            if (am.get("total") or 0) > 0:
                lines.append(f"Alavancagem mês: {am.get('greens',0)} greens / {am.get('reds',0)} resets de {am.get('total',0)} picks")

            lines.append(f"\n--- PICKS DE HOJE ---")

            if is_vip:
                # Picks VIP
                cur.execute("""
                    SELECT home_team_name, away_team_name, market, line, odd,
                           bet_house, confidence, result, stake
                    FROM picks_vip WHERE match_date = CURRENT_DATE ORDER BY confidence DESC
                """)
                vip_picks = cur.fetchall()
                if vip_picks:
                    lines.append(f"Picks VIP ({len(vip_picks)}):")
                    for p in [dict(r) for r in vip_picks]:
                        conf = f"{round(p['confidence']*100)}%" if p.get('confidence') else "?"
                        line_s = f" {p['line']}" if p.get('line') else ""
                        stake_s = f" | {p['stake']}u" if p.get('stake') else ""
                        lines.append(
                            f"  • {p['home_team_name']} x {p['away_team_name']}: "
                            f"{p['market']}{line_s} @ {p['odd']} ({p.get('bet_house','?')})"
                            f"{stake_s} | Conf: {conf} | {p.get('result') or 'pendente'}"
                        )
                else:
                    lines.append("Picks VIP: nenhum publicado hoje ainda.")

                # Múltipla
                cur.execute("""
                    SELECT home_team_1, away_team_1, market_1, line_1, odd_1,
                           home_team_2, away_team_2, market_2, line_2, odd_2,
                           odd_combined, tipo, result
                    FROM picks_multiplas
                    WHERE DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
                    ORDER BY created_at DESC LIMIT 1
                """)
                mult = cur.fetchone()
                if mult:
                    mult = dict(mult)
                    lines.append(f"\nMúltipla do dia (odd combinada: {mult['odd_combined']:.2f}) | {mult.get('result') or 'pendente'}:")
                    lines.append(f"  • {mult['home_team_1']} x {mult['away_team_1']}: {mult['market_1']}{' '+mult['line_1'] if mult.get('line_1') else ''} @ {mult['odd_1']}")
                    if mult.get('home_team_2'):
                        lines.append(f"  • {mult['home_team_2']} x {mult['away_team_2']}: {mult['market_2']}{' '+mult['line_2'] if mult.get('line_2') else ''} @ {mult['odd_2']}")

                # Alavancagem
                cur.execute("""
                    SELECT home_team_1, away_team_1, market_1, line_1, odd_1,
                           home_team_2, away_team_2, market_2, line_2, odd_2,
                           odd_combined, tipo, result
                    FROM picks_alavancagem WHERE match_date = CURRENT_DATE ORDER BY created_at DESC LIMIT 1
                """)
                alav_pick = cur.fetchone()
                if alav_pick:
                    alav_pick = dict(alav_pick)
                    lines.append(f"\nPick Alavancagem | {alav_pick.get('result') or 'pendente'}:")
                    lines.append(f"  • {alav_pick['home_team_1']} x {alav_pick['away_team_1']}: {alav_pick['market_1']}{' '+alav_pick['line_1'] if alav_pick.get('line_1') else ''} @ {alav_pick['odd_1']}")
                    if alav_pick.get('home_team_2'):
                        lines.append(f"  • {alav_pick['home_team_2']} x {alav_pick['away_team_2']}: {alav_pick['market_2']}{' '+alav_pick['line_2'] if alav_pick.get('line_2') else ''} @ {alav_pick['odd_2']}")

                # Histórico alavancagem (últimas 10)
                cur.execute("""
                    SELECT home_team_1, away_team_1, match_date, result
                    FROM picks_alavancagem ORDER BY match_date DESC LIMIT 10
                """)
                alav_hist = [dict(r) for r in cur.fetchall()]
                if alav_hist:
                    lines.append(f"\n--- HISTÓRICO ALAVANCAGEM (últimas {len(alav_hist)} entradas) ---")
                    for a in alav_hist:
                        lines.append(f"  {a.get('match_date','?')}: {a['home_team_1']} x {a['away_team_1']} · {a.get('result') or 'pendente'}")

            else:
                # Preview free (top 3 sem detalhes)
                cur.execute("""
                    SELECT home_team_name, away_team_name, market, result
                    FROM picks_vip WHERE match_date = CURRENT_DATE ORDER BY confidence DESC LIMIT 3
                """)
                preview = [dict(r) for r in cur.fetchall()]
                if preview:
                    lines.append("Prévia VIP de hoje (assine para ver odds e detalhes):")
                    for p in preview:
                        lines.append(f"  • {p['home_team_name']} x {p['away_team_name']}: {p['market']} | {p.get('result') or 'pendente'}")

            # Pick Seguro (gratuito — sempre visível)
            cur.execute("""
                SELECT home_team, away_team, market, line, odd, result
                FROM picks_free WHERE match_date = CURRENT_DATE ORDER BY created_at DESC LIMIT 1
            """)
            free_pick = cur.fetchone()
            if free_pick:
                fp = dict(free_pick)
                line_s = f" {fp['line']}" if fp.get('line') else ""
                lines.append(f"\nPick Seguro (gratis): {fp['home_team']} x {fp['away_team']} · {fp['market']}{line_s} @ {fp['odd']} | {fp.get('result') or 'pendente'}")

            return "\n".join(lines)
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.warning(f"Erro ao buscar contexto do site: {e}")
        return ""


@router.post("")
async def chat(body: ChatRequest, current_user: dict = Depends(get_current_user)):
    if not _AGENT_OK or run_agent is None:
        raise HTTPException(503, "Agente indisponível. Configure ANTHROPIC_API_KEY.")

    # Rate limit por usuário
    uid = str(current_user["id"])
    now = time.time()
    _chat_rate[uid] = [t for t in _chat_rate[uid] if now - t < _CHAT_WINDOW]
    if len(_chat_rate[uid]) >= _CHAT_LIMIT:
        raise HTTPException(429, f"Limite de {_CHAT_LIMIT} mensagens por minuto atingido. Aguarde.")
    _chat_rate[uid].append(now)

    if not body.messages:
        raise HTTPException(400, "Nenhuma mensagem enviada")

    last = body.messages[-1]
    if last.role != "user":
        raise HTTPException(400, "Última mensagem deve ser do usuário")

    user_text = last.content.strip()
    if not user_text:
        raise HTTPException(400, "Mensagem vazia")
    _MAX_MSG_LEN = 2000
    if len(user_text) > _MAX_MSG_LEN:
        raise HTTPException(400, f"Mensagem muito longa (máx {_MAX_MSG_LEN} caracteres)")

    history = [
        {"role": m.role, "content": m.content}
        for m in body.messages[:-1]
        if m.role in ("user", "assistant") and m.content.strip()
    ][-6:]

    # Sempre injeta contexto completo do site (picks, banca, alavancagem, desempenho)
    site_context = await asyncio.to_thread(_get_site_context, current_user["id"])
    full_message = f"{site_context}\n\n---\n\n{user_text}" if site_context else user_text

    async def generate():
        yield f"data: {json.dumps({'type': 'status', 'text': 'Buscando dados...'})}\n\n"

        try:
            response_text, _ = await run_agent(full_message, history)

            chunk_size = 35
            first = True
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'chunk', 'text': chunk, 'first': first})}\n\n"
                first = False
                await asyncio.sleep(0.012)

        except Exception as e:
            logger.error("Erro no agente: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'chunk', 'text': 'Erro ao processar sua mensagem. Tente novamente.', 'first': True})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
