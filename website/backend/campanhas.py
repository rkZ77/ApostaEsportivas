"""Disparos de reengajamento: o catalogo, o publico e o texto de cada um.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
O produto sempre teve um buraco no meio do funil: a pessoa se cadastra, olha
uma vez e some. O `/admin` ja media esse buraco (a aba Funil, e o painel de
engajamento antes dela), mas medir e' o que se faz quando nao da' pra agir ·
nao existia nenhuma forma de FALAR com quem sumiu, nem manual.

Aqui o disparo vira um objeto: quem recebe (`onde`), o que diz (`assunto`,
`paragrafos`) e por que existe (`objetivo`). Campanha nova e' uma entrada na
tupla, e a aba Disparos do /admin passa a mostra-la sozinha · publico, previa
do e-mail e botao. Escrever o SQL do publico na rota e o texto no componente
seria o mesmo defeito que `lib/oferta.ts` existiu pra matar: a tela que
dispara e a tela que conta quantos vao receber discordando sobre quem e'
"sumido".

AS DUAS TRAVAS QUE NAO SAO ENFEITE
-----------------------------------
1. `email_marketing_opt_out`. Isto e' marketing, nao e' transacional: quem se
   cadastrou autorizou uma conta, nao propaganda. Todo e-mail daqui sai com
   link de descadastro, e a coluna e' checada dentro do SQL do publico ·
   filtrar no Python deixaria a contagem da tela prometendo envios que nao
   acontecem.
2. `campanha_envios` com indice unico por (campanha, canal, user_id). Sem ele,
   dois cliques no botao mandam o mesmo e-mail duas vezes, e o segundo e' o que
   faz a pessoa marcar como spam. Mesmo motivo do `dedupe_key` do sino.

WHATSAPP DE CAMPANHA E' MANUAL DE PROPOSITO
--------------------------------------------
O aviso em tempo real (pick ao vivo) sai sozinho, porque a pessoa ligou o
opt-in no perfil pra aquilo. Campanha e' outra coisa: e' marketing pra quem
sumiu, e disparar isso em lote e' o caminho mais curto pro numero comprado ser
banido · a politica da Meta pra vertical de aposta trata o assunto no nivel da
CONTA (ver website/scripts/whatsapp/README.md). Entao a aba entrega a LISTA
com link `wa.me` por pessoa e o texto ja montado: quem manda e' uma pessoa,
uma conversa por vez, e o envio so' e' registrado quando o admin confirma.
"""
from dataclasses import dataclass
from urllib.parse import quote


#: Condicao base de QUALQUER publico. Conta apagada (LGPD) tem a PII trocada
#: por marcador, entao mandar e-mail pra ela seria mandar pro nada; conta
#: desativada pelo admin e' o mesmo caso. Admin fora porque somos nos.
_BASE = """
      u.active
  AND u.deleted_at IS NULL
  AND u.plan <> 'admin'
"""

#: So' pra e-mail. O opt-out entra aqui, e nao no Python, pelo motivo do topo.
_BASE_EMAIL = _BASE + """
  AND u.email IS NOT NULL AND u.email <> ''
  AND NOT COALESCE(u.email_marketing_opt_out, FALSE)
"""

#: So' pra WhatsApp. `phone_verified` porque telefone nao verificado pode ser
#: o do vizinho · foi pra isso que o SMS entrou em 18/08/2026, e mandar
#: mensagem pro numero errado e' denuncia na certa.
_BASE_WHATSAPP = _BASE + """
  AND u.phone IS NOT NULL AND u.phone <> ''
  AND COALESCE(u.phone_verified, FALSE)
"""


@dataclass(frozen=True)
class Campanha:
    id: str
    nome: str
    #: Aparece no /admin. Responde "por que mandar isto", nao "o que isto diz".
    objetivo: str
    #: Condicao SQL extra sobre `u` (alias de users). Sem AND na frente.
    onde: str
    assunto: str
    titulo: str
    #: `{nome}` e' o primeiro nome. Um paragrafo por elemento.
    paragrafos: tuple
    cta_rotulo: str
    cta_caminho: str
    #: Cola o placar real dos ultimos 30 dias no corpo. So' onde o numero e' o
    #: argumento · num e-mail de "sua conta esta pronta" ele e' ruido.
    mostra_numeros: bool = False
    #: Cola a lista de produtos novos. Ver NOVIDADES abaixo.
    mostra_novidades: bool = False
    #: Texto do wa.me. Curto: WhatsApp nao e' canal de conteudo aqui.
    whatsapp: str = ""


#: O QUE MUDOU NO PRODUTO, na ordem em que entrou.
#:
#: Escrito a mao aqui porque o backend nao le' `lib/oferta.ts`, que e' o
#: catalogo do frontend. A regra pra manter os dois honestos: so' entra nesta
#: lista o que JA ESTA NA TELA. E-mail que anuncia o que ainda nao saiu e' o
#: jeito mais rapido de a pessoa clicar, nao achar, e nao clicar na proxima.
NOVIDADES: tuple = (
    ("Picks ao vivo",
     "Um motor separado le' a partida em andamento e publica quando o campo "
     "desmente o que o mercado precificou."),
    ("Pick Jogador",
     "Estatistica individual: chutes no alvo, desarmes, participacao. O pick "
     "acompanha a vaga do titular e anula se ele nao comecar jogando."),
    ("Pick Boost",
     "As odds turbinadas das casas, passadas pelo mesmo criterio dos outros "
     "picks. Odd aumentada so' vale quando a probabilidade sustenta."),
    ("Pick Falta",
     "Mercado de faltas com modelo proprio, separado do de escanteios porque "
     "a dispersao das duas contagens nao e' a mesma."),
    ("Bilhete de uma casa so'",
     "Multipla e alavancagem saem todas da mesma casa, com pernas que nao se "
     "repetem entre os bilhetes do dia."),
    ("Auditoria do motor",
     "Deu RED? A pagina do pick mostra que jogos o motor leu pra decidir, com "
     "os numeros que ele tinha na hora da decisao."),
)


CAMPANHAS: tuple = (
    Campanha(
        id="novidades",
        nome="Novidades do produto",
        objetivo=(
            "Quem sumiu antes de metade do produto existir. Ao vivo, Pick Jogador, "
            "Pick Boost e Pick Falta entraram depois da ultima visita dessa gente: "
            "ela avaliou um site que nao e' mais este."
        ),
        onde="(u.last_login_at IS NULL OR u.last_login_at < NOW() - INTERVAL '15 days')",
        assunto="O Pick IA mudou bastante desde a sua ultima visita",
        titulo="Tem coisa nova desde que voce saiu",
        paragrafos=(
            "Ola {nome}, faz um tempo que voce nao aparece. Nesse meio tempo o "
            "site ganhou produto novo, e a conta que voce ja tem abre parte "
            "disso sem pagar nada.",
            "Da uma olhada no que entrou:",
        ),
        cta_rotulo="Ver o que saiu hoje",
        cta_caminho="/picks",
        mostra_numeros=True,
        mostra_novidades=True,
        whatsapp=(
            "Oi {nome}, aqui e' do Pick IA. Voce se cadastrou e faz um tempo que "
            "nao aparece. Entrou coisa nova no site: picks ao vivo, estatistica "
            "de jogador e odds turbinadas. Sua conta ja abre o pick gratuito do "
            "dia: {url}"
        ),
    ),
    Campanha(
        id="nunca_entrou",
        nome="Cadastrou e nunca entrou",
        objetivo=(
            "Criou a conta e nunca fez login. E' o vazamento mais caro do funil: "
            "a pessoa ja quis, so' nao chegou a ver nada."
        ),
        onde="u.last_login_at IS NULL AND u.created_at < NOW() - INTERVAL '2 days'",
        assunto="Sua conta no Pick IA esta pronta",
        titulo="Sua conta esta pronta",
        paragrafos=(
            "Ola {nome}, voce criou sua conta no Pick IA mas ainda nao entrou "
            "nenhuma vez. Nao ficou nada pendente do seu lado: e' so' fazer login.",
            "Todo dia sai um pick gratuito, com o mercado, a odd e a analise que "
            "sustenta a escolha. Da' pra conferir o metodo antes de decidir "
            "qualquer coisa.",
        ),
        cta_rotulo="Entrar agora",
        cta_caminho="/login",
        whatsapp=(
            "Oi {nome}, aqui e' do Pick IA. Vi que voce criou a conta mas nunca "
            "entrou. Nao ficou nada pendente, e' so' fazer login: {url}"
        ),
    ),
    Campanha(
        id="trial_expirado",
        nome="Testou e nao assinou",
        objetivo=(
            "Usou o teste, viu o produto por dentro e ficou no free. Ja sabe do "
            "que se trata, entao o argumento aqui e' o placar, nao a explicacao."
        ),
        onde=(
            "COALESCE(u.trial_used, FALSE) AND u.plan NOT IN ('vip','trial') "
            "AND (u.expires_at IS NULL OR u.expires_at < NOW() - INTERVAL '5 days')"
        ),
        assunto="O que a IA acertou desde que seu teste acabou",
        titulo="O placar continuou correndo",
        paragrafos=(
            "Ola {nome}, seu periodo de teste acabou faz um tempo e voce "
            "continua com a conta gratuita. Sem cobranca nenhuma, e sem "
            "assinatura correndo por tras.",
            "So' que os picks nao pararam. Este e' o desempenho medido dos "
            "ultimos 30 dias, com anulada fora da conta e meio-green contando "
            "como acerto, igual a pagina publica de resultados mostra:",
        ),
        cta_rotulo="Ver os planos",
        cta_caminho="/planos",
        mostra_numeros=True,
        whatsapp=(
            "Oi {nome}, aqui e' do Pick IA. Seu teste acabou e voce ficou no "
            "plano gratuito. O placar dos ultimos 30 dias esta aberto aqui, sem "
            "precisar logar: {url}"
        ),
    ),
    Campanha(
        id="vip_vencido",
        nome="Assinatura vencida",
        objetivo=(
            "Ja pagou e deixou vencer. Nao e' aquisicao, e' volta · trazer de "
            "volta quem ja assinou e' o caminho mais barato que existe aqui."
        ),
        onde=(
            "u.plan NOT IN ('vip','trial') "
            "AND u.expires_at IS NOT NULL "
            "AND u.expires_at BETWEEN NOW() - INTERVAL '120 days' AND NOW() - INTERVAL '7 days' "
            "AND EXISTS (SELECT 1 FROM payments p "
            "            WHERE p.user_id = u.id AND p.status = 'approved')"
        ),
        assunto="Sua assinatura do Pick IA venceu",
        titulo="Faz tempo que voce nao volta",
        paragrafos=(
            "Ola {nome}, sua assinatura venceu e nao foi renovada. Aqui a "
            "cobranca e' avulsa, entao nada ficou correndo no seu cartao.",
            "Desde entao entrou produto novo, e agora sao duas opcoes de plano. "
            "O desempenho medido dos ultimos 30 dias:",
        ),
        cta_rotulo="Voltar a assinar",
        cta_caminho="/planos",
        mostra_numeros=True,
        mostra_novidades=True,
        whatsapp=(
            "Oi {nome}, aqui e' do Pick IA. Sua assinatura venceu faz um tempo e "
            "nada ficou cobrando no seu cartao, a cobranca aqui e' avulsa. "
            "Entrou produto novo desde entao: {url}"
        ),
    ),
    Campanha(
        id="sem_seguir_pick",
        nome="Entrou e nunca seguiu pick",
        objetivo=(
            "Faz login, le' o pick e nao registra na banca. Enquanto nao seguir "
            "um pick, o produto nao tem placar PRA ELE · e e' o placar proprio "
            "que segura a pessoa."
        ),
        onde=(
            "u.last_login_at IS NOT NULL "
            "AND u.created_at < NOW() - INTERVAL '5 days' "
            "AND NOT EXISTS (SELECT 1 FROM user_followed_picks f WHERE f.user_id = u.id)"
        ),
        assunto="Seus picks nao estao virando placar",
        titulo="Falta um clique pro placar ser seu",
        paragrafos=(
            "Ola {nome}, voce ja entrou no Pick IA, mas ainda nao registrou "
            "nenhuma entrada na sua banca.",
            "O botao de seguir num pick faz duas coisas: lanca a entrada na sua "
            "banca com a stake que voce escolher, e te avisa quando o jogo "
            "resolve. Sem ele o site mostra o desempenho da IA, nao o SEU.",
        ),
        cta_rotulo="Ver os picks de hoje",
        cta_caminho="/picks",
        whatsapp=(
            "Oi {nome}, aqui e' do Pick IA. Voce ja entrou no site mas nunca "
            "seguiu um pick: e' o clique que monta a sua banca e te avisa quando "
            "o jogo resolve. Os picks de hoje estao aqui: {url}"
        ),
    ),
)

_POR_ID = {c.id: c for c in CAMPANHAS}


def campanha(cid: str) -> Campanha:
    if cid not in _POR_ID:
        raise KeyError(cid)
    return _POR_ID[cid]


#: Espaco minimo entre dois envios de campanha PRA MESMA PESSOA, no mesmo canal.
#:
#: O indice unico ja impede repetir a MESMA campanha. Isto impede o outro caso,
#: que e' mandar quatro campanhas diferentes na mesma semana pra quem se
#: encaixa em todas · e boa parte da base se encaixa em mais de uma.
JANELA_ENTRE_ENVIOS_DIAS = 14


def sql_publico(c: Campanha, canal: str) -> str:
    """SELECT dos destinatarios elegiveis DESTA campanha, neste canal.

    Uma consulta so' pra contar e pra enviar. Duas consultas parecidas e' como
    o painel comeca a prometer 300 envios e a fila sair com 180.
    """
    base = _BASE_EMAIL if canal == "email" else _BASE_WHATSAPP
    return f"""
        SELECT u.id, u.name, u.email, u.phone, u.plan,
               u.last_login_at, u.created_at
          FROM users u
         WHERE {base}
           AND ({c.onde})
           AND NOT EXISTS (
                 SELECT 1 FROM campanha_envios e
                  WHERE e.user_id = u.id
                    AND e.campanha = %(campanha)s
                    AND e.canal = %(canal)s
               )
           AND NOT EXISTS (
                 SELECT 1 FROM campanha_envios e
                  WHERE e.user_id = u.id
                    AND e.canal = %(canal)s
                    AND e.enviado_em > NOW() - INTERVAL '{JANELA_ENTRE_ENVIOS_DIAS} days'
               )
         ORDER BY u.last_login_at DESC NULLS LAST, u.created_at DESC
    """


def link_whatsapp(telefone: str, texto: str) -> str:
    """`wa.me` com o texto ja montado · o envio e' o dedo do admin."""
    numero = "".join(ch for ch in (telefone or "") if ch.isdigit())
    if not numero.startswith("55"):
        numero = "55" + numero
    return f"https://wa.me/{numero}?text={quote(texto)}"


def primeiro_nome(nome: str) -> str:
    partes = (nome or "").strip().split()
    return partes[0] if partes else "tudo bem"


# ── Descadastro sem login ────────────────────────────────────────────────────
#
# Quem sumiu não vai entrar no site pra desligar um e-mail. Vai marcar como
# spam · e reclamação de spam derruba a entrega dos TRANSACIONAIS junto, que
# são os que o produto não pode perder (confirmação de cadastro, senha,
# pagamento). O link de um clique é o que protege esses.
#
# HMAC e não um token gravado no banco: não há nada a revogar aqui (o pior uso
# de um token roubado é descadastrar alguém de propaganda), e uma coluna a mais
# em `users` significaria um UPDATE por destinatário só pra montar o link.

def token_descadastro(user_id) -> str:
    import hashlib
    import hmac
    import os

    segredo = (os.getenv("JWT_SECRET") or "").encode()
    assinatura = hmac.new(segredo, f"unsub:{user_id}".encode(),
                          hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{assinatura}"


def user_de_token(token: str):
    """Devolve o id ou None. `compare_digest` porque isto é comparação de
    assinatura, e `==` em string vaza tempo."""
    import hmac

    try:
        bruto, assinatura = (token or "").split(".", 1)
        user_id = int(bruto)
    except (ValueError, AttributeError):
        return None
    esperado = token_descadastro(user_id).split(".", 1)[1]
    return user_id if hmac.compare_digest(assinatura, esperado) else None
