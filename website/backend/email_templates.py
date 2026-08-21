"""Cascas e conteúdos dos e-mails transacionais do Pick IA.

POR QUE UM MÓDULO SÓ
--------------------
A mesma casca (fundo escuro, cartão de 560px, topo verde, rodapé) estava
copiada em três arquivos · routers/auth.py, routers/payments.py e
plan_expiry.py · e cada cópia tinha derivado um pouco da outra: duas traziam
o Instagram no rodapé e duas não, uma mostrava o logo e as outras não. Quando
o @ do Instagram mudou, o custo dessa duplicação ficou explícito: era preciso
caçar o link em três lugares, e dois deles nem tinham o link pra corrigir.

Aqui a casca é uma função só. Mudar o rodapé (ou o @) passa a ser uma linha
que vale pra todo e-mail que o produto manda, inclusive os que vierem depois.

REGRAS DE HTML DE E-MAIL QUE ESTE ARQUIVO SEGUE
----------------------------------------------
Cliente de e-mail não é navegador. Por isso, aqui:

  * layout em <table>, nunca flexbox/grid · o Outlook ignora `display:flex`
    e o conteúdo desaba um sobre o outro (era o caso do selo do e-mail de
    pagamento, que só ficava redondo no Gmail web);
  * todo estilo inline, porque o Gmail descarta <style> em boa parte dos casos;
  * cor de fundo declarada em cada célula, já que o modo escuro de alguns
    clientes reescreve o que está sem cor explícita;
  * nada de emoji · entidades geométricas (&#9679;) rendem igual em todo
    cliente e não dependem da fonte de emoji do aparelho.
"""
from urllib.parse import quote

# O @ vive aqui e em mais nenhum lugar do backend.
INSTAGRAM_URL    = "https://www.instagram.com/pickia.app/"
INSTAGRAM_HANDLE = "@pickia.app"

ASSINATURA = "Pick IA &middot; Tips por Inteligência Artificial"

# Paleta espelhando os tokens do site (--surface/--ink/--line), fixada em hex
# porque e-mail não tem variável CSS.
VERDE       = "#16a34a"
VERDE_CLARO = "#22c55e"
FUNDO       = "#0a0a0a"
CARTAO      = "#111111"
BORDA       = "#222222"
CAIXA       = "#1a1a1a"
CAIXA_BORDA = "#262626"
TEXTO       = "#ffffff"
TEXTO_2     = "#a1a1aa"
TEXTO_3     = "#71717a"
TEXTO_4     = "#52525b"


def url_logo(site_url: str) -> str:
    """Logo servida pelo próprio site · imagem embutida em base64 é bloqueada
    pelo Gmail, então a URL pública é o caminho que funciona sempre."""
    return f"{site_url.rstrip('/')}/static/logo.png"


def _topo(logo_url: str = "", tagline: bool = True) -> str:
    logo = ""
    if logo_url:
        logo = (
            f'<img src="{logo_url}" alt="Pick IA" width="72" height="72" '
            f'style="border-radius:50%;margin:0 auto 14px;display:block;" />'
        )
    sub = (
        f'<p style="margin:6px 0 0;color:#dcfce7;font-size:14px;">'
        f'Tips esportivas por Inteligência Artificial</p>'
        if tagline else ""
    )
    return f"""        <tr><td style="background:linear-gradient(135deg,{VERDE},#15803d);background-color:{VERDE};padding:32px 40px;text-align:center;">
          {logo}
          <h1 style="margin:0;color:{TEXTO};font-size:26px;font-weight:900;letter-spacing:-0.5px;">
            Pick<span style="color:#bbf7d0;">IA</span>
          </h1>
          {sub}
        </td></tr>"""


def _rodape(nota: str = "") -> str:
    """Rodapé único de todos os e-mails · é aqui que mora o Instagram."""
    extra = (
        f'<p style="margin:0 0 10px;color:{TEXTO_4};font-size:12px;line-height:1.5;">{nota}</p>'
        if nota else ""
    )
    return f"""        <tr><td style="background:{CARTAO};border-top:1px solid #1f1f1f;padding:20px 40px;text-align:center;">
          {extra}
          <p style="margin:0 0 6px;color:{TEXTO_4};font-size:12px;">
            Siga no Instagram:
            <a href="{INSTAGRAM_URL}" style="color:{VERDE_CLARO};text-decoration:none;font-weight:600;">{INSTAGRAM_HANDLE}</a>
          </p>
          <p style="margin:0;color:#3f3f46;font-size:11px;">{ASSINATURA}</p>
        </td></tr>"""


def casca(conteudo: str, logo_url: str = "", nota_rodape: str = "", tagline: bool = True) -> str:
    """Documento completo: topo, `conteudo` no meio, rodapé.

    `conteudo` entra como uma ou mais <tr> · quem chama é dono das linhas do
    miolo, e a casca não tenta adivinhar padding pra não brigar com layouts
    que precisem sangrar até a borda do cartão.
    """
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"></head>
<body style="margin:0;padding:0;background:{FUNDO};font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{FUNDO};padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:{CARTAO};border:1px solid {BORDA};border-radius:16px;overflow:hidden;max-width:560px;width:100%;">
{_topo(logo_url, tagline)}
{conteudo}
{_rodape(nota_rodape)}
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _botao(url: str, rotulo: str) -> str:
    return (
        f'<a href="{url}" style="display:inline-block;background:{VERDE};color:{TEXTO};'
        f'text-decoration:none;font-weight:800;font-size:15px;padding:14px 40px;'
        f'border-radius:10px;letter-spacing:0.3px;">{rotulo}</a>'
    )


def _card(cor_marcador: str, titulo: str, texto: str) -> str:
    return f"""<td width="48%" style="background:{CAIXA};border:1px solid {CAIXA_BORDA};border-radius:12px;padding:16px;vertical-align:top;">
                <div style="color:{cor_marcador};font-size:20px;line-height:1;margin-bottom:8px;">&#9679;</div>
                <div style="color:{TEXTO};font-size:14px;font-weight:700;margin-bottom:4px;">{titulo}</div>
                <div style="color:{TEXTO_3};font-size:12px;line-height:1.5;">{texto}</div>
              </td>"""


# ─────────────────────────────────────────────────────────────────────────────
# 1. CONFIRMAÇÃO DE E-MAIL
# ─────────────────────────────────────────────────────────────────────────────

def verificacao_html(primeiro_nome: str, site_url: str, token: str, logo_url: str = "") -> str:
    verify_url = f"{site_url}/verify-email?token={token}"
    conteudo = f"""        <tr><td style="background:{CARTAO};padding:36px 40px;text-align:center;">
          <p style="margin:0 0 8px;color:{TEXTO_3};font-size:13px;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Bem-vindo,</p>
          <h2 style="margin:0 0 16px;color:{TEXTO};font-size:22px;font-weight:800;">{primeiro_nome}!</h2>
          <p style="margin:0 0 8px;color:{TEXTO_2};font-size:15px;line-height:1.6;">
            Sua conta foi criada. Para ativar seu <strong style="color:{VERDE_CLARO};">acesso VIP gratuito de 2 dias</strong>,<br>confirme seu e-mail no botão abaixo.
          </p>
          <p style="margin:0 0 28px;color:{TEXTO_4};font-size:12px;">O link expira em 24 horas.</p>
          {_botao(verify_url, "Confirmar e-mail")}
          <p style="margin:24px 0 0;color:{TEXTO_4};font-size:11px;line-height:1.6;word-break:break-all;">
            Se o botão não abrir, cole este endereço no navegador:<br>
            <span style="color:{TEXTO_3};">{verify_url}</span>
          </p>
        </td></tr>"""
    return casca(
        conteudo, logo_url,
        nota_rodape="Você recebeu este e-mail porque este endereço foi usado para criar uma conta no Pick IA.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. BOAS-VINDAS (conta confirmada)
# ─────────────────────────────────────────────────────────────────────────────

def boas_vindas_html(primeiro_nome: str, site_url: str, logo_url: str = "") -> str:
    conteudo = f"""        <tr><td style="background:{CARTAO};padding:36px 40px;">
          <p style="margin:0 0 8px;color:{TEXTO_3};font-size:13px;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Bem-vindo,</p>
          <h2 style="margin:0 0 20px;color:{TEXTO};font-size:22px;font-weight:800;">{primeiro_nome}!</h2>
          <p style="margin:0 0 28px;color:{TEXTO_2};font-size:15px;line-height:1.6;">
            Sua conta foi confirmada. Você tem <strong style="color:{VERDE_CLARO};">2 dias de acesso VIP gratuito</strong> para explorar tudo que o Pick IA faz.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
            <tr>
              {_card(VERDE_CLARO, "Picks VIP", "Análises diárias com valor esperado positivo, odd e mercado definidos.")}
              <td width="4%"></td>
              {_card("#3b82f6", "Múltiplas e Alavancagem", "Combinações montadas pelo motor, com o caminho todo acompanhado.")}
            </tr>
            <tr><td colspan="3" style="padding-top:12px;"></td></tr>
            <tr>
              {_card("#ef4444", "Ao Vivo", "Picks durante a partida, com a estatística do jogo atualizando na tela.")}
              <td width="4%"></td>
              {_card("#f59e0b", "Gestão de Banca", "Controle de banca, metas e histórico completo de resultados.")}
            </tr>
          </table>

          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">{_botao(f"{site_url}/picks", "Acessar meus picks")}</td></tr>
          </table>
        </td></tr>"""
    return casca(conteudo, logo_url)


# ─────────────────────────────────────────────────────────────────────────────
# 3. E-MAILS DE CÓDIGO (redefinir senha e confirmar troca de senha)
# ─────────────────────────────────────────────────────────────────────────────
#
# Estes dois saíam em texto puro enquanto todos os outros vinham desenhados.
# O problema não é estético: e-mail de senha é justamente o que golpista
# imita, e o texto solto é o mais fácil de falsificar de forma convincente.
# Chegando na mesma casca dos demais, quem recebe tem uma referência visual
# pra comparar.
#
# Os dois compartilham o mesmo corpo porque são o mesmo gesto (digitar um
# código de 6 dígitos numa tela do site) · só muda o motivo, e é só isso que
# os parâmetros carregam.

def _codigo_html(rotulo: str, primeiro_nome: str, chamada: str, codigo: str,
                 minutos: int, cta_url: str, cta_rotulo: str, alerta: str,
                 logo_url: str = "") -> str:
    digitos = "".join(
        f'<td style="padding:0 4px;"><div style="background:{CAIXA};border:1px solid {CAIXA_BORDA};'
        f'border-radius:10px;color:{TEXTO};font-family:Consolas,Menlo,monospace;font-size:26px;'
        f'font-weight:800;padding:14px 0;width:44px;text-align:center;">{d}</div></td>'
        for d in codigo
    )
    conteudo = f"""        <tr><td style="background:{CARTAO};padding:36px 40px;text-align:center;">
          <p style="margin:0 0 8px;color:{TEXTO_3};font-size:13px;text-transform:uppercase;letter-spacing:1px;font-weight:600;">{rotulo}</p>
          <h2 style="margin:0 0 16px;color:{TEXTO};font-size:22px;font-weight:800;">Olá, {primeiro_nome}</h2>
          <p style="margin:0 0 24px;color:{TEXTO_2};font-size:15px;line-height:1.6;">{chamada}</p>

          <table cellpadding="0" cellspacing="0" align="center" style="margin:0 auto 16px;">
            <tr>{digitos}</tr>
          </table>
          <p style="margin:0 0 28px;color:{TEXTO_4};font-size:12px;">O código expira em {minutos} minutos.</p>

          {_botao(cta_url, cta_rotulo)}

          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:28px;">
            <tr><td style="background:{CAIXA};border:1px solid {CAIXA_BORDA};border-radius:12px;padding:14px 18px;text-align:left;">
              <p style="margin:0;color:{TEXTO_3};font-size:12px;line-height:1.6;">
                <strong style="color:{TEXTO_2};">Não foi você?</strong> {alerta}
              </p>
            </td></tr>
          </table>
        </td></tr>"""
    return casca(
        conteudo, logo_url,
        nota_rodape="O Pick IA nunca pede sua senha por e-mail, WhatsApp ou telefone.",
    )


def reset_senha_html(primeiro_nome: str, codigo: str, site_url: str, email: str = "",
                     minutos: int = 15, logo_url: str = "") -> str:
    # O e-mail vai no link (e não só o /forgot-password pelado) porque a tela
    # de recuperação tem dois passos no mesmo endereço: sem o parâmetro, quem
    # clica cai no passo 1 e só sai dali pedindo OUTRO código · o que acabou
    # de chegar seria invalidado pelo próprio clique.
    destino = f"{site_url}/forgot-password"
    if email:
        destino += f"?email={quote(email)}"
    return _codigo_html(
        rotulo="Redefinição de senha",
        primeiro_nome=primeiro_nome,
        chamada="Use o código abaixo na tela de redefinição para criar uma senha nova.",
        codigo=codigo,
        minutos=minutos,
        cta_url=destino,
        cta_rotulo="Redefinir minha senha",
        alerta=("Ignore este e-mail · sua senha atual continua valendo e ninguém "
                "troca nada sem este código."),
        logo_url=logo_url,
    )


def troca_senha_html(primeiro_nome: str, codigo: str, site_url: str,
                     minutos: int = 15, logo_url: str = "") -> str:
    return _codigo_html(
        rotulo="Confirmação de troca de senha",
        primeiro_nome=primeiro_nome,
        chamada="Digite o código abaixo no seu perfil para confirmar a nova senha.",
        codigo=codigo,
        minutos=minutos,
        cta_url=f"{site_url}/profile",
        cta_rotulo="Abrir meu perfil",
        alerta=("Ignore este e-mail e troque sua senha assim que puder · alguém "
                "com a sua senha atual pediu esta mudança."),
        logo_url=logo_url,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. ACESSO VIP ATIVADO (pagamento confirmado)
# ─────────────────────────────────────────────────────────────────────────────

def vip_ativado_html(primeiro_nome: str, plano: str, vence_em: str,
                     site_url: str, logo_url: str = "") -> str:
    conteudo = f"""        <tr><td style="background:{CARTAO};padding:36px 40px;text-align:center;">
          <table cellpadding="0" cellspacing="0" align="center" style="margin:0 auto 20px;">
            <tr><td style="background:#16a34a22;border:1px solid {VERDE};border-radius:999px;padding:7px 18px;
                           color:{VERDE_CLARO};font-size:12px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;">
              Acesso liberado
            </td></tr>
          </table>
          <h2 style="margin:0 0 8px;color:{TEXTO};font-size:22px;font-weight:800;">Tudo certo, {primeiro_nome}!</h2>
          <p style="margin:0 0 24px;color:{TEXTO_2};font-size:15px;line-height:1.6;">
            Seu pagamento foi confirmado e o acesso completo já está ativo na sua conta.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0" style="background:{CAIXA};border:1px solid {CAIXA_BORDA};border-radius:12px;margin-bottom:28px;">
            <tr><td style="padding:16px 20px;border-bottom:1px solid {CAIXA_BORDA};text-align:left;">
              <span style="color:{TEXTO_3};font-size:12px;text-transform:uppercase;letter-spacing:1px;">Plano</span>
              <div style="color:{TEXTO};font-size:15px;font-weight:700;margin-top:4px;">{plano}</div>
            </td></tr>
            <tr><td style="padding:16px 20px;text-align:left;">
              <span style="color:{TEXTO_3};font-size:12px;text-transform:uppercase;letter-spacing:1px;">Acesso até</span>
              <div style="color:{VERDE_CLARO};font-size:15px;font-weight:700;margin-top:4px;">{vence_em}</div>
            </td></tr>
          </table>

          {_botao(f"{site_url}/picks", "Acessar meus picks")}
        </td></tr>"""
    return casca(conteudo, logo_url)


# ─────────────────────────────────────────────────────────────────────────────
# 5. PLANO PERTO DE VENCER
# ─────────────────────────────────────────────────────────────────────────────

def plano_expirando_html(nome: str, titulo: str, corpo: str,
                         site_url: str, logo_url: str = "") -> str:
    primeiro = (nome or "").split(" ")[0] or "tudo bem"
    conteudo = f"""        <tr><td style="background:{CARTAO};padding:32px 40px;">
          <p style="margin:0 0 6px;color:{TEXTO_3};font-size:13px;">Olá, {primeiro}</p>
          <h2 style="margin:0 0 16px;color:{TEXTO};font-size:20px;font-weight:800;">{titulo}</h2>
          <p style="margin:0 0 26px;color:{TEXTO_2};font-size:15px;line-height:1.6;">{corpo}</p>
          {_botao(f"{site_url}/checkout", "Renovar agora")}
        </td></tr>"""
    return casca(
        conteudo, logo_url,
        nota_rodape="Você recebeu este aviso porque tem um plano ativo no Pick IA.",
    )
