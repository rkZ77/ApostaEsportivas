"""Envio de WhatsApp · aviso em tempo real e disparo de campanha.

IRMAO DE `sms.py`, E A DIFERENCA IMPORTA
----------------------------------------
O SMS existe pra UMA coisa: provar o telefone no cadastro. Ele nunca foi canal
de aviso porque o codigo de verificacao e o unico trafego que a operadora
cobra barato e ninguem denuncia.

Este modulo e' o outro lado: aviso que a pessoa PEDIU. A regra de ouro do
`website/scripts/whatsapp/README.md` continua valendo palavra por palavra ·
sem opt-in nao sai mensagem, e a politica da Meta pra vertical de aposta trata
o assunto no nivel da CONTA, nao do template. O que mudou e' que agora existe
o opt-in: o usuario liga o aviso no proprio perfil, com o telefone ja
verificado por SMS, e pode desligar na mesma tela.

O QUE E' TEMPLATE E O QUE E' TEXTO LIVRE
----------------------------------------
A Meta so' deixa iniciar conversa com TEMPLATE aprovado. Texto livre so' vale
dentro da janela de 24h depois de a pessoa responder. Por isso:

  * aviso em tempo real (pick ao vivo) sai como template · `enviar_template`;
  * resposta dentro da janela sai como texto · `enviar_texto`.

Se o template nao estiver aprovado, a API devolve erro e o aviso simplesmente
nao sai. Isso e' melhor do que o contrario: mensagem fora de template e' o que
faz o numero ser marcado, e o numero e' um so'.

CONFIGURACAO (Railway)

    WHATSAPP_PROVIDER=cloud          # ou "log" (padrao)
    WHATSAPP_TOKEN=...               # token permanente do app da Meta
    WHATSAPP_PHONE_ID=...            # Phone number ID, nao o numero
    WHATSAPP_API_VERSION=v21.0       # opcional

Sem `WHATSAPP_PROVIDER=cloud` nada sai da maquina. O modo `log` escreve a
mensagem no log e devolve sucesso, que e' o que faz o fluxo inteiro ser
testavel em dev · mesmo desenho do `sms.py`, pelo mesmo motivo.
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SEGS = 10.0

#: Templates que o produto usa. O nome tem que bater com o que esta aprovado
#: no painel da Meta · nome errado devolve 132001 e a mensagem nao sai.
#: O catalogo com o texto de cada um vive em website/scripts/whatsapp/README.md.
TEMPLATE_AO_VIVO = "pick_ao_vivo_v1"
TEMPLATE_PICKS_DO_DIA = "picks_do_dia_v1"
#: Green e red sao templates SEPARADOS de proposito (decisao do README): o
#: marcador vira texto fixo em vez de variavel, e o red pode ter tom sobrio em
#: vez de reaproveitar a frase comemorativa do green.
TEMPLATE_RESULTADO_GREEN = "resultado_green_v1"
TEMPLATE_RESULTADO_RED = "resultado_red_v1"


class WhatsAppNaoEnviado(Exception):
    """Falha de envio. Quem chama decide se mostra ou se so' loga."""


def _e164(telefone: str) -> str:
    """`(11) 99999-8888` -> `5511999998888`.

    A Cloud API quer so' digitos com codigo do pais. O banco ja guarda E.164
    desde `_validate_phone_br`, entao aqui e' so' tirar o `+` · o `55` na
    frente cobre a linha antiga que porventura tenha ficado sem ele.
    """
    digitos = re.sub(r"\D", "", telefone or "")
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos


def provedor_ativo() -> str:
    return (os.getenv("WHATSAPP_PROVIDER") or "log").strip().lower()


def whatsapp_configurado() -> bool:
    """Existe provedor de verdade neste ambiente?

    `log` conta como NAO configurado de proposito, igual no SMS: tratar o modo
    de desenvolvimento como disponivel faria o /admin dizer que 300 avisos
    sairam quando nenhum saiu.
    """
    return provedor_ativo() == "cloud" and bool(
        (os.getenv("WHATSAPP_TOKEN") or "").strip()
        and (os.getenv("WHATSAPP_PHONE_ID") or "").strip()
    )


def _url() -> str:
    versao = (os.getenv("WHATSAPP_API_VERSION") or "v21.0").strip()
    phone_id = (os.getenv("WHATSAPP_PHONE_ID") or "").strip()
    return f"https://graph.facebook.com/{versao}/{phone_id}/messages"


def _postar(corpo: dict, telefone: str) -> None:
    token = (os.getenv("WHATSAPP_TOKEN") or "").strip()
    if not token:
        raise WhatsAppNaoEnviado("WHATSAPP_TOKEN nao configurado.")
    try:
        resposta = httpx.post(
            _url(),
            json=corpo,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT_SEGS,
        )
    except Exception as e:
        raise WhatsAppNaoEnviado("Nao foi possivel falar com a Meta.") from e

    if resposta.status_code >= 400:
        # O corpo de erro da Meta traz `error.code`, e o codigo e' o que
        # diferencia "template nao aprovado" de "numero bloqueou a gente".
        # Sem ele no log, toda falha vira a mesma linha inutil.
        logger.warning("[WA] Meta respondeu %s: %s", resposta.status_code,
                       resposta.text[:300])
        raise WhatsAppNaoEnviado("A Meta recusou o envio.")


def enviar_template(telefone: str, template: str, variaveis: list | None = None,
                    idioma: str = "pt_BR") -> None:
    """Inicia conversa. E' o unico caminho valido fora da janela de 24h.

    `variaveis` sao os `{{1}}`, `{{2}}` do corpo aprovado, NA ORDEM. Trocar a
    ordem aqui sem trocar no painel da Meta manda o nome do jogo pro lugar da
    odd, e a mensagem sai errada sem dar erro nenhum.
    """
    if provedor_ativo() != "cloud":
        logger.info("[WA:log] Template %s para %s · %s", template, telefone, variaveis)
        return

    componentes = []
    if variaveis:
        componentes.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in variaveis],
        })
    _postar({
        "messaging_product": "whatsapp",
        "to": _e164(telefone),
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": idioma},
            **({"components": componentes} if componentes else {}),
        },
    }, telefone)


def enviar_texto(telefone: str, texto: str) -> None:
    """Texto livre. So' funciona DENTRO da janela de 24h.

    Existe porque a resposta a quem escreveu pra gente nao precisa de template,
    e forcar template ali gastaria aprovacao a toa. Fora da janela a Meta
    recusa com 131047, e e' correto que recuse.
    """
    if provedor_ativo() != "cloud":
        logger.info("[WA:log] Texto para %s · %s", telefone, texto[:120])
        return
    _postar({
        "messaging_product": "whatsapp",
        "to": _e164(telefone),
        "type": "text",
        "text": {"preview_url": True, "body": texto},
    }, telefone)
