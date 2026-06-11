import os
import re
import secrets
import smtplib
import pathlib
import shutil
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request, Response, status, Depends, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Optional
from database import get_connection
from auth_utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    set_auth_cookies, clear_auth_cookies,
    get_current_user, decode_token,
    REFRESH_COOKIE_NAME,
)

_AVATARS_DIR = pathlib.Path(__file__).parent.parent / "static" / "avatars"
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
    if len(password) < 8:
        raise HTTPException(400, "Senha deve ter pelo menos 8 caracteres")


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

def _send_email(to: str, subject: str, body: str):
    """Envia email via SMTP configurado nas vars de ambiente."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_addr = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        raise HTTPException(500, "SMTP não configurado no servidor")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to

    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.sendmail(from_addr, [to], msg.as_string())


# ── models ───────────────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: str
    cpf: str
    username: Optional[str] = None
    ref_code: Optional[str] = None

class LoginBody(BaseModel):
    identifier: str  # e-mail, CPF ou username
    password: str

class ForgotPasswordBody(BaseModel):
    email: EmailStr

class ResetPasswordBody(BaseModel):
    token: str
    new_password: str

class UpdateProfileBody(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    cpf: Optional[str] = None
    username: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


# ── endpoints ────────────────────────────────────────────────────────────────

@router.post("/register")
def register(body: RegisterBody, response: Response):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE email = %s", (body.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Email já cadastrado")

        # Valida phone, CPF e username
        if not body.phone or len(body.phone.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')) < 10:
            raise HTTPException(status_code=400, detail="Telefone inválido. Informe o número com DDD.")
        cpf_digits = _validate_cpf(body.cpf)
        cur.execute("SELECT id FROM users WHERE cpf = %s", (cpf_digits,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="CPF já cadastrado. Cada CPF permite apenas 1 conta.")

        # Resolve username (obrigatório — gerado automaticamente se não enviado)
        raw_username = (body.username or "").strip().lstrip("@").lower()
        if raw_username:
            if not _USERNAME_RE.match(raw_username):
                raise HTTPException(status_code=400, detail="Usuário inválido. Use 3–20 caracteres: letras minúsculas, números e _")
            cur.execute("SELECT id FROM users WHERE username = %s", (raw_username,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Usuário já em uso. Escolha outro.")
            final_username = raw_username
        else:
            final_username = _generate_username(body.name, cur)

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
        cur.execute(
            "INSERT INTO users (name, email, password_hash, phone, cpf, username, referred_by, referral_code) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, name, email, phone, username, plan, active, expires_at",
            (body.name, body.email, hash_password(body.password), body.phone, cpf_digits, final_username, referrer_id, new_ref_code),
        )
        user = dict(cur.fetchone())
        # Trial gratuito de 2 dias — apenas para usuários que forneceram CPF no cadastro
        plan_final = "free"
        expires_final = None
        if cpf_digits:
            trial_expires = datetime.now(timezone.utc) + timedelta(days=2)
            cur.execute(
                "UPDATE users SET plan='trial', expires_at=%s, trial_used=TRUE WHERE id=%s",
                (trial_expires, user["id"])
            )
            conn.commit()
            plan_final = "trial"
            expires_final = trial_expires.isoformat()
            user["trial_used"] = True
        conn.commit()
        user["plan"] = plan_final
        user["expires_at"] = expires_final
        token_data = {
            "sub": str(user["id"]), "id": user["id"],
            "name": user["name"], "email": user["email"],
            "plan": plan_final, "plan_expires_at": expires_final,
            "avatar_url": None,
        }
        access_token  = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        set_auth_cookies(response, access_token, refresh_token)
        return {"user": user}
    finally:
        cur.close(); conn.close()


@router.post("/login")
def login(body: LoginBody, response: Response):
    conn = get_connection()
    cur = conn.cursor()
    try:
        id_type, id_value = _resolve_identifier(body.identifier)
        if id_type == "email":
            cur.execute(
                "SELECT id, name, email, username, password_hash, plan, active, expires_at FROM users WHERE email = %s",
                (id_value,),
            )
        elif id_type == "cpf":
            cur.execute(
                "SELECT id, name, email, username, password_hash, plan, active, expires_at FROM users WHERE cpf = %s",
                (id_value,),
            )
        else:
            cur.execute(
                "SELECT id, name, email, username, password_hash, plan, active, expires_at FROM users WHERE username = %s",
                (id_value,),
            )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Credenciais inválidas")

        user = dict(row)
        if not user["active"]:
            raise HTTPException(status_code=403, detail="Conta desativada")
        if not verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Credenciais inválidas")

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

        plan_expires_at = user["expires_at"].isoformat() if user.get("expires_at") else None
        token_data = {
            "sub": str(user["id"]), "id": user["id"],
            "name": user["name"], "email": user["email"],
            "plan": user["plan"], "plan_expires_at": plan_expires_at,
            "avatar_url": user.get("avatar_url"),
        }
        access_token  = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        set_auth_cookies(response, access_token, refresh_token)
        user.pop("password_hash")
        user["expires_at"] = plan_expires_at
        return {"user": user}
    finally:
        cur.close(); conn.close()


@router.post("/logout")
def logout(response: Response):
    clear_auth_cookies(response)
    return {"status": "ok"}


@router.post("/refresh")
def refresh_token(request: Request, response: Response):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
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
    finally:
        cur.close(); conn.close()

    plan_expires_at = user["expires_at"].isoformat() if user.get("expires_at") else None
    token_data = {
        "sub": str(user["id"]), "id": user["id"],
        "name": user["name"], "email": user["email"],
        "plan": user["plan"], "plan_expires_at": plan_expires_at,
        "avatar_url": user.get("avatar_url"),
    }
    new_access  = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)
    set_auth_cookies(response, new_access, new_refresh)
    return {"status": "ok"}


@router.post("/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
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
            "SELECT id, name, email, phone, username, plan, active, expires_at, subscription_type, created_at, avatar_url, trial_used, (cpf IS NOT NULL) AS has_cpf FROM users WHERE id = %s",
            (current_user["sub"],),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        d = dict(row)
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
def update_profile(body: UpdateProfileBody, current_user: dict = Depends(get_current_user)):
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
            fields.append("name = %s"); values.append(body.name)

        if body.username is not None and body.username.strip():
            raw = body.username.strip().lstrip("@").lower()
            if not _USERNAME_RE.match(raw):
                raise HTTPException(400, "Usuário inválido. Use 3–20 caracteres: letras minúsculas, números e _")
            cur.execute("SELECT id FROM users WHERE username = %s AND id != %s", (raw, current_user["sub"]))
            if cur.fetchone():
                raise HTTPException(400, "Usuário já em uso. Escolha outro.")
            fields.append("username = %s"); values.append(raw)

        if body.phone is not None:
            fields.append("phone = %s"); values.append(body.phone or None)

        if body.cpf is not None and body.cpf.strip():
            cpf_digits = _validate_cpf(body.cpf)
            if not row["cpf"]:  # só deixa adicionar se ainda não tem CPF
                cur.execute("SELECT id FROM users WHERE cpf = %s AND id != %s", (cpf_digits, current_user["sub"]))
                if cur.fetchone():
                    raise HTTPException(400, "CPF já cadastrado em outra conta.")
                fields.append("cpf = %s"); values.append(cpf_digits)
                cpf_added = True

        if body.new_password:
            if not body.current_password:
                raise HTTPException(400, "Informe a senha atual para trocar")
            if not verify_password(body.current_password, row["password_hash"]):
                raise HTTPException(400, "Senha atual incorreta")
            _validate_password(body.new_password)
            fields.append("password_hash = %s"); values.append(hash_password(body.new_password))

        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")

        values.append(current_user["sub"])
        cur.execute(
            f"UPDATE users SET {', '.join(fields)}, updated_at = NOW() WHERE id = %s RETURNING id, name, email, plan",
            values,
        )
        updated = dict(cur.fetchone())
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

        token     = secrets.token_urlsafe(32)
        expires   = datetime.now(timezone.utc) + timedelta(hours=1)
        cur.execute(
            "UPDATE users SET reset_token = %s, reset_token_expires_at = %s WHERE id = %s",
            (token, expires, row["id"]),
        )
        conn.commit()

        site_url = os.getenv("SITE_URL", "http://localhost:5173")
        link     = f"{site_url}/reset-password?token={token}"
        nome     = row["name"]
        _send_email(
            to      = body.email,
            subject = "HPS Picks — Redefinição de senha",
            body    = (
                f"Olá {nome},\n\n"
                f"Recebemos uma solicitação para redefinir sua senha.\n\n"
                f"Clique no link abaixo (válido por 1 hora):\n{link}\n\n"
                f"Se não foi você, ignore este email.\n\n"
                f"— HPS Picks"
            ),
        )
        return {"ok": True}
    finally:
        cur.close(); conn.close()


@router.post("/reset-password")
def reset_password(body: ResetPasswordBody):
    """Valida token e atualiza a senha."""
    _validate_password(body.new_password)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM users WHERE reset_token = %s AND reset_token_expires_at > NOW()",
            (body.token,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(400, "Token inválido ou expirado")

        cur.execute(
            "UPDATE users SET password_hash = %s, reset_token = NULL, reset_token_expires_at = NULL WHERE id = %s",
            (hash_password(body.new_password), row["id"]),
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

        days_earned = total_converted * 7

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
