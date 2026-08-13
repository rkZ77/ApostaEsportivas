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
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# DB_*_PROD/DB_*_DEV vivem em .env.dev/.env.prod (separadas do .env
# principal) pra reduzir o raio de explosão caso um dos arquivos vaze.
_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)

from migrations import run_startup_migrations
from routers import admin, auth, banca, chat, fixtures, leaderboard, live, live_picks, notifications, payments, personal, public, social, suggestions
from runtime_env import side_effects_note

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
    # Sem o secret o webhook falha FECHADO (403 em tudo), entao a assinatura
    # some do site sem nenhum sinal. Faltar aqui e' incidente, nao detalhe.
    "MERCADOPAGO_WEBHOOK_SECRET": "confirmacao automatica de pagamento (webhook)",
    "ANTHROPIC_API_KEY": "IA / picks",
    "RESEND_API_KEY": "envio de emails",
    "TURNSTILE_SECRET_KEY": "verificação anti-bot (captcha) no login/cadastro",
    "VAPID_PRIVATE_KEY": "push notifications",
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

# Nada saia daqui sem compressao. O JSON da Home e' o caso extremo:
# /api/public/results devolve resumo + serie diaria + quebra por liga + a
# lista de recentes, texto repetitivo que o gzip corta em ~80%. Os bundles JS
# e CSS servidos pelo catch-all do SPA passam pelo mesmo caminho (o
# `dist/` e' servido pelo FastAPI, nao por um nginx na frente), entao ate'
# entao eles iam inteiros pro celular.
#
# 500 bytes de piso: abaixo disso o cabecalho de compressao custa mais do que
# economiza. Nivel 6, nao o 9 que vem por padrao: em JSON os dois chegam
# praticamente no mesmo tamanho, e o 9 gasta varias vezes mais CPU pra isso --
# num container pequeno esse tempo volta como latencia na propria resposta que
# a compressao deveria acelerar.
#
# Registrado ANTES do CORS de proposito. O Starlette empilha ao contrario (o
# ultimo add_middleware fica por fora), entao com esta ordem o CORS e' a
# camada externa e o gzip a interna: a resposta e' comprimida primeiro e so'
# depois recebe os cabecalhos de CORS, que assim nunca entram no corpo
# comprimido. Invertido, o preflight OPTIONS passaria pelo compressor a toa.
app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)

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
# Picks Ao Vivo (2026-08-11). Produto novo, DEV apenas nesta versao: os
# endpoints respondem "indisponivel" onde a tabela picks_live nao existe, e o
# disparo do motor recusa em producao (routers/live_picks.rodar_motor). Montar
# aqui nao muda nada pro pre-jogo -- nenhuma rota existente e' tocada.
app.include_router(live_picks.router)
app.include_router(notifications.router)
app.include_router(personal.router)


@app.on_event("startup")
async def start_rate_store_cleanup():
    asyncio.create_task(_cleanup_rate_stores())


# O scheduler.py foi REMOVIDO em 2026-08-01, por decisao do usuario: nada mais
# roda sozinho neste backend, em nenhum ambiente (prod, noprod, dev). Sairam
# junto os 5 jobs que existiam -- pipeline diario 00:10, resolve_picks 5min,
# reverify_stats 3h, banca_reminder 1h e expire_plans 1h.
#
# Tudo continua disparavel na mao, que e' como o produto passa a operar (o
# usuario gera os picks e publica no horario que quiser):
#   - gerar picks .... POST /api/admin/run-pipeline {"command": "tudo"}
#                      ou `python main.py tudo` na linha de comando
#   - resolver picks . POST /api/admin/resolve-picks
#   - reconferir ..... POST /api/admin/reverify-stats-results
#
# expire_plans nao deixou buraco: a expiracao de plano ja e' avaliada em
# tempo de leitura (lazy expiry em auth_utils.py::get_current_user,
# is_vip_active e require_vip, alem do login em routers/auth.py). O job so'
# acertava a coluna no banco; sem ele, VIP vencido perde o acesso do mesmo
# jeito, na requisicao seguinte.
@app.on_event("startup")
def run_startup_migrations_hook():
    logger.info("[STARTUP] %s", side_effects_note())
    run_startup_migrations(logger)


@app.on_event("shutdown")
def fechar_pool_hook():
    """Devolve as conexoes ao Postgres no encerramento.

    Sem isto, cada redeploy do Railway deixa ate DB_POOL_MAX conexoes penduradas
    no servidor ate o timeout dele -- e o Supabase limita conexoes por projeto.
    Alguns deploys seguidos e o proximo processo sobe sem conseguir conectar.
    """
    from database import fechar_pool
    fechar_pool()
    logger.info("[SHUTDOWN] pool de conexao fechado")


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

# O Vite assina cada arquivo de /assets com o hash do conteudo
# (Home-C6srAYyR.js): mudou o conteudo, muda o nome. Entao o conteudo daquele
# nome nunca muda, e revalidar e' viagem perdida.
#
# Sem este cabecalho o FileResponse mandava so' ETag/Last-Modified, e cada
# carregamento repetido da Home gastava uma ida e volta por chunk -- uns dez
# 304 em serie antes do primeiro pixel, o que no 4G custa mais que o download.
#
# O index.html e' o oposto: ele e' quem aponta pros hashes novos depois de um
# deploy. Se ficar em cache, o navegador continua pedindo chunk que nao existe
# mais (e cai no reload automatico do RouteErrorBoundary). Por isso revalida
# sempre.
_ASSET_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}
_HTML_CACHE  = {"Cache-Control": "no-cache"}

if _dist.exists():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Resolve e confirma que o resultado fica dentro de _dist -- sem isso,
        # full_path com ".." (ex: /../../../../etc/passwd) escapa do diretorio
        # do build e serve qualquer arquivo legivel pelo processo.
        candidate = (_dist / full_path).resolve()
        if candidate.is_relative_to(_dist) and candidate.is_file():
            eterno = full_path.startswith("assets/") and candidate.suffix != ".html"
            return FileResponse(str(candidate), headers=_ASSET_CACHE if eterno else None)
        return FileResponse(str(_dist / "index.html"), headers=_HTML_CACHE)
