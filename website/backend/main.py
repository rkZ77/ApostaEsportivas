import os
import time
import logging
from collections import defaultdict
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# ── Logging centralizado ──────────────────────────────────────────────────────
_log_level = logging.DEBUG if os.getenv("APP_ENV") != "production" else logging.INFO
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

from routers import auth, suggestions, admin, fixtures, public, chat, payments, social, banca, leaderboard, live

app = FastAPI(title="ApostaSmart API", version="1.0.0", docs_url=None, redoc_url=None)

# ── CORS ─────────────────────────────────────────────────────────────────────
_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
_allow_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)

# ── Security headers ──────────────────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"]   = "nosniff"
    response.headers["X-Frame-Options"]           = "DENY"
    response.headers["X-XSS-Protection"]          = "1; mode=block"
    response.headers["Referrer-Policy"]            = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]         = "geolocation=(), microphone=(), camera=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"]   = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'"
    )
    return response

# ── Rate limiting em memória (por IP) ────────────────────────────────────────
# Estrutura: { ip: [(timestamp, endpoint), ...] }
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT   = 120  # requisições
RATE_WINDOW  = 60   # segundos

# Bloqueio de login por IP após falhas
_login_failures: dict[str, list[float]] = defaultdict(list)
LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_SECS = 900  # 15 minutos

# Limite estrito para forgot-password (evita spam de emails): 3 tentativas / 15 min
_forgot_store: dict[str, list[float]] = defaultdict(list)
FORGOT_LIMIT  = 3
FORGOT_WINDOW = 900

@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Rate limit geral
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        return JSONResponse({"detail": "Muitas requisições. Tente novamente em breve."}, status_code=429)
    _rate_store[ip].append(now)

    # Bloqueio específico de login/register
    if request.url.path in ("/api/auth/login", "/api/auth/register"):
        _login_failures[ip] = [t for t in _login_failures[ip] if now - t < LOGIN_LOCKOUT_SECS]
        if len(_login_failures[ip]) >= LOGIN_MAX_FAILURES:
            remaining = int(LOGIN_LOCKOUT_SECS - (now - _login_failures[ip][0]))
            return JSONResponse(
                {"detail": f"Conta temporariamente bloqueada. Tente novamente em {remaining // 60} min."},
                status_code=429,
            )

    # Rate limit estrito para forgot-password: 3 por 15 min (evita spam de email)
    if request.url.path == "/api/auth/forgot-password":
        _forgot_store[ip] = [t for t in _forgot_store[ip] if now - t < FORGOT_WINDOW]
        if len(_forgot_store[ip]) >= FORGOT_LIMIT:
            return JSONResponse(
                {"detail": "Muitas tentativas de redefinição. Aguarde 15 minutos."},
                status_code=429,
            )
        _forgot_store[ip].append(now)

    response = await call_next(request)

    # Conta falha de autenticação (401/403 em rotas de auth)
    if request.url.path == "/api/auth/login" and response.status_code in (401, 403):
        _login_failures[ip].append(now)

    return response

from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response as _Response
import httpx as _httpx
import pathlib as _pathlib
_avatars_dir = _pathlib.Path(__file__).parent / "static" / "avatars"
_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_pathlib.Path(__file__).parent / "static")), name="static")

_LOGO_BASE = "https://media.api-sports.io/football"
_LOGO_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400, stale-while-revalidate=3600"}

@app.get("/api/proxy/team/{team_id}.png", include_in_schema=False)
async def proxy_team_logo(team_id: int):
    if not (1 <= team_id <= 999999):
        return _Response(status_code=400)
    try:
        async with _httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{_LOGO_BASE}/teams/{team_id}.png")
            if r.status_code == 200:
                return _Response(r.content, media_type="image/png", headers=_LOGO_CACHE_HEADERS)
    except Exception:
        pass
    return _Response(status_code=404)

@app.get("/api/proxy/league/{league_id}.png", include_in_schema=False)
async def proxy_league_logo(league_id: int):
    if not (1 <= league_id <= 999999):
        return _Response(status_code=400)
    try:
        async with _httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{_LOGO_BASE}/leagues/{league_id}.png")
            if r.status_code == 200:
                return _Response(r.content, media_type="image/png", headers=_LOGO_CACHE_HEADERS)
    except Exception:
        pass
    return _Response(status_code=404)

app.include_router(auth.router)
app.include_router(suggestions.router)
app.include_router(admin.router)
app.include_router(fixtures.router)
app.include_router(public.router)
app.include_router(chat.router)
app.include_router(payments.router)
app.include_router(social.router)
app.include_router(banca.router)
app.include_router(leaderboard.router)
app.include_router(live.router)


@app.on_event("startup")
def run_migrations():
    """Migrations não-destrutivas: ADD COLUMN IF NOT EXISTS."""
    from database import get_connection
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS home_team_id INTEGER;")
        cur.execute("ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS away_team_id INTEGER;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(30) UNIQUE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cpf VARCHAR(14) UNIQUE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(10) UNIQUE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token VARCHAR(100);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP;")
        cur.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id                SERIAL PRIMARY KEY,
                user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                mp_payment_id     VARCHAR(50) UNIQUE NOT NULL,
                plan_key          VARCHAR(20) NOT NULL,
                amount            NUMERIC(10,2) NOT NULL,
                status            VARCHAR(20) NOT NULL DEFAULT 'approved',
                expires_at        TIMESTAMP NOT NULL,
                payment_method    VARCHAR(50),
                created_at        TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_banca (
                user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                bankroll_start NUMERIC(10,2) NOT NULL DEFAULT 100,
                bankroll_goal  NUMERIC(10,2),
                updated_at     TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("ALTER TABLE user_banca ADD COLUMN IF NOT EXISTS bankroll_goal NUMERIC(10,2);")
        cur.execute("ALTER TABLE user_banca ADD COLUMN IF NOT EXISTS unit_value NUMERIC(10,2);")
        cur.execute("ALTER TABLE user_banca ADD COLUMN IF NOT EXISTS alav_bankroll_init NUMERIC(10,2);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_followed_picks (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pick_id     INTEGER NOT NULL,
                pick_type   VARCHAR(20) NOT NULL,
                stake_units NUMERIC(5,2) NOT NULL DEFAULT 1,
                followed_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (user_id, pick_id, pick_type)
            )
        """)

        # Social tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pick_reactions (
                id         SERIAL PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                pick_id    INTEGER NOT NULL,
                pick_type  VARCHAR(20) NOT NULL,
                reaction   VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (user_id, pick_id, pick_type, reaction)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pick_comments (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                user_name       TEXT NOT NULL,
                user_plan       TEXT NOT NULL DEFAULT 'free',
                user_avatar_url TEXT,
                pick_id         INTEGER NOT NULL,
                pick_type       VARCHAR(20) NOT NULL,
                content         TEXT NOT NULL,
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                user_name       TEXT NOT NULL,
                user_plan       TEXT NOT NULL DEFAULT 'free',
                user_avatar_url TEXT,
                content         TEXT NOT NULL,
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """)
        # Backfill registros existentes que têm fixture_id mas não têm team IDs
        cur.execute("""
            UPDATE picks_free pf
            SET home_team_id = f.home_team_id,
                away_team_id = f.away_team_id
            FROM fixtures f
            WHERE f.fixture_id = pf.fixture_id
              AND pf.home_team_id IS NULL
              AND f.home_team_id IS NOT NULL;
        """)
        conn.commit()
    except Exception as e:
        logger.error("[MIGRATION] Erro: %s", e)
        conn.rollback()
    finally:
        cur.close()
        conn.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve React SPA (deve ficar por último — só ativo se o build existir)
_dist = _pathlib.Path(__file__).parent / "dist"
if _dist.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = _dist / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_dist / "index.html"))
