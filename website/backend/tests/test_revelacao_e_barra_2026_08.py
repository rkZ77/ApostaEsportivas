"""Carregamento: barra verde em tudo e a tela que aparece inteira, de uma vez.

Nada aqui toca banco nem sobe navegador · o que se verifica e o CONTRATO entre
as pecas, que e onde este comportamento pode quebrar sem ninguem notar:

  * a barra do index.html so' e' encerrada por quem sabe que a tela ficou
    pronta, e uma tela sem carga inicial precisa encerra-la mesmo assim;
  * o portao de revelacao esconde por OPACIDADE, nunca desmontando o filho ·
    desmontar faria a pagina nunca disparar as chamadas que o portao espera,
    e ela abriria vazia no primeiro quadro;
  * o portao vive no proprio <main>, e nao num <div> em volta: sete telas
    passam grid/flex/space-y por `mainClassName` e dependem do conteudo ser
    filho direto dele.
"""

import os
import re

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB = os.path.dirname(_BACKEND)
_FRONT = os.path.join(_WEB, "frontend", "src")


def _front(caminho: str) -> str:
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        return f.read()


def _html() -> str:
    with open(os.path.join(_WEB, "frontend", "index.html"), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- barra inicial

def test_barra_inicial_e_css_puro_no_html():
    """Ela cobre justamente o trecho em que o JavaScript ainda nao rodou.

    Se um dia isso virar componente React, a primeira visita volta a ser uma
    tela vazia ate' o bundle montar · que e' o problema que ela existe pra
    resolver.
    """
    html = _html()
    assert 'id="barra-inicial"' in html
    assert "@keyframes barra-inicial-anda" in html
    assert "#00CC00" in html, "a barra e' a verde da marca"


def test_barra_inicial_para_antes_do_fim():
    """90% e nao 100%: o navegador nao sabe a fracao real do que falta, e uma
    barra que enche sozinha antes da tela chegar promete o que nao cumpre."""
    html = _html()
    fim = re.search(r"100%\s*\{\s*width:\s*(\d+)%", html)
    assert fim, "keyframe final da barra inicial sumiu"
    assert int(fim.group(1)) == 90


def test_quem_encerra_a_barra_inicial_e_a_revelacao():
    src = _front("hooks/useRevelacao.ts")
    assert "encerrarBarraInicial" in src


def test_barra_inicial_tem_teto_de_seguranca():
    """Tela que nunca revela (rede travada, erro de chunk) nao pode deixar a
    barra andando pra sempre no topo do site."""
    src = _front("lib/barraInicial.ts")
    assert "TETO_MS" in src and "setTimeout(encerrarBarraInicial" in src


def test_home_encerra_a_barra_sozinha():
    """A Home nao usa PageShell · sem esta chamada, a barra so' sumiria pelo
    teto de seguranca, doze segundos depois, na tela mais visitada do site."""
    assert "encerrarBarraInicial" in _front("pages/Home.tsx")


@pytest.mark.parametrize("pagina", [
    "pages/Login.tsx", "pages/ForgotPassword.tsx", "pages/NotFound.tsx",
    "pages/VerifyEmail.tsx", "pages/PickPublico.tsx",
])
def test_paginas_sem_pageshell_tambem_tem_portao(pagina):
    """Mesmo motivo da Home: fora do PageShell, ninguem encerraria a barra."""
    assert "useRevelacao" in _front(pagina)


# ------------------------------------------------------------------- o portao

def test_portao_esconde_por_opacidade_e_nao_desmonta():
    """`display:none` ou renderizar `null` quebrariam o mecanismo inteiro.

    O portao espera o contador de requisicoes em voo zerar, e quem dispara
    essas requisicoes e' a montagem dos filhos. Filho desmontado nao pede
    nada, o contador nunca sai de zero, e a tela revela vazia.
    """
    src = _front("hooks/useRevelacao.ts")
    assert "opacity-0" in src and "opacity-100" in src
    assert "hidden" not in src.split("classesRevelacao")[-1]


def test_portao_abre_uma_vez_so():
    """Metade das telas faz polling. Um portao que reagisse ao contador para
    sempre apagaria a tela sozinho a cada ciclo de atualizacao."""
    src = _front("hooks/useRevelacao.ts")
    assert "jaRevelou" in src


def test_portao_tem_teto():
    """Endpoint lento ou fora do ar nao pode segurar a tela indefinidamente."""
    src = _front("hooks/useRevelacao.ts")
    m = re.search(r"TETO_MS\s*=\s*([\d_]+)", src)
    assert m and int(m.group(1).replace("_", "")) <= 3000


def test_portao_vive_no_main_do_pageshell():
    """Num <div> em volta, ele viraria o unico filho do `grid lg:grid-cols-2`
    do Profile e do `space-y-5` de outras cinco telas, achatando o layout."""
    src = _front("components/PageShell.tsx")
    trecho = src[src.index("<main"):src.index("</main>")]
    assert "classesRevelacao(revelado)" in trecho


def test_paginas_estaticas_ficam_fora_do_portao():
    """Texto puro, zero requisicao · o portao so' somaria um fade a uma tela
    que ja esta pronta."""
    for p in ("pages/Termos.tsx", "pages/Privacidade.tsx"):
        assert "revelacao={false}" in _front(p)


# ------------------------------------------------------- barra em toda espera

def test_navegacao_nao_tem_mais_spinner_de_tela_cheia():
    """Era a quarta tela de uma navegacao so': sai a pagina, entra um fundo
    vazio com spinner, entra a pagina nova com os spinners dela, chega o
    conteudo. Quem comunica a espera agora e' a barra, que nao pisca a tela."""
    src = _front("App.tsx")
    assert "const PageLoader = () => null" in src
    assert "Spinner" not in src


def test_barra_acende_por_gesto_e_nao_por_requisicao():
    """Uma barra por requisicao piscaria sozinha o tempo todo: LivePicks, o
    sino e o Admin fazem polling em segundo plano. O criterio e' ter havido um
    toque ou uma tecla ha pouco."""
    src = _front("services/progressBus.ts")
    assert "nasceuDeUmGesto" in src
    assert "pointerdown" in src and "keydown" in src
    assert "pendentes === 1 && nasceuDeUmGesto()" in src, (
        "so' a primeira requisicao da rajada acende · as seguintes "
        "reiniciariam a barra do zero a cada resposta que chega"
    )


# ---------------------------------------------------------------- pre-carga

def test_prefetch_ignora_conexao_cara():
    """Adiantar chunk em 2G ou com economia de dados ligada deixa de ser
    economia de tempo e vira consumo do plano de quem nao pediu."""
    src = _front("lib/prefetch.ts")
    assert "saveData" in src and "2g" in src


def test_prefetch_escuta_o_documento_e_nao_link_por_link():
    """Pendurar handler em cada link significa esquecer os proximos sempre."""
    src = _front("lib/prefetch.ts")
    assert "pointerover" in src, "pointerenter nao sobe na arvore"
    assert "a[href]" in src


def test_prefetch_so_pega_link_interno():
    src = _front("lib/prefetch.ts")
    assert "startsWith('/')" in src
