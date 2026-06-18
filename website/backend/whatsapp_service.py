"""
WhatsApp notification service via Meta Cloud API.

Configurar no Railway:
  WHATSAPP_TOKEN    = Bearer token da Meta (System User token)
  WHATSAPP_PHONE_ID = Phone number ID (ex: 123456789012345)
  SITE_URL          = https://pickia.com.br  (já usado pelo sistema)

Referência: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

_TOKEN    = os.getenv("WHATSAPP_TOKEN", "")
_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
_SITE_URL = os.getenv("SITE_URL", "https://pickia.com.br").rstrip("/")
_API_URL  = f"https://graph.facebook.com/v19.0/{_PHONE_ID}/messages"

_CONFIGURED = bool(_TOKEN and _PHONE_ID)


def _send(phone: str, text: str) -> bool:
    """Envia mensagem de texto simples. phone deve estar em E.164 (+5511...)."""
    if not _CONFIGURED:
        logger.debug("[WHATSAPP] Não configurado — mensagem ignorada para %s", phone)
        return False
    try:
        r = httpx.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {"body": text},
            },
            timeout=10.0,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("[WHATSAPP] Erro ao enviar para %s: %s", phone, e)
        return False


def notify_new_pick(pick: dict, phones: list[str]) -> None:
    """Dispara quando um novo pick VIP é gerado."""
    home = pick.get("home_team", "")
    away = pick.get("away_team", "")
    market = pick.get("market", "")
    line   = pick.get("line", "")
    odd    = pick.get("odd", "")
    market_str = f"{market} {line}".strip()
    text = (
        f"🟡 *Novo Pick Disponível!*\n\n"
        f"*{home} x {away}*\n"
        f"Mercado: {market_str}\n"
        f"Odd: {odd}\n\n"
        f"▶ {_SITE_URL}/picks"
    )
    for phone in phones:
        _send(phone, text)


def notify_result(pick: dict, phones: list[str]) -> None:
    """Dispara quando o resultado de um pick é confirmado."""
    result = pick.get("result", "")
    emoji  = {"GREEN": "🟢", "RED": "🔴", "PUSH": "⚪", "HALF-WIN": "🟡", "HALF-LOSS": "🟠"}.get(result, "❓")
    home   = pick.get("home_team", "")
    away   = pick.get("away_team", "")
    market = pick.get("market", "")
    odd    = pick.get("odd", "")
    profit = pick.get("profit")
    profit_str = f"{float(profit):+.2f}u" if profit is not None else ""
    text = (
        f"{emoji} *Resultado: {result}*{' · ' + profit_str if profit_str else ''}\n\n"
        f"*{home} x {away}*\n"
        f"Mercado: {market} · Odd: {odd}\n\n"
        f"▶ {_SITE_URL}/picks"
    )
    for phone in phones:
        _send(phone, text)


def send_daily_summary(date: str, stats: dict, phones: list[str]) -> None:
    """Resumo diário enviado via APScheduler (ex: 23h)."""
    profit  = float(stats.get("profit", 0))
    greens  = stats.get("greens", 0)
    reds    = stats.get("reds", 0)
    total   = stats.get("total", 0)
    roi     = stats.get("roi") or 0
    sign    = "+" if profit >= 0 else ""
    text = (
        f"📊 *Resumo do dia {date}*\n\n"
        f"✅ Green: {greens}   ❌ Red: {reds}   Total: {total}\n"
        f"Lucro: {sign}{profit:.2f}u   ROI: {sign}{roi:.1f}%\n\n"
        f"▶ {_SITE_URL}/picks"
    )
    for phone in phones:
        _send(phone, text)
