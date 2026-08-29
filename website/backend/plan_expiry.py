"""Avisos de plano · sino + e-mail, pendurados no login e no /auth/me.

POR QUE NA REQUISIÇÃO E NÃO NUM JOB
-----------------------------------
Este backend não tem mais scheduler: ele foi removido em 2026-08-01 por decisão
do usuário e nada roda sozinho aqui, em ambiente nenhum (ver o comentário longo
em main.py). Um aviso de vencimento não precisa de job: quem precisa ver é
justamente quem voltou a usar o site, e o login é o momento em que a pessoa
está olhando. Quem não entra também não renova.

O login sozinho não bastava: o cookie de sessão dura 30 dias e o uso é
mobile-first, então o assinante mensal que deixa o app aberto pode atravessar
o ciclo inteiro sem digitar a senha de novo · e atravessava sem receber um
único e-mail de renovação. Por isso o aviso também roda no /auth/me, que é a
rota que toda visita chama. A `dedupe_key` já garantia um aviso por faixa,
então repetir o gatilho em outra rota não repete a mensagem: só amplia o
alcance.

O efeito colateral bom disso é que o aviso nunca chega para uma conta
abandonada · não gastamos e-mail com quem sumiu.

POR QUE FAIXAS E NÃO "TODO LOGIN"
---------------------------------
Sem faixa, alguém que entra três vezes por dia receberia três e-mails por dia
na última semana do plano. As faixas abaixo transformam a contagem contínua em
poucos eventos discretos, e a `dedupe_key` garante um aviso por evento mesmo
com dez logins no mesmo dia.

Renovar muda `expires_at`, que entra na chave · o ciclo seguinte volta a
avisar normalmente, sem precisar limpar nada.

AS FAIXAS SÃO EM HORAS, E POR PLANO (2026-08-28)
------------------------------------------------
Elas eram `(3, 1, 0)` DIAS, iguais pros dois planos, e comparadas contra
`dias_restantes`, que trunca pra baixo. As duas escolhas juntas produziram o
defeito que o usuário viu: **o e-mail de "seu teste expira" saía no instante
em que o teste era criado.**

O teste dura 2 dias. No momento da ativação faltam 47h59, e:

  · truncado, isso vira `1` · a contagem diz "um dia" quando ainda há dois;
  · a faixa mais distante era 3 dias, e 1 <= 3, então ela disparava ali mesmo.

Ou seja: a pessoa confirmava o e-mail, ganhava o teste e recebia na mesma hora
um aviso de que ele estava acabando. O mesmo vale pro VIP curto (o crédito de
indicação dá 1 dia).

A correção é medir em HORAS pra decidir, e continuar contando em DIAS pra
escrever · o texto fala do último dia cheio da pessoa, e ali truncar é o certo.
E a lista passa a ser por plano, porque uma faixa de 3 dias não cabe num plano
de 2: a faixa mais distante de um plano nunca pode ser maior que o próprio
plano, senão ela nasce vencida.

O usuário pediu explicitamente o aviso de 1 dia no teste (28/08). São dois
eventos ali: um dia inteiro antes, e as últimas horas.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone

from email_templates import NOTA_PLANO_ENCERRADO, aviso_de_plano_html, url_logo

logger = logging.getLogger(__name__)

# Rótulo do plano na mensagem. O nome importa: "seu VIP vence" e "seu teste
# grátis acaba" pedem ações diferentes de quem lê, e o mesmo texto genérico
# ("seu plano") faria o trial parecer cobrança.
LABEL_PLANO = {"vip": "Plano VIP", "trial": "Teste grátis"}

#: Faixas de aviso em HORAS restantes, por plano, da mais distante pra mais
#: próxima. Ver o cabeçalho: em horas porque o dia truncado disparava a faixa
#: no ato da criação, e por plano porque o teste dura 2 dias e não cabe numa
#: faixa de 3.
#:
#:   VIP    72h (decidir) · 24h (lembrar) · 6h (último aviso)
#:   teste  24h (é o aviso de 1 dia que o usuário pediu) · 6h
FAIXAS_POR_PLANO = {
    "vip":   (72, 24, 6),
    "trial": (24, 6),
}

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


def horas_restantes(expires_at, agora: datetime | None = None) -> float | None:
    """Horas até o vencimento, SEM truncar · é o número que decide a faixa.

    Separado de `dias_restantes` de propósito: aquele arredonda pra baixo pra
    escrever a frase certa ("seu último dia cheio"), e usar o mesmo número pra
    decidir era o que fazia um plano de 2 dias nascer dentro da faixa de 1.
    """
    if not expires_at:
        return None
    agora = agora or datetime.now(timezone.utc)
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return (exp - agora).total_seconds() / 3600


def faixa_do_aviso(horas: float, plan: str = "vip") -> int | None:
    """Faixa em que essas horas caem, ou None se ainda é cedo pra avisar."""
    for faixa in sorted(FAIXAS_POR_PLANO.get(plan, FAIXAS_POR_PLANO["vip"])):
        if horas <= faixa:
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

    horas = horas_restantes(user.get("expires_at"), agora=agora)
    if horas is None or horas < 0:
        # Já vencido não é aviso de vencimento: o login rebaixa pra free antes
        # de chegar aqui, e insistir seria oferecer renovação de algo que a
        # pessoa já perdeu (isso é outra conversa, não este aviso).
        return None

    # Decide em horas, escreve em dias · ver o cabeçalho.
    faixa = faixa_do_aviso(horas, plan)
    if faixa is None:
        return None
    dias = dias_restantes(user.get("expires_at"), agora=agora) or 0

    exp = user["expires_at"]
    data_exp = exp.date() if hasattr(exp, "date") else exp
    # A faixa entra na chave com o "h": ela mudou de unidade, e uma chave nova
    # evita que um aviso de 3 DIAS já gravado bloqueie o de 72 HORAS.
    chave = f"plano_expirando:{plan}:{data_exp}:{faixa}h"

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
            aviso_de_plano_html(
                user.get("name") or "", titulo, corpo, site_url, url_logo(site_url)
            ),
        )

    return chave


# ─────────────────────────────────────────────────────────────────────────────
# ACESSO ENCERRADO · o teste acabou, ou a assinatura venceu
# ─────────────────────────────────────────────────────────────────────────────
#
# O aviso acima é de plano PERTO de vencer, e ele sai de cena quando o prazo
# passa ("já vencido não é aviso de vencimento"). O que vem abaixo é a outra
# conversa que aquele comentário deixou em aberto: acabou, e a pessoa está de
# volta no free sem ter decidido nada.
#
# Até 23/08/2026 só o teste grátis avisava. O VIP era rebaixado em silêncio,
# com o argumento de que renovação já tinha o aviso de faixa · mas aquele aviso
# é de ANTES, e quem não entrou no site naqueles três dias não leu nenhum dos
# dois. O assinante que some por uma semana voltava pro free sem nunca ver uma
# frase sobre isso, e o único texto que sobrava pra ele era o convite genérico
# de quem nunca assinou ("você está no plano gratuito"). Perder um assinante
# não é a mesma coisa que nunca ter tido um, e a tela não pode falar como se
# fosse.
#
# A CHAVE DO TESTE É FIXA, A DO VIP TEM DATA
# ------------------------------------------
# Regras diferentes porque os fatos são diferentes. O teste acontece uma vez na
# vida da conta (grava `trial_used = TRUE` e nunca é reativado, ver
# routers/auth.py::_ativar_trial_se_elegivel), então a chave fixa entrega o
# "uma vez só" de graça. VIP vence a cada ciclo: com chave fixa, a segunda
# expiração cairia no ON CONFLICT DO UPDATE de create_notification, que
# preserva `read_at` de propósito · a notificação voltaria já marcada como
# lida, e o popup nunca mais abriria pra quem assinou de novo e deixou vencer
# de novo. Com a data do vencimento na chave, cada ciclo é um evento próprio.
DEDUPE_TRIAL_ENCERRADO = "trial_encerrado"


def dedupe_vip_encerrado(data_exp) -> str:
    """Chave do aviso de VIP vencido · uma por ciclo de assinatura."""
    return f"vip_encerrado:{data_exp}"


# (título, corpo, rótulo do botão) de cada encerramento. A lista de perdas é a
# mesma nos dois porque o acesso perdido é o mesmo · o que muda é o verbo:
# quem testou ASSINA, quem assinou RENOVA.
_PERDAS = ("os picks VIP, as múltiplas, a alavancagem, os mercados de faltas "
           "e defesas e o agente de futebol")

ENCERRAMENTO = {
    "trial": (
        "Seu teste grátis acabou",
        f"Você voltou pro plano free e {_PERDAS} ficaram para trás. "
        "Assine para destravar tudo de novo.",
        "Assinar o VIP",
    ),
    "vip": (
        "Seu VIP acabou",
        f"Sua assinatura venceu e a conta voltou pro plano free: {_PERDAS} "
        "ficaram para trás. Renove para destravar tudo de novo.",
        "Renovar o VIP",
    ),
}


def _avisar_acesso_encerrado(cur, user: dict, plan: str, chave: str,
                             enviar_email=None, site_url: str = "") -> None:
    """Sino + e-mail + gatilho do popup de conversão. Não commita: quem chama
    é dono da transação (mesmo contrato de create_notification).

    Nunca propaga exceção. Esta função roda pendurada no login, no refresh e no
    /auth/me; uma falha aqui derrubaria a entrada da pessoa no site por causa
    de um aviso, que é a troca errada.

    O e-mail sai só quando a notificação é NOVA. create_notification faz upsert
    e sozinho não distingue "criei agora" de "já existia" · sem a checagem, uma
    corrida entre duas requisições da mesma conta (o front chama /auth/me ao
    montar e ao voltar pra aba) mandaria o mesmo e-mail duas vezes.
    """
    titulo, corpo, cta = ENCERRAMENTO[plan]

    try:
        cur.execute(
            "SELECT 1 FROM notifications WHERE user_id = %s AND dedupe_key = %s",
            (user["id"], chave),
        )
        if cur.fetchone():
            return

        from routers.notifications import (TYPE_TRIAL_ENDED, TYPE_VIP_ENDED,
                                           create_notification)
        create_notification(
            cur, user["id"],
            TYPE_TRIAL_ENDED if plan == "trial" else TYPE_VIP_ENDED,
            titulo, chave, body=corpo, url="/checkout",
        )
    except Exception:
        # Sem linha no sino não se manda e-mail: o dedupe mora na tabela, e um
        # e-mail sem ela é um e-mail que pode repetir na próxima requisição.
        return

    if not enviar_email or not user.get("email"):
        return
    try:
        enviar_email(
            user["email"],
            titulo,
            f"{titulo}\n\n{corpo}\n\nDestrave em {site_url}/checkout",
            aviso_de_plano_html(user.get("name") or "", titulo, corpo, site_url,
                                url_logo(site_url), cta=cta,
                                nota=NOTA_PLANO_ENCERRADO),
        )
    except Exception:
        pass


def expirar_plano_vencido(cur, user: dict, agora: datetime | None = None,
                          enviar_email=None, site_url: str = "") -> bool:
    """Rebaixa pra free quem tem VIP/trial vencido. True quando rebaixou agora.

    REGRA ÚNICA PROS TRÊS CAMINHOS que avaliam isso -- login, refresh e
    /auth/me. Eram três cópias do mesmo if, e em 2026-08-20 elas ganharam uma
    responsabilidade a mais (avisar o fim do acesso): manter as três em dia na
    mão é como uma delas fica pra trás em silêncio, e a que ficasse seria
    justamente a que rebaixa a conta sem nunca oferecer a assinatura.

    Muta `user` no lugar, porque os três chamadores seguem usando o dict
    depois desta linha pra montar a resposta.

    `enviar_email` é injetado em vez de importado pra não criar ciclo com
    routers/auth.py, que é quem tem o `_send_email`. Passar None manda só a
    notificação · é o que o staging faz, pra não mandar e-mail de verdade para
    o usuário real do banco de produção.

    Quem assinou durante o teste nem chega aqui · o pagamento já trocou o plano
    pra `vip`, e o CASE WHEN de routers/payments.py cobre exatamente isso.
    """
    plan = user.get("plan")
    if plan not in PLANOS_COM_VALIDADE or not user.get("expires_at"):
        return False

    exp = user["expires_at"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if (agora or datetime.now(timezone.utc)) <= exp:
        return False

    cur.execute("UPDATE users SET plan='free', expires_at=NULL WHERE id=%s", (user["id"],))
    _avisar_acesso_encerrado(
        cur, user, plan,
        DEDUPE_TRIAL_ENCERRADO if plan == "trial" else dedupe_vip_encerrado(exp.date()),
        enviar_email=enviar_email, site_url=site_url,
    )

    user["plan"] = "free"
    user["expires_at"] = None
    return True


# ─────────────────────────────────────────────────────────────────────────────
# VARREDURA · quem NÃO volta também precisa ser rebaixado
# ─────────────────────────────────────────────────────────────────────────────
#
# Tudo acima é preguiçoso: `expirar_plano_vencido` só roda quando a pessoa
# aparece (login, refresh, /auth/me). Isso funciona pra quem volta, e falha
# exatamente pra quem interessa · em 2026-08-29 o banco de produção tinha três
# testes vencidos há dois dias ainda com `plan = 'trial'`, um deles de uma
# conta que nunca fez login. Nenhum aviso de encerramento havia sido criado na
# vida do site (`notifications` tinha 10 `plan_expiring` e zero `trial_ended`).
#
# Duas consequências, e a segunda é a cara:
#
#   · o relatório mente. O /admin lista a pessoa como "trial" e a contagem de
#     testes ativos soma gente que já perdeu o acesso (o acesso em si nunca
#     vazou: `auth_utils.get_current_user` derruba pra free pela data antes de
#     qualquer rota VIP responder · o defeito é de ESTADO e de AVISO, não de
#     permissão);
#   · o e-mail "seu teste acabou" nunca sai. Ele é o único canal que alcança
#     quem parou de abrir o site, e é a hora exata de oferecer a assinatura ·
#     o momento em que a conversão vale mais é justamente o que o gatilho
#     preguiçoso não cobre.
#
# Nada de agendador aqui (removido em 2026-08-01 e a decisão vale): a
# varredura pega carona numa VISITA qualquer ao site, no mesmo formato de
# stats_sweep.py e de routers/live.py::maybe_resolve_pending. Site parado não
# gasta nada, e o freio de banco é uma consulta que na maior parte do tempo
# responde "não tem ninguém".
_VARREDURA_INTERVALO = int(os.getenv("PLAN_SWEEP_INTERVAL_SECONDS", "900"))

#: Teto por passada. Não é performance: é raio de explosão. Se algum dia uma
#: alteração de coluna deixar meia base "vencida", a primeira passada mexe em
#: 200 contas e as próximas continuam · o log mostra o número e dá tempo de
#: parar antes de mandar e-mail pra base inteira.
_VARREDURA_LIMITE = int(os.getenv("PLAN_SWEEP_LIMIT", "200"))

_estado = {"ultima": 0.0, "rodando": False, "ultimo_resultado": None}
_lock = threading.Lock()


def _vencidos(cur, limite: int) -> list[dict]:
    cur.execute(
        """
        SELECT id, name, email, plan, expires_at
          FROM users
         WHERE plan = ANY(%s) AND expires_at IS NOT NULL AND expires_at < NOW()
         ORDER BY expires_at
         LIMIT %s
        """,
        (list(PLANOS_COM_VALIDADE), limite),
    )
    return [dict(r) for r in cur.fetchall()]


def varrer_planos_vencidos(cur, enviar_email=None, site_url: str = "",
                           limite: int = _VARREDURA_LIMITE) -> dict:
    """Rebaixa e avisa TODO mundo com plano vencido. Não commita.

    Reusa `expirar_plano_vencido` conta a conta em vez de fazer um UPDATE em
    massa: é a mesma função dos três caminhos de requisição, então não existe
    um segundo jeito de rebaixar alguém que possa divergir do primeiro (e é
    ela que cria a notificação e dispara o e-mail).

    A comparação de vencimento fica no SQL, e não no Python, porque
    `expires_at` é TIMESTAMP sem fuso: no banco ele e o NOW() vivem no mesmo
    referencial. `expirar_plano_vencido` reconfere em Python assumindo UTC, o
    que no máximo deixa passar quem venceu há pouco · esse volta na próxima.
    """
    resumo = {"rebaixados": 0, "trial": 0, "vip": 0, "ids": []}
    for user in _vencidos(cur, limite):
        plano = user["plan"]
        if expirar_plano_vencido(cur, user, enviar_email=enviar_email,
                                 site_url=site_url):
            resumo["rebaixados"] += 1
            resumo[plano] = resumo.get(plano, 0) + 1
            resumo["ids"].append(user["id"])
    return resumo


def _ha_plano_vencido(cur) -> bool:
    """Freio de banco: uma consulta, e quase sempre a resposta é não."""
    cur.execute(
        "SELECT 1 FROM users WHERE plan = ANY(%s) AND expires_at IS NOT NULL "
        "AND expires_at < NOW() LIMIT 1",
        (list(PLANOS_COM_VALIDADE),),
    )
    return cur.fetchone() is not None


def _passada(enviar_email, site_url: str) -> None:
    from database import get_connection

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            resumo = varrer_planos_vencidos(cur, enviar_email=enviar_email,
                                            site_url=site_url)
            conn.commit()
            _estado["ultimo_resultado"] = resumo
            if resumo["rebaixados"]:
                logger.info("[PLAN-SWEEP] %s", resumo)
        finally:
            cur.close()
    except Exception as e:
        if conn is not None:
            conn.rollback()
        _estado["ultimo_resultado"] = {"erro": str(e)[:200]}
        logger.error("[PLAN-SWEEP] falhou: %s", e, exc_info=True)
    finally:
        if conn is not None:
            conn.close()
        with _lock:
            _estado["rodando"] = False


def maybe_expirar_vencidos(enviar_email=None, site_url: str = "") -> bool:
    """Chamada de dentro de rotas de leitura. NUNCA bloqueia quem chamou.

    O rebaixamento em si é barato (um UPDATE por conta), mas o e-mail não: ele
    fala com um servidor de SMTP, uma vez por pessoa. O visitante que por acaso
    disparou a varredura não pode esperar por isso, então a passada vai pra
    thread de fundo · igual à varredura de estatística.

    Retorna True quando disparou a passada agora. Diferente do stats_sweep,
    não exige produção: rebaixar não gasta cota de API nenhuma, e o freio que
    importa (não mandar e-mail de verdade pro assinante real a partir do
    staging) já mora em quem injeta o `enviar_email`.
    """
    agora = time.time()
    with _lock:
        if _estado["rodando"] or agora - _estado["ultima"] < _VARREDURA_INTERVALO:
            return False
        _estado["ultima"] = agora
        _estado["rodando"] = True

    from database import get_connection

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            tem = _ha_plano_vencido(cur)
        finally:
            cur.close()
    except Exception as e:
        logger.warning("[PLAN-SWEEP] freio de banco falhou: %s", e)
        with _lock:
            _estado["rodando"] = False
        return False
    finally:
        if conn is not None:
            conn.close()

    if not tem:
        with _lock:
            _estado["rodando"] = False
        return False

    threading.Thread(target=_passada, args=(enviar_email, site_url),
                     name="plan-sweep", daemon=True).start()
    return True


def estado_da_varredura() -> dict:
    """Retrato pro /admin. Só leitura."""
    return {
        "intervalo_s": _VARREDURA_INTERVALO,
        "limite": _VARREDURA_LIMITE,
        "rodando": _estado["rodando"],
        "ultima_passada_ha_s": (round(time.time() - _estado["ultima"])
                                if _estado["ultima"] else None),
        "ultimo_resultado": _estado["ultimo_resultado"],
    }
