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


def _get_picks_context(user_id: int) -> str:
    """Busca os picks do dia no banco e formata como contexto para o agente."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            plan_row = cur.execute(
                "SELECT plan FROM users WHERE id = %s", (user_id,)
            )
            plan_row = cur.fetchone()
            plan = (plan_row["plan"] if plan_row else "free")
            is_vip = plan in ("vip", "admin")

            # Stats de desempenho do mês
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE result IS NOT NULL) AS total,
                    COUNT(*) FILTER (WHERE result = 'GREEN')   AS greens,
                    COUNT(*) FILTER (WHERE result = 'RED')     AS reds,
                    COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit
                FROM picks_vip
                WHERE DATE_TRUNC('month', match_date) = DATE_TRUNC('month', CURRENT_DATE)
            """)
            stats = dict(cur.fetchone() or {})
            total  = stats.get("total", 0) or 0
            greens = stats.get("greens", 0) or 0
            win_rate = round(greens / total * 100, 1) if total > 0 else 0.0

            context_lines = [
                f"=== PICKS DO SITE (hoje) ===",
                f"Desempenho do mês: {greens}/{total} acertos ({win_rate}% win rate) | Lucro: {float(stats.get('profit', 0)):.2f}u",
            ]

            if is_vip:
                # Picks do dia
                cur.execute("""
                    SELECT home_team_name, away_team_name, market, line, odd,
                           bet_house, confidence, result
                    FROM picks_vip
                    WHERE match_date = CURRENT_DATE
                    ORDER BY confidence DESC
                """)
                picks = cur.fetchall()
                if picks:
                    context_lines.append(f"\nPicks de hoje ({len(picks)} picks):")
                    for p in picks:
                        p = dict(p)
                        conf_pct = f"{round(p['confidence'] * 100)}%" if p.get('confidence') else "?"
                        resultado = p.get('result') or 'pendente'
                        line_str = f" {p['line']}" if p.get('line') else ""
                        context_lines.append(
                            f"- {p['home_team_name']} x {p['away_team_name']}: "
                            f"{p['market']}{line_str} @ {p['odd']} ({p.get('bet_house','?')}) "
                            f"| Conf: {conf_pct} | Resultado: {resultado}"
                        )
                else:
                    context_lines.append("Nenhum pick publicado para hoje ainda.")

                # Dica do dia
                cur.execute("""
                    SELECT home_team, away_team, market, line, odd, confidence, result
                    FROM picks_free
                    WHERE match_date = CURRENT_DATE
                    ORDER BY created_at DESC LIMIT 1
                """)
                dica = cur.fetchone()
                if dica:
                    dica = dict(dica)
                    line_str = f" {dica['line']}" if dica.get('line') else ""
                    context_lines.append(
                        f"\nPick Seguro do dia: {dica['home_team']} x {dica['away_team']} — "
                        f"{dica['market']}{line_str} @ {dica['odd']} | "
                        f"Resultado: {dica.get('result') or 'pendente'}"
                    )
            else:
                # Preview grátis (top 3 sem detalhes completos)
                cur.execute("""
                    SELECT home_team_name, away_team_name, market, result
                    FROM picks_vip
                    WHERE match_date = CURRENT_DATE
                    ORDER BY confidence DESC LIMIT 3
                """)
                picks = cur.fetchall()
                if picks:
                    context_lines.append(f"\nPrévia dos picks de hoje (top 3):")
                    for p in picks:
                        p = dict(p)
                        resultado = p.get('result') or 'pendente'
                        context_lines.append(
                            f"- {p['home_team_name']} x {p['away_team_name']}: "
                            f"{p['market']} | Resultado: {resultado}"
                        )
                    context_lines.append("(Assine VIP para ver odds, casas de aposta e todos os detalhes)")

            return "\n".join(context_lines)
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.warning(f"Erro ao buscar picks para contexto: {e}")
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

    history = [
        {"role": m.role, "content": m.content}
        for m in body.messages[:-1]
        if m.role in ("user", "assistant") and m.content.strip()
    ][-6:]

    # Injeta contexto dos picks se a pergunta parecer relacionada ao site
    picks_keywords = ("pick", "tip", "dica", "sugestão", "hoje", "resultado", "green", "red",
                      "acerto", "win rate", "desempenho", "bater", "bateu", "perdeu")
    user_lower = user_text.lower()
    include_picks = any(kw in user_lower for kw in picks_keywords)

    picks_context = ""
    if include_picks:
        picks_context = await asyncio.to_thread(_get_picks_context, current_user["id"])

    full_message = user_text
    if picks_context:
        full_message = f"{picks_context}\n\n---\n\n{user_text}"

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
