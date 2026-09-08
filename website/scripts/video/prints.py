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

from fechamento import MESES

SAIDA = Path(__file__).parent / "carrossel" / "prints"

# Celular real, nao janela estreita: o layout muda de verdade e a fonte fica no
# tamanho que a pessoa ve. dpr 3 pra o print aguentar a ampliacao no slide.
VIEWPORT = {"width": 390, "height": 844}
DPR = 3

# Mes do fechamento. Virou o mes seguinte, troca aqui e roda de novo, ou
# passa `--mes` na linha de comando.
MES_FECHAMENTO = "2026-08"


def rotulo_mes(mes: str) -> str:
    """AAAA-MM no rotulo que a pagina mostra: "Agosto de 2026"."""
    ano, num = mes.split("-")
    return f"{MESES[num].capitalize()} de {ano}"


# Mes e produto sao dois seletores lado a lado na propria pagina, cada um com
# seu `aria-label`. Nao ha' mais gaveta de filtros pra abrir e fechar: a versao
# antiga deste arquivo clicava num botao "Filtros" que deixou de existir, e o
# print falhava por timeout sem dizer o motivo.

# nome -> {rota, mes, fonte, rolar, altura}
#
# `mes` liga o filtro de mes. A pagina guarda o mes em estado, nao na URL,
# entao nao da' pra pedir agosto por query string.
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
    "mes-resumo": {"rota": "/resultados", "mes": True, "rolar": 0, "altura": 780},
    "mes-ligas":  {"rota": "/resultados", "mes": True, "rolar": 1150, "altura": 780},
    "mes-lista":  {"rota": "/resultados", "mes": True, "rolar": 1800, "altura": 780},

    # Um print por produto, com o proprio filtro ligado. Sem isso os cinco
    # slides do carrossel de produtos mostravam a mesma lista, e o carrossel
    # parecia travado num quadro so'.
    "mes-vip":       {"rota": "/resultados", "mes": True, "fonte": "VIP",       "rolar": 1200, "altura": 780},
    "mes-live":      {"rota": "/resultados", "mes": True, "fonte": "Ao Vivo",   "rolar": 1200, "altura": 780},
    "mes-free":      {"rota": "/resultados", "mes": True, "fonte": "Free",      "rolar": 1200, "altura": 780},
    "mes-multiplas": {"rota": "/resultados", "mes": True, "fonte": "Múltiplas", "rolar": 1200, "altura": 780},
    # Jogadores e Boost entraram porque em setembro eles pesam: o de jogadores
    # e' o pior produto do mes, e um carrossel de produto que nao mostra o pior
    # nao e' transparencia, e' vitrine.
    "mes-jogadores": {"rota": "/resultados", "mes": True, "fonte": "Jogadores", "rolar": 1200, "altura": 780},
    "mes-boost":     {"rota": "/resultados", "mes": True, "fonte": "Pick Boost", "rolar": 1200, "altura": 780},
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


def _escolher(pagina, seletor: str, opcao: str) -> None:
    """Abre um dos seletores da pagina e marca uma opcao.

    Sao listbox de verdade (`aria-haspopup`), nao `<select>` nativo, e o rotulo
    visivel do botao e' o valor escolhido · por isso o alvo e' o `aria-label`,
    que nao muda quando o filtro muda.
    """
    pagina.locator(f"button[aria-label='{seletor}']").first.click()
    pagina.wait_for_timeout(700)
    pagina.get_by_role("option", name=opcao, exact=True).first.click()
    pagina.wait_for_timeout(1600)


def capturar(pagina, nome: str, base: str, mes: str = MES_FECHAMENTO,
             sufixo: str = "") -> Path:
    cfg = PRINTS[nome]
    pagina.goto(base.rstrip("/") + cfg["rota"], wait_until="networkidle")
    pagina.wait_for_timeout(1200)

    # O banner de cookies e' um botao de verdade e cobre o rodape do print.
    # Aceitar e' mais limpo que esconder no CSS: some e nao volta na proxima
    # rota da mesma sessao.
    aceitar = pagina.get_by_role("button", name="Entendi")
    if aceitar.count():
        aceitar.first.click()
        pagina.wait_for_timeout(400)
    pagina.evaluate(_ESCONDER)

    # O mes entra por parametro pra que um print de setembro nao sobrescreva o
    # de agosto: os dois posts convivem, e um slide que afirma o numero de um
    # mes ao lado do print de outro desmente o proprio post.
    if cfg.get("mes"):
        _escolher(pagina, "Mês", rotulo_mes(mes))
    if cfg.get("fonte"):
        _escolher(pagina, "Produto", cfg["fonte"])
    if cfg.get("mes") or cfg.get("fonte"):
        pagina.evaluate("window.scrollTo(0, 0)")
        pagina.wait_for_timeout(600)

    if cfg["rolar"]:
        pagina.evaluate(f"window.scrollTo(0, {cfg['rolar']})")
        pagina.wait_for_timeout(900)

    SAIDA.mkdir(parents=True, exist_ok=True)
    # So' os prints com filtro de mes ganham sufixo. `home` e `planos` sao os
    # mesmos em qualquer mes, e duplica-los so' encheria a pasta.
    destino = SAIDA / f"{nome}{sufixo if cfg.get('mes') else ''}.png"
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
    p.add_argument("--mes", default=MES_FECHAMENTO,
                   help="mes AAAA-MM dos prints 'mes-*' (padrao: %(default)s)")
    args = p.parse_args()

    # Mes diferente do padrao ganha sufixo no arquivo. Sem sufixo o carrossel
    # de agosto continua achando os prints dele onde sempre estiveram.
    sufixo = "" if args.mes == MES_FECHAMENTO else f"-{args.mes}"

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
                destino = capturar(pagina, nome, args.url, args.mes, sufixo)
                print(f"[{nome}] {destino}")
            except Exception as erro:
                print(f"[{nome}] falhou: {erro}", file=sys.stderr)
        nav.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
