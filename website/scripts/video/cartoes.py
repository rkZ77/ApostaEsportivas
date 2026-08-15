"""
Cartões de abertura e de fecho, desenhados em HTML e fotografados em 1080x1920.

Por que HTML e não filtro do ffmpeg: `drawtext` faz texto, não faz layout. O
cartão precisa de hierarquia, respiro e a cor da marca no lugar certo, e isso
se escreve muito melhor em CSS. O Playwright já está aqui, então tira a foto.

As cores saem dos mesmos tokens do site (`frontend/src/index.css`): fundo
#0a0a0c, texto #fafafa, verde da marca #00CC00.
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

LARGURA, ALTURA = 1080, 1920

FUNDO = "#0a0a0c"
TINTA = "#fafafa"
TINTA_3 = "#94949e"
ACENTO = "#00CC00"

_BASE = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:{LARGURA}px; height:{ALTURA}px; background:{FUNDO}; color:{TINTA};
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
  display:flex; flex-direction:column; justify-content:center;
  padding:0 96px; position:relative; overflow:hidden;
}}
/* Brilho verde atrás do texto: dá profundidade sem competir com a leitura.
   Centrado em 52% porque o bloco de texto fica no meio-baixo do quadro · em
   26% o brilho caía no vazio acima do título. */
body::before {{
  content:''; position:absolute; left:44%; top:52%;
  width:1600px; height:1600px; transform:translate(-50%,-50%);
  background:radial-gradient(circle, rgba(0,204,0,.20) 0%, rgba(0,204,0,0) 64%);
  pointer-events:none;
}}
.marca {{
  position:absolute; top:150px; left:96px;
  font-size:38px; font-weight:800; letter-spacing:-.02em; color:{TINTA};
}}
.marca span {{ color:{ACENTO}; }}
.conteudo {{ position:relative; z-index:1; }}
.barra {{
  width:132px; height:9px; background:{ACENTO};
  border-radius:99px; margin-bottom:52px;
}}
.gancho {{
  font-size:104px; font-weight:900; line-height:1.03; letter-spacing:-.035em;
}}
.titulo {{
  font-size:44px; font-weight:700; color:{TINTA_3}; margin-top:40px;
  letter-spacing:-.01em;
}}
.fecho {{ font-size:92px; font-weight:900; line-height:1.06; letter-spacing:-.03em; }}
.cta {{
  display:inline-block; margin-top:64px; padding:30px 56px;
  background:{ACENTO}; color:#04140a; border-radius:22px;
  font-size:44px; font-weight:900; letter-spacing:-.01em;
}}
.rodape {{
  position:absolute; bottom:150px; left:96px; right:96px;
  font-size:32px; font-weight:600; color:{TINTA_3};
}}
"""

_ABERTURA = """
<div class="marca">Pick<span>IA</span></div>
<div class="conteudo">
  <div class="barra"></div>
  <div class="gancho">{gancho}</div>
  <div class="titulo">{titulo}</div>
</div>
"""

_FECHO = """
<div class="marca">Pick<span>IA</span></div>
<div class="conteudo">
  <div class="barra"></div>
  <div class="fecho">{fecho}</div>
  <div class="cta">{cta}</div>
</div>
<div class="rodape">Aposta é entretenimento adulto. Jogue com responsabilidade.</div>
"""


def _pagina(corpo: str) -> str:
    return f"<!doctype html><meta charset='utf-8'><style>{_BASE}</style>{corpo}"


def render(cena: str, textos: dict[str, str], destino: Path) -> tuple[Path, Path]:
    """Gera abertura.png e fecho.png de uma cena. Devolve os dois caminhos."""
    destino.mkdir(parents=True, exist_ok=True)
    abertura = destino / f"{cena}-abertura.png"
    fecho = destino / f"{cena}-fecho.png"

    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(
            viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1
        )

        pagina.set_content(_pagina(_ABERTURA.format(**textos)))
        pagina.screenshot(path=str(abertura))

        pagina.set_content(_pagina(_FECHO.format(**textos)))
        pagina.screenshot(path=str(fecho))

        navegador.close()

    return abertura, fecho


if __name__ == "__main__":
    import sys

    from cenas import CARTOES

    saida = Path(__file__).parent / "cartoes"
    alvos = sys.argv[1:] or list(CARTOES)
    for nome in alvos:
        if nome not in CARTOES:
            print(f"cena desconhecida: {nome}")
            continue
        a, f = render(nome, CARTOES[nome], saida)
        print(f"{nome}: {a.name}, {f.name}")
