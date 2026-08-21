import os
import time
import hmac
import hashlib
import logging
import resend
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import mercadopago
from auth_utils import get_current_user, invalidar_cache_usuario
from database import get_connection
from email_templates import url_logo, vip_ativado_html

logger = logging.getLogger(__name__)

# Rate limit por usuario ao criar preferencia de pagamento -- sem isso, um
# script podia gerar preferencias no MercadoPago sem limite (nao afeta
# integridade do plano/saldo, so evita ruido/custo na API do MP).
_rate_buckets: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
_RATE_WINDOW = 60


def _check_rate(bucket: str, user_id: int, limit: int) -> None:
    now = time.time()
    marcas = _rate_buckets[bucket][user_id] = [
        t for t in _rate_buckets[bucket][user_id] if now - t < _RATE_WINDOW
    ]
    if len(marcas) >= limit:
        raise HTTPException(429, "Muitas tentativas. Aguarde um momento e tente novamente.")
    marcas.append(now)

def _send_vip_email(to: str, name: str, plan_key: str, expires_at) -> None:
    api_key   = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("RESEND_FROM", "Pick IA <contato@pickia.com.br>")
    site_url  = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")

    if not api_key:
        return

    first_name  = name.strip().split()[0]
    plan_label  = PLAN_LABELS.get(plan_key, plan_key.capitalize())
    expires_str = expires_at.strftime("%d/%m/%Y") if hasattr(expires_at, "strftime") else str(expires_at)[:10]

    html = vip_ativado_html(
        first_name, plan_label, expires_str, site_url, url_logo(site_url)
    )

    try:
        resend.api_key = api_key
        resend.Emails.send({
            "from":    from_addr,
            "to":      [to],
            "subject": "Acesso ativado · Pick IA",
            "text":    f"Olá {first_name}, seu acesso foi ativado! Plano {plan_label} válido até {expires_str}. Acesse: {site_url}/picks",
            "html":    html,
        })
        logger.info("[EMAIL] VIP email enviado para %s", to)
    except Exception as e:
        logger.warning("[EMAIL] Falha ao enviar VIP email para %s: %s", to, e)


def _mp_manifest(data_id: str, request_id: str, ts: str) -> str:
    """Template oficial do MercadoPago:

        id:<data.id>;request-id:<x-request-id>;ts:<ts>;

    Dois detalhes que a doc exige e que já custaram caro aqui:

      1. O ponto e vírgula FINAL, depois do ts, faz parte da mensagem. Sem ele
         o hash nunca bate e toda notificação legítima vira 403.
      2. Campo ausente sai do template inteiro, junto com o seu ';' -- não
         entra como string vazia.
    """
    pedacos = []
    if data_id:
        pedacos.append(f"id:{data_id};")
    if request_id:
        pedacos.append(f"request-id:{request_id};")
    if ts:
        pedacos.append(f"ts:{ts};")
    return "".join(pedacos)


def _verify_mp_signature(x_signature: str, x_request_id: str, data_id: str, secret: str) -> bool:
    """Verifica a assinatura HMAC-SHA256 do MercadoPago.

    `data_id` tem que vir do QUERY STRING da notificação (`?data.id=...`), não
    do corpo: é sobre o valor da URL que o MercadoPago assina.
    """
    try:
        # O MercadoPago envia: x-signature = ts=<timestamp>,v1=<hash>
        partes = dict(
            (k.strip(), v.strip())
            for k, v in (p.split("=", 1) for p in x_signature.split(",") if "=" in p)
        )
        ts = partes.get("ts", "")
        v1 = partes.get("v1", "")
        if not ts or not v1:
            return False

        # A doc manda usar o id em minúsculo quando ele é alfanumérico. Como
        # nem toda notificação é de pagamento (id numérico), testa as duas
        # formas -- ambas continuam sendo HMAC com o segredo, então aceitar a
        # variante não afrouxa nada.
        for candidato in dict.fromkeys([data_id, data_id.lower()]):
            manifesto = _mp_manifest(candidato, x_request_id, ts)
            esperado = hmac.new(secret.encode(), manifesto.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(esperado, v1):
                return True
        return False
    except Exception:
        return False

router = APIRouter(prefix="/api/payments", tags=["payments"])

#
# FONTE DE VERDADE DO PREÇO.
#
# Isto aqui é o que o MercadoPago cobra de fato. Antes o valor também estava
# escrito à mão no Checkout, no Planos, na Home e no JSON-LD do index.html, e o
# JSON-LD ficou anunciando R$ 49,90 pro Google enquanto a cobrança era 39,90
# sem ninguém perceber.
#
# Quem quiser mostrar preço na tela lê de GET /api/payments/plans (público).
# Não copiar número daqui pro front.
#
PLANS = {
    "mensal":     {"price": 39.90,  "title": "Plano Picks Mensal",     "days": 30},
    "trimestral": {"price": 99.90,  "title": "Plano Picks Trimestral", "days": 90},
    "semestral":  {"price": 199.90, "title": "Plano Picks Semestral",  "days": 180},
    "anual":      {"price": 359.90, "title": "Plano Picks Anual",      "days": 365},
}

# Rótulo curto de cada ciclo, pra tela não precisar traduzir a chave.
PLAN_LABELS = {
    "mensal": "Mensal", "trimestral": "Trimestral",
    "semestral": "Semestral", "anual": "Anual",
}
PLAN_PERIODS = {
    "mensal": "1 mês", "trimestral": "3 meses",
    "semestral": "6 meses", "anual": "12 meses",
}
# ISO 8601 de duração, exigido pelo billingIncrement do schema.org.
PLAN_ISO_PERIOD = {
    "mensal": "P1M", "trimestral": "P3M", "semestral": "P6M", "anual": "P1Y",
}


def _plan_payload(key: str) -> dict:
    """Um plano já com tudo que a tela precisa mostrar.

    O desconto é calculado aqui, e não no front, porque era mais um lugar onde
    a conta podia divergir: o Planos.tsx derivava `savePct` com 39.90 escrito
    de novo no meio da expressão.
    """
    info = PLANS[key]
    months = round(info["days"] / 30) or 1
    per_month = info["price"] / months
    monthly_price = PLANS["mensal"]["price"]
    full_price = monthly_price * months
    savings = round(full_price - info["price"], 2)
    save_pct = round((1 - info["price"] / full_price) * 100) if full_price > 0 else 0

    return {
        "id":            key,
        "label":         PLAN_LABELS[key],
        "title":         info["title"],
        "price":         info["price"],
        "days":          info["days"],
        "period":        PLAN_PERIODS[key],
        "months":        months,
        "price_per_month": round(per_month, 2),
        "iso_period":    PLAN_ISO_PERIOD[key],
        # 0 no mensal, que é a própria régua de comparação
        "savings":       savings if key != "mensal" else 0.0,
        "save_pct":      save_pct if key != "mensal" else 0,
    }


@router.get("/plans")
def list_plans():
    """Catálogo de planos VIP · sem autenticação.

    Público de propósito: a Home e a página de Planos mostram preço pra
    visitante deslogado, e é justamente esse caminho que ficava desatualizado
    quando o valor era escrito à mão no front.
    """
    return {
        "currency": "BRL",
        "plans": [_plan_payload(k) for k in PLANS],
    }


# Teto para o registro de recusa vinda de fora. O /webhook nao tem
# autenticacao -- quem descobrir a URL consegue disparar recusa a vontade, e
# sem teto isso vira insercao ilimitada numa tabela do banco.
_recusas_registradas: list[float] = []
_LIMITE_RECUSAS = 20
_JANELA_RECUSAS = 600


def _pode_registrar_recusa() -> bool:
    agora = time.time()
    _recusas_registradas[:] = [t for t in _recusas_registradas if agora - t < _JANELA_RECUSAS]
    if len(_recusas_registradas) >= _LIMITE_RECUSAS:
        return False
    _recusas_registradas.append(agora)
    return True


def _record_event(source: str, status: str, mp_payment_id="", detail: str = "") -> None:
    """Deixa rastro de toda tentativa de processar pagamento.

    Existe porque o modo de falha real foi silencioso: o webhook rejeitava a
    notificação por assinatura e ninguém ficava sabendo -- nem o comprador,
    que continuava free, nem o relatório, que não contava a venda. Com a
    trilha, "o MercadoPago chamou?" vira uma consulta em vez de um palpite.

    Nunca propaga erro: falha em registrar não pode derrubar uma ativação.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO payment_events (source, status, mp_payment_id, detail)
                   VALUES (%s, %s, %s, %s)""",
                (source[:20], status[:30], str(mp_payment_id or "")[:50], (detail or "")[:300]),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.warning("[PAYMENTS] Falha ao registrar evento %s/%s: %s", source, status, e)


def _apply_approved_payment(payment: dict, source: str) -> dict:
    """Grava o pagamento e ativa o VIP a partir de um objeto de pagamento do MP.

    Único caminho de ativação do sistema: webhook, retorno do checkout e as
    duas rotas de admin passam todos por aqui. Antes cada um tinha a sua
    versão da regra e elas já divergiam -- o /admin/sync-payment, por exemplo,
    não creditava a indicação nem mandava o e-mail que o webhook mandava.

    Idempotente pelo mp_payment_id: reprocessar o mesmo pagamento não estende
    o VIP de novo.
    """
    payment_id = str(payment.get("id") or "")
    status     = payment.get("status")

    if status != "approved":
        return {"status": "not_approved", "payment_id": payment_id, "detail": f"status={status}"}

    external_ref = payment.get("external_reference") or ""
    parts = external_ref.split(":", 1)
    if len(parts) != 2:
        _record_event(source, "ref_invalida", payment_id, f"external_reference={external_ref!r}")
        return {"status": "error", "payment_id": payment_id, "detail": "external_reference inválido"}

    user_id, plan_key = parts
    plan_info = PLANS.get(plan_key)
    if not plan_info:
        _record_event(source, "plano_invalido", payment_id, f"plano={plan_key!r}")
        return {"status": "error", "payment_id": payment_id, "detail": f"plano inválido: {plan_key}"}

    try:
        user_id_int = int(user_id)
    except ValueError:
        _record_event(source, "ref_invalida", payment_id, f"user_id={user_id!r}")
        return {"status": "error", "payment_id": payment_id, "detail": "user_id inválido"}

    amount         = float(payment.get("transaction_amount") or plan_info["price"])
    payment_method = payment.get("payment_type_id") or payment.get("payment_method_id") or "unknown"

    conn = get_connection()
    cur = conn.cursor()
    try:
        # Renovacao/upgrade estende a partir do maior entre "agora" e o expires_at
        # atual (se o usuario ainda tem VIP ativo), em vez de sempre sobrescrever
        # com "agora + dias do plano" -- sem isso, quem renova antes de vencer
        # (comportamento comum) perdia os dias restantes que ja tinha pago.
        # Mesmo padrao ja usado abaixo pro credito de indicacao (GREATEST).
        cur.execute("SELECT name, email, expires_at, ga_client_id FROM users WHERE id = %s", (user_id_int,))
        row = cur.fetchone()
        if not row:
            logger.error("[PAYMENTS] user_id=%s não encontrado · pagamento %s ignorado", user_id, payment_id)
            _record_event(source, "usuario_inexistente", payment_id, f"user_id={user_id}")
            return {"status": "error", "payment_id": payment_id, "detail": "usuário não encontrado"}

        user_name     = row["name"]
        user_email    = row["email"]
        ga_client_id  = row["ga_client_id"]
        current_expires = row["expires_at"]  # naive UTC (coluna timestamp without time zone)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        base = current_expires if (current_expires and current_expires > now_naive) else now_naive
        expires_at = base + timedelta(days=plan_info["days"])

        # Registra pagamento ANTES do UPDATE · garante idempotência real
        # ON CONFLICT DO NOTHING: se payment_id já existe, rowcount=0 e não ativa VIP de novo
        cur.execute(
            """
            INSERT INTO payments (user_id, mp_payment_id, plan_key, amount, status, expires_at, payment_method)
            VALUES (%s, %s, %s, %s, 'approved', %s, %s)
            ON CONFLICT (mp_payment_id) DO NOTHING
            """,
            (user_id_int, payment_id, plan_key, amount, expires_at, payment_method),
        )
        if cur.rowcount == 0:
            conn.rollback()
            logger.info("[PAYMENTS] Pagamento %s já processado anteriormente · ignorando", payment_id)
            return {"status": "duplicate", "payment_id": payment_id, "user_id": user_id_int, "plan": plan_key}

        logger.info("[PAYMENTS] Ativando VIP para user_id=%s plano=%s expires=%s (via %s)",
                    user_id, plan_key, expires_at, source)
        cur.execute(
            "UPDATE users SET plan='vip', expires_at=%s, subscription_type=%s WHERE id=%s",
            (expires_at, plan_key, user_id_int),
        )

        # Crédito de indicação: +2 dias VIP para o referrer quando indicado assina VIP
        cur.execute(
            "SELECT referred_by FROM users WHERE id = %s AND referred_by IS NOT NULL",
            (user_id_int,),
        )
        ref_row = cur.fetchone()
        if ref_row:
            cur.execute(
                """
                UPDATE users
                SET plan       = CASE WHEN plan IN ('free', 'trial') THEN 'vip' ELSE plan END,
                    expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + INTERVAL '2 days'
                WHERE id = %s
                """,
                (ref_row["referred_by"],),
            )

        conn.commit()
        # O usuario acabou de pagar e esta olhando a tela: sem isto ele
        # continuaria vendo o site como free ate o TTL do cache de sessao
        # expirar (auth_utils). O referrer entra junto porque o credito de
        # indicacao tambem pode ter promovido ele a VIP agora.
        invalidar_cache_usuario(user_id_int)
        if ref_row:
            invalidar_cache_usuario(ref_row["referred_by"])
        logger.info("[PAYMENTS] VIP ativado para user_id=%s email=%s", user_id, user_email)
    finally:
        cur.close()
        conn.close()

    _record_event(source, "ativado", payment_id, f"user_id={user_id} plano={plan_key}")

    # Receita no GA. Só chega aqui quem passou pelo ON CONFLICT DO NOTHING lá em
    # cima, então é um evento por pagamento real · reprocessar o mesmo pagamento
    # sai como "duplicate" antes deste ponto. Em thread pelo mesmo motivo do
    # e-mail: o webhook do MercadoPago tem timeout, e esperar o Google responder
    # pra confirmar um pagamento seria trocar dinheiro por métrica.
    import threading

    from analytics import send_purchase

    threading.Thread(
        target=send_purchase,
        args=(ga_client_id, user_id_int, payment_id, plan_key, plan_info["title"], amount),
        daemon=True,
    ).start()

    # Email de confirmação de VIP (em thread separada para não atrasar a resposta)
    if user_email and user_name:
        import threading
        threading.Thread(
            target=_send_vip_email,
            args=(user_email, user_name, plan_key, expires_at),
            daemon=True,
        ).start()

    return {
        "status":     "activated",
        "payment_id": payment_id,
        "user_id":    user_id_int,
        "plan":       plan_key,
        "amount":     amount,
        "expires_at": expires_at,
        "user_email": user_email,
        "user_name":  user_name,
    }


# Só é assinatura do site o pagamento cujo external_reference tem a forma que
# `create_preference` monta. A conta do MercadoPago é a mesma usada para a vida
# pessoal e tem milhares de transferências no meio; sem esse filtro a
# reconciliação tentaria "ativar VIP" para cada uma delas.
def _e_assinatura(payment: dict) -> bool:
    ref = str(payment.get("external_reference") or "")
    partes = ref.split(":", 1)
    return len(partes) == 2 and partes[0].isdigit() and partes[1] in PLANS


def _search_subscription_payments(sdk, begin: str, max_pages: int = 20) -> list[dict]:
    """Assinaturas aprovadas na conta do MercadoPago desde `begin` (ex.: 'NOW-30DAYS').

    É a rede de segurança: independe de o webhook ter chegado, porque pergunta
    ao MercadoPago o que ele tem, e não o que nos foi entregue.
    """
    LIMIT = 50
    encontrados: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        resposta = (sdk.payment().search(filters={
            "sort":       "date_created",
            "criteria":   "desc",
            "range":      "date_created",
            "begin_date": begin,
            "end_date":   "NOW",
            "status":     "approved",
            "limit":      LIMIT,
            "offset":     offset,
        }) or {}).get("response") or {}
        pagina = resposta.get("results") or []
        encontrados.extend(p for p in pagina if _e_assinatura(p))
        if len(pagina) < LIMIT:
            break
        offset += LIMIT
    return encontrados


def _search_user_payments(sdk, user_id: int) -> list[dict]:
    """Assinaturas aprovadas de UM usuário, por busca exata de external_reference.

    Consulta direta em vez de varrer a janela de datas: a conta tem milhares de
    pagamentos que não são do site, e a varredura poderia paginar sem nunca
    chegar no que interessa. São quatro consultas exatas, uma por plano.

    Timeout curto porque este caminho roda dentro do login e do retorno do
    checkout: MercadoPago lento não pode virar tela travada. Se estourar, quem
    resolve é a camada seguinte (webhook, ou o botão do /admin).
    """
    from mercadopago.config import RequestOptions

    opcoes = RequestOptions(connection_timeout=6)
    encontrados: list[dict] = []
    for plano in PLANS:
        resposta = (sdk.payment().search(
            filters={"external_reference": f"{user_id}:{plano}", "status": "approved"},
            request_options=opcoes,
        ) or {}).get("response") or {}
        encontrados.extend(p for p in (resposta.get("results") or []) if _e_assinatura(p))
    return encontrados


def _reconcile(begin: str, source: str, user_id: int | None = None) -> dict:
    """Reprocessa no banco toda assinatura aprovada que o MercadoPago conhece.

    Quem já está em `payments` cai no ON CONFLICT e não mexe em nada, então
    rodar duas vezes é inofensivo.
    """
    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        raise HTTPException(500, "MERCADOPAGO_ACCESS_TOKEN não configurado")

    sdk = mercadopago.SDK(access_token)
    try:
        pagamentos = (_search_user_payments(sdk, user_id) if user_id is not None
                      else _search_subscription_payments(sdk, begin))
    except Exception as e:
        logger.error("[PAYMENTS] Falha ao consultar o MercadoPago: %s", e)
        raise HTTPException(502, "Não foi possível consultar o MercadoPago agora.")

    ativados, ja_tinha, falhas = [], 0, []
    for pagamento in pagamentos:
        resultado = _apply_approved_payment(pagamento, source)
        if resultado["status"] == "activated":
            ativados.append({
                "payment_id": resultado["payment_id"],
                "user_id":    resultado["user_id"],
                "plan":       resultado["plan"],
                "amount":     resultado["amount"],
                "email":      resultado.get("user_email"),
            })
        elif resultado["status"] == "duplicate":
            ja_tinha += 1
        else:
            falhas.append({"payment_id": resultado["payment_id"], "detail": resultado.get("detail", "")})

    return {
        "encontrados":  len(pagamentos),
        "ativados":     ativados,
        "ja_registrados": ja_tinha,
        "falhas":       falhas,
    }


def try_activate_pending(user_id: int) -> dict | None:
    """Ativa o VIP de quem foi pro MercadoPago e ainda está sem acesso.

    Chamada no login, que é o único momento recorrente que este backend tem
    desde que o scheduler saiu · mesmo motivo do aviso de plano expirando em
    routers/auth.py. Fecha o caso que nenhuma outra camada pega: pagou por
    boleto ou Pix, fechou o navegador, o webhook falhou, e a pessoa só volta
    dias depois. Quando ela volta, entra VIP.

    Nunca levanta exceção: nada aqui pode derrubar um login.
    """
    try:
        resultado = _reconcile("NOW-30DAYS", "login", user_id=user_id)
        ativados = resultado["ativados"]
        return ativados[0] if ativados else None
    except Exception as e:
        logger.warning("[LOGIN] Falha ao conferir pagamento pendente do user %s: %s", user_id, e)
        return None


class CreatePreferenceBody(BaseModel):
    plan: str
    # Cookie `_ga` cru, lido pelo front. Vem do navegador, então é tratado como
    # entrada não confiável: só o formato conhecido é aceito (ver parse_ga_cookie)
    # e o resto vira string vazia.
    ga_cookie: Optional[str] = None


@router.post("/create")
def create_preference(body: CreatePreferenceBody, current_user: dict = Depends(get_current_user)):
    _check_rate("create_pref", current_user["id"], 6)
    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        raise HTTPException(500, "MERCADOPAGO_ACCESS_TOKEN não configurado")

    plan_info = PLANS.get(body.plan)
    if not plan_info:
        raise HTTPException(400, "Plano inválido. Use: mensal, trimestral, semestral ou anual")

    sdk = mercadopago.SDK(access_token)
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    backend_url  = os.getenv("BACKEND_URL",  "http://localhost:8000")

    preference_data = {
        "items": [{
            "title":       plan_info["title"],
            "description": f"Acesso VIP ao Pick IA, picks esportivos por IA por {plan_info['days']} dias",
            "quantity":    1,
            "unit_price":  plan_info["price"],
            "currency_id": "BRL",
            "category_id": "services",
        }],
        "payer": {"email": current_user.get("email", "")},
        "back_urls": {
            "success": f"{frontend_url}/checkout/sucesso",
            "failure": f"{frontend_url}/checkout/falha",
            "pending": f"{frontend_url}/checkout/pendente",
        },
        "auto_return": "approved",
        "external_reference": f"{current_user['sub']}:{body.plan}",
        "notification_url": f"{backend_url}/api/payments/webhook",
        "statement_descriptor": "PICK IA",
    }

    result = sdk.preference().create(preference_data)
    if result.get("status", 0) >= 400:
        logger.error("Erro MercadoPago ao criar preferência: %s", result.get("response"))
        raise HTTPException(500, "Erro ao processar pagamento. Tente novamente.")

    preference = result["response"]
    sandbox = os.getenv("MERCADOPAGO_SANDBOX", "true").lower() == "true"

    # Marca que esta pessoa foi pro MercadoPago. É o que faz o login saber em
    # quem vale a pena gastar consulta à API depois · ver try_activate_pending.
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            # O client_id só é gravado quando veio um cookie legível: se o
            # usuário voltar ao checkout com bloqueador ligado, o COALESCE
            # preserva o id capturado numa visita anterior em vez de apagá-lo.
            from analytics import parse_ga_cookie

            ga_client_id = parse_ga_cookie(body.ga_cookie or "")
            cur.execute(
                "UPDATE users SET checkout_started_at = NOW(), "
                "ga_client_id = COALESCE(NULLIF(%s, ''), ga_client_id) WHERE id = %s",
                (ga_client_id, current_user["id"]),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        # Não impede o pagamento: só reduz a chance de auto-reparo depois.
        logger.warning("[PAYMENTS] Falha ao marcar checkout do user %s: %s", current_user["id"], e)

    return {
        "init_point": preference.get("sandbox_init_point") if sandbox else preference.get("init_point"),
        "id": preference.get("id"),
    }


@router.post("/webhook")
async def webhook(request: Request):
    body = await request.body()

    try:
        data = __import__("json").loads(body)
    except Exception:
        raise HTTPException(400, "Payload inválido")

    # Verificação de assinatura HMAC do MercadoPago (obrigatória em qualquer ambiente ·
    # sem o secret configurado, o webhook fica sem autenticação nenhuma, então falha
    # fechado sempre, independente de APP_ENV)
    webhook_secret = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.error("[WEBHOOK] MERCADOPAGO_WEBHOOK_SECRET não configurado · bloqueando requisição")
        raise HTTPException(500, "Webhook não configurado")

    x_signature  = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")
    # O `data.id` assinado é o do QUERY STRING. O corpo é só fallback pro caso
    # de notificação sem query param -- foi usar o do corpo, e sem o ';' final
    # do template, que fez toda notificação legítima virar 403 aqui.
    data_id = request.query_params.get("data.id") or str(data.get("data", {}).get("id") or "")
    if not x_signature or not _verify_mp_signature(x_signature, x_request_id, data_id, webhook_secret):
        logger.warning("[WEBHOOK] Assinatura inválida · rejeitando requisição de %s (data.id=%s)",
                       request.client.host if request.client else "unknown", data_id)
        if _pode_registrar_recusa():
            _record_event("webhook", "assinatura_invalida", data_id)
        raise HTTPException(403, "Assinatura inválida")

    event_type = data.get("type") or request.query_params.get("type") or ""
    logger.info("[WEBHOOK] Evento recebido: type=%s data=%s", event_type, data.get("data"))

    if event_type != "payment":
        logger.info("[WEBHOOK] Ignorado (type=%s)", event_type)
        return {"status": "ignored"}

    access_token = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
    if not access_token:
        logger.error("[WEBHOOK] MERCADOPAGO_ACCESS_TOKEN não configurado")
        _record_event("webhook", "sem_token", data_id)
        return {"status": "error", "detail": "token missing"}

    payment_id = data.get("data", {}).get("id") or data_id
    if not payment_id:
        logger.warning("[WEBHOOK] payment_id ausente no payload")
        return {"status": "ignored"}

    logger.info("[WEBHOOK] Consultando pagamento id=%s", payment_id)
    sdk = mercadopago.SDK(access_token)
    payment = (sdk.payment().get(payment_id) or {}).get("response") or {}

    resultado = _apply_approved_payment(payment, "webhook")
    if resultado["status"] == "not_approved":
        logger.info("[WEBHOOK] Pagamento %s não aprovado · %s", payment_id, resultado["detail"])
        return {"status": "pending"}
    if resultado["status"] == "duplicate":
        return {"status": "ok", "detail": "already processed"}
    if resultado["status"] == "error":
        return {"status": "error", "detail": resultado["detail"]}

    return {"status": "ok"}


@router.post("/confirm")
def confirm_payment(current_user: dict = Depends(get_current_user)):
    """Ativa o VIP perguntando ao MercadoPago, sem depender do webhook.

    A tela de retorno do checkout chama isto. É o que impede a falha de hoje
    de se repetir do ponto de vista de quem pagou: mesmo com o webhook fora do
    ar, quem volta do MercadoPago sai da página já como VIP.

    Idempotente, e olha só os pagamentos do próprio usuário logado.
    """
    # Teto mais folgado que o de criar preferência: a tela de retorno repete a
    # chamada enquanto espera a confirmação, e travar justo aí é o pior momento.
    _check_rate("confirm", current_user["id"], 12)
    user_id = int(current_user["sub"])
    resultado = _reconcile("NOW-3DAYS", "checkout", user_id=user_id)

    ativados = resultado["ativados"]
    return {
        "activated":  len(ativados),
        "plan":       ativados[0]["plan"] if ativados else None,
        "already_ok": resultado["ja_registrados"] > 0,
    }


@router.get("/history")
def payment_history(current_user: dict = Depends(get_current_user)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT mp_payment_id, plan_key, amount, status, payment_method, expires_at, created_at
            FROM payments
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (current_user["sub"],),
        )
        rows = cur.fetchall()
        return [
            {
                "id":             r["mp_payment_id"],
                "plan":           r["plan_key"],
                "amount":         float(r["amount"]),
                "status":         r["status"],
                "payment_method": r["payment_method"],
                "expires_at":     r["expires_at"].isoformat() if r["expires_at"] else None,
                "created_at":     r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()
