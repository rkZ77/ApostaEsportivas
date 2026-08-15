import os
import threading
import time
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from database import get_connection

SECRET_KEY = os.getenv("JWT_SECRET", "")
if not SECRET_KEY or SECRET_KEY == "change-me-in-production-please":
    _env = os.getenv("APP_ENV", "production").lower()
    if _env in ("production", "prod"):
        raise RuntimeError("JWT_SECRET não configurado! Defina JWT_SECRET antes de iniciar em produção.")
    import warnings
    warnings.warn("⚠️  JWT_SECRET não configurado! Use apenas em desenvolvimento.", stacklevel=1)
    SECRET_KEY = "dev-only-insecure-secret-do-not-use-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS  = 12
REFRESH_TOKEN_EXPIRE_DAYS  = 30

COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"
_IS_PRODUCTION = os.getenv("APP_ENV", "production").lower() in ("production", "prod")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


_ACCESS_MAX_AGE  = ACCESS_TOKEN_EXPIRE_HOURS * 3600
_REFRESH_MAX_AGE = REFRESH_TOKEN_EXPIRE_DAYS * 86400
_TOKEN_MAX_AGE   = _ACCESS_MAX_AGE  # compat alias


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload["type"] = "access"
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    payload = {"sub": data["sub"], "type": "refresh"}
    if "session_id" in data:
        payload["session_id"] = data["session_id"]
    payload["exp"] = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    """Define cookies httpOnly para acesso e refresh token."""
    secure = _IS_PRODUCTION
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=_ACCESS_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=_REFRESH_MAX_AGE,
        path="/api/auth/refresh",
    )


def set_access_cookie(response, access_token: str) -> None:
    """Atualiza apenas o access token (sem renovar o refresh token)."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=_IS_PRODUCTION,
        samesite="strict",
        max_age=_ACCESS_MAX_AGE,
        path="/",
    )


def clear_auth_cookies(response) -> None:
    """Remove os cookies de autenticação."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/auth/refresh")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")


def _hash_session(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


# ─── Cache da linha de `users` usada na checagem de sessão ───────────────────
#
# POR QUE ISTO EXISTE, com o numero medido em 13/08 (ver database.py:71-82):
# cada ida ao banco custa 154ms, e este SELECT rodava em TODA requisicao
# autenticada, antes do handler comecar. A tela de Picks dispara 10 chamadas
# quase ao mesmo tempo -- eram 10 x 154ms so' pra conferir a sessao, e 10 slots
# do pool (que tem 10 no total) gastos antes de qualquer trabalho util.
#
# A JANELA E' CURTA DE PROPOSITO. Ela e' o atraso maximo pra tres coisas que o
# usuario percebe: pagamento aprovado virar VIP na tela, sessao derrubada por
# login em outro aparelho, e conta desativada pelo admin parar de responder.
# 30s e' o teto que se aceita nesses tres casos; nao suba isto sem pensar neles.
#
# Admin NUNCA entra no cache: e' quem muda plano dos outros e precisa ver o
# efeito na hora, e sao poucas contas, entao o ganho aqui seria irrelevante.
_SESSAO_TTL = 30.0
_sessao_cache: dict[int, tuple[float, dict]] = {}
_sessao_lock = threading.Lock()


def invalidar_cache_usuario(user_id) -> None:
    """Derruba a linha em cache de um usuario.

    Chamada de todo lugar que mexe em plano, sessao ou `active` -- ver a lista
    em routers/auth.py, routers/payments.py e routers/admin.py. Esquecer uma
    chamada dessas nao vira bug permanente: o pior caso e' o TTL acima.
    """
    if user_id is None:
        return
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return
    with _sessao_lock:
        _sessao_cache.pop(uid, None)


def _linha_de_sessao(user_id) -> dict | None:
    """A linha de `users` que a checagem precisa, do cache ou do banco."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None

    agora = time.time()
    with _sessao_lock:
        entrada = _sessao_cache.get(uid)
        if entrada and agora - entrada[0] < _SESSAO_TTL:
            return entrada[1]

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, active, session_token, last_login_device, last_login_at, plan, expires_at FROM users WHERE id = %s",
            (uid,),
        )
        row = cur.fetchone()
    finally:
        cur.close(); conn.close()

    if row is None:
        return None

    # dict comum: RealDictRow e' ligado ao cursor, que ja fechou.
    linha = dict(row)
    if linha.get("plan") != "admin":
        with _sessao_lock:
            _sessao_cache[uid] = (agora, linha)
    return linha


def get_current_user(request: Request, bearer: str | None = Depends(oauth2_scheme)) -> dict:
    # Cookie httpOnly tem prioridade; cai para Bearer como fallback (mobile/API)
    token = request.cookies.get(COOKIE_NAME) or bearer
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    payload = decode_token(token)

    # Um refresh token nunca deve ser aceito como access token (evita que um refresh
    # vazado sirva de credencial de API por 30 dias em vez das 12h do access token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    # Verifica usuário ativo e sessão única
    row = _linha_de_sessao(payload.get("sub"))

    if not row or not row["active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado ou desativado")

    # O claim "plan" do JWT pode ficar defasado por até ACCESS_TOKEN_EXPIRE_HOURS
    # (ex: admin rebaixado continuaria passando em require_admin com o token antigo).
    # Reconsulta sempre o plano/expiração reais do banco em vez de confiar no JWT.
    payload = dict(payload)
    payload["plan"] = row["plan"]
    payload["plan_expires_at"] = row["expires_at"].isoformat() if row["expires_at"] else None

    # Sessão única: session_token no JWT deve bater com o hash guardado no banco
    # Admin fica isento · pode acessar de múltiplos dispositivos simultaneamente
    if payload.get("plan") != "admin":
        session_id = payload.get("session_id")
        if row["session_token"] and session_id:
            if _hash_session(session_id) != row["session_token"]:
                device = row.get("last_login_device") or "outro dispositivo"
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"SESSION_INVALIDATED|{device}",
                )

    # Lazy expiry: se o plano VIP/trial já passou, trata como free
    if payload.get("plan") in ("vip", "trial") and payload.get("plan_expires_at"):
        try:
            exp_dt = datetime.fromisoformat(payload["plan_expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                payload = dict(payload)
                payload["plan"] = "free"
        except (ValueError, TypeError):
            pass
    return payload


def is_vip_active(user: dict) -> bool:
    """True se o usuário tem plano VIP/trial/admin ativo (não expirado)."""
    plan = user.get("plan", "free")
    if plan not in ("vip", "trial", "admin"):
        return False
    if plan == "admin":
        return True
    expires_at = user.get("plan_expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                return False
        except (ValueError, TypeError):
            pass
    return True


def require_vip(user: dict = Depends(get_current_user)) -> dict:
    if user.get("plan") not in ("vip", "trial", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso VIP necessário")
    # Verifica expiração do plano (admin nunca expira)
    if user.get("plan") in ("vip", "trial"):
        expires_at = user.get("plan_expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp_dt:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Plano VIP expirado. Renove para continuar.")
            except ValueError:
                pass
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("plan") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso admin necessário")
    return user


def get_current_user_optional(request: Request) -> dict | None:
    """Usuario logado, ou None se nao houver sessao valida.

    Existe pra endpoint PUBLICO que mostra mais coisa pra quem tem conta, sem
    exigir login pra funcionar. O caso que motivou: o teaser da Dica do Dia na
    home, que esconde o mercado de visitante anonimo.

    Ponto importante: o filtro tem que ser AQUI, no servidor. Mandar o dado e
    borrar no CSS nao esconde nada -- basta abrir o DevTools. Se o campo nao
    pode ser visto, ele nao pode sair daqui.
    """
    try:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth[7:]
        if not token:
            return None

        payload = decode_token(token)
        if payload.get("type") != "access":
            return None

        # Mesmo cache do caminho autenticado: a Home anonima e a Home logada
        # batem no mesmo endpoint (/public/free-pick-today), entao sem isto o
        # visitante logado pagaria uma ida ao banco a mais que o anonimo.
        row = _linha_de_sessao(payload.get("sub"))

        if not row or not row["active"]:
            return None
        return {"id": row["id"], "active": row["active"], "plan": row["plan"]}
    except Exception:
        # Token expirado, malformado ou banco fora: pro publico anonimo isso
        # nao e erro, e so "sem sessao".
        return None
