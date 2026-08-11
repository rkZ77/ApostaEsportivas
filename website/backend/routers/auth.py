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
from auth_utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    set_auth_cookies, set_access_cookie, clear_auth_cookies,
    get_current_user, decode_token,
    REFRESH_COOKIE_NAME, COOKIE_NAME, oauth2_scheme,
)

_AVATARS_DIR = pathlib.Path(__file__).parent.parent / "static" / "avatars"
_LOGO_PATH   = pathlib.Path(__file__).parent.parent / "static" / "logo.png"

# Lockout por conta (além do lockout por IP em main.py): sem isso, um ataque
# distribuído por IP contorna o limite por IP mas ainda bate sempre na mesma
# conta-alvo. Chave é o identifier normalizado (email/cpf/username), não o id
# do usuário, já que uma conta inexistente/errada também deve contar.
_account_login_failures: dict[str, list[float]] = defaultdict(list)
ACCOUNT_LOGIN_MAX_FAILURES = 10
ACCOUNT_LOGIN_LOCKOUT_SECS = 900


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


def _validate_cpf(cpf: str) -> str:
    """Valida CPF brasileiro e retorna apenas dígitos. Lança 400 se inválido."""
    digits = re.sub(r"\D", "", cpf)
    if len(digits) != 11:
        raise HTTPException(400, "CPF inválido. Informe os 11 dígitos.")
    if len(set(digits)) == 1:
        raise HTTPException(400, "CPF inválido.")
    # Dígito verificador 1
    s = sum(int(digits[i]) * (10 - i) for i in range(9))
    d1 = (s * 10 % 11) % 10
    if d1 != int(digits[9]):
        raise HTTPException(400, "CPF inválido.")
    # Dígito verificador 2
    s = sum(int(digits[i]) * (11 - i) for i in range(10))
    d2 = (s * 10 % 11) % 10
    if d2 != int(digits[10]):
        raise HTTPException(400, "CPF inválido.")
    return digits

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
    Tipos: 'email', 'cpf', 'username'
    """
    stripped = identifier.strip()
    digits = re.sub(r"\D", "", stripped)
    if len(digits) == 11:
        return "cpf", digits
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
    cpf: str
    username: Optional[str] = None
    ref_code: Optional[str] = None
    accepted_terms: bool = False
    captcha_token: Optional[str] = None

class LoginBody(BaseModel):
    identifier: str  # e-mail, CPF ou username
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
    cpf: Optional[str] = None
    username: Optional[str] = None


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

        # Valida phone, CPF e username
        phone_e164 = _validate_phone_br(body.phone)
        cpf_digits = _validate_cpf(body.cpf)
        cur.execute("SELECT id FROM users WHERE cpf = %s", (cpf_digits,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="CPF já cadastrado. Cada CPF permite apenas 1 conta.")

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
            "INSERT INTO users (name, email, password_hash, phone, cpf, username, referred_by, referral_code, terms_accepted_at, terms_ip) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s) RETURNING id, name, email, phone, username, plan, active, expires_at",
            (' '.join(w.capitalize() for w in body.name.strip().split()), body.email, hash_password(body.password), phone_e164, cpf_digits, final_username, referrer_id, new_ref_code, client_ip),
        )
        user = dict(cur.fetchone())
        # Trial gratuito de 2 dias · apenas para usuários que forneceram CPF no cadastro
        plan_final = "free"
        expires_final = None
        if cpf_digits:
            trial_expires = datetime.now(timezone.utc) + timedelta(days=2)
            cur.execute(
                "UPDATE users SET plan='trial', expires_at=%s, trial_used=TRUE WHERE id=%s",
                (trial_expires, user["id"])
            )
            plan_final = "trial"
            expires_final = trial_expires.isoformat()
            user["trial_used"] = True

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


@router.post("/login")
def login(body: LoginBody, response: Response, request: Request):
    _verify_captcha(body.captcha_token, request)
    lockout_key = body.identifier.strip().lower()
    _check_account_lockout(lockout_key)

    conn = get_connection()
    cur = conn.cursor()
    try:
        id_type, id_value = _resolve_identifier(body.identifier)
        _LOGIN_COLS = "id, name, email, phone, username, password_hash, plan, active, expires_at, email_verified, avatar_url"
        if id_type == "email":
            cur.execute(f"SELECT {_LOGIN_COLS} FROM users WHERE email = %s", (id_value,))
        elif id_type == "cpf":
            cur.execute(f"SELECT {_LOGIN_COLS} FROM users WHERE cpf = %s", (id_value,))
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

        # Auto-expire VIP/trial expirado
        if user["plan"] in ("vip", "trial") and user.get("expires_at"):
            exp = user["expires_at"]
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                cur.execute("UPDATE users SET plan='free', expires_at=NULL WHERE id=%s", (user["id"],))
                conn.commit()
                user["plan"] = "free"
                user["expires_at"] = None

        # Sessão única: novo login invalida sessão anterior e grava dispositivo
        device = _detect_device(request.headers.get("user-agent", ""))
        session_id = secrets.token_hex(32)
        cur.execute(
            "UPDATE users SET session_token=%s, last_login_device=%s, last_login_at=NOW() WHERE id=%s",
            (hashlib.sha256(session_id.encode()).hexdigest(), device, user["id"])
        )
        conn.commit()

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
        conn.commit()
        site_url = (os.getenv("SITE_URL") or "https://pickia.com.br").rstrip("/")
        background_tasks.add_task(_send_welcome_email, row["email"], row["name"], site_url)
        return {"ok": True}
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
            "SELECT id, name, email, phone, username, plan, active, expires_at, subscription_type, created_at, avatar_url, trial_used, email_verified, (cpf IS NOT NULL) AS has_cpf, last_login_device, last_login_at FROM users WHERE id = %s",
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
        return d
    finally:
        cur.close(); conn.close()


@router.post("/activate-trial")
def activate_trial(response: Response, current_user: dict = Depends(get_current_user)):
    """Ativa 2 dias de trial VIP para usuários free que nunca usaram trial."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, plan, trial_used, cpf FROM users WHERE id = %s", (current_user["sub"],))
        user = cur.fetchone()
        if not user:
            raise HTTPException(404, "Usuário não encontrado")

        if dict(user).get("trial_used"):
            raise HTTPException(400, "Você já utilizou o período de teste gratuito.")

        if dict(user)["plan"] not in ("free",):
            raise HTTPException(400, "Disponível apenas para usuários Free.")

        if not dict(user).get("cpf"):
            raise HTTPException(400, "Informe seu CPF no perfil para ativar o trial. Cada CPF pode usar o trial apenas uma vez.")

        trial_expires = datetime.now(timezone.utc) + timedelta(days=2)
        cur.execute(
            "UPDATE users SET plan='trial', expires_at=%s, trial_used=TRUE WHERE id=%s",
            (trial_expires, current_user["sub"]),
        )
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


@router.put("/profile")
def update_profile(body: UpdateProfileBody, response: Response, current_user: dict = Depends(get_current_user)):
    """Usuário atualiza próprio nome, telefone, CPF ou senha."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT password_hash, plan, trial_used, cpf FROM users WHERE id = %s", (current_user["sub"],))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Usuário não encontrado")

        fields, values = [], []
        cpf_added = False

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
            fields.append("phone = %s"); values.append(normalized)

        if body.cpf is not None and body.cpf.strip():
            cpf_digits = _validate_cpf(body.cpf)
            if not row["cpf"]:  # só deixa adicionar se ainda não tem CPF
                cur.execute("SELECT id FROM users WHERE cpf = %s AND id != %s", (cpf_digits, current_user["sub"]))
                if cur.fetchone():
                    raise HTTPException(400, "CPF já cadastrado em outra conta.")
                fields.append("cpf = %s"); values.append(cpf_digits)
                cpf_added = True

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

        # Se CPF foi adicionado agora e usuário ainda não usou trial, ativar automaticamente
        if cpf_added and row["plan"] == "free" and not row["trial_used"]:
            trial_expires = datetime.now(timezone.utc) + timedelta(days=2)
            cur.execute(
                "UPDATE users SET plan='trial', expires_at=%s, trial_used=TRUE WHERE id=%s",
                (trial_expires, current_user["sub"]),
            )
            conn.commit()
            updated["plan"] = "trial"
            updated["trial_activated"] = True

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
    aqui o usuário já está autenticado, então não precisa e-mail/CPF, só o
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
