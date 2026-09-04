"""Home: o que segura o LCP e o que sai da fila do primeiro segundo.

MEDICAO DE ORIGEM (PageSpeed mobile, 04/09/2026): LCP 5,7 s com 2.340 ms de
"atraso de renderizacao" e TTFB zero. O elemento de LCP era o paragrafo do
hero -- ele nascia em `opacity: 0` esperando o framer-motion montar e mais
300 ms de `delay`, e elemento invisivel nao conta como pintado.

Na mesma medicao, seis chamadas publicas saiam juntas no carregamento, todas
entre 4,6 s e 6,3 s. Uma a uma elas custam menos de 2 s: o que o relatorio
mostrava era a fila delas no unico worker do servidor.

Como o resto da suite, isto le codigo, nao roda navegador.
"""

import os
import re

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _front(caminho: str) -> str:
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        return f.read()


def _front_codigo(caminho: str) -> str:
    """Fonte sem comentario · uma asserção de ausência não pode ser satisfeita
    pelo comentário que explica a ausência."""
    src = _front(caminho)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"(?<!:)//[^\n]*", "", src)


def _hero(codigo: str) -> str:
    """Trecho entre o <h1> e o fim dos botoes · o bloco que define o LCP."""
    inicio = codigo.index("<h1")
    fim = codigo.index("Ver resultados reais")
    return codigo[inicio:fim]


# ──────────────────────────── LCP ────────────────────────────────────────

def test_o_hero_nao_anima_com_framer():
    """O paragrafo do hero e' o elemento de LCP.

    Com `motion.p initial={{opacity: 0}}` ele so' comecava a aparecer depois
    de o framer montar e de um `delay` de 300 ms · essa espera ERA o LCP. Em
    CSS a animacao ja' esta correndo no primeiro quadro em que o elemento
    existe.
    """
    # O texto do hero mora em home/HeroTexto.tsx desde 04/09 · e o unico
    # componente que o build pre-renderiza em HTML (scripts/prerender-hero.mjs).
    hero = _hero(_front_codigo("home/HeroTexto.tsx"))
    assert "motion." not in hero
    # As classes vem por template porque o hero pre-renderizado nao reanima ao
    # montar (prop `animar`) · o que importa e' que a entrada seja CSS.
    assert "entra-2" in hero


def test_a_entrada_do_hero_existe_em_css():
    css = _front("index.css")
    assert "@keyframes entra-suave" in css
    # `both` guarda o estado inicial durante o atraso · sem ele o texto pisca
    # visivel antes de comecar a animar.
    assert "both" in css[css.index(".entra {"):css.index("@keyframes entra-suave")]


def test_o_atraso_do_paragrafo_e_curto():
    """A escada de atrasos existe (o efeito e' esse), mas em milissegundos.

    O elemento de LCP nao pode ficar esperando: 120 ms e' o teto aceito aqui.
    """
    css = _front("index.css")
    atrasos = [int(ms) for ms in re.findall(r"\.entra-\d \{ animation-delay: (\d+)ms; \}", css)]
    assert atrasos, "as classes de atraso sumiram"
    assert max(atrasos) <= 180


# ──────────────────── Fila de chamadas do carregamento ───────────────────

def test_secoes_de_baixo_so_buscam_quando_chegam_perto():
    """Resultados, curva e ligas ficam abaixo da dobra.

    Enquanto elas buscavam no `mount`, disputavam o unico worker com as tres
    chamadas do topo -- e o topo e' o que a pessoa esta olhando.
    """
    resultados = _front_codigo("home/RecentResults.tsx")
    assert "usePertoDaTela" in resultados
    # As duas chamadas da secao (lista paginada e curva) dependem do gatilho.
    assert resultados.count("if (!perto) return") >= 2

    leagues = _front_codigo("home/Leagues.tsx")
    assert "usePertoDaTela" in leagues
    assert "carregar={perto}" in leagues


def test_as_tres_chamadas_do_topo_continuam_saindo_na_hora():
    """O adiamento nao pode ter subido pro topo.

    Dica do dia, fila de jogos e indicadores desenham a primeira tela: adiar
    qualquer uma delas troca um problema de fila por uma tela vazia.
    """
    assert "if (!perto) return" not in _front_codigo("home/FreePickHero.tsx")
    assert "if (!perto) return" not in _front_codigo("home/NextGames.tsx")


def test_o_hook_devolve_true_sem_intersection_observer():
    """Navegador sem IO (ou jsdom) tem que se comportar como antes do hook ·
    caso contrario a secao nunca carrega e o dado some da tela."""
    hook = _front_codigo("hooks/usePertoDaTela.ts")
    assert "typeof IntersectionObserver === 'undefined'" in hook
    assert "setPerto(true)" in hook


# ──────────────────────────── Marquee ────────────────────────────────────

def test_a_fita_so_mede_quando_chega_perto_da_tela():
    """56 ms de reflow forcado no carregamento, para uma fita abaixo da dobra.

    Medir custa layout (`scrollWidth` + `clientWidth` com ResizeObserver por
    cima), e o laco de rAF empurrava a rolagem de uma fita que ninguem estava
    vendo.
    """
    marquee = _front_codigo("components/ui/Marquee.tsx")
    assert "IntersectionObserver" in marquee
    assert "!perto) return" in marquee
    assert "items.length > 0 && perto" in marquee
