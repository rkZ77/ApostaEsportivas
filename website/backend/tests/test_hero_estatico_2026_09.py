"""Hero pre-renderizado no build, e o que so' monta quando faz falta.

O paragrafo do hero e' o elemento de LCP da Home. Depois de tirar o framer do
caminho (test_home_lcp_2026_09), o que sobrou segurando o LCP era o proprio
React precisar existir: o texto so' aparecia quando o bundle terminava de
baixar, avaliar e montar. `scripts/prerender-hero.mjs` resolve isso rendendo
o HeroTexto em HTML durante o build e injetando no index.html.

Estes testes seguram as invariantes que quebram CALADAS · o hero que diverge
do componente, o markup que some do build, a secao que nunca monta pra quem
nao rola. Nada aqui abre navegador: e' leitura de codigo, como o resto da
suite.
"""

import os
import re

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND = os.path.join(os.path.dirname(_BACKEND), "frontend")
_FRONT = os.path.join(_FRONTEND, "src")


def _front(caminho: str) -> str:
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        return f.read()


def _script(nome: str) -> str:
    with open(os.path.join(_FRONTEND, "scripts", nome), encoding="utf-8") as f:
        return f.read()


# ─────────────────── O hero estatico e o componente ──────────────────────

def test_o_hero_e_gerado_a_partir_do_componente():
    """UMA fonte para o texto do hero.

    A alternativa -- escrever o markup a mao no index.html -- ja foi tentada
    neste projeto em outro campo: o JSON-LD com preco fixo anunciou R$ 49,90
    pro Google enquanto a cobranca era R$ 39,90, porque ninguem lembra de
    editar HTML estatico ao mexer no produto.
    """
    script = _script("prerender-hero.mjs")
    assert "src/home/HeroTexto" in script
    assert "renderToStaticMarkup" in script

    indice = os.path.join(_FRONTEND, "index.html")
    with open(indice, encoding="utf-8") as f:
        html = f.read()
    # O index.html de ORIGEM continua com o container vazio · quem preenche e'
    # o build. Texto de hero escrito aqui a mao e' exatamente o que nao pode.
    assert '<div id="root"></div>' in html
    assert "Palpites de futebol" not in html


def test_o_build_roda_o_prerender():
    with open(os.path.join(_FRONTEND, "package.json"), encoding="utf-8") as f:
        pkg = f.read()
    assert "prerender-hero.mjs" in pkg
    # Depois do vite build: ele injeta no dist/index.html que o vite acabou de
    # escrever, entao a ordem nao e' detalhe.
    assert pkg.index("vite build") < pkg.index("prerender-hero.mjs")


def test_o_react_nao_reanima_o_hero_ja_pintado():
    """Sem isto o texto faria fade duas vezes: uma no HTML estatico (CSS puro,
    logo no primeiro quadro) e outra quando o React montasse por cima."""
    home = _front("pages/Home.tsx")
    assert "HERO_JA_PINTADO" in home
    assert "data-hero-estatico" in home
    assert "animar={!HERO_JA_PINTADO}" in home

    # Lido no modulo, e nao dentro do componente: quando o Home renderiza, o
    # createRoot ja esvaziou o container e a marca nao esta mais la.
    assert home.index("const HERO_JA_PINTADO") < home.index("export default function Home")


def test_o_hero_estatico_nao_vaza_para_as_outras_rotas():
    """O mesmo index.html serve o SPA inteiro · sem isto, /login mostraria o
    hero da Home por um segundo antes de o React montar a tela certa."""
    script = _script("prerender-hero.mjs")
    assert "data-fora-da-home" in script
    assert "location.pathname" in script


def test_o_hero_nao_depende_de_dado_nem_de_contexto():
    """Ele e' renderizado FORA do navegador, sem provider nenhum. Estado,
    efeito ou chamada de API aqui quebram o build, nao a tela."""
    # Sem comentario: o cabecalho do arquivo LISTA o que nao pode entrar, e a
    # lista faria o teste falhar por causa da propria documentacao.
    bruto = _front("home/HeroTexto.tsx")
    hero = re.sub(r"/\*.*?\*/", "", bruto, flags=re.DOTALL)
    for proibido in ("useState", "useEffect", "useAuth", "api.", "useNavigate", "useLocation"):
        assert proibido not in hero, proibido


# ────────────────────────── Montagem adiada ──────────────────────────────

def test_secoes_de_baixo_nao_sao_montadas_no_primeiro_paint():
    home = _front("pages/Home.tsx")
    assert "SecaoAdiada" in home
    # Sete blocos abaixo da dobra: resultados, como funciona, produtos, ligas,
    # planos, CTA final e rodape.
    assert home.count("<SecaoAdiada") >= 7

    # E os quatro que viraram chunk proprio nao podem voltar a ser import
    # estatico · seria montagem adiada com download adiantado.
    for secao in ("HowItWorks", "Products", "Leagues", "FinalCTA", "RecentResults", "Plans"):
        assert f"lazy(() => import('../home/{secao}'))" in home, secao


def test_o_topo_da_home_continua_sincrono():
    """Hero, dica do dia, fila de jogos e indicadores sao a primeira tela.
    Adiar qualquer um deles troca peso por tela vazia."""
    home = _front("pages/Home.tsx")
    for imediato in ("HeroTexto", "FreePickHero", "NextGames", "StatsBand"):
        assert f"import {imediato} from" in home or f"import {imediato}," in home, imediato
        assert f"lazy(() => import('../home/{imediato}'))" not in home, imediato


def test_quem_nunca_rola_tambem_recebe_a_pagina_inteira():
    """O gatilho de rolagem sozinho deixaria a pagina pela metade pro Ctrl+F,
    pro leitor de tela e pra qualquer rastreador que renderize sem rolar."""
    secao = _front("components/SecaoAdiada.tsx")
    assert "requestIdleCallback" in secao
    assert "perto || ocioso" in secao


def test_o_espaco_da_secao_e_reservado_antes_de_montar():
    """Sem altura reservada, cada secao que nasce empurra o que vem depois ·
    CLS pago pra ganhar DOM, que e' troca ruim."""
    secao = _front("components/SecaoAdiada.tsx")
    assert "minHeight" in secao

    home = _front("pages/Home.tsx")
    alturas = [int(n) for n in re.findall(r"alturaMinima=\{(\d+)\}", home)]
    assert len(alturas) >= 7
    assert all(a >= 200 for a in alturas), alturas
