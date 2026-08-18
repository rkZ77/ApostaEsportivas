import os
import re
import time
import base64
import hashlib
import logging
import secrets
import pathlib
import shutil
import httpx
from collections import defaultdict

def _detect_device(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua:
        return "iPhone/iPad"
    if "android" in ua:
        return "Android"
    if "mobile" in ua or "phone" in ua:
        return "Celular"
    if "tablet" in ua:
        return "Tablet"
    if "windows" in ua or "mac" in ua or "linux" in ua:
        return "Computador"
    return "Dispositivo desconhecido"

import resend
logger = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Response, status, Depends, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional
from database import get_connection
from sms import SMSNaoEnviado, enviar_sms, sms_configurado
from auth_utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    set_auth_cookies, set_access_cookie, clear_auth_cookies,
    get_current_user, decode_token,
    REFRESH_COOKIE_NAME, COOKIE_NAME, oauth2_scheme,
    invalidar_cache_usuario,
)

_AVATARS_DIR = pathlib.Path(__file__).parent.parent / "static" / "avatars"
_LOGO_PATH   = pathlib.Path(__file__).parent.parent / "static" / "logo.png"

# Lockout por conta (além do lockout por IP em main.py): sem isso, um ataque
# distribuído por IP contorna o limite por IP mas ainda bate sempre na mesma
# conta-alvo. Chave é o identifier normalizado (email/username), não o id
# do usuário, já que uma conta inexistente/errada também deve contar.
_account_login_failures: dict[str, list[float]] = defaultdict(list)
ACCOUNT_LOGIN_MAX_FAILURES = 10
ACCOUNT_LOGIN_LOCKOUT_SECS = 900

# ── Carencia de confirmacao de e-mail ───────────────────────────────────────
#
# O cadastro loga a pessoa na hora e manda o link em background, entao ate
# 18/08/2026 dava pra usar a conta pra sempre sem nunca confirmar nada. Travar
# no ato do cadastro resolveria, mas jogaria fora quem tem o e-mail caindo em
# spam -- exatamente a friccao que a saida do CPF acabou de remover.
#
# Meio termo: entra livre por EMAIL_GATE_CARENCIA_DIAS, depois o login exige a
# confirmacao. Quem esta ativo no site confirma nesse prazo sem nem perceber;
# quem digitou e-mail errado para no dia 3, que e' o objetivo.
def _gate_carencia_dias() -> int:
    """Dias de folga antes do login exigir a confirmacao."""
    try:
        valor = int(os.getenv("EMAIL_GATE_CARENCIA_DIAS", "3"))
    except ValueError:
        return 3
    # Zero seria a trava imediata que foi descartada de proposito: e-mail no
    # spam viraria cadastro perdido no dia 1.
    return valor if valor >= 1 else 3


def _gate_desde() -> str:
    """Data de corte, em YYYY-MM-DD.

    So vale pra quem se cadastrou a partir daqui. Contas antigas -- inclusive
    VIP pagante -- nunca tiveram esse contrato: trava-las seria cobrar
    retroativamente uma regra que nao existia no cadastro delas, e tirar do ar
    gente que paga.

    O formato e' conferido porque este valor entra no SQL por interpolacao (a
    data nao cabe em placeholder dentro de `DATE '...'`). Variavel de ambiente
    e' controlada por quem opera o servidor, mas uma constante que vira SQL sem
    validacao e' o tipo de coisa que envelhece mal.
    """
    valor = (os.getenv("EMAIL_GATE_DESDE") or "").strip()
    return valor if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor) else "2026-08-18"


# Lidos uma vez, no import: sao decisao de operacao, nao de requisicao.
EMAIL_GATE_CARENCIA_DIAS = _gate_carencia_dias()
EMAIL_GATE_DESDE = _gate_desde()

# Reenvio automatico ao esbarrar no gate. Sem cooldown, dez tentativas de login
# viram dez e-mails e o dominio paga por isso na reputacao.
EMAIL_GATE_REENVIO_COOLDOWN_SECS = 300
_email_gate_ultimo_reenvio: dict[int, float] = {}


def _check_account_lockout(key: str) -> None:
    now = time.time()
    attempts = [t for t in _account_login_failures[key] if now - t < ACCOUNT_LOGIN_LOCKOUT_SECS]
    _account_login_failures[key] = attempts
    if len(attempts) >= ACCOUNT_LOGIN_MAX_FAILURES:
        remaining = int(ACCOUNT_LOGIN_LOCKOUT_SECS - (now - attempts[0]))
        raise HTTPException(status_code=429, detail=f"Conta temporariamente bloqueada. Tente novamente em {remaining // 60} min.")


def _record_account_failure(key: str) -> None:
    _account_login_failures[key].append(time.time())


# Rate limit por usuário autenticado para mutações sensíveis de perfil (troca
# de senha/email, avatar) -- mesmo padrão usado em banca.py/social.py. Sem
# isso, um atacante com sessão válida podia tentar milhares de códigos de
# confirmação (900 mil combinações, código de 6 dígitos) dentro da janela
# de expiração usando só o budget genérico de IP.
_profile_mutation_rate: dict[int, list[float]] = defaultdict(list)
_PROFILE_MUTATION_LIMIT = 5
_PROFILE_MUTATION_WINDOW = 60


def _check_profile_rate(user_id: int) -> None:
    now = time.time()
    attempts = [t for t in _profile_mutation_rate[user_id] if now - t < _PROFILE_MUTATION_WINDOW]
    _profile_mutation_rate[user_id] = attempts
    if len(attempts) >= _PROFILE_MUTATION_LIMIT:
        raise HTTPException(429, "Muitas requisições. Aguarde um momento e tente novamente.")
    _profile_mutation_rate[user_id].append(now)


# Verificação anti-bot (Cloudflare Turnstile) em login/cadastro. Sem
# TURNSTILE_SECRET_KEY configurada (ex: dev local), pula a verificação --
# mesmo padrão de "integração opcional" já usado pra pagamentos/IA/email
# (ver _OPTIONAL_VARS em main.py).
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _verify_captcha(token: str | None, request: Request) -> None:
    if not TURNSTILE_SECRET_KEY:
        return
    if not token:
        raise HTTPException(status_code=400, detail="Verificação de segurança pendente. Tente novamente.")
    try:
        resp = httpx.post(
            _TURNSTILE_VERIFY_URL,
            data={
                "secret": TURNSTILE_SECRET_KEY,
                "response": token,
                "remoteip": request.headers.get("CF-Connecting-IP") or (request.client.host if request.client else ""),
            },
            timeout=8.0,
        )
        ok = bool(resp.json().get("success"))
    except (httpx.HTTPError, ValueError):
        logging.getLogger("auth").warning("Falha ao contatar Turnstile pra verificação de captcha")
        raise HTTPException(status_code=503, detail="Não foi possível validar a verificação de segurança. Tente novamente.")
    if not ok:
        raise HTTPException(status_code=400, detail="Verificação de segurança falhou. Tente novamente.")


def _hash_token(token: str) -> str:
    """SHA-256 hex digest de um token · nunca armazena plaintext no DB."""
    return hashlib.sha256(token.encode()).hexdigest()

def _logo_data_uri() -> str:
    try:
        data = _LOGO_PATH.read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode()
    except Exception:
        return ""

def _logo_url(site_url: str) -> str:
    return f"{site_url}/static/logo.png"
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_SIZE = 3 * 1024 * 1024  # 3 MB

# Assinaturas de magic bytes para cada formato de imagem permitido
_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "jpg"),          # JPEG
    (b"\x89PNG\r\n\x1a\n", "png"),     # PNG
    (b"GIF87a", "gif"),                # GIF87
    (b"GIF89a", "gif"),                # GIF89
    (b"RIFF", "webp"),                 # WebP (precisa checar bytes 8-12 também)
]


def _detect_image_type(data: bytes) -> str | None:
    """Retorna extensão detectada pelos magic bytes, ou None se não for imagem válida."""
    for sig, ext in _MAGIC_SIGNATURES:
        if data[:len(sig)] == sig:
            if ext == "webp" and data[8:12] != b"WEBP":
                continue
            return ext
    return None


def _validate_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(400, "Senha deve ter pelo menos 10 caracteres")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(400, "Senha deve ter letra maiúscula")
    if not re.search(r"\d", password):
        raise HTTPException(400, "Senha deve ter número")


_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")

# DDDs válidos no Brasil (11-99, exceto blocos não atribuídos)
_VALID_DDDS = {
    11,12,13,14,15,16,17,18,19,
    21,22,24,27,28,
    31,32,33,34,35,37,38,
    41,42,43,44,45,46,47,48,49,
    51,53,54,55,
    61,62,63,64,65,66,67,68,69,
    71,73,74,75,77,79,
    81,82,83,84,85,86,87,88,89,
    91,92,93,94,95,96,97,98,99,
}


def _validate_phone_br(phone: str) -> str:
    """Valida e normaliza telefone brasileiro para E.164 (+55XXXXXXXXXXX)."""
    digits = re.sub(r"\D", "", phone)
    # Remove prefixo +55 ou 55 se presente
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) not in (10, 11):
        raise HTTPException(400, "Telefone inválido. Use o formato (DDD) 9XXXX-XXXX.")
    ddd = int(digits[:2])
    if ddd not in _VALID_DDDS:
        raise HTTPException(400, f"DDD {ddd} inválido. Verifique o número informado.")
    # Celular com 11 dígitos deve começar com 9
    if len(digits) == 11 and digits[2] != "9":
        raise HTTPException(400, "Celular deve começar com 9 após o DDD (ex: 11 9XXXX-XXXX).")
    return f"+55{digits}"


def _generate_username(name: str, cur) -> str:
    """Gera username único a partir do primeiro nome."""
    base = re.sub(r"[^a-z0-9]", "", name.split()[0].lower())[:15] or "user"
    for _ in range(20):
        candidate = base + str(secrets.randbelow(9000) + 1000)
        cur.execute("SELECT id FROM users WHERE username = %s", (candidate,))
        if not cur.fetchone():
            return candidate
    return base + secrets.token_hex(3)


def _resolve_identifier(identifier: str) -> tuple[str, str]:
    """Detecta tipo do identificador e retorna (tipo, valor_normalizado).
    Tipos: 'email', 'username'

    O CPF era um terceiro tipo ate 18/08/2026 e saiu junto com o campo do
    cadastro: manter o login por um dado que conta nova nao tem mais so'
    serviria pra sustentar uma coluna que ninguem alimenta. Quem tinha CPF
    continua entrando por e-mail ou usuario, que toda conta tem.
    """
    stripped = identifier.strip()
    if "@" in stripped:
        return "email", stripped.lower()
    return "username", stripped.lower()


router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── helpers ─────────────────────────────────────────────────────────────────

# Header que o app nativo (Android/iOS) manda em todas as chamadas. Navegador
# nenhum manda isso sozinho, então serve de opt-in explícito.
_HEADER_CLIENTE = "x-client-platform"
_CLIENTES_NATIVOS = {"android", "ios"}


def _e_cliente_nativo(request: Request) -> bool:
    """True quando quem chama é o app, não o site."""
    return request.headers.get(_HEADER_CLIENTE, "").strip().lower() in _CLIENTES_NATIVOS


def _tokens_no_corpo(request: Request, access_token: str, refresh_token: str | None) -> dict:
    """Tokens no corpo da resposta -- só para o app nativo.

    O site continua exatamente como está: sessão em cookie httpOnly, nada a
    mais no corpo. Este bloco existe porque Android e iOS não têm cookie jar
    confiável entre reinícios do app, então lá a sessão persistente mora no
    keystore do sistema (expo-secure-store) e o cliente precisa receber o
    token para poder guardá-lo. `auth_utils.get_current_user` já aceitava
    Bearer como fallback justamente para esse caso -- o que faltava era o
    caminho de entrega do token.

    Segurança: o custo real é o refresh token virar credencial de 30 dias na
    mão do cliente. Isso é aceitável aqui porque ele nasce amarrado ao
    `session_id`, e a sessão única já invalida o token antigo no próximo
    login do usuário. Para o navegador nada muda: sem o header, nada disso
    aparece no corpo.
    """
    if not _e_cliente_nativo(request):
        return {}
    saida = {"access_token": access_token, "token_type": "bearer"}
    if refresh_token:
        saida["refresh_token"] = refresh_token
    return saida


def _send_email(to: str, subject: str, body: str, html: str | None = None):
    api_key  = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("RESEND_FROM", "Pick IA <contato@pickia.com.br>")

    if not api_key:
        logger.warning("[EMAIL] RESEND_API_KEY não configurado · email para %s ignorado", to)
        return

    resend.api_key = api_key
    params: resend.Emails.SendParams = {
        "from": from_addr,
        "to":   [to],
        "subject": subject,
        "text": body,
    }
    if html:
        params["html"] = html

    try:
        resend.Emails.send(params)
        logger.info("[EMAIL] Enviado para %s · assunto: %s", to, subject)
    except Exception as e:
        logger.error("[EMAIL] Falha ao enviar para %s: %s", to, e)


def _welcome_html(first_name: str, site_url: str, logo_b64: str = "", logo_url: str = "") -> str:
    logo_src = logo_url or logo_b64
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#111;border:1px solid #222;border-radius:16px;overflow:hidden;max-width:560px;width:100%;">

        <!-- Header verde -->
        <tr><td style="background:linear-gradient(135deg,#16a34a,#15803d);padding:36px 40px;text-align:center;">
          <img src="{logo_src}" alt="Pick IA" width="80" height="80"
               style="border-radius:50%;margin-bottom:16px;display:block;margin-left:auto;margin-right:auto;" />
          <h1 style="margin:0;color:#fff;font-size:28px;font-weight:900;letter-spacing:-0.5px;">
            Pick<span style="color:#bbf7d0;">IA</span>
          </h1>
          <p style="margin:6px 0 0;color:#dcfce7;font-size:14px;">Tips esportivas por Inteligência Artificial</p>
        </td></tr>

        <!-- Corpo -->
        <tr><td style="padding:36px 40px;">
          <p style="margin:0 0 8px;color:#71717a;font-size:13px;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Bem-vindo,</p>
          <h2 style="margin:0 0 20px;color:#fff;font-size:22px;font-weight:800;">{first_name}!</h2>
          <p style="margin:0 0 28px;color:#a1a1aa;font-size:15px;line-height:1.6;">
            Sua conta foi criada com sucesso. Você tem <strong style="color:#22c55e;">2 dias de acesso VIP gratuito</strong> para explorar todas as funcionalidades.
          </p>

          <!-- Features -->
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
            <tr>
              <td width="48%" style="background:#1a1a1a;border:1px solid #262626;border-radius:12px;padding:16px;vertical-align:top;">
                <div style="color:#22c55e;font-size:20px;margin-bottom:8px;">&#9679;</div>
                <div style="color:#fff;font-size:14px;font-weight:700;margin-bottom:4px;">Picks VIP com IA</div>
                <div style="color:#71717a;font-size:12px;line-height:1.5;">Análises diárias geradas por IA com odds e mercados otimizados.</div>
              </td>
              <td width="4%"></td>
              <td width="48%" style="background:#1a1a1a;border:1px solid #262626;border-radius:12px;padding:16px;vertical-align:top;">
                <div style="color:#3b82f6;font-size:20px;margin-bottom:8px;">&#9632;</div>
                <div style="color:#fff;font-size:14px;font-weight:700;margin-bottom:4px;">Múltiplas e Alavancagem</div>
                <div style="color:#71717a;font-size:12px;line-height:1.5;">Combinações inteligentes para maximizar o retorno da banca.</div>
              </td>
            </tr>
            <tr><td colspan="3" style="padding-top:12px;"></td></tr>
            <tr>
              <td width="48%" style="background:#1a1a1a;border:1px solid #262626;border-radius:12px;padding:16px;vertical-align:top;">
                <div style="color:#ef4444;font-size:20px;margin-bottom:8px;">&#9679;</div>
                <div style="color:#fff;font-size:14px;font-weight:700;margin-bottom:4px;">Ao Vivo</div>
                <div style="color:#71717a;font-size:12px;line-height:1.5;">Acompanhe seus picks em tempo real com estatísticas da partida.</div>
              </td>
              <td width="4%"></td>
              <td width="48%" style="background:#1a1a1a;border:1px solid #262626;border-radius:12px;padding:16px;vertical-align:top;">
                <div style="color:#f59e0b;font-size:20px;margin-bottom:8px;">&#9650;</div>
                <div style="color:#fff;font-size:14px;font-weight:700;margin-bottom:4px;">Gestão de Banca</div>
                <div style="color:#71717a;font-size:12px;line-height:1.5;">Controle de bankroll, metas e histórico completo de resultados.</div>
              </td>
            </tr>
          </table>

          <!-- CTA -->
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">
              <a href="{site_url}/picks"
                 style="display:inline-block;background:#16a34a;color:#fff;text-decoration:none;font-weight:800;font-size:15px;padding:14px 40px;border-radius:10px;letter-spacing:0.3px;">
                Acessar meus picks
              </a>
            </td></tr>
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="border-top:1px solid #1f1f1f;padding:20px 40px;text-align:center;">
          <p style="margin:0 0 6px;color:#52525b;font-size:12px;">
            Siga no Instagram:
            <a href="https://www.instagram.com/pickia.br/" style="color:#22c55e;text-decoration:none;">@pickia.br</a>
          </p>
          <p style="margin:0;color:#3f3f46;font-size:11px;">Pick IA &mdash; Tips por Inteligência Artificial</p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _verification_html(first_name: str, site_url: str, token: str, logo_b64: str = "", logo_url: str = "") -> str:
    logo_src = logo_url or logo_b64
    verify_url = f"{site_url}/verify-email?token={token}"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#111;border:1px solid #222;border-radius:16px;overflow:hidden;max-width:560px;width:100%;">
        <tr><td style="background:linear-gradient(135deg,#16a34a,#15803d);padding:36px 40px;text-align:center;">
          <img src="{logo_src}" alt="Pick IA" width="80" height="80"
               style="border-radius:50%;margin-bottom:16px;display:block;margin-left:auto;margin-right:auto;" />
          <h1 style="margin:0;color:#fff;font-size:28px;font-weight:900;letter-spacing:-0.5px;">Pick<span style="color:#bbf7d0;">IA</span></h1>
          <p style="margin:6px 0 0;color:#dcfce7;font-size:14px;">Tips esportivas por Inteligência Artificial</p>
        </td></tr>
        <tr><td style="padding:36px 40px;text-align:center;">
          <p style="margin:0 0 8px;color:#71717a;font-size:13px;text-transform:uppercase;letter-spacing:1px;font-weight:600;">Bem-vindo,</p>
          <h2 style="margin:0 0 16px;color:#fff;font-size:22px;font-weight:800;">{first_name}!</h2>
          <p style="margin:0 0 8px;color:#a1a1aa;font-size:15px;line-height:1.6;">
            Sua conta foi criada. Para ativar seu <strong style="color:#22c55e;">acesso VIP gratuito de 2 dias</strong>,<br>confirme seu e-mail clicando no botão abaixo.
          </p>
          <p style="margin:0 0 28px;color:#52525b;font-size:12px;">O link expira em 24 horas.</p>
          <a href="{verify_url}"
             style="display:inline-block;background:#16a34a;color:#fff;text-decoration:none;font-weight:800;font-size:16px;padding:16px 48px;border-radius:12px;letter-spacing:0.3px;">
            Confirmar e-mail
          </a>
        </td></tr>
        <tr><td style="border-top:1px solid #1f1f1f;padding:20px 40px;text-align:center;">
          <p style="margin:0 0 6px;color:#52525b;font-size:12px;">
            Siga no Instagram: <a href="https://www.instagram.com/pickia.br/" style="color:#22c55e;text-decoration:none;">@pickia.br</a>
          </p>
          <p style="margin:0;color:#3f3f46;font-size:11px;">Pick IA &mdash; Tips por Inteligência Artificial</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_verification_email(to: str, name: str, token: str, site_url: str) -> None:
    first_name = name.strip().split()[0]
    verify_url = f"{site_url}/verify-email?token={token}"
    _send_email(
        to=to,
        subject="Seu cadastro no Pick IA está quase pronto",
        body=(
            f"Olá {first_name},\n\n"
            f"Confirme seu e-mail para ativar seu acesso VIP gratuito de 2 dias:\n\n"
            f"{verify_url}\n\n"
            f"O link expira em 24 horas.\n\n"
            f"Equipe Pick IA"
        ),
        html=_verification_html(first_name, site_url, token, logo_url=_logo_url(site_url)),
    )


# ── models ───────────────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: str
    username: Optional[str] = None
    ref_code: Optional[str] = None
    accepted_terms: bool = False
    captcha_token: Optional[str] = None

class LoginBody(BaseModel):
    identifier: str  # e-mail ou username
    password: str
    captcha_token: Optional[str] = None

class ForgotPasswordBody(BaseModel):
    email: EmailStr

class ResetPasswordBody(BaseModel):
    email: EmailStr
    code: str
    new_password: str

class UpdateProfileBody(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    username: Optional[str] = None


class VerifyPhoneBody(BaseModel):
    code: str


class RequestPasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


class ConfirmPasswordChangeBody(BaseModel):
    code: str


# ── endpoints ────────────────────────────────────────────────────────────────

@router.post("/register")
def register(body: RegisterBody, response: Response, background_tasks: BackgroundTasks, request: Request):
    _verify_captcha(body.captcha_token, request)
    if not body.accepted_terms:
        raise HTTPException(status_code=400, detail="Você precisa aceitar os Termos de Uso e a Política de Privacidade.")
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE email = %s", (body.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email já cadastrado")

        # Valida phone e username.
        #
        # O CPF saiu do cadastro em 18/08/2026. Ele nunca teve funcao fiscal
        # aqui -- nao aparece em pagamento nem em nota, so' ancorava o trial --
        # e pedir CPF em site de aposta e' onde o cadastro morre. Quem segura o
        # trial agora e' o telefone: CPF de terceiro se acha no Google, chip
        # novo custa dinheiro. Ele ja era coletado, so' nao era unico.
        phone_e164 = _validate_phone_br(body.phone)
        cur.execute("SELECT id FROM users WHERE phone = %s", (phone_e164,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Telefone já cadastrado. Cada número permite apenas 1 conta.")

        # Resolve username (obrigatório)
        raw_username = (body.username or "").strip().lstrip("@").lower()
        if not raw_username:
            raise HTTPException(status_code=400, detail="Escolha um nome de usuário.")
        if not _USERNAME_RE.match(raw_username):
            raise HTTPException(status_code=400, detail="Usuário inválido. Use 3–20 caracteres: letras minúsculas, números e _")
        cur.execute("SELECT id FROM users WHERE username = %s", (raw_username,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Usuário já em uso. Escolha outro.")
        final_username = raw_username

        # Resolve referrer
        referrer_id: Optional[int] = None
        if body.ref_code:
            cur.execute("SELECT id FROM users WHERE referral_code = %s", (body.ref_code.upper(),))
            ref_row = cur.fetchone()
            if ref_row:
                referrer_id = ref_row["id"]

        # Gera código de indicação único para o novo usuário
        new_ref_code: Optional[str] = None
        for _ in range(10):
            candidate = secrets.token_hex(3).upper()
            cur.execute("SELECT id FROM users WHERE referral_code = %s", (candidate,))
            if not cur.fetchone():
                new_ref_code = candidate
                break

        _validate_password(body.password)
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        cur.execute(
            "INSERT INTO users (name, email, password_hash, phone, username, referred_by, referral_code, terms_accepted_at, terms_ip) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s) RETURNING id, name, email, phone, username, plan, active, expires_at",
            (' '.join(w.capitalize() for w in body.name.strip().split()), body.email, hash_password(body.password), phone_e164, final_username, referrer_id, new_ref_code, client_ip),
        )
        user = dict(cur.fetchone())
        # O trial NAO nasce mais junto com a conta.
        #
        # Antes ele saia no INSERT porque o CPF obrigatorio ja era a barreira.
        # Sem CPF, dar 2 dias de VIP a quem so' digitou um e-mail entrega o
        # trial pra qualquer descartavel. Agora ele espera a prova de contato
        # e sai por `_ativar_trial_se_elegivel`, no link do e-mail ou no
        # codigo do WhatsApp. Efeito colateral bom: o trial vira a recompensa
        # de confirmar o contato, que e' o que faz a base ficar limpa.
        plan_final = "free"
        expires_final = None

        # Crédito de indicação por registro: +1 dia VIP para o referrer
        if referrer_id:
            cur.execute(
                """
                UPDATE users
                SET plan      = CASE WHEN plan IN ('free', 'trial') THEN 'vip' ELSE plan END,
                    expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW()) + INTERVAL '1 day'
                WHERE id = %s
                """,
                (referrer_id,),
            )

        # Commit do INSERT, trial e crédito de indicação ANTES do token
        conn.commit()

        # Token de verificação de e-mail (operação separada; não desfaz o cadastro se falhar)
        email_token: Optional[str] = None
        try:
            email_token = secrets.token_urlsafe(32)
            cur.execute("UPDATE users SET email_verification_token=%s WHERE id=%s", (_hash_token(email_token), user["id"]))
            conn.commit()
        except Exception:
            conn.rollback()
            email_token = None

        # Sessão única: gera token e guarda hash no banco
        session_id = secrets.token_hex(32)
        cur.execute("UPDATE users SET session_token=%s WHERE id=%s",
                    (hashlib.sha256(session_id.encode()).hexdigest(), user["id"]))
        conn.commit()
        invalidar_cache_usuario(user["id"])

        user["plan"] = plan_final
        user["expires_at"] = expires_final
        user["email_verified"] = False
        token_data = {
            "sub": str(user["id"]), "id": user["id"],
            "name": user["name"], "email": user["email"],
            "plan": plan_final, "plan_expires_at": expires_final,
            "avatar_url": None,
            "session_id": session_id,
        }
        access_token  = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        set_auth_cookies(response, access_token, refresh_token)

        # Envio de e-mail de verificação em background (não bloqueia a resposta)
        site_url = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")
        if email_token:
            background_tasks.add_task(_send_verification_email, body.email, body.name, email_token, site_url)

        return {"user": user, **_tokens_no_corpo(request, access_token, refresh_token)}
    finally:
        cur.close(); conn.close()


def _mascarar_email(email: str) -> str:
    """`fulano@dominio.com` -> `fu***@dominio.com`.

    A pessoa precisa reconhecer o endereco pra saber onde procurar (ou pra
    perceber que digitou errado), mas a resposta de um 403 nao deve entregar
    o e-mail inteiro de uma conta pra quem estiver com a tela na frente.
    """
    usuario, _, dominio = email.partition("@")
    if not dominio:
        return email
    visivel = usuario[:2] if len(usuario) > 2 else usuario[:1]
    return f"{visivel}***@{dominio}"


def _deve_barrar_por_email(plano: str | None, gate_travado: bool | None) -> bool:
    """A conta perde o login por nao ter confirmado o e-mail?

    Funcao separada porque esta e a regra que fica entre o assinante e o
    produto que ele pagou. Ate a correcao de 18/08/2026 ela olhava so a data e
    o e-mail, e um assinante novo que nunca clicou no link levaria 403 no
    terceiro dia -- pagando. Aqui ela fica testavel sem subir servidor nenhum.

    So barra quem esta no free. VIP, trial e admin entram sempre.
    """
    return plano == "free" and bool(gate_travado)


def _reenviar_verificacao_no_gate(cur, conn, user: dict, background_tasks: BackgroundTasks) -> None:
    """Gera um link novo e agenda o envio, respeitando o cooldown.

    Envolto em try/except porque nada aqui pode mudar a resposta: o login ja
    esta barrado de qualquer forma, e falhar o reenvio nao deve virar 500 --
    a pessoa ainda tem o e-mail original na caixa.
    """
    agora = time.time()
    ultimo = _email_gate_ultimo_reenvio.get(user["id"], 0.0)
    if agora - ultimo < EMAIL_GATE_REENVIO_COOLDOWN_SECS:
        return
    try:
        token = secrets.token_urlsafe(32)
        cur.execute(
            "UPDATE users SET email_verification_token=%s WHERE id=%s",
            (_hash_token(token), user["id"]),
        )
        conn.commit()
        _email_gate_ultimo_reenvio[user["id"]] = agora
        site_url = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")
        background_tasks.add_task(
            _send_verification_email, user["email"], user["name"], token, site_url
        )
    except Exception as e:
        conn.rollback()
        logger.warning("[LOGIN] Falha ao reenviar verificacao (user %s): %s", user["id"], e)


@router.post("/login")
def login(body: LoginBody, response: Response, request: Request, background_tasks: BackgroundTasks):
    _verify_captcha(body.captcha_token, request)
    lockout_key = body.identifier.strip().lower()
    _check_account_lockout(lockout_key)

    conn = get_connection()
    cur = conn.cursor()
    try:
        id_type, id_value = _resolve_identifier(body.identifier)
        # O gate e' avaliado no banco de proposito: `created_at` e' TIMESTAMP
        # sem fuso, entao compara-lo com um datetime do Python exigiria
        # adivinhar o fuso da coluna. No SQL, ele e o NOW() vivem no mesmo
        # referencial e a pergunta se responde sozinha. Os dois valores
        # interpolados sao constantes do modulo, nunca entrada de usuario.
        _LOGIN_COLS = (
            "id, name, email, phone, username, password_hash, plan, active, expires_at, "
            "email_verified, avatar_url, "
            f"(email_verified IS NOT TRUE "
            f" AND created_at >= DATE '{EMAIL_GATE_DESDE}' "
            f" AND created_at < NOW() - INTERVAL '{EMAIL_GATE_CARENCIA_DIAS} days') AS email_gate_travado"
        )
        if id_type == "email":
            cur.execute(f"SELECT {_LOGIN_COLS} FROM users WHERE email = %s", (id_value,))
        else:
            cur.execute(f"SELECT {_LOGIN_COLS} FROM users WHERE username = %s", (id_value,))
        row = cur.fetchone()
        if not row:
            _record_account_failure(lockout_key)
            raise HTTPException(status_code=401, detail="Credenciais inválidas")

        user = dict(row)
        if not user["active"]:
            raise HTTPException(status_code=403, detail="Conta desativada")
        if not verify_password(body.password, user["password_hash"]):
            _record_account_failure(lockout_key)
            raise HTTPException(status_code=401, detail="Credenciais inválidas")
        _account_login_failures.pop(lockout_key, None)

        # Passou da carencia sem confirmar o e-mail: barra e reenvia o link.
        #
        # O reenvio sai daqui, e nao de um endpoint publico, porque a senha ja
        # foi conferida duas linhas acima -- ninguem consegue usar isto pra
        # descobrir se um e-mail tem conta, nem pra disparar e-mail pros
        # outros. E' tambem o unico caminho que sobra pra pessoa: /auth/
        # resend-verification exige estar logada, e logada ela nao consegue
        # mais ficar.
        # Auto-expire VIP/trial expirado.
        #
        # Vem ANTES do gate de e-mail de proposito: e' ele quem decide se a
        # conta ainda tem plano, e o gate so' vale pra quem esta' no free.
        if user["plan"] in ("vip", "trial") and user.get("expires_at"):
            exp = user["expires_at"]
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                cur.execute("UPDATE users SET plan='free', expires_at=NULL WHERE id=%s", (user["id"],))
                conn.commit()
                user["plan"] = "free"
                user["expires_at"] = None

        # Passou da carencia sem confirmar o e-mail: barra e reenvia o link.
        #
        # SO' PRA QUEM ESTA' NO FREE. Quem tem VIP, trial ou admin entra sempre,
        # confirmado ou nao: trancar do lado de fora alguem que acabou de pagar
        # e' o pior erro possivel desta tela, e nao seria hipotetico -- ate' a
        # correcao de 18/08/2026 a condicao olhava so' a data e o e-mail, entao
        # um assinante novo que nunca clicou no link levaria 403 no terceiro
        # dia. O trial nem chega aqui, ja' que so' nasce apos a verificacao.
        if _deve_barrar_por_email(user["plan"], user.get("email_gate_travado")):
            _reenviar_verificacao_no_gate(cur, conn, user, background_tasks)
            raise HTTPException(
                status_code=403,
                detail=(
                    "Confirme seu e-mail para continuar. Acabamos de reenviar o link para "
                    f"{_mascarar_email(user['email'])} · confira também o spam."
                ),
            )

        # Sessão única: novo login invalida sessão anterior e grava dispositivo
        device = _detect_device(request.headers.get("user-agent", ""))
        session_id = secrets.token_hex(32)
        cur.execute(
            "UPDATE users SET session_token=%s, last_login_device=%s, last_login_at=NOW() WHERE id=%s",
            (hashlib.sha256(session_id.encode()).hexdigest(), device, user["id"])
        )
        conn.commit()
        # Sem isto, a sessao do aparelho ANTIGO sobreviveria ate o TTL do cache
        # em auth_utils -- o "voce foi desconectado" chegaria 30s atrasado.
        invalidar_cache_usuario(user["id"])

        # Aviso de plano perto de vencer · sino + e-mail, uma vez por faixa
        # (ver plan_expiry.py). Fica no login porque este backend nao tem mais
        # scheduler, e porque e' aqui que a pessoa esta olhando.
        #
        # Envolto em try/except de proposito: nem notificacao nem e-mail podem
        # derrubar um login. Se isto falhar, o usuario entra do mesmo jeito e
        # o proximo login tenta de novo (a faixa so' e' marcada quando o
        # INSERT da notificacao passa).
        try:
            from plan_expiry import avisar_plano_expirando
            from runtime_env import side_effects_enabled
            avisar_plano_expirando(
                cur, user,
                site_url=(os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/"),
                # Staging aponta pro banco de PRODUCAO: sem esse freio, um
                # login de teste no noprod mandaria e-mail de renovacao de
                # verdade. A notificacao no sino continua (idempotente).
                enviar_email=_send_email if side_effects_enabled() else None,
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning("[LOGIN] Falha ao avisar plano expirando (user %s): %s", user["id"], e)

        # Auto-reparo de assinatura. Se a pessoa foi pro MercadoPago e voltou
        # sem acesso, pergunta ao MercadoPago antes de montar o token · assim
        # ela entra ja como VIP, sem precisar recarregar.
        #
        # Fecha o unico caso que as outras camadas nao pegam: pagou por boleto
        # ou Pix, fechou o navegador antes da aprovacao, o webhook falhou, e so'
        # voltou dias depois. Custa consulta a API, entao so' roda pra quem
        # comecou um checkout ha' pouco e continua sem plano -- nao pra todo
        # login. Mesma logica do aviso de plano expirando acima: este backend
        # nao tem scheduler, e o login e' o momento em que a pessoa esta aqui.
        # A leitura de checkout_started_at fica FORA da query principal, e num
        # try proprio, de proposito: a coluna nasce numa migration de startup, e
        # se por qualquer motivo ela nao existir no banco, o pior que acontece e'
        # o auto-reparo nao rodar. Dentro do SELECT do login, a mesma ausencia
        # derrubaria o login de todo mundo.
        if user["plan"] in ("free", "trial"):
            iniciado = None
            try:
                cur.execute("SELECT checkout_started_at FROM users WHERE id = %s", (user["id"],))
                linha = cur.fetchone()
                iniciado = linha["checkout_started_at"] if linha else None
            except Exception as e:
                conn.rollback()
                logger.warning("[LOGIN] checkout_started_at indisponivel: %s", e)

            if iniciado:
                if iniciado.tzinfo is None:
                    iniciado = iniciado.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - iniciado < timedelta(days=30):
                    from routers.payments import try_activate_pending
                    ativado = try_activate_pending(user["id"])
                    if ativado:
                        logger.info("[LOGIN] VIP ativado no login para user %s (pagamento %s)",
                                    user["id"], ativado["payment_id"])
                        user["plan"] = "vip"
                        user["expires_at"] = ativado["expires_at"]

        plan_expires_at = user["expires_at"].isoformat() if user.get("expires_at") else None
        token_data = {
            "sub": str(user["id"]), "id": user["id"],
            "name": user["name"], "email": user["email"],
            "plan": user["plan"], "plan_expires_at": plan_expires_at,
            "avatar_url": user.get("avatar_url"),
            "session_id": session_id,
        }
        access_token  = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        set_auth_cookies(response, access_token, refresh_token)
        user.pop("password_hash")
        user["expires_at"] = plan_expires_at
        return {"user": user, **_tokens_no_corpo(request, access_token, refresh_token)}
    finally:
        cur.close(); conn.close()


@router.post("/logout")
def logout(request: Request, response: Response, bearer: str | None = Depends(oauth2_scheme)):
    """Além de limpar os cookies no navegador, gira o session_token no banco --
    sem isso, um access token já emitido (ex: copiado por XSS, ou em uso via
    Bearer no mobile) continuava válido por até 12h mesmo depois do logout,
    já que só o cookie local era apagado, nunca a sessão no servidor."""
    token = request.cookies.get(COOKIE_NAME) or bearer
    if token:
        try:
            payload = decode_token(token)
            user_id = payload.get("sub")
        except HTTPException:
            user_id = None
        if user_id:
            conn = get_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE users SET session_token = %s WHERE id = %s",
                    (hashlib.sha256(secrets.token_hex(32).encode()).hexdigest(), user_id),
                )
                conn.commit()
                invalidar_cache_usuario(user_id)
            finally:
                cur.close(); conn.close()
    clear_auth_cookies(response)
    return {"status": "ok"}


@router.post("/logout-other-sessions")
def logout_other_sessions(response: Response, current_user: dict = Depends(get_current_user)):
    """Encerra qualquer outra sessão ativa (girando o session_token) sem
    exigir troca de senha -- util quando o usuario suspeita que esqueceu
    logado em outro aparelho. Emite um novo par de tokens pra manter o
    dispositivo atual logado."""
    _reissue_tokens_for_user(response, current_user["sub"], current_user.get("name", ""), current_user.get("email", ""))
    return {"ok": True}


class VerifyEmailBody(BaseModel):
    token: str


def _send_welcome_email(to: str, name: str, site_url: str) -> None:
    first_name = name.strip().split()[0]
    _send_email(
        to,
        subject=f"{first_name}, seus picks estão te esperando",
        body=f"Olá {first_name}, sua conta foi confirmada! Acesse: {site_url}/picks",
        html=_welcome_html(first_name, site_url, logo_url=_logo_url(site_url)),
    )


def _ativar_trial_se_elegivel(cur, user_id: int) -> Optional[datetime]:
    """Libera os 2 dias de VIP quando a conta prova um contato real.

    Regra unica pros tres caminhos que ativam trial -- o link do e-mail, o
    botao do perfil e o codigo do WhatsApp, quando a WABA sair -- pra que a
    condicao nao se separe em tres copias que divergem. Vale e-mail OU
    telefone: se a Meta reprovar o template de OTP, o cadastro continua
    entregando trial pelo e-mail em vez de travar.

    Retorna o vencimento quando ativou e None quando nao havia o que ativar.
    Nao commita de proposito: quem chama e' dono da transacao.
    """
    cur.execute(
        "SELECT plan, trial_used, email_verified, phone_verified FROM users WHERE id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    u = dict(row)
    if u.get("plan") != "free" or u.get("trial_used"):
        return None
    if not (u.get("email_verified") or u.get("phone_verified")):
        return None
    expira = datetime.now(timezone.utc) + timedelta(days=2)
    cur.execute(
        "UPDATE users SET plan='trial', expires_at=%s, trial_used=TRUE WHERE id=%s",
        (expira, user_id),
    )
    return expira


@router.post("/verify-email")
def verify_email_endpoint(body: VerifyEmailBody, background_tasks: BackgroundTasks):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, email, name FROM users WHERE email_verification_token = %s",
            (_hash_token(body.token),),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(400, "Link inválido ou já utilizado.")
        cur.execute(
            "UPDATE users SET email_verified=true, email_verification_token=NULL WHERE id=%s",
            (row["id"],),
        )
        # Confirmar o e-mail e' o que paga o trial agora. O cookie de sessao
        # nao e' reemitido aqui porque este endpoint tambem roda deslogado
        # (link aberto em outro aparelho); o plano novo entra no proximo
        # /auth/me, que e' o que a tela consulta ao voltar.
        trial_expira = _ativar_trial_se_elegivel(cur, row["id"])
        conn.commit()
        site_url = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")
        background_tasks.add_task(_send_welcome_email, row["email"], row["name"], site_url)
        return {
            "ok": True,
            "trial_ativado": trial_expira is not None,
            "trial_expires_at": trial_expira.isoformat() if trial_expira else None,
        }
    finally:
        cur.close(); conn.close()


@router.post("/resend-verification")
def resend_verification(background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT email, name, email_verified FROM users WHERE id=%s", (current_user["id"],))
        row = cur.fetchone()
        if not row or row["email_verified"]:
            return {"ok": True}
        token = secrets.token_urlsafe(32)
        cur.execute("UPDATE users SET email_verification_token=%s WHERE id=%s", (_hash_token(token), current_user["id"]))
        conn.commit()
        site_url = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")
        background_tasks.add_task(_send_verification_email, row["email"], row["name"], token, site_url)
        return {"ok": True}
    finally:
        cur.close(); conn.close()


@router.post("/refresh")
def refresh_token(request: Request, response: Response):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token and _e_cliente_nativo(request):
        # App nativo guarda o refresh no keystore e o manda como Bearer, já
        # que não tem o cookie de path /api/auth/refresh. Só é lido aqui,
        # onde o token de refresh é esperado -- nas rotas normais continua
        # valendo a regra de `get_current_user`, que recusa type != access.
        cabecalho = request.headers.get("authorization", "")
        if cabecalho.lower().startswith("bearer "):
            token = cabecalho[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")
    try:
        payload = decode_token(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Refresh token inválido")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token incorreto")

    # Busca dados atualizados do usuário no banco
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, name, email, plan, active, expires_at, avatar_url FROM users WHERE id = %s",
            (int(payload["sub"]),),
        )
        row = cur.fetchone()
        if not row or not row["active"]:
            raise HTTPException(status_code=401, detail="Usuário inativo")
        user = dict(row)

        # Auto-expire: se VIP/trial expirou, baixa para free no banco agora
        if user["plan"] in ("vip", "trial") and user.get("expires_at"):
            exp = user["expires_at"]
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                cur.execute("UPDATE users SET plan='free', expires_at=NULL WHERE id=%s", (user["id"],))
                conn.commit()
                user["plan"] = "free"
                user["expires_at"] = None

    finally:
        cur.close(); conn.close()

    plan_expires_at = user["expires_at"].isoformat() if user.get("expires_at") else None
    token_data = {
        "sub": str(user["id"]), "id": user["id"],
        "name": user["name"], "email": user["email"],
        "plan": user["plan"], "plan_expires_at": plan_expires_at,
        "avatar_url": user.get("avatar_url"),
    }
    if payload.get("session_id"):
        token_data["session_id"] = payload["session_id"]
    new_access = create_access_token(token_data)
    set_access_cookie(response, new_access)  # não renova o refresh → sessão expira em 30 dias
    return {"status": "ok", **_tokens_no_corpo(request, new_access, None)}


@router.post("/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    _check_profile_rate(current_user["sub"])
    # Primeira checagem: content-type declarado (pode ser forjado)
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, "Tipo de arquivo inválido. Use JPG, PNG ou WebP.")

    contents = file.file.read()
    if len(contents) > _MAX_SIZE:
        raise HTTPException(400, "Arquivo muito grande. Máximo 3 MB.")

    # Segunda checagem: magic bytes reais do arquivo (não pode ser forjado)
    detected_ext = _detect_image_type(contents)
    if not detected_ext:
        raise HTTPException(400, "Arquivo não reconhecido como imagem válida.")

    ext = detected_ext

    uid = current_user["sub"]
    dest = _AVATARS_DIR / f"{uid}.{ext}"

    # Remove avatar anterior de qualquer extensão
    for old in _AVATARS_DIR.glob(f"{uid}.*"):
        old.unlink(missing_ok=True)

    dest.write_bytes(contents)
    avatar_url = f"/static/avatars/{uid}.{ext}"

    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (avatar_url, uid))
        conn.commit()
    finally:
        cur.close(); conn.close()

    return {"avatar_url": avatar_url}


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, name, email, phone, username, plan, active, expires_at, subscription_type, created_at, avatar_url, trial_used, email_verified, phone_verified, last_login_device, last_login_at FROM users WHERE id = %s",
            (current_user["sub"],),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        d = dict(row)
        if d.get("last_login_at"):
            d["last_login_at"] = d["last_login_at"].isoformat()
        # Auto-expire: mesma lógica do login/refresh
        if d.get("plan") in ("vip", "trial") and d.get("expires_at"):
            exp = d["expires_at"]
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                cur.execute("UPDATE users SET plan='free', expires_at=NULL WHERE id=%s", (d["id"],))
                conn.commit()
                d["plan"] = "free"
                d["expires_at"] = None
        if d.get("expires_at"):
            d["expires_at"] = d["expires_at"].isoformat()
        # A tela do perfil so' oferece verificacao por SMS quando ha provedor
        # configurado. Sem isso, o botao responderia "codigo enviado" com o
        # codigo indo pro log do servidor e o usuario esperando um SMS que
        # nunca sai. Vem do backend, e nao de uma constante no front, pra que
        # ligar o SMS seja so' setar a variavel no Railway -- sem deploy novo.
        d["sms_disponivel"] = sms_configurado()
        return d
    finally:
        cur.close(); conn.close()


@router.post("/activate-trial")
def activate_trial(response: Response, current_user: dict = Depends(get_current_user)):
    """Ativa 2 dias de trial VIP para usuários free que nunca usaram trial."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, plan, trial_used, email_verified, phone_verified FROM users WHERE id = %s",
            (current_user["sub"],),
        )
        user = cur.fetchone()
        if not user:
            raise HTTPException(404, "Usuário não encontrado")
        user = dict(user)

        if user.get("trial_used"):
            raise HTTPException(400, "Você já utilizou o período de teste gratuito.")

        if user["plan"] not in ("free",):
            raise HTTPException(400, "Disponível apenas para usuários Free.")

        if not (user.get("email_verified") or user.get("phone_verified")):
            raise HTTPException(400, "Confirme seu e-mail para ativar o teste gratuito. O link foi enviado no cadastro.")

        trial_expires = _ativar_trial_se_elegivel(cur, current_user["sub"])
        if not trial_expires:
            raise HTTPException(400, "Não foi possível ativar o teste gratuito.")
        conn.commit()

        token_data = {
            "sub": str(current_user["sub"]), "id": current_user["id"],
            "name": current_user.get("name", ""), "email": current_user.get("email", ""),
            "plan": "trial", "plan_expires_at": trial_expires.isoformat(),
            "avatar_url": current_user.get("avatar_url"),
        }
        access_token  = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        set_auth_cookies(response, access_token, refresh_token)
        return {
            "plan": "trial",
            "expires_at": trial_expires.isoformat(),
            "message": "Trial VIP ativado com sucesso! Você tem 2 dias de acesso completo.",
        }
    finally:
        cur.close(); conn.close()


# ── Verificação de telefone por SMS ──────────────────────────────────────────
#
# O telefone virou a chave de "1 conta por pessoa" quando o CPF saiu do
# cadastro, mas número não conferido não prova nada -- dá pra digitar o do
# vizinho. Estes dois endpoints são o que transforma `users.phone` em barreira,
# e o que faz `phone_verified` valer trial em `_ativar_trial_se_elegivel`.

PHONE_CODE_VALIDADE_MIN   = 10
PHONE_CODE_MAX_TENTATIVAS = 5
PHONE_CODE_COOLDOWN_SEGS  = 60
PHONE_CODE_MAX_POR_DIA    = 5


def _gerar_codigo_numerico() -> str:
    """6 dígitos, com `secrets` e não `random`.

    `random` é previsível a partir de saídas anteriores · para um código que
    dá acesso a trial, isso é uma chave adivinhável.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


@router.post("/phone/send-code")
def enviar_codigo_telefone(current_user: dict = Depends(get_current_user)):
    """Manda um código de 6 dígitos por SMS para o telefone da conta."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT phone, phone_verified FROM users WHERE id = %s",
            (current_user["sub"],),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Usuário não encontrado")
        row = dict(row)
        if not row.get("phone"):
            raise HTTPException(400, "Cadastre um telefone no perfil antes de verificar.")
        if row.get("phone_verified"):
            return {"ok": True, "ja_verificado": True}
        # A UI ja esconde o botao quando nao ha provedor, mas quem chama a API
        # direto precisa ouvir "nao da" em vez de receber sucesso e esperar um
        # SMS que ficou so' no log.
        if not sms_configurado():
            raise HTTPException(503, "Verificação por SMS indisponível no momento. Confirme seu e-mail.")

        # Cooldown e teto diário no banco, não em memória: o Railway reinicia o
        # processo a cada deploy e um teto em RAM zeraria junto, o que num
        # canal pago é dinheiro indo embora.
        cur.execute(
            f"""
            SELECT
              COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 day') AS no_dia,
              COUNT(*) FILTER (
                WHERE created_at > NOW() - INTERVAL '{PHONE_CODE_COOLDOWN_SEGS} seconds'
              ) AS recentes
            FROM phone_verification_codes
            WHERE user_id = %s
            """,
            (current_user["sub"],),
        )
        uso = dict(cur.fetchone() or {})
        if (uso.get("recentes") or 0) > 0:
            raise HTTPException(429, "Aguarde um minuto para pedir um novo código.")
        if (uso.get("no_dia") or 0) >= PHONE_CODE_MAX_POR_DIA:
            raise HTTPException(429, "Muitas tentativas hoje. Tente novamente amanhã.")

        codigo = _gerar_codigo_numerico()
        cur.execute(
            f"""
            INSERT INTO phone_verification_codes (user_id, phone, code_hash, expires_at)
            VALUES (%s, %s, %s, NOW() + INTERVAL '{PHONE_CODE_VALIDADE_MIN} minutes')
            """,
            (current_user["sub"], row["phone"], _hash_token(codigo)),
        )
        conn.commit()

        # O envio vem DEPOIS do commit de propósito: se o SMS sair e a gravação
        # falhar, o usuário recebe um código que o banco não conhece.
        try:
            enviar_sms(
                row["phone"],
                f"{codigo} e o seu codigo de verificacao Pick IA. Vale por {PHONE_CODE_VALIDADE_MIN} minutos.",
            )
        except SMSNaoEnviado as e:
            logger.warning("[OTP] Falha ao enviar SMS (user %s): %s", current_user["sub"], e)
            raise HTTPException(502, "Não foi possível enviar o SMS agora. Tente em alguns minutos.")

        return {"ok": True, "expira_em_minutos": PHONE_CODE_VALIDADE_MIN}
    finally:
        cur.close(); conn.close()


@router.post("/phone/verify-code")
def verificar_codigo_telefone(body: VerifyPhoneBody, current_user: dict = Depends(get_current_user)):
    """Confere o código e, se bater, marca o telefone e libera o trial."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT phone, phone_verified FROM users WHERE id = %s", (current_user["sub"],))
        usuario = dict(cur.fetchone() or {})
        if not usuario:
            raise HTTPException(404, "Usuário não encontrado")
        if usuario.get("phone_verified"):
            return {"ok": True, "ja_verificado": True, "trial_ativado": False}

        cur.execute(
            """
            SELECT id, phone, code_hash, attempts, expires_at < NOW() AS expirado
            FROM phone_verification_codes
            WHERE user_id = %s AND consumed_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (current_user["sub"],),
        )
        registro = cur.fetchone()
        if not registro:
            raise HTTPException(400, "Peça um código antes de verificar.")
        registro = dict(registro)

        if registro["expirado"]:
            raise HTTPException(400, "Código expirado. Peça um novo.")
        if registro["attempts"] >= PHONE_CODE_MAX_TENTATIVAS:
            raise HTTPException(429, "Muitas tentativas. Peça um código novo.")
        # O número mudou depois que o código saiu: validar aqui carimbaria
        # `phone_verified` num telefone que ninguém conferiu.
        if registro["phone"] != usuario.get("phone"):
            raise HTTPException(400, "O telefone mudou. Peça um código novo.")

        informado = re.sub(r"\D", "", body.code or "")
        if _hash_token(informado) != registro["code_hash"]:
            cur.execute(
                "UPDATE phone_verification_codes SET attempts = attempts + 1 WHERE id = %s",
                (registro["id"],),
            )
            conn.commit()
            restantes = PHONE_CODE_MAX_TENTATIVAS - (registro["attempts"] + 1)
            if restantes <= 0:
                raise HTTPException(429, "Muitas tentativas. Peça um código novo.")
            raise HTTPException(400, f"Código incorreto. Restam {restantes} tentativas.")

        cur.execute(
            "UPDATE phone_verification_codes SET consumed_at = NOW() WHERE id = %s",
            (registro["id"],),
        )
        cur.execute("UPDATE users SET phone_verified = TRUE WHERE id = %s", (current_user["sub"],))
        # Mesmo helper do link de e-mail: telefone provado também paga trial.
        trial_expira = _ativar_trial_se_elegivel(cur, current_user["sub"])
        conn.commit()
        invalidar_cache_usuario(current_user["sub"])

        return {
            "ok": True,
            "trial_ativado": trial_expira is not None,
            "trial_expires_at": trial_expira.isoformat() if trial_expira else None,
        }
    finally:
        cur.close(); conn.close()


@router.put("/profile")
def update_profile(body: UpdateProfileBody, response: Response, current_user: dict = Depends(get_current_user)):
    """Usuário atualiza próprio nome, usuário, telefone ou senha."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT password_hash, plan, trial_used, phone FROM users WHERE id = %s", (current_user["sub"],))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Usuário não encontrado")

        fields, values = [], []

        if body.name:
            fields.append("name = %s"); values.append(' '.join(w.capitalize() for w in body.name.strip().split()))

        if body.username is not None and body.username.strip():
            raw = body.username.strip().lstrip("@").lower()
            if not _USERNAME_RE.match(raw):
                raise HTTPException(400, "Usuário inválido. Use 3–20 caracteres: letras minúsculas, números e _")
            cur.execute("SELECT id FROM users WHERE username = %s AND id != %s", (raw, current_user["sub"]))
            if cur.fetchone():
                raise HTTPException(400, "Usuário já em uso. Escolha outro.")
            fields.append("username = %s"); values.append(raw)

        if body.phone is not None:
            normalized = _validate_phone_br(body.phone) if body.phone.strip() else None
            # Mesma unicidade do cadastro: sem ela, trocar o telefone pelo
            # perfil seria a porta lateral pra reusar um numero ja gasto.
            if normalized:
                cur.execute("SELECT id FROM users WHERE phone = %s AND id != %s", (normalized, current_user["sub"]))
                if cur.fetchone():
                    raise HTTPException(400, "Telefone já cadastrado em outra conta.")
            if normalized != row["phone"]:
                # Numero novo e' numero nao provado: a verificacao antiga nao
                # vale pra ele, senao trocar de numero herdaria o selo.
                fields.append("phone_verified = FALSE")
            fields.append("phone = %s"); values.append(normalized)

        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        values.append(current_user["sub"])
        cur.execute(
            f"UPDATE users SET {', '.join(fields)}, updated_at = NOW() WHERE id = %s RETURNING id, name, email, plan",
            values,
        )
        updated = dict(cur.fetchone())

        # Sincroniza @username nas mensagens do chat se o nome mudou
        if body.name:
            cur.execute("SELECT username FROM users WHERE id = %s", (current_user["sub"],))
            u_row = cur.fetchone()
            display_name = f"@{u_row['username']}" if u_row and u_row.get("username") else body.name
            cur.execute(
                "UPDATE chat_messages SET user_name = %s WHERE user_id = %s",
                (display_name, current_user["sub"]),
            )
            cur.execute(
                "UPDATE pick_comments SET user_name = %s WHERE user_id = %s",
                (display_name, current_user["sub"]),
            )

        conn.commit()

        return updated
    finally:
        cur.close(); conn.close()


def _reissue_tokens_for_user(response: Response, user_id: int, name: str, email: str) -> None:
    """Gira o session_token (derruba qualquer outra sessão) e reemite os
    cookies de auth pra manter só o dispositivo atual logado. Usado depois de
    qualquer troca de senha bem-sucedida."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        new_session_id = secrets.token_hex(32)
        cur.execute(
            "UPDATE users SET session_token=%s WHERE id=%s RETURNING plan, expires_at, avatar_url",
            (hashlib.sha256(new_session_id.encode()).hexdigest(), user_id),
        )
        u = cur.fetchone()
        conn.commit()
        invalidar_cache_usuario(user_id)
        token_data = {
            "sub": str(user_id), "id": user_id,
            "name": name, "email": email,
            "plan": u["plan"], "plan_expires_at": u["expires_at"].isoformat() if u["expires_at"] else None,
            "avatar_url": u["avatar_url"],
            "session_id": new_session_id,
        }
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        set_auth_cookies(response, access_token, refresh_token)
    finally:
        cur.close(); conn.close()


@router.post("/profile/password/request")
def request_password_change(body: RequestPasswordChangeBody, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Passo 1 da troca de senha logada: confirma a senha atual, valida a
    nova, e manda um código de 6 dígitos por e-mail. A senha só muda de fato
    na confirmação (/profile/password/confirm) -- reusa reset_token/
    reset_token_expires_at (mesmas colunas do "esqueci minha senha"), mas
    aqui o usuário já está autenticado, então não precisa e-mail/usuário, só o
    código bater com o hash guardado pra este user_id."""
    _check_profile_rate(current_user["sub"])
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT password_hash, name, email FROM users WHERE id = %s", (current_user["sub"],))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Usuário não encontrado")
        if not verify_password(body.current_password, row["password_hash"]):
            raise HTTPException(400, "Senha atual incorreta")
        _validate_password(body.new_password)

        code = str(secrets.randbelow(900000) + 100000)  # 100000–999999
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        cur.execute(
            "UPDATE users SET reset_token=%s, reset_token_expires_at=%s, pending_password_hash=%s WHERE id=%s",
            (_hash_token(code), expires, hash_password(body.new_password), current_user["sub"]),
        )
        conn.commit()

        first_name = row["name"].strip().split()[0] if row["name"] else ""
        background_tasks.add_task(
            _send_email,
            row["email"],
            "Confirme a troca de senha · Pick IA",
            (
                f"Olá {first_name},\n\n"
                f"Seu código para confirmar a troca de senha é:\n\n"
                f"  {code}\n\n"
                f"O código expira em 15 minutos.\n"
                f"Se não foi você quem pediu, ignore este email e sua senha continua a mesma.\n\n"
                f"Equipe Pick IA"
            ),
        )
        return {"ok": True}
    finally:
        cur.close(); conn.close()


@router.post("/profile/password/confirm")
def confirm_password_change(body: ConfirmPasswordChangeBody, response: Response, current_user: dict = Depends(get_current_user)):
    """Passo 2: valida o código enviado por e-mail e efetiva a troca de
    senha, girando a sessão (derruba qualquer outro dispositivo logado)."""
    _check_profile_rate(current_user["sub"])
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name, email, pending_password_hash FROM users "
            "WHERE id = %s AND reset_token = %s AND reset_token_expires_at > NOW()",
            (current_user["sub"], _hash_token(body.code)),
        )
        row = cur.fetchone()
        if not row or not row["pending_password_hash"]:
            raise HTTPException(400, "Código inválido ou expirado")

        cur.execute(
            "UPDATE users SET password_hash=%s, reset_token=NULL, reset_token_expires_at=NULL, pending_password_hash=NULL WHERE id=%s",
            (row["pending_password_hash"], current_user["sub"]),
        )
        conn.commit()
        name, email = row["name"], row["email"]
    finally:
        cur.close(); conn.close()

    _reissue_tokens_for_user(response, current_user["sub"], name, email)
    return {"ok": True}


class ChangeEmailBody(BaseModel):
    new_email: str
    current_password: str

@router.post("/change-email")
def change_email(body: ChangeEmailBody, background_tasks: BackgroundTasks, request: Request, current_user: dict = Depends(get_current_user)):
    """Troca o e-mail do usuário e envia novo link de verificação."""
    _check_profile_rate(current_user["sub"])
    new_email = body.new_email.strip().lower()
    if not new_email or "@" not in new_email:
        raise HTTPException(400, "E-mail inválido")
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (current_user["sub"],))
        pw_row = cur.fetchone()
        if not pw_row or not verify_password(body.current_password, pw_row["password_hash"]):
            raise HTTPException(400, "Senha atual incorreta")
        cur.execute("SELECT id FROM users WHERE email = %s AND id != %s", (new_email, current_user["sub"]))
        if cur.fetchone():
            raise HTTPException(400, "E-mail já cadastrado em outra conta")
        token = secrets.token_urlsafe(32)
        cur.execute(
            "UPDATE users SET email=%s, email_verified=FALSE, email_verification_token=%s, updated_at=NOW() WHERE id=%s RETURNING name",
            (new_email, _hash_token(token), current_user["sub"]),
        )
        row = cur.fetchone()
        conn.commit()
        site_url = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")
        background_tasks.add_task(_send_verification_email, new_email, row["name"], token, site_url)
        return {"ok": True, "email": new_email}
    finally:
        cur.close(); conn.close()


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordBody):
    """Gera token de reset e envia email."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, name FROM users WHERE email = %s AND active = true", (body.email,))
        row = cur.fetchone()
        # Sempre retorna 200 para não revelar se email existe
        if not row:
            return {"ok": True}

        code    = str(secrets.randbelow(900000) + 100000)  # 100000–999999
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        cur.execute(
            "UPDATE users SET reset_token = %s, reset_token_expires_at = %s WHERE id = %s",
            (_hash_token(code), expires, row["id"]),
        )
        conn.commit()

        nome = row["name"]
        _send_email(
            to      = body.email,
            subject = "Redefinição de senha · Pick IA",
            body    = (
                f"Olá {nome},\n\n"
                f"Seu código para redefinir a senha é:\n\n"
                f"  {code}\n\n"
                f"O código expira em 15 minutos.\n"
                f"Se não foi você, ignore este email.\n\n"
                f"Equipe Pick IA"
            ),
        )
        return {"ok": True}
    finally:
        cur.close(); conn.close()


@router.post("/reset-password")
def reset_password(body: ResetPasswordBody):
    """Valida código de 6 dígitos e atualiza a senha."""
    _validate_password(body.new_password)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM users WHERE email = %s AND reset_token = %s AND reset_token_expires_at > NOW()",
            (body.email, _hash_token(body.code)),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(400, "Código inválido ou expirado")

        # Gira o session_token junto: sem isso, uma sessão que já estivesse
        # aberta (ex: dispositivo roubado que motivou o reset) continuava
        # valida ate o access token expirar sozinho (ate 12h) mesmo depois
        # da senha ter sido trocada.
        new_session_token = hashlib.sha256(secrets.token_hex(32).encode()).hexdigest()
        cur.execute(
            "UPDATE users SET password_hash = %s, reset_token = NULL, reset_token_expires_at = NULL, session_token = %s WHERE id = %s",
            (hash_password(body.new_password), new_session_token, row["id"]),
        )
        conn.commit()
        invalidar_cache_usuario(row["id"])
        return {"ok": True}
    finally:
        cur.close(); conn.close()


@router.get("/referral")
def get_referral(current_user: dict = Depends(get_current_user)):
    """Retorna código de indicação e stats do usuário."""
    user_id = int(current_user["sub"])
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT referral_code FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Usuário não encontrado")

        ref_code = row["referral_code"]

        # Gera código se não tiver
        if not ref_code:
            for _ in range(10):
                candidate = secrets.token_hex(3).upper()
                cur.execute("SELECT id FROM users WHERE referral_code = %s", (candidate,))
                if not cur.fetchone():
                    ref_code = candidate
                    break
            cur.execute("UPDATE users SET referral_code = %s WHERE id = %s", (ref_code, user_id))
            conn.commit()

        # Indicados
        cur.execute("SELECT COUNT(*) AS total FROM users WHERE referred_by = %s", (user_id,))
        total_indicated = cur.fetchone()["total"]

        # Convertidos (plano vip)
        cur.execute(
            "SELECT COUNT(*) AS total FROM users WHERE referred_by = %s AND plan IN ('vip', 'admin')",
            (user_id,),
        )
        total_converted = cur.fetchone()["total"]

        # 1 dia por registro + 2 dias adicionais por conversão VIP
        days_earned = int(total_indicated) * 1 + int(total_converted) * 2

        site_url = os.getenv("SITE_URL", "http://localhost:5173")

        return {
            "referral_code":    ref_code,
            "referral_link":    f"{site_url}/login?ref={ref_code}",
            "total_indicated":  int(total_indicated),
            "total_converted":  int(total_converted),
            "days_earned":      days_earned,
        }
    finally:
        cur.close(); conn.close()
