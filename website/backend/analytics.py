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
import logging
import os

import requests

from runtime_env import is_production

logger = logging.getLogger(__name__)

GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "")
GA_API_SECRET     = os.getenv("GA_API_SECRET", "")
GA_ENDPOINT       = "https://www.google-analytics.com/mp/collect"


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
