"""Superfície do site para agentes de IA.

POR QUE ESTE MÓDULO EXISTE.

O site é uma SPA Vite. Quem pede o HTML de /como-funciona recebe
`<div id="root"></div>` e um bundle de JavaScript · o texto só existe depois
que o navegador executa React. Buscador grande tem renderizador de JS e dá um
jeito; agente de IA lendo por HTTP simples, não. Na prática o conteúdo do site
é invisível pra esse tipo de leitor, e nenhuma quantidade de meta tag conserta
isso.

Este módulo serve a MESMA informação em markdown, por três portas:

  1. `/llms.txt` e `/llms-full.txt`, que são o índice e o corpo (llmstxt.org).
  2. `/<pagina>.md` e negociação por `Accept: text/markdown` na URL normal.
  3. `/mcp`, um servidor MCP só de leitura sobre o que já é público.

REGRA QUE VALE PRA TODO ESTE ARQUIVO: nada aqui pode mostrar mais do que a
tela pública mostra. O mercado da dica do dia continua bloqueado pra quem não
tem conta, e pick VIP não entra em markdown nenhum. Se um dia parecer que
"é só texto, não tem problema", lembre que texto é exatamente o que o
agente lê.

FONTE DA VERDADE. Preço vem de `routers.payments.PLANS`, número vem do banco
pelas funções de `routers.public`, e a lista de posts vem do manifesto que o
build do frontend gera. Nada de valor copiado na mão: já aconteceu de o
index.html anunciar R$ 49,90 enquanto a cobrança real era R$ 39,90, e um
arquivo que agente lê erra do mesmo jeito, só que mais rápido.
"""
import json
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

SITE = os.getenv("SITE_URL", "https://pickia.com.br").rstrip("/")

# O build do frontend escreve este arquivo dentro do dist (ver
# frontend/scripts/gerar-blog-index.mjs). Ler o `src/blog/content/` direto não
# funciona: a imagem de produção copia só o `dist`, o código-fonte do frontend
# não existe lá dentro.
_DIST = pathlib.Path(__file__).parent / "dist"
_BLOG_INDEX = _DIST / "blog-index.json"

MEDIA_MARKDOWN = "text/markdown; charset=utf-8"
MEDIA_TEXTO = "text/plain; charset=utf-8"
MEDIA_LINKSET = "application/linkset+json"

# Cache curto. O conteúdo muda quando sai pick ou post, não a cada minuto, e
# um agente que reconsulta não pode custar uma varredura de banco por vez.
_CACHE_CURTO = {"Cache-Control": "public, max-age=300"}
_CACHE_LONGO = {"Cache-Control": "public, max-age=3600"}


# ──────────────────────────────────────────────────────────────────────────
# Blog
# ──────────────────────────────────────────────────────────────────────────
def posts_do_blog() -> list[dict]:
    """Posts publicados, do mais novo pro mais velho.

    Devolve lista vazia quando o manifesto não existe (dev sem build), e o
    llms.txt simplesmente não lista a seção · melhor uma seção a menos do que
    o processo inteiro cair porque o blog não foi gerado.
    """
    try:
        if not _BLOG_INDEX.is_file():
            return []
        dados = json.loads(_BLOG_INDEX.read_text(encoding="utf-8"))
        posts = dados.get("posts", []) if isinstance(dados, dict) else dados
        return sorted(posts, key=lambda p: p.get("publishedAt", ""), reverse=True)
    except Exception:
        logger.warning("[AGENT] blog-index.json ilegível", exc_info=True)
        return []


# ──────────────────────────────────────────────────────────────────────────
# Conteúdo das páginas
# ──────────────────────────────────────────────────────────────────────────
def _planos() -> list[dict]:
    from routers.payments import PLANS, PLAN_PERIODS

    return [
        {
            "chave": chave,
            "titulo": info["title"],
            "preco": float(info["price"]),
            "dias": int(info["days"]),
            "periodo": PLAN_PERIODS.get(chave, ""),
        }
        for chave, info in PLANS.items()
    ]


def _brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


_SOBRE_O_PRODUTO = """\
Pick IA publica entradas de futebol (picks) geradas por um motor estatístico
próprio, a partir de dados de jogo, escalação e mercado. Uma camada de revisão
por IA pode vetar uma entrada antes de ela ser publicada, mas não é ela quem
escolhe o pick.

Cada pick traz o jogo, o mercado, a odd de referência no momento da publicação
e o tamanho sugerido da entrada em unidades. O resultado de cada pick é
resolvido depois pelo placar oficial e entra no histórico público, verde ou
vermelho · o histórico não é editado.
"""


def md_home() -> str:
    planos = _planos()
    mensal = next((p for p in planos if p["chave"] == "mensal"), None)
    linha_preco = (
        f"assinatura a partir de {_brl(mensal['preco'])} por {mensal['periodo']}"
        if mensal
        else "assinatura paga por período"
    )
    return f"""# Pick IA

> Picks de futebol com análise estatística, cobrindo o Brasileirão e as
> principais ligas europeias. Parte do conteúdo é gratuita e {linha_preco}.

{_SOBRE_O_PRODUTO}

## O que é gratuito

- Dica do dia: um pick por dia, aberto. Visitante sem conta vê o jogo e a odd;
  o mercado exige conta gratuita.
- Resultados: o histórico completo de picks resolvidos, com lucro e taxa de
  acerto, sem precisar de conta.
- Blog: material sobre gestão de banca e leitura de mercado.

## O que é pago

Picks VIP, múltiplas, caminhos de alavancagem, faltas e defesas de goleiro.
Contas novas têm 2 dias de teste com acesso VIP.

## Links

- [Como funciona]({SITE}/como-funciona): o método, os tipos de pick e como o
  resultado é resolvido.
- [Resultados]({SITE}/resultados): histórico público, atualizado conforme os
  jogos terminam.
- [Planos]({SITE}/planos): preços e o que cada plano libera.
- [Blog]({SITE}/blog)
- [Termos de uso]({SITE}/termos)
- [Política de privacidade]({SITE}/privacidade)

## Aviso

Aposta esportiva envolve risco de perda financeira e é proibida para menores
de 18 anos. Pick nenhum é garantia de retorno, e desempenho passado não
prevê resultado futuro.
"""


def md_como_funciona() -> str:
    return f"""# Como funciona o Pick IA

> Como os picks são gerados, quais tipos existem e como o resultado é apurado.

{_SOBRE_O_PRODUTO}

## Tipos de pick

- VIP: a entrada principal do dia, exclusiva de assinante.
- Dica do dia (free): uma entrada aberta por dia.
- Múltipla: combinação de mais de um jogo no mesmo bilhete.
- Alavancagem: um caminho de entradas encadeadas, onde o lucro de uma etapa
  compõe a próxima. Enquanto o caminho está aberto ele não é dinheiro
  realizado; ele só entra no resultado quando encerra.
- Faltas: mercados de faltas cometidas.
- Defesas de goleiro: mercados de defesas.

## Como o resultado é apurado

O placar oficial e as estatísticas do jogo chegam por integração de dados
esportivos, e cada pick é marcado como GREEN, RED, PUSH ou meia entrada
conforme o mercado. A apuração é automática e o histórico publicado em
[Resultados]({SITE}/resultados) é o mesmo que alimenta as estatísticas do
site.

## Gestão de banca

O tamanho sugerido de cada entrada é expresso em unidades, não em reais, para
que a mesma recomendação sirva a bancas de tamanhos diferentes. O usuário
registra a própria banca no site e acompanha o retorno pelas entradas que
seguiu, que podem ter odd diferente da publicada · quem entra depois pega o
preço que o mercado estiver dando naquele momento.

## Limites

- A cobertura é diária e depende de haver jogo com dado suficiente. Não existe
  volume fixo de picks por dia, e dia sem entrada é resultado possível.
- Não há horário fixo de publicação.
"""


def md_planos() -> str:
    linhas = [
        f"| {p['titulo']} | {p['periodo']} | {_brl(p['preco'])} |" for p in _planos()
    ]
    return f"""# Planos e preços do Pick IA

> Preços vigentes, lidos da mesma tabela que a cobrança usa.

| Plano | Período | Preço |
| --- | --- | --- |
{chr(10).join(linhas)}

## O que o plano libera

Picks VIP, múltiplas, caminhos de alavancagem, faltas e defesas de goleiro,
além do agente de conversa sobre os picks. A dica do dia e a página de
resultados continuam abertas sem plano.

## Teste

Conta nova recebe 2 dias com acesso VIP, uma vez por conta.

## Pagamento

O pagamento é processado pelo MercadoPago, com PIX ou cartão. O acesso vale
pelo período contratado.

Página de compra: [{SITE}/planos]({SITE}/planos)
"""


def md_resultados() -> str:
    """Números reais, do mesmo lugar que a página de Resultados lê."""
    from routers.public import public_results

    try:
        dados = public_results(slim=True)
    except Exception:
        logger.warning("[AGENT] falha ao montar resultados em markdown", exc_info=True)
        return f"""# Resultados do Pick IA

> O histórico não pôde ser lido agora. A página em HTML tem o dado completo.

[Resultados]({SITE}/resultados)
"""

    s = dados.get("summary") or {}
    total = int(s.get("total") or 0)
    greens = int(s.get("greens") or 0)
    reds = int(s.get("reds") or 0)
    profit = float(s.get("profit") or 0)
    roi = s.get("roi")
    ligas = int(s.get("leagues_count") or 0)
    acerto = round(greens / total * 100, 1) if total else 0.0

    linhas_fonte = []
    for fonte in dados.get("by_source") or []:
        linhas_fonte.append(
            f"| {fonte.get('source', '?')} | {fonte.get('total', 0)} | "
            f"{fonte.get('greens', 0)} | {fonte.get('reds', 0)} | "
            f"{fonte.get('win_rate', 0)}% | {fonte.get('roi', 0)}% |"
        )
    tabela = (
        "| Tipo | Picks | Green | Red | Acerto | ROI |\n| --- | --- | --- | --- | --- | --- |\n"
        + "\n".join(linhas_fonte)
        if linhas_fonte
        else "_Sem quebra por tipo disponível._"
    )

    return f"""# Resultados do Pick IA

> Histórico público de todos os picks já resolvidos. Números apurados pelo
> placar oficial, sem seleção de amostra.

## Consolidado

- Picks resolvidos: {total}
- Green: {greens}
- Red: {reds}
- Taxa de acerto: {acerto}%
- Lucro acumulado em unidades: {round(profit, 2)}
- ROI: {roi if roi is not None else "n/d"}%
- Ligas cobertas: {ligas}

## Por tipo de pick

{tabela}

Página em HTML, com filtro por mês e por liga: [{SITE}/resultados]({SITE}/resultados)

Aposta esportiva envolve risco de perda. Desempenho passado não prevê
resultado futuro.
"""


def md_blog() -> str:
    posts = posts_do_blog()
    if not posts:
        return f"""# Blog do Pick IA

> Material sobre gestão de banca, leitura de mercado e método.

A lista de artigos não está disponível neste momento.
[{SITE}/blog]({SITE}/blog)
"""
    itens = []
    for p in posts:
        slug = p.get("slug", "")
        itens.append(
            f"- [{p.get('title', slug)}]({SITE}/blog/{slug}): "
            f"{p.get('description', '')} "
            f"({p.get('category', '')}, {p.get('publishedAt', '')})"
        )
    return f"""# Blog do Pick IA

> Material sobre gestão de banca, leitura de mercado e método, em português.

## Artigos

{chr(10).join(itens)}
"""


def md_termos() -> str:
    return f"""# Termos de uso do Pick IA

> Esta é uma página de apoio para leitura automatizada. O texto que vale
> juridicamente é o publicado em HTML, e não este resumo.

Texto integral: [{SITE}/termos]({SITE}/termos)

Pontos que o texto integral cobre: uso da plataforma, natureza informativa dos
picks, ausência de garantia de retorno, regras de assinatura e cancelamento,
e proibição de uso por menores de 18 anos.

Nenhum conteúdo do Pick IA é recomendação de investimento, e aposta esportiva
envolve risco de perda financeira.
"""


def md_privacidade() -> str:
    return f"""# Política de privacidade do Pick IA

> Esta é uma página de apoio para leitura automatizada. O texto que vale
> juridicamente é o publicado em HTML, e não este resumo.

Texto integral: [{SITE}/privacidade]({SITE}/privacidade)

Pontos que o texto integral cobre: quais dados a conta guarda, uso de medição
de audiência, base legal, retenção, e como pedir exclusão de conta e dados.
"""


@dataclass(frozen=True)
class Pagina:
    caminho: str
    titulo: str
    resumo: str
    corpo: Callable[[], str]


PAGINAS: tuple[Pagina, ...] = (
    Pagina("/", "Pick IA", "O que é o produto, o que é grátis e o que é pago.", md_home),
    Pagina(
        "/como-funciona",
        "Como funciona",
        "Método, tipos de pick e como o resultado é apurado.",
        md_como_funciona,
    ),
    Pagina("/planos", "Planos e preços", "Preços vigentes e o que cada plano libera.", md_planos),
    Pagina(
        "/resultados",
        "Resultados",
        "Histórico público de picks resolvidos, com acerto e ROI.",
        md_resultados,
    ),
    Pagina("/blog", "Blog", "Artigos sobre gestão de banca e leitura de mercado.", md_blog),
    Pagina("/termos", "Termos de uso", "Resumo e link para o texto integral.", md_termos),
    Pagina(
        "/privacidade",
        "Privacidade",
        "Resumo e link para o texto integral.",
        md_privacidade,
    ),
)

_POR_CAMINHO = {p.caminho: p for p in PAGINAS}


# ──────────────────────────────────────────────────────────────────────────
# llms.txt
# ──────────────────────────────────────────────────────────────────────────
def llms_txt() -> str:
    """Índice no formato de llmstxt.org: H1, blockquote, seções em H2."""
    paginas = "\n".join(
        f"- [{p.titulo}]({SITE}{p.caminho}.md): {p.resumo}"
        for p in PAGINAS
        if p.caminho != "/"
    )
    posts = posts_do_blog()
    secao_blog = ""
    if posts:
        linhas = "\n".join(
            f"- [{p.get('title', p.get('slug', ''))}]({SITE}/blog/{p.get('slug', '')}): "
            f"{p.get('description', '')}"
            for p in posts
        )
        secao_blog = f"\n## Blog\n\n{linhas}\n"

    return f"""# Pick IA

> Plataforma brasileira de picks de futebol com análise estatística. Publica
> entradas diárias para Brasileirão, Champions League, Premier League e La
> Liga, com histórico de resultados aberto. Parte do conteúdo é gratuita e o
> restante é assinatura. Conteúdo em português do Brasil.

O site é uma aplicação de página única, então o HTML sozinho não carrega o
texto. Estas versões em markdown existem para leitura automatizada. A mesma
URL responde markdown quando a requisição manda `Accept: text/markdown`.

## Páginas

- [Início]({SITE}/index.md): {_POR_CAMINHO["/"].resumo}
{paginas}
{secao_blog}
## Dados abertos

- [Catálogo de APIs]({SITE}/.well-known/api-catalog): índice das APIs públicas.
- [Descrição OpenAPI]({SITE}/openapi.json): contrato da API.
- [Servidor MCP]({SITE}/.well-known/mcp.json): ferramentas de leitura sobre os
  dados públicos.

## Opcional

- [Conteúdo completo]({SITE}/llms-full.txt): todas as páginas acima em um só
  arquivo.
- [Registro de agente]({SITE}/auth.md): o que existe e o que não existe hoje
  para agentes que agem em nome de um usuário.

## Avisos

- Aposta esportiva envolve risco de perda financeira, é proibida para menores
  de 18 anos e nada aqui é recomendação de investimento.
- Desempenho passado não prevê resultado futuro.
- Pick de assinante não é publicado nestes arquivos.
"""


def llms_full_txt() -> str:
    partes = [llms_txt(), ""]
    for p in PAGINAS:
        partes.append("\n---\n")
        partes.append(p.corpo())
    return "\n".join(partes)


# ──────────────────────────────────────────────────────────────────────────
# Negociação de conteúdo
# ──────────────────────────────────────────────────────────────────────────
def _qualidades(accept: str) -> dict[str, float]:
    """Tipos aceitos com seu q, minúsculo e sem os outros parâmetros."""
    saida: dict[str, float] = {}
    for parte in (accept or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        pedacos = parte.split(";")
        tipo = pedacos[0].strip().lower()
        q = 1.0
        for extra in pedacos[1:]:
            extra = extra.strip().lower()
            if extra.startswith("q="):
                try:
                    q = float(extra[2:])
                except ValueError:
                    q = 0.0
        saida[tipo] = q
    return saida


def prefere_markdown(accept: str) -> bool:
    """True quando o cliente pediu markdown E não prefere HTML.

    Navegador manda `text/html,application/xhtml+xml,...`, então nunca cai
    aqui. O `*/*` de curl também não: pedir "qualquer coisa" não é pedir
    markdown, e devolver markdown pro curl padrão quebraria a intuição de
    quem depura o site.
    """
    q = _qualidades(accept)
    q_md = max(q.get("text/markdown", 0.0), q.get("text/x-markdown", 0.0))
    if q_md <= 0:
        return False
    return q_md >= max(q.get("text/html", 0.0), q.get("application/xhtml+xml", 0.0))


def caminho_com_markdown(caminho: str) -> Optional[str]:
    """Normaliza o caminho pedido para uma chave de PAGINAS, ou None."""
    if not caminho:
        return None
    limpo = caminho.rstrip("/") or "/"
    return limpo if limpo in _POR_CAMINHO else None


def markdown_de(caminho: str) -> Optional[str]:
    pagina = _POR_CAMINHO.get(caminho)
    return pagina.corpo() if pagina else None


def link_header(caminho: str) -> Optional[str]:
    """Valor do cabeçalho Link para uma página conhecida.

    `alternate` aponta pra versão markdown da mesma página, que é o que faz um
    agente descobrir o formato sem adivinhar sufixo. Os outros dois valem em
    qualquer página e são baratos.
    """
    chave = caminho_com_markdown(caminho)
    if chave is None:
        return None
    sufixo = "/index.md" if chave == "/" else f"{chave}.md"
    return ", ".join(
        [
            f'<{SITE}{sufixo}>; rel="alternate"; type="text/markdown"',
            f'<{SITE}/llms.txt>; rel="alternate"; type="text/plain"',
            f'<{SITE}/.well-known/api-catalog>; rel="api-catalog"',
            f'<{SITE}/openapi.json>; rel="service-desc"; type="application/json"',
        ]
    )


def resposta_markdown(caminho: str) -> Optional[Response]:
    corpo = markdown_de(caminho)
    if corpo is None:
        return None
    cabecalhos = {**_CACHE_CURTO, "Vary": "Accept"}
    link = link_header(caminho)
    if link:
        cabecalhos["Link"] = link
    return Response(content=corpo, media_type=MEDIA_MARKDOWN, headers=cabecalhos)


# ──────────────────────────────────────────────────────────────────────────
# Rotas de arquivo
# ──────────────────────────────────────────────────────────────────────────
@router.get("/llms.txt")
def rota_llms():
    # text/plain e não text/markdown de propósito: llmstxt.org serve como
    # texto, e cliente que não conhece markdown ainda consegue ler.
    return Response(llms_txt(), media_type=MEDIA_TEXTO, headers=_CACHE_CURTO)


@router.get("/llms-full.txt")
def rota_llms_full():
    return Response(llms_full_txt(), media_type=MEDIA_TEXTO, headers=_CACHE_CURTO)


def sitemap_xml() -> str:
    """Sitemap das paginas publicas, no formato sitemaps.org.

    So entra URL que responde conteudo pra quem nao tem conta. Tela atras de
    PrivateRoute (picks, banca, perfil, admin) fica de fora: indexar uma rota
    que redireciona pro login gasta rastreio e nao rende nada.

    As paginas publicas de pick (`/p/<tipo>/<id>`) tambem ficam de fora, de
    proposito. Sao milhares, cada uma com pouco texto e a analise bloqueada,
    e o que elas mostram ja esta consolidado em /resultados.

    A lista de posts vem do mesmo manifesto do llms.txt, entao publicar um
    artigo atualiza o sitemap sozinho no build seguinte.
    """
    from xml.sax.saxutils import escape

    urls: list[tuple[str, str, str]] = [
        ("/", "daily", "1.0"),
        ("/como-funciona", "monthly", "0.8"),
        ("/planos", "monthly", "0.8"),
        ("/resultados", "daily", "0.9"),
        ("/performance", "weekly", "0.6"),
        ("/blog", "weekly", "0.7"),
        ("/termos", "yearly", "0.2"),
        ("/privacidade", "yearly", "0.2"),
    ]

    linhas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for caminho, freq, prioridade in urls:
        linhas.append("  <url>")
        linhas.append(f"    <loc>{escape(SITE + caminho)}</loc>")
        linhas.append(f"    <changefreq>{freq}</changefreq>")
        linhas.append(f"    <priority>{prioridade}</priority>")
        linhas.append("  </url>")

    for post in posts_do_blog():
        slug = (post.get("slug") or "").strip()
        if not slug:
            continue
        linhas.append("  <url>")
        linhas.append(f"    <loc>{escape(f'{SITE}/blog/{slug}')}</loc>")
        publicado = (post.get("publishedAt") or "").strip()
        if publicado:
            linhas.append(f"    <lastmod>{escape(publicado)}</lastmod>")
        linhas.append("    <changefreq>monthly</changefreq>")
        linhas.append("    <priority>0.6</priority>")
        linhas.append("  </url>")

    linhas.append("</urlset>")
    return "\n".join(linhas) + "\n"


@router.get("/sitemap.xml")
def rota_sitemap():
    return Response(
        sitemap_xml(),
        media_type="application/xml",
        headers=_CACHE_LONGO,
    )


@router.get("/index.md")
def rota_index_md():
    return resposta_markdown("/")


for _pagina in PAGINAS:
    if _pagina.caminho == "/":
        continue

    def _fabrica(caminho: str):
        def _rota():
            return resposta_markdown(caminho)

        return _rota

    router.add_api_route(
        f"{_pagina.caminho}.md",
        _fabrica(_pagina.caminho),
        methods=["GET"],
        include_in_schema=False,
        name=f"markdown_{_pagina.caminho.strip('/')}",
    )


@router.get("/p/{pick_type}/{pick_id}.md")
def rota_pick_md(pick_type: str, pick_id: int):
    """Markdown do teaser público de um pick.

    Usa a MESMA função da API pública, que já decide o que pode sair. Não
    existe segunda regra de exposição aqui: a primeira já divergiu uma vez
    neste projeto e não vai divergir por causa de markdown.
    """
    from fastapi import HTTPException
    from routers.public import public_pick

    try:
        d = public_pick(pick_type, pick_id)
    except HTTPException as e:
        return Response(
            f"# Pick não encontrado\n\n{e.detail}\n",
            status_code=e.status_code,
            media_type=MEDIA_MARKDOWN,
        )

    jogo = f"{d.get('home_team_name', '?')} x {d.get('away_team_name', '?')}"
    if d.get("teams_preview"):
        jogo = " · ".join(d["teams_preview"])
    resultado = d.get("result") or "ainda sem resultado"
    corpo = f"""# Pick {pick_type} · {jogo}

- Jogo: {jogo}
- Liga: {d.get('league_name') or 'n/d'}
- Data: {d.get('match_date') or 'n/d'}
- Odd publicada: {d.get('odd') or 'n/d'}
- Resultado: {resultado}

O mercado e a análise deste pick não são públicos. Página em HTML:
[{SITE}/p/{pick_type}/{pick_id}]({SITE}/p/{pick_type}/{pick_id})
"""
    return Response(corpo, media_type=MEDIA_MARKDOWN, headers=_CACHE_CURTO)


# ──────────────────────────────────────────────────────────────────────────
# .well-known
# ──────────────────────────────────────────────────────────────────────────
@router.get("/.well-known/api-catalog")
def rota_api_catalog():
    """Catálogo de APIs no formato linkset da RFC 9727."""
    catalogo = {
        "linkset": [
            {
                "anchor": f"{SITE}/api/public",
                "service-desc": [
                    {"href": f"{SITE}/openapi.json", "type": "application/json"}
                ],
                "service-doc": [
                    {"href": f"{SITE}/como-funciona.md", "type": "text/markdown"}
                ],
                "status": [{"href": f"{SITE}/api/health", "type": "application/json"}],
                "author": [{"href": f"{SITE}/"}],
            }
        ]
    }
    return Response(
        json.dumps(catalogo, ensure_ascii=False, indent=2),
        media_type=MEDIA_LINKSET,
        headers=_CACHE_LONGO,
    )


def auth_md() -> str:
    """O que existe hoje para agente que age em nome de um usuário.

    Escrito no negativo de propósito. A convenção auth.md (WorkOS) descreve
    registro automatizado de agente sobre OAuth, e o Pick IA não tem servidor
    OAuth nem emissão de credencial para terceiro. Publicar um auth.md
    otimista faria um agente tentar um fluxo que não existe e falhar depois de
    já ter dito ao usuário que ia conseguir.
    """
    return f"""# Registro de agente · Pick IA

> Resumo: hoje o Pick IA NÃO suporta registro nem login automatizado de
> agente em nome de um usuário. Leitura pública é aberta e não pede
> credencial nenhuma.

## O que um agente pode fazer sem conta

- Ler as páginas públicas em markdown, listadas em [llms.txt]({SITE}/llms.txt).
- Chamar a API pública de leitura descrita em
  [openapi.json]({SITE}/openapi.json) e indexada em
  [api-catalog]({SITE}/.well-known/api-catalog).
- Usar o servidor MCP de leitura em `{SITE}/mcp`, sem autenticação, descrito
  em [mcp.json]({SITE}/.well-known/mcp.json).

## O que exige conta humana

Criar conta, assinar, ver pick de assinante, registrar banca e acompanhar
entradas seguidas. O cadastro é feito por pessoa, no site, com verificação de
e-mail e desafio anti-bot. Não há emissão de credencial para agente, não há
`client_credentials`, e não existe endpoint de registro automatizado.

## Se você é um agente com credencial do usuário

Não faça login com a senha do usuário. Não existe fluxo suportado para isso, e
sessão criada fora do site pode ser encerrada sem aviso.

## Contato

Pedido de integração: [{SITE}/planos]({SITE}/planos) tem o canal de contato do
site.
"""


@router.get("/auth.md")
@router.get("/.well-known/auth.md")
def rota_auth_md():
    return Response(auth_md(), media_type=MEDIA_MARKDOWN, headers=_CACHE_LONGO)


def mcp_card() -> dict:
    """Cartão do servidor MCP.

    Formato conforme o rascunho SEP-2127 (`/.well-known/mcp.json`) do Model
    Context Protocol, que ainda é rascunho: se o campo mudar de nome, é aqui
    que muda.
    """
    return {
        "name": "pickia",
        "title": "Pick IA",
        "description": (
            "Leitura dos dados públicos do Pick IA: histórico de resultados, "
            "dica gratuita do dia, contagem de picks publicados e planos."
        ),
        "version": "1.0.0",
        "websiteUrl": SITE,
        "documentationUrl": f"{SITE}/llms.txt",
        "transports": {"streamable-http": {"url": f"{SITE}/mcp"}},
        "authentication": {"type": "none"},
        "capabilities": {"tools": {}},
    }


@router.get("/.well-known/mcp.json")
def rota_mcp_card():
    return Response(
        json.dumps(mcp_card(), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers=_CACHE_LONGO,
    )


# ──────────────────────────────────────────────────────────────────────────
# Servidor MCP (somente leitura)
# ──────────────────────────────────────────────────────────────────────────
PROTOCOLO_MCP = "2025-06-18"

FERRAMENTAS = [
    {
        "name": "resultados_publicos",
        "title": "Resultados públicos",
        "description": (
            "Desempenho consolidado dos picks já resolvidos: total, greens, "
            "reds, taxa de acerto, lucro em unidades e ROI, com quebra por "
            "tipo de pick. Aceita filtro por mês."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mes": {
                    "type": "string",
                    "description": "Mês no formato YYYY-MM. Omitido, devolve o histórico inteiro.",
                    "pattern": "^[0-9]{4}-[0-9]{2}$",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "picks_de_hoje",
        "title": "Picks publicados hoje",
        "description": (
            "Quantos picks foram publicados hoje, por tipo (vip, free, "
            "múltiplas, alavancagem, faltas, jogadores). Não inclui o conteúdo "
            "dos picks de assinante."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "dica_gratuita_de_hoje",
        "title": "Dica gratuita do dia",
        "description": (
            "O pick gratuito do dia. Sem conta, devolve jogo, liga e odd, com "
            "o mercado marcado como bloqueado, a mesma regra da página "
            "pública."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "planos_e_precos",
        "title": "Planos e preços",
        "description": "Planos de assinatura vigentes, com preço e período.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _texto(conteudo: str) -> dict:
    return {"content": [{"type": "text", "text": conteudo}]}


def _erro_ferramenta(mensagem: str) -> dict:
    # Erro de ferramenta volta como resultado com isError, não como erro de
    # JSON-RPC: o protocolo reserva o erro de transporte pra falha de
    # protocolo, e cliente que recebe erro de transporte costuma desistir da
    # sessão inteira em vez de mostrar a mensagem.
    return {"content": [{"type": "text", "text": mensagem}], "isError": True}


def executar_ferramenta(nome: str, argumentos: dict, request: Request) -> dict:
    if nome == "resultados_publicos":
        from routers.public import public_results

        mes = (argumentos or {}).get("mes")
        dados = public_results(month=mes, slim=True)
        s = dados.get("summary") or {}
        resumo = {
            "periodo": mes or "histórico completo",
            "picks_resolvidos": s.get("total", 0),
            "greens": s.get("greens", 0),
            "reds": s.get("reds", 0),
            "lucro_em_unidades": s.get("profit", 0),
            "roi_percentual": s.get("roi"),
            "ligas_cobertas": s.get("leagues_count", 0),
            "por_tipo": dados.get("by_source", []),
            "aviso": "Desempenho passado não prevê resultado futuro.",
        }
        return _texto(json.dumps(resumo, ensure_ascii=False, indent=2, default=str))

    if nome == "picks_de_hoje":
        from routers.public import public_today_summary

        return _texto(
            json.dumps(public_today_summary(), ensure_ascii=False, indent=2, default=str)
        )

    if nome == "dica_gratuita_de_hoje":
        from routers.public import public_free_pick_today

        return _texto(
            json.dumps(
                public_free_pick_today(request), ensure_ascii=False, indent=2, default=str
            )
        )

    if nome == "planos_e_precos":
        return _texto(json.dumps(_planos(), ensure_ascii=False, indent=2))

    return _erro_ferramenta(f"Ferramenta desconhecida: {nome}")


def _resposta_rpc(id_, resultado=None, erro=None) -> dict:
    corpo = {"jsonrpc": "2.0", "id": id_}
    if erro is not None:
        corpo["error"] = erro
    else:
        corpo["result"] = resultado
    return corpo


@router.post("/mcp")
async def rota_mcp(request: Request):
    """Servidor MCP por HTTP, só leitura, sem autenticação.

    Sem autenticação porque tudo que ele devolve já é público no site. No dia
    em que uma ferramenta precisar de dado de assinante, o caminho é OAuth de
    verdade (RFC 9728) e não um atalho por token no query string.
    """
    try:
        corpo = await request.json()
    except Exception:
        return _resposta_rpc(None, erro={"code": -32700, "message": "JSON inválido"})

    if isinstance(corpo, list):
        return _resposta_rpc(
            None, erro={"code": -32600, "message": "Lote não suportado"}
        )

    metodo = corpo.get("method")
    id_ = corpo.get("id")
    params = corpo.get("params") or {}

    if metodo == "initialize":
        pedido = params.get("protocolVersion")
        return _resposta_rpc(
            id_,
            {
                # Ecoa a versão do cliente quando é a que falamos; senão
                # responde a nossa e deixa o cliente decidir se continua.
                "protocolVersion": pedido if pedido == PROTOCOLO_MCP else PROTOCOLO_MCP,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "pickia", "version": "1.0.0"},
                "instructions": (
                    "Dados públicos do Pick IA. Nada aqui é recomendação de "
                    "investimento, e pick de assinante não é exposto."
                ),
            },
        )

    if metodo in ("notifications/initialized", "notifications/cancelled"):
        # Notificação não tem id e não leva resposta.
        return Response(status_code=202)

    if metodo == "ping":
        return _resposta_rpc(id_, {})

    if metodo == "tools/list":
        return _resposta_rpc(id_, {"tools": FERRAMENTAS})

    if metodo == "tools/call":
        nome = params.get("name") or ""
        argumentos = params.get("arguments") or {}
        try:
            # Threadpool: as ferramentas leem o banco com psycopg2, que é
            # bloqueante, e esta rota é async. Sem isto, uma consulta lenta
            # pedida por um agente trava o event loop do processo inteiro.
            resultado = await run_in_threadpool(
                executar_ferramenta, nome, argumentos, request
            )
            return _resposta_rpc(id_, resultado)
        except Exception:
            logger.warning("[MCP] ferramenta %s falhou", nome, exc_info=True)
            return _resposta_rpc(
                id_, _erro_ferramenta("Não foi possível ler este dado agora.")
            )

    return _resposta_rpc(
        id_, erro={"code": -32601, "message": f"Método não suportado: {metodo}"}
    )
