import asyncio
import io
import logging
import mimetypes
import os
import pathlib
import re
import time
from collections import defaultdict

import httpx
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# DB_*_PROD/DB_*_DEV vivem em .env.dev/.env.prod (separadas do .env
# principal) pra reduzir o raio de explosão caso um dos arquivos vaze.
_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)

import agent_web
from migrations import run_startup_migrations
from routers import admin, auth, banca, chat, explorer, fixtures, leaderboard, live, live_picks, notifications, payments, personal, public, social, suggestions
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
async def superficie_de_agente(request: Request, call_next):
    """Mesma URL, markdown pra quem pediu markdown.

    Fica ANTES do security_headers no arquivo de proposito. O Starlette
    empilha ao contrario, entao definido aqui este middleware e' o mais
    interno, e a resposta em markdown ainda sobe pelo security_headers e
    recebe nosscript, nosniff e companhia. Definido depois, ela sairia sem
    cabecalho de seguranca nenhum.

    O `Vary: Accept` nao e' detalhe: sem ele o Cloudflare guardaria a primeira
    resposta (HTML ou markdown) e serviria ela pros dois publicos.
    """
    if request.method != "GET":
        return await call_next(request)

    chave = agent_web.caminho_com_markdown(request.url.path)
    if chave is None:
        return await call_next(request)

    if agent_web.prefere_markdown(request.headers.get("accept", "")):
        # Threadpool porque /resultados.md le' o banco, e psycopg2 e' bloqueante.
        # Chamado direto aqui dentro, ele travaria o event loop do processo
        # inteiro (WEB_CONCURRENCY e' 1) enquanto a consulta roda: um agente
        # lento seguraria a Home de todo mundo. Rota sincrona nao tem esse
        # problema porque o FastAPI ja' a joga no threadpool sozinho; middleware
        # nao.
        pronta = await run_in_threadpool(agent_web.resposta_markdown, chave)
        if pronta is not None:
            return pronta

    response = await call_next(request)

    link = agent_web.link_header(chave)
    if link:
        response.headers["Link"] = link

    # Merge por token: "Accept-Encoding" ja' costuma estar la', e comparar por
    # substring diria que "Accept" ja' existe.
    tokens = [t.strip() for t in response.headers.get("Vary", "").split(",") if t.strip()]
    if not any(t.lower() == "accept" for t in tokens):
        tokens.append("Accept")
    response.headers["Vary"] = ", ".join(tokens)
    return response


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

# LADO MAXIMO DO ESCUDO SERVIDO.
#
# A origem manda 150x150 pesando 20 a 45KB, e a tela desenha a 16px
# (LeagueLogo), 18 a 24px (TeamLogo) ou 32px (Fixtures). 64 cobre o maior uso em
# retina (32 x2) e nada mais. Medido em escudos reais: 45KB -> 3.1KB.
_LOGO_LADO = 64

# Versao no nome do arquivo em cache. O cache em disco de antes guarda a imagem
# ORIGINAL; sem trocar a chave, servidor que ja rodou continuaria devolvendo os
# 45KB pra sempre, e a mudanca so' valeria em maquina nova.
_LOGO_CACHE_V = "v2-64"

# ONDE O CACHE MORA.
#
# `/tmp` some a cada deploy e a cada restart do container no Railway. Com uns 20
# escudos por tela de Picks, o primeiro visitante depois de todo deploy pagava
# 20 downloads na API-Sports mais 20 reducoes no Pillow -- e, ate' 14/08, com o
# Pillow rodando dentro do handler async, ou seja, travando o event loop do
# processo (que e' um so') pra todo mundo que estivesse usando o site.
#
# LOGO_CACHE_DIR aponta pra um volume persistente quando existir um. Sem a
# variavel o comportamento e' o de antes, entao isto nao quebra nada em dev.
_logo_disk_cache = pathlib.Path(os.getenv("LOGO_CACHE_DIR", "/tmp/pickia_logos"))
try:
    _logo_disk_cache.mkdir(parents=True, exist_ok=True)
except OSError:
    logger.warning("[LOGO] %s indisponivel, caindo pro /tmp", _logo_disk_cache)
    _logo_disk_cache = pathlib.Path("/tmp/pickia_logos")
    _logo_disk_cache.mkdir(parents=True, exist_ok=True)


def _reduzir_logo(bruto: bytes) -> bytes:
    """Escudo no tamanho que a tela usa. Devolve o original se nao der.

    Paletiza em 256 cores porque escudo e' arte chapada: quase nao ha perda
    visivel e o arquivo cai muito mais do que so' redimensionando (45KB ->
    21.6KB so' com resize, 3.1KB com resize + paleta).

    Nunca levanta. Falha aqui nao pode virar escudo faltando na tela -- serve o
    original, que e' pesado porem correto.
    """
    try:
        from PIL import Image

        with Image.open(io.BytesIO(bruto)) as im:
            im = im.convert("RGBA")
            if max(im.size) <= _LOGO_LADO:
                return bruto
            im.thumbnail((_LOGO_LADO, _LOGO_LADO), Image.LANCZOS)
            # FASTOCTREE preserva o canal alfa; o metodo padrao (mediancut) nao,
            # e escudo sem transparencia ganha um quadrado branco atras.
            paleta = im.quantize(colors=256, method=Image.FASTOCTREE)
            saida = io.BytesIO()
            paleta.save(saida, "PNG", optimize=True)
            reduzido = saida.getvalue()
        return reduzido if len(reduzido) < len(bruto) else bruto
    except Exception:
        logger.warning("[LOGO] reducao falhou, servindo original", exc_info=True)
        return bruto


def _ler_cache_logo(cache_path: pathlib.Path) -> bytes | None:
    try:
        return cache_path.read_bytes()
    except OSError:
        return None


def _gravar_cache_logo(cache_path: pathlib.Path, conteudo: bytes) -> None:
    # Grava em temporario e renomeia: dois requests pedindo o mesmo escudo ao
    # mesmo tempo nao podem deixar um PNG pela metade no cache.
    try:
        tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(conteudo)
        tmp.replace(cache_path)
    except OSError:
        logger.warning("[LOGO] nao consegui gravar %s", cache_path, exc_info=True)


async def _serve_logo(kind: str, item_id: int) -> Response:
    cache_path = _logo_disk_cache / f"{kind}_{item_id}_{_LOGO_CACHE_V}.png"

    # TUDO QUE BLOQUEIA VAI PRO THREADPOOL.
    #
    # Este handler e' `async`, entao qualquer coisa sincrona aqui dentro trava o
    # event loop -- e com um worker so' (ver Dockerfile) isso e' o site inteiro
    # parado. Leitura de disco e' rapida mas nao e' de graca quando sao 20
    # escudos de uma vez; `_reduzir_logo` e' LANCZOS + quantize do Pillow, que e'
    # CPU pura e chegava a segundos por escudo em cache frio.
    cached = await run_in_threadpool(_ler_cache_logo, cache_path)
    if cached is not None:
        return Response(cached, media_type="image/png", headers=_LOGO_CACHE_HEADERS)

    url = f"{_LOGO_BASE}/{kind}s/{item_id}.png"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url)
            if r.status_code == 200 and r.content:
                conteudo = await run_in_threadpool(_reduzir_logo, r.content)
                await run_in_threadpool(_gravar_cache_logo, cache_path, conteudo)
                return Response(conteudo, media_type="image/png", headers=_LOGO_CACHE_HEADERS)
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
app.include_router(explorer.router)
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
# Superficie pra agente de IA: llms.txt, markdown das paginas publicas,
# /.well-known e o servidor MCP. Precisa entrar ANTES do catch-all do SPA
# (fim deste arquivo), senao /llms.txt cai no index.html.
app.include_router(agent_web.router)


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

def _codificacoes_aceitas(request: Request) -> set[str]:
    """Tokens de Accept-Encoding, sem os parametros de qualidade.

    Por token e nao por `"br" in cabecalho`: substring casaria dentro de
    qualquer outra palavra e mandaria brotli pra quem nao pediu, o que vira
    pagina em branco e nao erro visivel.
    """
    bruto = request.headers.get("accept-encoding", "")
    return {p.split(";")[0].strip().lower() for p in bruto.split(",") if p.strip()}


def _resposta_de_arquivo(request: Request, arquivo: pathlib.Path, cache: dict,
                         status: int = 200) -> FileResponse:
    """Serve o arquivo, preferindo a versao pre-comprimida quando existir.

    O `.br`/`.gz` sai do build (frontend/scripts/precomprimir.mjs), nao daqui:
    comprimir por requisicao gasta CPU do mesmo processo que responde a API, e
    brotli em nivel 11 e' caro demais pra isso. Pre-comprimido, servir e' so'
    mandar outro arquivo do disco.

    O media_type vem do nome ORIGINAL. Sem isso o FileResponse olharia
    `index.js.br` e mandaria octet-stream, e o navegador nao executaria o script.
    """
    aceitas = _codificacoes_aceitas(request)
    tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"

    for codificacao, sufixo in (("br", ".br"), ("gzip", ".gz")):
        if codificacao not in aceitas:
            continue
        pronto = arquivo.with_name(arquivo.name + sufixo)
        if not pronto.is_file():
            continue
        cabecalhos = {**cache, "Content-Encoding": codificacao, "Vary": "Accept-Encoding"}
        return FileResponse(str(pronto), media_type=tipo, headers=cabecalhos,
                            status_code=status)

    # GZipMiddleware cuida do caso sem arquivo pronto (ele pula quando ja existe
    # Content-Encoding, entao os dois caminhos nao se atropelam).
    return FileResponse(str(arquivo), media_type=tipo, headers=cache or None,
                        status_code=status)


#: Extensao curta de arquivo (.php, .env, .zip). Deliberadamente estreita: um
#: slug com ponto no meio ("versao-2.0-do-motor") tem sufixo longo e com hifen,
#: entao nao casa e continua sendo tratado como rota.
_EXTENSAO_DE_ARQUIVO = re.compile(r"^\.[A-Za-z0-9]{1,6}$")

if _dist.exists():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        # Resolve e confirma que o resultado fica dentro de _dist -- sem isso,
        # full_path com ".." (ex: /../../../../etc/passwd) escapa do diretorio
        # do build e serve qualquer arquivo legivel pelo processo.
        candidate = (_dist / full_path).resolve()
        # Pedido direto a um .br/.gz cai no index.html: eles existem so' como
        # variante do arquivo real e serviria bytes comprimidos sem o cabecalho
        # que diz isso.
        pedido_comprimido = candidate.suffix in (".br", ".gz")
        if candidate.is_relative_to(_dist) and candidate.is_file() and not pedido_comprimido:
            eterno = full_path.startswith("assets/") and candidate.suffix != ".html"
            return _resposta_de_arquivo(request, candidate, _ASSET_CACHE if eterno else {})
        # SOFT 404: QUEM PEDE ARQUIVO E NAO ACHA RECEBE 404 DE VERDADE.
        #
        # Tudo o que nao e' arquivo real cai aqui e recebia o index.html com
        # status 200, inclusive /wp-login.php e /.env -- a tela dizia "pagina
        # nao encontrada" pro humano enquanto o servidor dizia "200 OK" pro
        # Google. E' o soft 404 classico.
        #
        # A regra so' afirma 404 onde da' pra ter certeza: caminho terminado em
        # extensao curta de arquivo (.php, .env, .sql, .zip) NUNCA e' rota do
        # SPA, porque as rotas do React nao tem ponto (/picks, /blog/slug,
        # /p/vip/12). O resto -- inclusive um /pickss digitado errado --
        # continua 200, porque distinguir rota valida de typo exigiria repetir
        # aqui a tabela de rotas do App.tsx, e duas copias da mesma regra e'
        # como elas comecam a divergir. Pra esse caso o `noindex` da pagina ja'
        # segura a indexacao.
        #
        # O corpo continua sendo o index.html: quem chegou por um link velho
        # ve a pagina de erro do site, com o caminho de volta, em vez de um
        # texto cru do servidor.
        # `.env` e `.htaccess` entram pelo nome, e nao pelo sufixo: pathlib
        # trata nome iniciado por ponto como arquivo oculto SEM extensao, entao
        # `.suffix` volta vazio e eles escapariam da regra. Rota do SPA nenhuma
        # comeca com ponto.
        parece_arquivo = (candidate.name.startswith(".")
                          or bool(_EXTENSAO_DE_ARQUIVO.match(candidate.suffix)))
        return _resposta_de_arquivo(request, _dist / "index.html", _HTML_CACHE,
                                    status=404 if parece_arquivo else 200)
