"""Aviso de plano perto de vencer · sino + e-mail, disparado no login.

POR QUE NO LOGIN E NÃO NUM JOB
------------------------------
Este backend não tem mais scheduler: ele foi removido em 2026-08-01 por decisão
do usuário e nada roda sozinho aqui, em ambiente nenhum (ver o comentário longo
em main.py). Um aviso de vencimento não precisa de job: quem precisa ver é
justamente quem voltou a usar o site, e o login é o momento em que a pessoa
está olhando. Quem não entra também não renova.

O efeito colateral bom disso é que o aviso nunca chega para uma conta
abandonada · não gastamos e-mail com quem sumiu.

POR QUE FAIXAS E NÃO "TODO LOGIN"
---------------------------------
Sem faixa, alguém que entra três vezes por dia receberia três e-mails por dia
na última semana do plano. As faixas abaixo transformam a contagem contínua de
dias em três eventos discretos, e a `dedupe_key` garante um aviso por evento
mesmo com dez logins no mesmo dia.

Renovar muda `expires_at`, que entra na chave · o ciclo seguinte volta a
avisar normalmente, sem precisar limpar nada.
"""
from datetime import datetime, timezone

# Rótulo do plano na mensagem. O nome importa: "seu VIP vence" e "seu teste
# grátis acaba" pedem ações diferentes de quem lê, e o mesmo texto genérico
# ("seu plano") faria o trial parecer cobrança.
LABEL_PLANO = {"vip": "Plano VIP", "trial": "Teste grátis"}

# Faixas de aviso em dias restantes, da mais distante pra mais próxima.
# Três avisos no total: um pra decidir, um pra lembrar, um pro último dia.
FAIXAS = (3, 1, 0)

PLANOS_COM_VALIDADE = ("vip", "trial")


def dias_restantes(expires_at, agora: datetime | None = None) -> int | None:
    """Dias inteiros até o vencimento, ou None se não houver data.

    Trunca pra baixo de propósito: faltando 1,9 dia o usuário está no seu
    último dia cheio, e arredondar pra cima ("faltam 2 dias") daria uma
    folga que ele não tem.
    """
    if not expires_at:
        return None
    agora = agora or datetime.now(timezone.utc)
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return (exp - agora).days


def faixa_do_aviso(dias: int) -> int | None:
    """Faixa em que esses dias caem, ou None se ainda é cedo pra avisar."""
    for faixa in sorted(FAIXAS):
        if dias <= faixa:
            return faixa
    return None


def _texto_prazo(dias: int) -> str:
    if dias <= 0:
        return "expira hoje"
    if dias == 1:
        return "expira amanhã"
    return f"expira em {dias} dias"


def _mensagem(plan: str, dias: int) -> tuple[str, str]:
    """(título, corpo) do aviso, já com o nome do plano na frente."""
    label = LABEL_PLANO.get(plan, "Plano")
    titulo = f"Seu {label} {_texto_prazo(dias)}"
    if plan == "trial":
        corpo = ("Quando o teste acabar você volta pro plano free e perde os picks VIP, "
                 "múltiplas, alavancagem e o agente de futebol. Assine para continuar.")
    else:
        corpo = ("Renove para não perder os picks VIP, múltiplas, alavancagem, "
                 "mercados de faltas e defesas e o agente de futebol.")
    return titulo, corpo


def _html(nome: str, titulo: str, corpo: str, site_url: str) -> str:
    """Mesma casca visual dos outros e-mails (fundo escuro, cartão, topo verde)."""
    primeiro = (nome or "").split(" ")[0] or "tudo bem"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#111;border:1px solid #222;border-radius:16px;overflow:hidden;max-width:560px;width:100%;">
        <tr><td style="background:linear-gradient(135deg,#16a34a,#15803d);padding:28px 40px;text-align:center;">
          <h1 style="margin:0;color:#fff;font-size:24px;font-weight:900;letter-spacing:-0.5px;">
            Pick<span style="color:#bbf7d0;">IA</span>
          </h1>
        </td></tr>
        <tr><td style="padding:32px 40px;">
          <p style="margin:0 0 6px;color:#71717a;font-size:13px;">Olá, {primeiro}</p>
          <h2 style="margin:0 0 16px;color:#fff;font-size:20px;font-weight:800;">{titulo}</h2>
          <p style="margin:0 0 26px;color:#a1a1aa;font-size:15px;line-height:1.6;">{corpo}</p>
          <a href="{site_url}/checkout"
             style="display:inline-block;background:#16a34a;color:#fff;text-decoration:none;
                    padding:13px 26px;border-radius:10px;font-weight:800;font-size:15px;">
            Renovar agora
          </a>
        </td></tr>
        <tr><td style="padding:0 40px 32px;">
          <p style="margin:0;color:#52525b;font-size:12px;line-height:1.5;">
            Você recebeu este aviso porque tem uma assinatura ativa no Pick IA.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def avisar_plano_expirando(cur, user: dict, site_url: str,
                           enviar_email=None, agora: datetime | None = None) -> str | None:
    """Cria a notificação do sino e, uma vez por faixa, dispara o e-mail.

    Usa o cursor/transação do chamador (mesmo contrato de create_notification);
    quem chama é que faz o commit.

    `enviar_email` é injetado em vez de importado pra não criar ciclo com
    routers/auth.py, que é quem tem o `_send_email`. Passar None manda só a
    notificação · é o que o staging faz, pra não mandar e-mail de verdade
    para o usuário real do banco de produção.

    Retorna a dedupe_key quando avisou agora, None quando não havia o que
    avisar ou a faixa já tinha sido avisada.
    """
    plan = (user.get("plan") or "").lower()
    if plan not in PLANOS_COM_VALIDADE:
        return None

    dias = dias_restantes(user.get("expires_at"), agora=agora)
    if dias is None or dias < 0:
        # Já vencido não é aviso de vencimento: o login rebaixa pra free antes
        # de chegar aqui, e insistir seria oferecer renovação de algo que a
        # pessoa já perdeu (isso é outra conversa, não este aviso).
        return None

    faixa = faixa_do_aviso(dias)
    if faixa is None:
        return None

    exp = user["expires_at"]
    data_exp = exp.date() if hasattr(exp, "date") else exp
    chave = f"plano_expirando:{plan}:{data_exp}:{faixa}"

    # Existência antes de criar: create_notification faz upsert, então sozinho
    # ele não distingue "criei agora" de "já existia" -- e é essa distinção que
    # decide se o e-mail sai. Sem isso, todo login reenviaria o e-mail.
    cur.execute(
        "SELECT 1 FROM notifications WHERE user_id = %s AND dedupe_key = %s",
        (user["id"], chave),
    )
    if cur.fetchone():
        return None

    from routers.notifications import TYPE_PLAN_EXPIRING, create_notification

    titulo, corpo = _mensagem(plan, dias)
    create_notification(
        cur, user["id"], TYPE_PLAN_EXPIRING, titulo, chave,
        body=corpo, url="/checkout",
        payload={"plan": plan, "dias_restantes": dias, "expires_at": str(data_exp)},
    )

    if enviar_email:
        enviar_email(
            user["email"],
            titulo,
            f"{titulo}\n\n{corpo}\n\nRenove em {site_url}/checkout",
            _html(user.get("name") or "", titulo, corpo, site_url),
        )

    return chave
