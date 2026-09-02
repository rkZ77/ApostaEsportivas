"""
Prova do template de carrossel do Instagram.

    python templates.py

Renderiza uma tira de 3 slides (capa, conteudo, fecho) lado a lado, pra
aprovar o padrao antes de escrever o conteudo. Depois de aprovado, este layout
vira o de `carrossel.py`.

Padrao "Tela": o site aparece em todo slide, num aparelho que sangra pela
borda de baixo. O texto vive no terco de cima, onde o feed nao corta, e o canto
inferior esquerdo que sobra ao lado do aparelho fica com a assinatura.

Os prints saem de `prints.py`. Slide sem print desenha a moldura vazia, entao
da' pra diagramar antes de ter a foto.
"""
from __future__ import annotations

import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

from cartoes import ACENTO, FUNDO, TINTA, TINTA_3, _logo_embutido

L, A = 1080, 1350
AQUI = Path(__file__).parent
PRINTS = AQUI / "carrossel" / "prints"
SAIDA = AQUI / "templates"

# (kicker, titulo, texto, print, rodape_direito)
SLIDES = [
    ("Como funciona",
     "Quatro leituras\ndo mesmo jogo",
     "O que roda por trás de um pick.",
     "home", "arraste"),
    ("Leitura 2 de 4",
     "Radar Ao Vivo",
     "Lê o jogo enquanto ele acontece e entra quando a odd atrasa.",
     "home-motores", "arraste"),
    ("Comece hoje",
     "Pick gratis\ntodo dia",
     "Sem cartão, sem conta.",
     "home", "link na bio"),
]

_CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ display:flex; background:#000; margin:0; }}
.slide {{
  width:{L}px; height:{A}px; background:{FUNDO}; color:{TINTA};
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
  position:relative; overflow:hidden; flex:none; padding:74px;
}}
/* Brilho da marca atras do texto, no mesmo lugar dos cartoes do video. */
.slide::before {{
  content:''; position:absolute; left:38%; top:26%; width:1100px; height:1100px;
  transform:translate(-50%,-50%);
  background:radial-gradient(circle, rgba(0,204,0,.14) 0%, rgba(0,204,0,0) 66%);
}}
.topo {{ display:flex; align-items:center; gap:16px; position:relative; z-index:2; }}
.topo img {{ width:62px; height:62px; display:block; }}
.wordmark {{ font-size:30px; font-weight:800; letter-spacing:-.02em; }}
.wordmark i {{ font-style:normal; color:{ACENTO}; }}

.texto {{ position:relative; z-index:2; margin-top:52px; }}
.kicker {{
  font-size:25px; font-weight:800; letter-spacing:.18em; text-transform:uppercase;
  color:{ACENTO}; margin-bottom:22px;
}}
.h {{ font-size:78px; font-weight:900; line-height:1.04; letter-spacing:-.035em;
  white-space:pre-line; }}
.p {{ font-size:36px; font-weight:500; line-height:1.36; color:#c7c7cf;
  margin-top:20px; max-width:760px; }}
.pilula {{
  display:inline-block; margin-top:34px; padding:22px 44px; background:{ACENTO};
  color:#04140a; border-radius:18px; font-size:34px; font-weight:900;
}}

/* O aparelho sangra pela borda de baixo: mostra tela de verdade sem gastar o
   slide inteiro, e o corte no rodape sugere que tem mais pra ver no site.
   Centrado e abaixo do texto · encostado na direita ele passava por baixo da
   linha de apoio e comia a ultima palavra. */
.aparelho {{
  position:absolute; left:50%; transform:translateX(-50%);
  top:600px; width:604px; height:820px;
  border:12px solid #3a3a44; border-top-left-radius:58px;
  border-top-right-radius:58px; overflow:hidden;
  background:#141418; z-index:1;
  /* A borda precisa ser mais clara que o fundo do site, senao o aparelho
     some · o print e o slide sao os dois #0a0a0c. */
  box-shadow:0 0 0 2px #101014, 0 -18px 70px rgba(0,0,0,.85);
}}
.aparelho img {{ width:100%; display:block; }}
.aparelho .vazio {{
  height:100%; display:flex; align-items:center; justify-content:center;
  font-size:28px; font-weight:700; color:#4a4a54; letter-spacing:.04em;
}}

/* Faixa de baixo: um degrade dissolve o aparelho na borda em vez de corta-lo
   na faca, e ainda devolve o espaco da assinatura, que o aparelho tomou. */
.rodape {{
  position:absolute; left:0; right:0; bottom:0; z-index:3;
  padding:110px 74px 56px;
  background:linear-gradient(to bottom, rgba(10,10,12,0) 0%, {FUNDO} 58%);
  display:flex; justify-content:space-between; align-items:flex-end;
  font-size:25px; font-weight:600; color:{TINTA_3};
}}
.rodape .arraste {{ color:{ACENTO}; font-weight:800; }}
.trilho {{ display:inline-flex; gap:8px; width:230px; margin-bottom:14px; }}
.trilho i {{ height:6px; flex:1; border-radius:99px; background:#2b2b31; }}
.trilho i.on {{ background:{ACENTO}; }}
"""


def _print_embutido(nome: str) -> str:
    arquivo = PRINTS / f"{nome}.png"
    if not arquivo.exists():
        return f"<div class='vazio'>print de {nome}</div>"
    uri = "data:image/png;base64," + base64.b64encode(arquivo.read_bytes()).decode()
    return f"<img src='{uri}' alt=''>"


def tira(logo: str) -> str:
    partes = []
    total = len(SLIDES)
    for i, (kicker, titulo, texto, nome_print, direita) in enumerate(SLIDES, start=1):
        pilula = ("<div><span class='pilula'>pickia.com.br</span></div>"
                  if i == total else "")
        barras = "".join(
            f"<i class='{'on' if n < i else ''}'></i>" for n in range(total)
        )
        partes.append(
            f"<div class='slide'>"
            f"<div class='topo'>{logo}<span class='wordmark'>Pick<i>IA</i></span></div>"
            f"<div class='texto'><div class='kicker'>{kicker}</div>"
            f"<div class='h'>{titulo}</div><div class='p'>{texto}</div>{pilula}</div>"
            f"<div class='aparelho'>{_print_embutido(nome_print)}</div>"
            f"<div class='rodape'>"
            f"<span><span class='trilho'>{barras}</span><br>pickia.com.br</span>"
            f"<span class='arraste'>{direita}</span></div>"
            f"</div>"
        )
    return "".join(partes)


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    uri = _logo_embutido()
    logo = f"<img src='{uri}' alt=''>" if uri else ""
    html = f"<!doctype html><meta charset='utf-8'><style>{_CSS}</style>{tira(logo)}"
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(
            viewport={"width": L * len(SLIDES), "height": A}, device_scale_factor=1
        )
        pag.set_content(html)
        destino = SAIDA / "template-tela.png"
        pag.screenshot(path=str(destino))
        nav.close()
    print(destino)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
