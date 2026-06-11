import os
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = os.getenv("JWT_SECRET", "")
if not SECRET_KEY or SECRET_KEY == "change-me-in-production-please":
    _env = os.getenv("APP_ENV", "production").lower()
    if _env in ("production", "prod"):
        raise RuntimeError("JWT_SECRET não configurado! Defina JWT_SECRET antes de iniciar em produção.")
    import warnings
    warnings.warn("⚠️  JWT_SECRET não configurado! Use apenas em desenvolvimento.", stacklevel=1)
    SECRET_KEY = "dev-only-insecure-secret-do-not-use-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 2
REFRESH_TOKEN_EXPIRE_DAYS = 7   # expira 7 dias após o login; sem renovação automática

COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"
_IS_PRODUCTION = os.getenv("APP_ENV", "production").lower() in ("production", "prod")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload["type"] = "access"
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    payload = {"sub": data["sub"], "type": "refresh"}
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
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
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
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
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


def get_current_user(request: Request, bearer: str | None = Depends(oauth2_scheme)) -> dict:
    # Cookie httpOnly tem prioridade; cai para Bearer como fallback (mobilel/API)
    token = request.cookies.get(COOKIE_NAME) or bearer
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    payload = decode_token(token)
    # Lazy expiry: se o plano VIP/trial já passou, trata como free sem DB call
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
