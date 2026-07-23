import asyncio
import logging
import os

import resend


async def _job_expire_plans(logger: logging.Logger):
    while True:
        await asyncio.sleep(3600)
        try:
            from database import get_connection

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET plan='free', expires_at=NULL "
                "WHERE plan IN ('vip','trial') AND expires_at IS NOT NULL AND expires_at < NOW()"
            )
            affected = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            if affected:
                logger.info("[EXPIRE-PLANS] %d plano(s) expirado(s) -> free", affected)
        except Exception as e:
            logger.error("[EXPIRE-PLANS] Erro: %s", e)


def start_expire_plans_task(logger: logging.Logger) -> None:
    asyncio.create_task(_job_expire_plans(logger))


def _send_banca_reminder(logger: logging.Logger, to: str, first_name: str):
    api_key = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("RESEND_FROM", "Pick IA <contato@pickia.com.br>")
    site_url = os.getenv("SITE_URL", "https://pickia.com.br")
    if not api_key:
        return

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#111;border:1px solid #222;border-radius:16px;overflow:hidden;max-width:560px;width:100%;">
        <tr><td style="background:#ca8a04;padding:36px 40px;text-align:center;">
          <h1 style="margin:0;color:#fff;font-size:26px;font-weight:900;">Falta so 1 passo!</h1>
          <p style="margin:8px 0 0;color:#fef9c3;font-size:14px;">Configure sua banca e comece a acompanhar seus picks</p>
        </td></tr>
        <tr><td style="padding:36px 40px;">
          <h2 style="margin:0 0 20px;color:#fff;font-size:20px;font-weight:800;">Ola, {first_name}!</h2>
          <p style="margin:0 0 24px;color:#a1a1aa;font-size:15px;line-height:1.6;">
            Voce criou sua conta no <strong style="color:#fff;">Pick IA</strong>, mas ainda nao configurou sua banca.
            Leva menos de 30 segundos.
          </p>
          <p style="text-align:center;margin:0 0 24px;">
            <a href="{site_url}/banca" style="display:inline-block;background:#ca8a04;color:#fff;text-decoration:none;font-weight:800;font-size:15px;padding:14px 40px;border-radius:10px;">
              Configurar minha banca agora
            </a>
          </p>
        </td></tr>
        <tr><td style="border-top:1px solid #1f1f1f;padding:20px 40px;text-align:center;">
          <p style="margin:0;color:#3f3f46;font-size:11px;">Pick IA - Tips por Inteligencia Artificial</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    try:
        resend.api_key = api_key
        resend.Emails.send({
            "from": from_addr,
            "to": [to],
            "subject": "Como acompanhar seus picks no Pick IA",
            "text": f"Ola {first_name}, configure sua banca em {site_url}/banca",
            "html": html,
        })
        logger.info("[BANCA-REMINDER] Email enviado para %s", to)
    except Exception as e:
        logger.error("[BANCA-REMINDER] Falha ao enviar para %s: %s", to, e)


def _send_pipeline_failure_alert(logger: logging.Logger, error_msg: str):
    api_key = os.getenv("RESEND_API_KEY", "")
    to = os.getenv("ADMIN_ALERT_EMAIL", "")
    if not api_key or not to:
        return
    from_addr = os.getenv("RESEND_FROM", "Pick IA <contato@pickia.com.br>")
    try:
        resend.api_key = api_key
        resend.Emails.send({
            "from": from_addr,
            "to": [to],
            "subject": "[Pick IA] Pipeline diario falhou",
            "text": f"O pipeline diario (00:10 BR) falhou e nao publicou os picks de hoje.\n\nErro: {error_msg}",
        })
    except Exception as e:
        logger.error("[PIPELINE-ALERT] Falha ao enviar alerta: %s", e)


def _job_banca_reminder(logger: logging.Logger):
    from database import get_connection

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.email, u.name
            FROM users u
            LEFT JOIN user_banca ub ON ub.user_id = u.id
            WHERE ub.user_id IS NULL
              AND u.active = TRUE
              AND u.created_at BETWEEN NOW() - INTERVAL '25 hours' AND NOW() - INTERVAL '23 hours'
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        for row in rows:
            first_name = row["name"].split()[0]
            _send_banca_reminder(logger, row["email"], first_name)
    except Exception as e:
        logger.error("[BANCA-REMINDER] Erro ao buscar usuarios: %s", e)


def _job_resolve_picks(logger: logging.Logger):
    try:
        from routers.live import resolve_all_pending

        resolved = resolve_all_pending()
        if any(v > 0 for v in resolved.values()):
            logger.info("[SCHEDULER] Picks resolvidos: %s", resolved)
    except Exception as e:
        logger.error("[SCHEDULER] Erro em resolve_picks: %s", e)


def _job_reverify_stats(logger: logging.Logger):
    try:
        from routers.live import reverify_recent_stats_results

        result = reverify_recent_stats_results()
        if result["corrected"]:
            logger.warning("[SCHEDULER] Resultados corrigidos por revisao tardia do provedor: %s",
                            result["corrected"])
    except Exception as e:
        logger.error("[SCHEDULER] Erro em reverify_stats: %s", e)


def _job_run_daily_pipeline(logger: logging.Logger):
    try:
        from routers.admin import _pipeline_status, _run_tudo

        if _pipeline_status.get("tudo", {}).get("status") == "running":
            logger.info("[SCHEDULER] Pipeline diario ja esta rodando, ignorando disparo duplicado.")
            return
        logger.info("[SCHEDULER] Iniciando pipeline diario (00:10 BR)...")
        asyncio.run(_run_tudo())
        status = _pipeline_status.get("tudo", {})
        if status.get("status") == "error":
            logger.error("[SCHEDULER] Pipeline diario falhou: %s", status.get("error"))
            _send_pipeline_failure_alert(logger, status.get("error") or "erro desconhecido")
        else:
            try:
                from routers.notifications import send_push_to_all_vip

                send_push_to_all_vip(
                    title="Picks do dia publicados",
                    body="Seus picks de hoje estao disponiveis. Confira agora!",
                    url="/picks",
                )
            except Exception as push_err:
                logger.warning("[PUSH] Erro ao enviar push pos-pipeline: %s", push_err)
    except Exception as e:
        logger.error("[SCHEDULER] Erro no pipeline diario: %s", e)
        _send_pipeline_failure_alert(logger, str(e))


def _job_run_dev_pipeline(logger: logging.Logger):
    try:
        from routers.admin import _pipeline_status, _run_dev_pipeline

        if _pipeline_status.get("dev_tudo", {}).get("status") == "running":
            logger.info("[SCHEDULER] Pipeline DEV ja esta rodando, ignorando disparo duplicado.")
            return
        logger.info("[SCHEDULER] Iniciando pipeline DEV (00:10 BR)...")
        asyncio.run(_run_dev_pipeline())
        status = _pipeline_status.get("dev_tudo", {})
        if status.get("status") == "error":
            logger.error("[SCHEDULER] Pipeline DEV falhou: %s", status.get("error"))
    except Exception as e:
        logger.error("[SCHEDULER] Erro no pipeline DEV: %s", e)


def start_background_scheduler(logger: logging.Logger) -> None:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda: _job_banca_reminder(logger), "interval", hours=1, id="banca_reminder")
        scheduler.add_job(lambda: _job_resolve_picks(logger), "interval", minutes=5, id="resolve_picks")
        scheduler.add_job(lambda: _job_reverify_stats(logger), "interval", hours=1, id="reverify_stats")
        # Pipeline diario de geracao de picks (00:10 BR) -- ficou pausado desde o
        # corte de IA em producao (2026-07-17), porque na epoca _run_tudo() ainda
        # chamava os scripts de IA antigos. Agora que routers.admin::_PIPELINE_SCRIPTS
        # aponta pro motor deterministico (engine_pipelines), reativado: sem esse
        # job nada gera picks novos automaticamente (o unico jeito de picks
        # aparecerem seria disparo manual via /admin ou linha de comando).
        scheduler.add_job(
            lambda: _job_run_daily_pipeline(logger),
            CronTrigger(hour=0, minute=10, timezone="America/Sao_Paulo"),
            id="daily_pipeline",
            misfire_grace_time=3600,
        )
        dev_pipeline_enabled = bool(os.getenv("DB_HOST_DEV"))
        if dev_pipeline_enabled:
            scheduler.add_job(
                lambda: _job_run_dev_pipeline(logger),
                CronTrigger(hour=0, minute=10, timezone="America/Sao_Paulo"),
                id="dev_daily_pipeline",
                misfire_grace_time=3600,
            )
        scheduler.start()
        logger.info(
            "[SCHEDULER] Iniciado - lembrete banca 1h | resolve picks 5min | "
            "reconfere escanteios/cartoes 1h | "
            "pipeline diario (motor) ATIVADO 00:10 BR | homologacao DEV %s",
            "ATIVADO 00:10 BR" if dev_pipeline_enabled else "desativada (sem DB_HOST_DEV)",
        )
    except Exception as e:
        logger.error("[SCHEDULER] Falha ao iniciar: %s", e)
