"""Envio de SMS · usado só para o código de verificação de telefone.

Existe porque o telefone virou a chave de "1 conta por pessoa" quando o CPF
saiu do cadastro (18/08/2026), e um telefone que ninguém provou não segura
nada: dá pra digitar o número do vizinho. O SMS é o que transforma a coluna
`users.phone` em barreira de verdade.

Por que SMS e não WhatsApp: a política da Meta sobre o setor de apostas exige
autorização prévia por escrito e trata o assunto no nível da conta, não do
template · ver `website/scripts/whatsapp/README.md`. As bibliotecas não
oficiais (Baileys e parentes) resolveriam sem burocracia, mas OTP é o padrão
de tráfego mais fácil de flagrar e o preço de errar é o número banido de vez.
SMS custa centavos e não coloca o número da operação em risco.

Configuração (Railway):

    SMS_PROVIDER=comtele        # ou "log" (padrão)
    SMS_COMTELE_AUTH_KEY=...    # "Chave de API" no painel da Comtele
    SMS_SENDER=PickIA           # opcional, só aparece nos relatórios deles

Sem `SMS_PROVIDER=comtele` nada sai da máquina: o modo `log` escreve o código
no log e devolve sucesso, que é o que faz o fluxo inteiro ser testável em dev
sem gastar crédito nem precisar de chave.
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

_COMTELE_URL = "https://sms.comtele.com.br/api/v2/send"
_TIMEOUT_SEGS = 10.0


class SMSNaoEnviado(Exception):
    """Falha de envio que o chamador precisa mostrar pro usuário."""


def _so_digitos_br(telefone: str) -> str:
    """`+5511999998888` -> `11999998888`.

    A Comtele espera DDD + número, sem o código do país. O banco guarda E.164
    desde a normalização de `_validate_phone_br`, então a conversão é sempre
    tirar o `+55` da frente.
    """
    digitos = re.sub(r"\D", "", telefone or "")
    if digitos.startswith("55") and len(digitos) > 11:
        digitos = digitos[2:]
    return digitos


def provedor_ativo() -> str:
    return (os.getenv("SMS_PROVIDER") or "log").strip().lower()


def _enviar_comtele(telefone: str, texto: str) -> None:
    chave = (os.getenv("SMS_COMTELE_AUTH_KEY") or "").strip()
    if not chave:
        raise SMSNaoEnviado("SMS_COMTELE_AUTH_KEY não configurado.")

    corpo = {
        "Sender": (os.getenv("SMS_SENDER") or "PickIA").strip(),
        "Receivers": _so_digitos_br(telefone),
        "Content": texto,
    }
    try:
        resposta = httpx.post(
            _COMTELE_URL,
            json=corpo,
            headers={"auth-key": chave},
            timeout=_TIMEOUT_SEGS,
        )
    except Exception as e:
        raise SMSNaoEnviado("Não foi possível falar com a operadora.") from e

    if resposta.status_code >= 400:
        # O corpo pode vir vazio (o 401 deles não traz JSON), então o status é
        # o único dado garantido pro log.
        logger.warning("[SMS] Comtele respondeu %s: %s", resposta.status_code, resposta.text[:200])
        raise SMSNaoEnviado("A operadora recusou o envio.")

    try:
        dados = resposta.json()
    except Exception:
        dados = {}
    # HTTP 200 com Success=false acontece (número inválido, crédito acabado).
    # Sem esta checagem o usuário ficaria esperando um SMS que nunca saiu.
    if dados and dados.get("Success") is False:
        logger.warning("[SMS] Comtele recusou: %s", str(dados.get("Message"))[:200])
        raise SMSNaoEnviado("A operadora recusou o envio.")


def enviar_sms(telefone: str, texto: str) -> None:
    """Envia e levanta `SMSNaoEnviado` se não deu.

    Não retorna bool de propósito: um `False` ignorado viraria "código
    enviado" na tela sem SMS nenhum na mão do usuário.
    """
    provedor = provedor_ativo()
    if provedor == "comtele":
        _enviar_comtele(telefone, texto)
        return
    # Modo de desenvolvimento. O código vai pro log justamente pra dar pra
    # concluir o fluxo sem provedor configurado.
    logger.info("[SMS:log] Para %s · %s", telefone, texto)
