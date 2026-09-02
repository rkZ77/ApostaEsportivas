"""
Prints do site pros carrosseis do Instagram.

    python prints.py --listar
    python prints.py --todos
    python prints.py --print home --url http://localhost:5173

Fotografa o site num viewport de celular (o publico e' mobile) e guarda em
`carrossel/prints/<nome>.png`. O carrossel monta o slide em volta desses
arquivos · se um print faltar, o slide desenha a moldura vazia no lugar.

Nada e' escrito no banco: as rotas que precisam de dado sao servidas por
`page.route` com as fixtures de `fixtures.py`, mesmo motivo do video (uma conta
demo que segue picks entra no ranking publico de verdade).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SAIDA = Path(__file__).parent / "carrossel" / "prints"

# Celular real, nao janela estreita: o layout muda de verdade e a fonte fica no
# tamanho que a pessoa ve. dpr 3 pra o print aguentar a ampliacao no slide.
VIEWPORT = {"width": 390, "height": 844}
DPR = 3

# Mes do fechamento. Virou setembro, troca aqui e roda de novo.
MES_FECHAMENTO = "2026-08"
MES = ["Filtros", MES_FECHAMENTO, "Filtros"]


# O grupo "Fonte" tem 10 opcoes, e acima de 8 o FilterPanel troca os botoes
# por um <select> nativo. Por isso o produto entra por `fonte` e o mes por
# `cliques`: sao dois controles diferentes na mesma gaveta.

# nome -> {rota, cliques, rolar, altura}
#
# `cliques` e' uma lista de textos clicados na ordem, antes de rolar. E' assim
# que o filtro de mes entra: a pagina de Resultados guarda o mes em estado, nao
# na URL, entao nao da' pra pedir agosto por query string. Abre o painel de
# filtros, clica no mes, fecha o painel.
# altura = quanto do topo da pagina entra no print, em px de CSS. Um print alto
# demais vira tijolinho ilegivel dentro do slide.
PRINTS: dict[str, dict] = {
    "home":             {"rota": "/",              "rolar": 0,    "altura": 780},
    "home-passos":      {"rota": "/",              "rolar": 1500, "altura": 780},
    "resultados":       {"rota": "/resultados",    "rolar": 0,    "altura": 780},
    "resultados-meio":  {"rota": "/resultados",    "rolar": 900,  "altura": 780},
    "resultados-ligas": {"rota": "/resultados",    "rolar": 1800, "altura": 780},
    "resultados-lista": {"rota": "/resultados",    "rolar": 2700, "altura": 780},

    # O fechamento mensal precisa da pagina JA' filtrada: um slide que afirma
    # 253 picks ao lado de um print marcando 508 desmente o proprio post.
    "mes-resumo": {"rota": "/resultados", "cliques": MES, "rolar": 0, "altura": 780},
    "mes-ligas":  {"rota": "/resultados", "cliques": MES, "rolar": 1150, "altura": 780},
    "mes-lista":  {"rota": "/resultados", "cliques": MES, "rolar": 1800, "altura": 780},

    # Um print por produto, com o proprio filtro ligado. Sem isso os cinco
    # slides do carrossel de produtos mostravam a mesma lista, e o carrossel
    # parecia travado num quadro so'.
    "mes-vip":       {"rota": "/resultados", "cliques": MES, "fonte": "VIP",       "rolar": 1200, "altura": 780},
    "mes-live":      {"rota": "/resultados", "cliques": MES, "fonte": "Ao Vivo",   "rolar": 1200, "altura": 780},
    "mes-free":      {"rota": "/resultados", "cliques": MES, "fonte": "Free",      "rolar": 1200, "altura": 780},
    "mes-multiplas": {"rota": "/resultados", "cliques": MES, "fonte": "Múltiplas", "rolar": 1200, "altura": 780},
    "como-funciona":    {"rota": "/como-funciona", "rolar": 0,    "altura": 780},
    "como-funciona-passos": {"rota": "/como-funciona", "rolar": 1200, "altura": 780},
    "planos":           {"rota": "/planos",        "rolar": 300,  "altura": 780},
}

# Elementos que estragam print: toast de erro, popup, banner de aviso. O toast
# de erro aparece sempre que o print roda com a API local desligada, e um
# retangulo vermelho escrito "erro no servidor" e' a ultima coisa que a gente
# quer num post de captacao.
_ESCONDER = """
const css = document.createElement('style');
css.textContent = `
  [class*="z-[9999]"], [role="dialog"], [data-tour],
  .fixed.bottom-0, .fixed.bottom-4, .fixed.bottom-6 { display: none !important; }
  /* O cabecalho sai: o slide ja tem o logo em cima, e dois wordmarks na mesma
     imagem viram ruido. */
  header, nav[class*="sticky"][class*="top-0"] { display: none !important; }
`;
document.head.appendChild(css);
"""


def capturar(pagina, nome: str, base: str) -> Path:
    cfg = PRINTS[nome]
    pagina.goto(base.rstrip("/") + cfg["rota"], wait_until="networkidle")
    pagina.wait_for_timeout(1200)
    pagina.evaluate(_ESCONDER)

    # Por papel, nao por texto: o botao de filtro carrega dois icones junto do
    # rotulo, entao o no' de texto nunca bate exato. O produto entra no meio da
    # sequencia, com a gaveta ja' aberta pelo primeiro clique.
    cliques = list(cfg.get("cliques", []))
    fonte = cfg.get("fonte")
    for i, texto in enumerate(cliques):
        pagina.get_by_role("button", name=texto).first.click()
        pagina.wait_for_timeout(1400)
        if fonte and i == 0:
            pagina.locator("select").first.select_option(label=fonte)
            pagina.wait_for_timeout(1600)
    if cfg.get("cliques"):
        pagina.evaluate("window.scrollTo(0, 0)")
        pagina.wait_for_timeout(600)

    if cfg["rolar"]:
        pagina.evaluate(f"window.scrollTo(0, {cfg['rolar']})")
        pagina.wait_for_timeout(900)

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"{nome}.png"
    pagina.screenshot(
        path=str(destino),
        clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": cfg["altura"]},
    )
    return destino


def main() -> int:
    p = argparse.ArgumentParser(description="Prints do site pro carrossel")
    p.add_argument("--url", default="http://localhost:5173")
    p.add_argument("--print", dest="prints", action="append", default=[])
    p.add_argument("--todos", action="store_true")
    p.add_argument("--listar", action="store_true")
    args = p.parse_args()

    if args.listar:
        for nome, cfg in PRINTS.items():
            print(f"  {nome:<16} {cfg['rota']}")
        return 0

    escolhidos = list(PRINTS) if args.todos else args.prints
    if not escolhidos:
        print("erro: use --print <nome>, --todos ou --listar", file=sys.stderr)
        return 2

    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(
            viewport=VIEWPORT,
            device_scale_factor=DPR,
            is_mobile=True,
            has_touch=True,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        pagina = ctx.new_page()
        for nome in escolhidos:
            try:
                destino = capturar(pagina, nome, args.url)
                print(f"[{nome}] {destino}")
            except Exception as erro:
                print(f"[{nome}] falhou: {erro}", file=sys.stderr)
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
