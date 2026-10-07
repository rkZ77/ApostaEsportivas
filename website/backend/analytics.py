"""Receita no Google Analytics, pelo lado do servidor.

POR QUE NÃO NO NAVEGADOR. O caminho óbvio seria disparar `gtag('event',
'purchase')` na página de retorno do checkout. Ele perde dinheiro de duas
formas, e as duas são enviesadas:

  1. O MercadoPago leva o usuário pra fora do site. Quem paga por PIX
     costuma fechar a aba na tela de confirmação e nunca volta pro
     /checkout/sucesso -- o pagamento acontece, o evento não.
  2. Público mobile e nicho de aposta tem taxa alta de bloqueador. O que o
     bloqueador derruba não é uma amostra aleatória da base.

Somando os dois, o relatório mostraria menos receita do que existe, e menos
justamente nos canais que mais convertem. Pior que não medir.

Aqui o evento sai de `_apply_approved_payment`, que é o único ponto onde um
pagamento vira VIP (webhook, retorno do checkout e os dois botões do admin
passam todos por lá) e que já é idempotente por `mp_payment_id`. Um pagamento,
um evento, independente de o usuário ter voltado pro site.

O PREÇO DISSO é o `client_id`: sem ele o GA registra a receita como sessão
nova e direta, e a pergunta que justifica o trabalho todo -- de qual canal veio
quem paga -- fica sem resposta. Por isso o checkout captura o `_ga` do
navegador e guarda em `users.ga_client_id`; este módulo só o lê de volta.
"""
import hashlib
import logging
import os
import re
import time

import requests

from runtime_env import is_production

logger = logging.getLogger(__name__)

GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "")
GA_API_SECRET     = os.getenv("GA_API_SECRET", "")
GA_ENDPOINT       = "https://www.google-analytics.com/mp/collect"

# Meta (API de Conversões). O pixel do navegador fica no index.html; aqui sai
# só o Purchase, pelo mesmo motivo do purchase do GA (ver docstring do módulo).
# O token da API de Conversões nasce dentro de UM pixel no Gerenciador de
# Eventos. O site tem dois (ver index.html); a variável aceita lista separada
# por vírgula, mas só vale incluir pixel a que o token tem acesso. O padrão é
# o pixel onde o token foi gerado (2026-10-07).
META_PIXEL_IDS     = [p.strip() for p in os.getenv("META_PIXEL_ID", "4622246931353146").split(",") if p.strip()]
META_CAPI_TOKEN    = os.getenv("META_CAPI_TOKEN", "")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v24.0")

# `_fbp` e `_fbc` têm formato fixo: fb.<subdominio>.<timestamp>.<resto>. Vêm
# do navegador, então o que não bate com isso é descartado em vez de repassado.
_COOKIE_META_RE = re.compile(r"^fb\.\d\.\d{10,13}\.[A-Za-z0-9_\-.]{1,500}$")


def parse_ga_cookie(raw: str) -> str:
    """Extrai o client_id do cookie `_ga`.

    O formato é `GA1.1.<client_id>`, e o client_id em si tem um ponto no meio
    (`1234567890.1699999999`) -- então o corte é pelos dois primeiros campos,
    não por split('.') simples, que devolveria só metade do id.
    """
    parts = (raw or "").strip().split(".")
    if len(parts) < 4:
        return ""
    return f"{parts[2]}.{parts[3]}"


def send_purchase(client_id: str, user_id: int, payment_id: str,
                  plan_key: str, plan_title: str, amount: float) -> None:
    """Manda um `purchase` pro GA4 via Measurement Protocol.

    Nunca levanta exceção: é chamado depois do commit que ativa o VIP, e
    analytics não pode derrubar (nem parecer que derrubou) um pagamento que
    já entrou.
    """
    if not (GA_MEASUREMENT_ID and GA_API_SECRET):
        return
    # Só produção. O noprod aponta pro banco de produção e um teste de
    # pagamento lá dentro contaminaria o relatório real com receita que não
    # existe · mesmo motivo pelo qual `is_production` existe pra cota de API.
    if not is_production():
        logger.info("[GA] Fora de produção · purchase de %s não enviado.", payment_id)
        return
    if not client_id:
        # Sem client_id o evento entraria como sessão nova e direta, inflando
        # "Direct" e roubando o crédito do canal que de fato trouxe a venda.
        # Registrar receita errada é pior do que não registrar.
        logger.info("[GA] Sem client_id pro user %s · purchase de %s não enviado.", user_id, payment_id)
        return

    payload = {
        "client_id": client_id,
        # user_id interno, nunca e-mail ou CPF: mandar PII pro GA viola os
        # termos de uso e pode derrubar a propriedade inteira.
        "user_id": str(user_id),
        "non_personalized_ads": True,
        "events": [{
            "name": "purchase",
            "params": {
                # transaction_id é o que faz o GA descartar duplicata se este
                # pagamento for reprocessado por outro caminho.
                "transaction_id": str(payment_id),
                "value":          round(float(amount), 2),
                "currency":       "BRL",
                "items": [{
                    "item_id":       plan_key,
                    "item_name":     plan_title,
                    "item_category": "assinatura",
                    "price":         round(float(amount), 2),
                    "quantity":      1,
                }],
            },
        }],
    }

    try:
        resp = requests.post(
            GA_ENDPOINT,
            params={"measurement_id": GA_MEASUREMENT_ID, "api_secret": GA_API_SECRET},
            json=payload,
            timeout=5,
        )
        # O Measurement Protocol responde 204 pra praticamente tudo, inclusive
        # payload inválido. Erro de formato só aparece no endpoint /debug, então
        # 2xx aqui significa "chegou", não "está correto".
        if resp.status_code >= 300:
            logger.warning("[GA] purchase %s recusado: HTTP %s", payment_id, resp.status_code)
        else:
            logger.info("[GA] purchase %s enviado · R$ %.2f", payment_id, amount)
    except Exception as e:
        logger.warning("[GA] Falha ao enviar purchase %s: %s", payment_id, e)


def parse_meta_cookie(raw: str) -> str:
    """Devolve o `_fbp`/`_fbc` se tiver o formato do Meta, senão string vazia."""
    raw = (raw or "").strip()
    return raw if _COOKIE_META_RE.match(raw) else ""


def _sha256(valor: str) -> str:
    return hashlib.sha256(valor.strip().lower().encode("utf-8")).hexdigest()


def _meta_user_data(user_id: int, email: str, nome: str, fbp: str, fbc: str,
                    ip: str, user_agent: str) -> dict:
    """Monta o `user_data` da API de Conversões.

    E-mail, nome e id vão em SHA-256, normalizados (minúsculo, sem espaço nas
    pontas) · é o formato que o Meta exige pra casar com a conta do Facebook.
    IP, user agent, fbp e fbc vão crus, como a documentação pede. Conta
    excluída tem e-mail no domínio `.invalid` (ver auth.py) e não manda e-mail.
    """
    dados: dict = {"external_id": [_sha256(str(user_id))]}
    if email and not email.lower().endswith(".invalid"):
        dados["em"] = [_sha256(email)]
    partes = (nome or "").split()
    if partes:
        dados["fn"] = [_sha256(partes[0])]
        if len(partes) > 1:
            dados["ln"] = [_sha256(partes[-1])]
    if fbp:
        dados["fbp"] = fbp
    if fbc:
        dados["fbc"] = fbc
    if ip:
        dados["client_ip_address"] = ip
    if user_agent:
        dados["client_user_agent"] = user_agent
    return dados


def send_meta_purchase(user_id: int, payment_id: str, plan_key: str, plan_title: str,
                       amount: float, email: str, nome: str, fbp: str, fbc: str,
                       ip: str, user_agent: str) -> None:
    """Manda um `Purchase` pra API de Conversões do Meta.

    Mesmas regras do `send_purchase`: nunca levanta exceção e só roda em
    produção. Diferente do GA, não depende de cookie: sem `fbp` o Meta ainda
    casa a venda pelo e-mail, só que com nota de correspondência menor.
    """
    if not META_CAPI_TOKEN:
        return
    if not is_production():
        logger.info("[META] Fora de produção · Purchase de %s não enviado.", payment_id)
        return

    valor = round(float(amount), 2)
    frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
    evento = {
        "event_name": "Purchase",
        "event_time": int(time.time()),
        # event_id é a chave de deduplicação do Meta: se o mesmo pagamento for
        # reprocessado por outro caminho, ou se um dia o navegador também
        # mandar Purchase, a venda conta uma vez só.
        "event_id": f"purchase-{payment_id}",
        "action_source": "website",
        "user_data": _meta_user_data(user_id, email, nome, fbp, fbc, ip, user_agent),
        "custom_data": {
            "currency": "BRL",
            "value": valor,
            "order_id": str(payment_id),
            "content_ids": [plan_key],
            "content_name": plan_title,
            "content_type": "product",
            "contents": [{"id": plan_key, "quantity": 1, "item_price": valor}],
        },
    }
    if frontend_url:
        evento["event_source_url"] = f"{frontend_url}/checkout"

    for pixel_id in META_PIXEL_IDS:
        try:
            resp = requests.post(
                f"https://graph.facebook.com/{META_GRAPH_VERSION}/{pixel_id}/events",
                params={"access_token": META_CAPI_TOKEN},
                json={"data": [evento]},
                timeout=5,
            )
            # Ao contrário do GA, o Meta valida o payload e responde 400 com o
            # motivo. O corpo vai pro log porque é ali que aparece token vencido
            # ou token sem acesso a este pixel.
            if resp.status_code >= 300:
                logger.warning("[META] Purchase %s recusado no pixel %s: HTTP %s %s",
                               payment_id, pixel_id, resp.status_code, resp.text[:300])
            else:
                logger.info("[META] Purchase %s enviado ao pixel %s · R$ %.2f",
                            payment_id, pixel_id, valor)
        except Exception as e:
            logger.warning("[META] Falha ao enviar Purchase %s ao pixel %s: %s",
                           payment_id, pixel_id, e)
