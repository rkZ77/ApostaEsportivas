import asyncio
import logging
import os
import pathlib
import time
from collections import defaultdict

import httpx
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv(find_dotenv())

from migrations import run_startup_migrations
from routers import admin, auth, banca, chat, fixtures, leaderboard, live, notifications, payments, public, social, suggestions
from scheduler import start_background_scheduler, start_expire_plans_task

_log_level = logging.DEBUG if os.getenv("APP_ENV") != "production" else logging.INFO
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

_REQUIRED_VARS = ["JWT_SECRET"]
_OPTIONAL_VARS = {
    "MERCADOPAGO_ACCESS_TOKEN": "pagamentos",
    "ANTHROPIC_API_KEY": "IA / picks",
    "RESEND_API_KEY": "envio de emails",
    "TURNSTILE_SECRET_KEY": "verificação anti-bot (captcha) no login/cadastro",
}

_missing_required = [v for v in _REQUIRED_VARS if not os.getenv(v)]
if _missing_required:
    logger.critical("[STARTUP] Variaveis obrigatorias ausentes: %s - servidor nao ira funcionar!", _missing_required)

_has_db = os.getenv("DATABASE_URL") or os.getenv("DB_HOST") or os.getenv("DB_HOST_PROD")
if not _has_db:
    logger.warning("[STARTUP] Nenhuma variavel de banco configurada (DATABASE_URL, DB_HOST ou DB_HOST_PROD)")

for _var, _desc in _OPTIONAL_VARS.items():
    if not os.getenv(_var):
        logger.warning("[STARTUP] %s nao configurada - %s desabilitado", _var, _desc)

app = FastAPI(title="Pick IA API", version="1.0.0", docs_url=None, redoc_url=None)
_SERVER_VERSION = str(int(time.time()))

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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://www.googletagmanager.com https://www.google-analytics.com https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://www.google-analytics.com https://analytics.google.com https://region1.google-analytics.com https://challenges.cloudflare.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "frame-src https://challenges.cloudflare.com; "
        "frame-ancestors 'none'"
    )
    return response


_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 300
RATE_WINDOW = 60

_login_failures: dict[str, list[float]] = defaultdict(list)
LOGIN_MAX_FAILURES = 10
LOGIN_LOCKOUT_SECS = 900

_forgot_store: dict[str, list[float]] = defaultdict(list)
FORGOT_LIMIT = 3
FORGOT_WINDOW = 900

_reset_store: dict[str, list[float]] = defaultdict(list)
RESET_LIMIT = 5
RESET_WINDOW = 900

_TRUST_XFF = os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() in ("1", "true", "yes")


def _get_real_ip(request: Request) -> str:
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    if _TRUST_XFF:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    # So limita trafego de API -- rotas do SPA (/, /picks, /admin, ...) e
    # assets estaticos (JS/CSS/imagens do build, servidos pelo mesmo app via
    # /static e o catch-all serve_spa) passam direto. Achado com dado real de
    # producao: um unico carregamento de pagina com cache frio dispara 15-30
    # requests so de chunk JS/CSS -- contava tudo isso contra o mesmo budget
    # das chamadas de API, entao uso legitimo com poucas abas abertas (ex:
    # admin acompanhando o pipeline + picks ao vivo) estourava 429 sem
    # nenhum abuso de verdade acontecendo.
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    ip = _get_real_ip(request)
    now = time.time()

    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        return JSONResponse({"detail": "Muitas requisicoes. Tente novamente em breve."}, status_code=429)
    _rate_store[ip].append(now)

    if request.url.path in ("/api/auth/login", "/api/auth/register"):
        _login_failures[ip] = [t for t in _login_failures[ip] if now - t < LOGIN_LOCKOUT_SECS]
        if len(_login_failures[ip]) >= LOGIN_MAX_FAILURES:
            remaining = int(LOGIN_LOCKOUT_SECS - (now - _login_failures[ip][0]))
            return JSONResponse(
                {"detail": f"Conta temporariamente bloqueada. Tente novamente em {remaining // 60} min."},
                status_code=429,
            )

    if request.url.path == "/api/auth/forgot-password":
        _forgot_store[ip] = [t for t in _forgot_store[ip] if now - t < FORGOT_WINDOW]
        if len(_forgot_store[ip]) >= FORGOT_LIMIT:
            return JSONResponse({"detail": "Muitas tentativas de redefinicao. Aguarde 15 minutos."}, status_code=429)
        _forgot_store[ip].append(now)

    if request.url.path == "/api/auth/reset-password":
        _reset_store[ip] = [t for t in _reset_store[ip] if now - t < RESET_WINDOW]
        if len(_reset_store[ip]) >= RESET_LIMIT:
            return JSONResponse({"detail": "Muitas tentativas de reset. Aguarde 15 minutos."}, status_code=429)
        _reset_store[ip].append(now)

    response = await call_next(request)

    if request.url.path == "/api/auth/login" and response.status_code in (401, 403):
        _login_failures[ip].append(now)

    return response


async def _cleanup_rate_stores():
    while True:
        await asyncio.sleep(600)
        now = time.time()
        for store, window in (
            (_rate_store, RATE_WINDOW),
            (_login_failures, LOGIN_LOCKOUT_SECS),
            (_forgot_store, FORGOT_WINDOW),
            (_reset_store, RESET_WINDOW),
        ):
            stale = [ip for ip, ts in list(store.items()) if not any(now - t < window for t in ts)]
            for ip in stale:
                store.pop(ip, None)


_base_dir = pathlib.Path(__file__).parent
_static_dir = _base_dir / "static"
_avatars_dir = _static_dir / "avatars"
_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_LOGO_BASE = "https://media.api-sports.io/football"
_LOGO_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800, stale-while-revalidate=86400"}
_logo_disk_cache = pathlib.Path("/tmp/pickia_logos")
_logo_disk_cache.mkdir(parents=True, exist_ok=True)


async def _serve_logo(kind: str, item_id: int) -> Response:
    cache_path = _logo_disk_cache / f"{kind}_{item_id}.png"
    if cache_path.exists():
        return Response(cache_path.read_bytes(), media_type="image/png", headers=_LOGO_CACHE_HEADERS)

    url = f"{_LOGO_BASE}/{kind}s/{item_id}.png"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.content:
                cache_path.write_bytes(r.content)
                return Response(r.content, media_type="image/png", headers=_LOGO_CACHE_HEADERS)
    except Exception:
        pass
    return Response(status_code=404)


@app.get("/api/proxy/team/{team_id}.png", include_in_schema=False)
async def proxy_team_logo(team_id: int):
    if not (1 <= team_id <= 999999):
        return Response(status_code=400)
    return await _serve_logo("team", team_id)


@app.get("/api/proxy/league/{league_id}.png", include_in_schema=False)
async def proxy_league_logo(league_id: int):
    if not (1 <= league_id <= 999999):
        return Response(status_code=400)
    return await _serve_logo("league", league_id)


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
app.include_router(notifications.router)


@app.on_event("startup")
async def start_rate_store_cleanup():
    asyncio.create_task(_cleanup_rate_stores())


@app.on_event("startup")
async def start_expire_plans():
    start_expire_plans_task(logger)


@app.on_event("startup")
def run_migrations_and_scheduler():
    if run_startup_migrations(logger):
        start_background_scheduler(logger)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/version", include_in_schema=False)
def get_version():
    return {"v": _SERVER_VERSION}


_SITEMAP_BASE = "https://pickia.com.br"
_SITEMAP_PICK_TABLES = [
    ("vip",         "picks_vip"),
    ("free",        "picks_free"),
    ("multipla",    "picks_multiplas"),
    ("alavancagem", "picks_alavancagem"),
]


@app.get("/sitemap.xml", include_in_schema=False)
def dynamic_sitemap():
    """Sitemap gerado a partir do banco -- inclui as paginas publicas de
    resultado/pick individual (/resultados, /p/:tipo/:id), que ja existem e
    sao publicas mas antes ficavam de fora do sitemap estatico."""
    from database import get_connection

    static_urls = [
        (f"{_SITEMAP_BASE}/", "weekly", "1.0"),
        (f"{_SITEMAP_BASE}/planos", "weekly", "0.9"),
        (f"{_SITEMAP_BASE}/como-funciona", "monthly", "0.7"),
        (f"{_SITEMAP_BASE}/resultados", "daily", "0.8"),
        (f"{_SITEMAP_BASE}/login", "monthly", "0.6"),
        (f"{_SITEMAP_BASE}/termos", "yearly", "0.3"),
        (f"{_SITEMAP_BASE}/privacidade", "yearly", "0.3"),
    ]

    pick_urls: list[tuple[str, str]] = []
    conn = get_connection()
    cur = conn.cursor()
    for pick_type, table in _SITEMAP_PICK_TABLES:
        try:
            cur.execute(
                f"SELECT id, match_date FROM {table} WHERE result IS NOT NULL ORDER BY match_date DESC LIMIT 200"
            )
            pick_urls += [
                (f"{_SITEMAP_BASE}/p/{pick_type}/{row[0]}", str(row[1]))
                for row in cur.fetchall()
            ]
        except Exception:
            logger.warning("[SITEMAP] falha ao ler %s", table, exc_info=True)
            conn.rollback()
    cur.close()
    conn.close()

    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, changefreq, priority in static_urls:
        parts.append(f"  <url><loc>{loc}</loc><changefreq>{changefreq}</changefreq><priority>{priority}</priority></url>")
    for loc, lastmod in pick_urls:
        parts.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod><changefreq>monthly</changefreq><priority>0.5</priority></url>")
    parts.append("</urlset>")

    return Response(content="\n".join(parts), media_type="application/xml")


_dist = _base_dir / "dist"
if _dist.exists():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = _dist / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_dist / "index.html"))
