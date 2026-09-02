"""
Carrosséis do Instagram: PNG 1080x1350, desenhados em HTML.

    python carrossel.py --listar
    python carrossel.py --todos
    python carrossel.py --carrossel fechamento

1080x1350 é 4:5, o formato que ocupa mais altura no feed. Quadrado 1:1
desperdiça tela em celular, e 9:16 o feed corta.

PADRÃO "TELA" (aprovado em 02/09/2026)
--------------------------------------
Todo slide mostra o site num aparelho que sangra pela borda de baixo. O texto
vive no terço de cima, que é a faixa que o feed nunca corta, e o degradê do
rodapé dissolve o aparelho na borda em vez de cortá-lo na faca.

Os prints saem de `prints.py`, que fotografa o site num viewport de celular.
Slide sem print desenha a moldura vazia, então dá pra diagramar antes de ter a
foto.

NÚMERO NO SLIDE
---------------
Carrossel com `"mes"` preenchido resolve `{placeholder}` com os números
públicos daquele mês, lidos por `fechamento.py`. Nenhum número é digitado à
mão aqui: o que o post afirma é o mesmo que /resultados mostra, e se divergir
é porque o mês virou, não porque alguém errou de teclar.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from cartoes import ACENTO, FUNDO, TINTA, TINTA_3, _logo_embutido
from fechamento import numeros

LARGURA, ALTURA = 1080, 1350
AQUI = Path(__file__).parent
PRINTS = AQUI / "carrossel" / "prints"

# Slide bom tem UMA ideia. Se precisou de dois parágrafos, era dois slides.
#
# capa/cta: (título, texto, print) · slides: (título, texto, print)
# O kicker verde da capa é o `rotulo`; nos slides de conteúdo ele vira a
# contagem, porque no meio do carrossel o que a pessoa quer saber é quanto
# falta.
CARROSSEIS: dict[str, dict] = {
    # ---------------------------------------------------------------- dia 1
    "fechamento": {
        "mes": "2026-08",
        "rotulo": "Fechamento de {mes}",
        "capa": ("{mes_ano}\nfechou em {lucro}",
                 "Todo pick publicado, green e red, está no site.",
                 "mes-resumo"),
        "slides": [
            ("{picks} picks resolvidos",
             "Em {dias} dias, espalhados por {ligas} ligas.",
             "mes-lista"),
            ("ROI de {roi}",
             "É o lucro sobre tudo que foi arriscado, não sobre o que deu certo.",
             "mes-resumo"),
            ("{acerto} de acerto",
             "{greens} green e {reds} red. O red aparece na mesma tela.",
             "mes-resumo"),
            ("{liga_melhor} puxou o mês",
             "{liga_melhor_lucro} só nessa liga.",
             "mes-ligas"),
            ("{liga_pior} tirou {liga_pior_lucro}",
             "O mês teve buraco, e o buraco fica publicado do mesmo tamanho.",
             "mes-ligas"),
        ],
        "cta": ("Confira você mesmo",
                "O histórico abre sem conta e sem cartão.",
                "mes-resumo"),
    },
    # ---------------------------------------------------------------- dia 2
    "produtos": {
        "mes": "2026-08",
        "rotulo": "Produto por produto",
        "capa": ("Nem tudo\ndeu lucro",
                 "O fechamento de {mes} aberto por tipo de pick.",
                 "mes-resumo"),
        "slides": [
            ("{vip_nome}: {vip_lucro}",
             "{vip_picks} picks, {vip_acerto} de acerto, ROI de {vip_roi}.",
             "mes-vip"),
            ("{live_nome}: {live_lucro}",
             "{live_picks} picks lidos com o jogo em andamento. ROI de {live_roi}.",
             "mes-live"),
            ("{free_nome}: {free_lucro}",
             "O pick grátis fechou {mes} no vermelho. Está publicado assim mesmo.",
             "mes-free"),
            ("{multiplas_nome}: {multiplas_lucro}",
             "{multiplas_acerto} de acerto e ainda assim lucro. Odd alta faz isso.",
             "mes-multiplas"),
            ("Por que mostrar o que perdeu",
             "Porque um placar que só tem green não é placar, é anúncio.",
             "mes-resumo"),
        ],
        "cta": ("Tudo isso está aberto",
                "Filtre por produto, por liga ou por mês.",
                "mes-ligas"),
    },
    # ---------------------------------------------------------------- dia 3
    "como-funciona": {
        "rotulo": "Por dentro",
        "capa": ("De onde vem\num pick?",
                 "O caminho inteiro, em cinco telas.",
                 "como-funciona"),
        "slides": [
            ("1. Lê o jogo",
             "Finalização, escanteio, falta, ritmo. Estatística real das duas equipes.",
             "como-funciona-passos"),
            ("2. Calcula a chance",
             "A probabilidade daquele mercado acontecer naquela partida.",
             "home-passos"),
            ("3. Compara com a odd",
             "Odd é probabilidade disfarçada. Dá pra saber quanto a casa está pagando a mais.",
             "home-passos"),
            ("4. Só então vira pick",
             "Sem diferença a favor, o jogo não entra. A maioria não entra.",
             "como-funciona"),
            ("5. Fica registrado",
             "Green ou red, vai pro histórico público no mesmo dia.",
             "resultados-lista"),
        ],
        "cta": ("Veja o método inteiro",
                "A página Como Funciona abre sem login.",
                "como-funciona"),
    },
    # ---------------------------------------------------------------- dia 4
    "banca": {
        "mes": "2026-08",
        "rotulo": "Gestão de banca",
        "capa": ("Apostar sem banca\né torcer",
                 "A parte que decide se você sobrevive ao mês ruim.",
                 "planos"),
        "slides": [
            ("Banca é o dinheiro separado",
             "O que você pode perder inteiro sem mexer em conta de casa.",
             "planos"),
            ("Unidade é o tamanho da entrada",
             "Entre 1% e 5% da banca. O site trava se você passar disso.",
             "planos"),
            ("Cinco reds seguidos acontecem",
             "Com unidade grande eles zeram você. Com unidade certa, custam um mau dia.",
             "mes-ligas"),
            ("O stake sai calculado",
             "Em {mes}: {stake_label}.",
             "mes-lista"),
            ("Registrar é o que fecha a conta",
             "Sem registro você lembra dos greens e esquece dos reds.",
             "planos"),
        ],
        "cta": ("Configure a sua banca",
                "Leva menos de um minuto.",
                "planos"),
    },
    # ---------------------------------------------------------------- dia 5
    "comecar": {
        "rotulo": "Comece hoje",
        "capa": ("Tem pick grátis\ntodo dia",
                 "Sem cartão, e sem precisar acreditar em ninguém.",
                 "home"),
        "slides": [
            ("A Dica do Dia é aberta",
             "Um pick por dia, liberado pra qualquer conta.",
             "home"),
            ("O histórico vem antes",
             "Confira o placar de meses inteiros antes de gastar um real.",
             "resultados"),
            ("O VIP tem 2 dias grátis",
             "Todos os picks, o raciocínio de cada um e a gestão de banca junto.",
             "planos"),
            ("Não somos casa de aposta",
             "Você aposta onde já aposta. Aqui você decide no quê.",
             "planos"),
            ("E se não servir",
             "Você sai. O histórico continua aberto do mesmo jeito.",
             "resultados"),
        ],
        "cta": ("Criar conta grátis",
                "pickia.com.br",
                "home"),
    },
}

_ESTILO = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:{LARGURA}px; height:{ALTURA}px; background:{FUNDO}; color:{TINTA};
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
  position:relative; overflow:hidden; padding:74px;
}}
/* Brilho da marca atrás do texto, no mesmo lugar dos cartões do vídeo. */
body::before {{
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
/* Título longo desce de tamanho em vez de invadir o aparelho. */
.h.longo {{ font-size:64px; }}
.p {{ font-size:36px; font-weight:500; line-height:1.36; color:#c7c7cf;
  margin-top:20px; max-width:800px; }}
.pilula {{
  display:inline-block; margin-top:30px; padding:22px 44px; background:{ACENTO};
  color:#04140a; border-radius:18px; font-size:34px; font-weight:900;
}}

/* O aparelho sangra pela borda de baixo: mostra tela de verdade sem gastar o
   slide inteiro, e o corte no rodapé sugere que tem mais pra ver no site.
   A borda é mais clara que o fundo de propósito, senão o aparelho some: o
   print e o slide são os dois #0a0a0c. */
.aparelho {{
  position:absolute; left:50%; transform:translateX(-50%);
  top:600px; width:604px; height:820px;
  border:12px solid #3a3a44; border-top-left-radius:58px;
  border-top-right-radius:58px; overflow:hidden;
  background:#141418; z-index:1;
  box-shadow:0 0 0 2px #101014, 0 -18px 70px rgba(0,0,0,.85);
}}
.aparelho img {{ width:100%; display:block; }}
.aparelho .vazio {{
  height:100%; display:flex; align-items:center; justify-content:center;
  font-size:28px; font-weight:700; color:#4a4a54; letter-spacing:.04em;
}}

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
    """O print como data URI: a página é renderizada sem servidor."""
    arquivo = PRINTS / f"{nome}.png"
    if not arquivo.exists():
        return f"<div class='vazio'>print de {nome}</div>"
    uri = "data:image/png;base64," + base64.b64encode(arquivo.read_bytes()).decode()
    return f"<img src='{uri}' alt=''>"


def _pagina(kicker: str, titulo: str, texto: str, nome_print: str,
            pilula: bool, acesos: int, total: int, direita: str,
            logo: str) -> str:
    # 34 caracteres por linha é o que cabe em 78px sem esbarrar no aparelho.
    maior_linha = max((len(l) for l in titulo.split("\n")), default=0)
    classe = "h longo" if maior_linha > 34 else "h"
    barras = "".join(f"<i class='{'on' if n < acesos else ''}'></i>"
                     for n in range(total))
    botao = "<div><span class='pilula'>pickia.com.br</span></div>" if pilula else ""
    return (
        f"<!doctype html><meta charset='utf-8'><style>{_ESTILO}</style>"
        f"<div class='topo'>{logo}<span class='wordmark'>Pick<i>IA</i></span></div>"
        f"<div class='texto'><div class='kicker'>{kicker}</div>"
        f"<div class='{classe}'>{titulo}</div><div class='p'>{texto}</div>{botao}</div>"
        f"<div class='aparelho'>{_print_embutido(nome_print)}</div>"
        f"<div class='rodape'>"
        f"<span><span class='trilho'>{barras}</span><br>pickia.com.br</span>"
        f"<span class='arraste'>{direita}</span></div>"
    )


def render(nome: str, destino: Path) -> list[Path]:
    dados = CARROSSEIS[nome]
    destino.mkdir(parents=True, exist_ok=True)
    uri = _logo_embutido()
    logo = f"<img src='{uri}' alt=''>" if uri else ""

    n = numeros(dados["mes"]) if dados.get("mes") else {}
    preencher = (lambda t: t.format(**n)) if n else (lambda t: t)

    rotulo = preencher(dados["rotulo"])
    paginas: list[tuple] = []

    titulo, texto, print_capa = dados["capa"]
    paginas.append((rotulo, preencher(titulo), preencher(texto), print_capa,
                    False, "arraste"))

    total = len(dados["slides"])
    for i, (titulo, texto, nome_print) in enumerate(dados["slides"], start=1):
        paginas.append((f"{i:02d} de {total:02d}", preencher(titulo),
                        preencher(texto), nome_print, False, "arraste"))

    titulo, texto, print_cta = dados["cta"]
    paginas.append((rotulo, preencher(titulo), preencher(texto), print_cta,
                    True, "link na bio"))

    gerados: list[Path] = []
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(
            viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1
        )
        for i, (kicker, titulo, texto, nome_print, pilula, direita) in enumerate(paginas):
            arquivo = destino / f"{nome}-{i:02d}.png"
            pagina.set_content(_pagina(
                kicker, titulo, texto, nome_print, pilula,
                i + 1, len(paginas), direita, logo,
            ))
            pagina.screenshot(path=str(arquivo))
            gerados.append(arquivo)
        navegador.close()

    return gerados


def main() -> int:
    p = argparse.ArgumentParser(description="Gera carrosséis 1080x1350 pro Instagram")
    p.add_argument("--carrossel", action="append", default=[])
    p.add_argument("--todos", action="store_true")
    p.add_argument("--listar", action="store_true")
    p.add_argument("--saida", default=str(AQUI / "carrossel"))
    args = p.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.listar:
        print("carrosséis disponíveis:\n")
        for nome, d in CARROSSEIS.items():
            mes = d.get("mes", "sem número")
            print(f"  {nome:<15} {len(d['slides']) + 2} slides · {mes}")
        return 0

    escolhidos = list(CARROSSEIS) if args.todos else args.carrossel
    if not escolhidos:
        print("erro: use --carrossel <nome>, --todos ou --listar", file=sys.stderr)
        return 2

    desconhecidos = [c for c in escolhidos if c not in CARROSSEIS]
    if desconhecidos:
        print(f"erro: não existe: {', '.join(desconhecidos)}", file=sys.stderr)
        return 2

    saida = Path(args.saida)
    for nome in escolhidos:
        arquivos = render(nome, saida)
        print(f"[{nome}] {len(arquivos)} slides em {saida / nome}-NN.png")

    print(f"\npronto em {saida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
