"""
Stories do Instagram: PNG 1080x1920, desenhados em HTML.

    python stories.py --listar
    python stories.py --todos
    python stories.py --sequencia setembro

POR QUE NAO E' O CARROSSEL RECORTADO
------------------------------------
Story nao e' carrossel em outro tamanho. No feed a pessoa para e le'; no story
ela decide em dois segundos se toca pra avancar. Entao aqui a tela tem UM
numero grande e uma linha de apoio, e o texto corrido do carrossel vira lista
de tres a seis linhas, nunca paragrafo.

A identidade e' a mesma (cores de `cartoes.py`, aparelho sangrando do padrao
"Tela"), e o numero sai do mesmo lugar: `fechamento.py`, que le a rota publica
`/api/public/results`. Nenhum numero e' digitado aqui.

ZONA SEGURA
-----------
O Instagram cobre os 250px de cima (avatar, barrinhas de progresso) e os 340px
de baixo (caixa de resposta, adesivo de link). Todo texto vive entre essas duas
faixas. Imagem pode invadir, texto nao. `--guias` desenha as faixas por cima
pra conferir o enquadramento antes de publicar.

O ULTIMO STORY LEVA O LINK
--------------------------
O adesivo de link fica na mao de quem publica, entao o fecho de cada sequencia
deixa o rodape livre e diz "arrasta pra cima". E' onde o adesivo entra.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from cartoes import ACENTO, FUNDO, TINTA, TINTA_3, _logo_embutido
from fechamento import MESES, NOMES_FONTE, _n, _u, dados, numeros

LARGURA, ALTURA = 1080, 1920
AQUI = Path(__file__).parent
PRINTS = AQUI / "carrossel" / "prints"

VERMELHO = "#f2555a"

# Faixas que a interface do Instagram cobre.
TOPO_SEGURO, BASE_SEGURA = 250, 340

DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


# ---------------------------------------------------------------- dado extra
# `numeros()` entrega o resumo do mes. Story de resultado tambem quer o dia a
# dia e os picks nominais do ultimo dia, que moram no JSON cru.

def _picks(n: int) -> str:
    """"1 pick" e nao "1 picks". Uma liga com pick unico existe todo mes."""
    return f"{n} pick" if n == 1 else f"{n} picks"


def linhas_dias(mes: str, quantos: int = 6) -> list[tuple[str, str, str]]:
    """Os ultimos dias do mes: (rotulo, valor, sinal)."""
    saida = []
    for d in dados(mes)["by_day"][-quantos:]:
        data = dt.date.fromisoformat(d["match_date"])
        rotulo = f"{data.day:02d}/{data.month:02d} {DIAS_SEMANA[data.weekday()]}"
        saida.append((
            f"{rotulo}<i>{_picks(d['total'])}, {d['greens']} green</i>",
            _u(d["profit"]),
            "verde" if d["profit"] >= 0 else "vermelho",
        ))
    return saida


def _com_o_pior(itens: list, quantos: int) -> list:
    """Os melhores mais o pior de todos.

    O pior entra sempre, mesmo quando a lista e' longa: um story de produto que
    corta os cinco primeiros esconde justamente o que da' credibilidade ao
    resto. Se o pior ja' estava entre os melhores, nao repete.
    """
    if len(itens) <= quantos:
        return itens
    return itens[: quantos - 1] + itens[-1:]


def linhas_produtos(mes: str, quantos: int = 5) -> list[tuple[str, str, str]]:
    """Produto por produto, do que mais lucrou pro que mais perdeu."""
    fontes = sorted(dados(mes)["by_source"], key=lambda f: f["profit"], reverse=True)
    return [
        (f"{NOMES_FONTE.get(f['source'], f['source'])}<i>{_picks(f['total'])}, "
         f"ROI {_n(f['roi'], 1)}%</i>",
         _u(f["profit"]),
         "verde" if f["profit"] >= 0 else "vermelho")
        for f in _com_o_pior(fontes, quantos)
    ]


def linhas_ligas(mes: str, quantos: int = 5) -> list[tuple[str, str, str]]:
    ligas = sorted(dados(mes)["by_league"], key=lambda x: x["profit"], reverse=True)
    return [
        (f"{l['league_name']}<i>{_picks(l['total'])}</i>",
         _u(l["profit"]),
         "verde" if l["profit"] >= 0 else "vermelho")
        for l in _com_o_pior(ligas, quantos)
    ]


def _linha_em_portugues(linha: str) -> str:
    """"Under 14.5" vira "Menos de 14.5", como o site escreve.

    A API devolve a linha em ingles e quem traduz e' o front
    (frontend/src/utils/marketTranslate.ts, que e' a fonte da verdade). Aqui
    so' o Over/Under interessa, que e' o formato de toda linha que chega em
    `recent`. Sem isso o story sai com o mercado em ingles ao lado de um print
    do site em portugues.
    """
    for ingles, portugues in (("Over ", "Mais de "), ("Under ", "Menos de ")):
        if linha.startswith(ingles):
            return portugues + linha[len(ingles):]
    return linha


def linhas_do_dia(mes: str, quantos: int = 5) -> list[tuple[str, str, str]]:
    """Picks nominais do dia mais recente. E' o story de todo dia."""
    dia = dados(mes)["by_day"][-1]["match_date"]
    recentes = [r for r in dados(mes)["recent"] if r["match_date"] == dia]

    # No maximo dois picks do mesmo jogo. Numa rodada com poucos jogos o motor
    # publica cinco mercados da mesma partida, e o story virava cinco linhas
    # com o mesmo "Vitoria x Gremio" repetido, que nao mostra cobertura nenhuma.
    saida, por_jogo = [], {}
    for r in recentes:
        jogo = f"{r['home_team_name']} x {r['away_team_name']}"
        if por_jogo.get(jogo, 0) >= 2:
            continue
        por_jogo[jogo] = por_jogo.get(jogo, 0) + 1
        produto = NOMES_FONTE.get(r["source"], r["source"])
        saida.append((
            f"{jogo}<i>{produto}, {_linha_em_portugues(r['line'])} "
            f"em {_n(r['odd'])}</i>",
            r["result"],
            # PUSH nao ganhou nem perdeu. Sai em cinza, como no site: pintado
            # de verde por ter lucro zero, ele passava por acerto.
            "neutro" if r["result"] == "PUSH"
            else "verde" if r["profit"] >= 0 else "vermelho",
        ))
        if len(saida) == quantos:
            break
    return saida


def numeros_do_dia(mes: str) -> dict[str, str]:
    """Resumo do dia mais recente, no mesmo formato de `numeros()`."""
    d = dados(mes)["by_day"][-1]
    data = dt.date.fromisoformat(d["match_date"])
    return {
        "dia_data": f"{data.day:02d} de {MESES[f'{data.month:02d}']}",
        "dia_curto": f"{data.day:02d}/{data.month:02d}",
        "dia_picks": str(d["total"]),
        "dia_greens": str(d["greens"]),
        "dia_reds": str(d["reds"]),
        "dia_lucro": _u(d["profit"]),
        "dia_acerto": f"{_n(d['greens'] / d['total'] * 100, 1)}%" if d["total"] else "0%",
    }


# ------------------------------------------------------------------ conteudo
# Cada tela e' um dicionario com `layout`. Tres layouts, porque story que muda
# de cara a cada toque vira apresentacao de slide, e story que nunca muda o
# leitor acha que travou.
#
#   numero  -> um valor gigante e a linha que explica de onde ele veio
#   lista   -> tres a seis linhas de dado, rotulo na esquerda, valor na direita
#   tela    -> o aparelho do padrao "Tela", pro fecho com o adesivo de link
#
# `fonte` diz de onde as linhas do layout `lista` saem.

SEQUENCIAS: dict[str, dict] = {
    # ------------------------------------------------- o mes que esta correndo
    "setembro": {
        "mes": "2026-09",
        "stories": [
            {"layout": "numero", "kicker": "{Mes} até agora", "numero": "{lucro}",
             "titulo": "{picks} picks resolvidos",
             "texto": "Em {dias} dias, espalhados por {ligas} ligas. "
                      "Green e red, tudo publicado."},
            {"layout": "lista", "kicker": "Dia a dia", "titulo": "Teve dia ruim",
             "fonte": "dias",
             "texto": "O dia negativo fica na mesma tela que o positivo."},
            {"layout": "numero", "kicker": "Acerto", "numero": "{acerto}",
             "titulo": "{greens} green e {reds} red",
             "texto": "A mesma conta do site: meio-green conta como acerto "
                      "e pick anulado sai da conta."},
            {"layout": "lista", "kicker": "Produto por produto",
             "titulo": "Nem tudo lucrou", "fonte": "produtos",
             "texto": "Um placar que só tem green não é placar, é anúncio."},
            {"layout": "tela", "kicker": "Confira você mesmo",
             "titulo": "O histórico\nabre sem conta",
             "texto": "Filtre por mês, por liga e por produto.",
             # A lista, e nao o resumo: ela mostra GREEN, RED e PUSH na mesma
             # rolagem, que e' exatamente o que o story acabou de afirmar.
             "print": "mes-lista-2026-09", "cta": "arrasta pra cima"},
        ],
    },
    # ----------------------------------------------------- fechamento fechado
    "agosto": {
        "mes": "2026-08",
        "stories": [
            {"layout": "numero", "kicker": "Fechamento de {mes}", "numero": "{lucro}",
             "titulo": "{Mes_ano}",
             "texto": "{picks} picks resolvidos em {dias} dias. "
                      "O mês inteiro, não o print escolhido a dedo."},
            {"layout": "numero", "kicker": "Retorno", "numero": "{roi}",
             "titulo": "de ROI sobre {stake} arriscadas",
             "texto": "É o lucro sobre tudo que entrou, não sobre o que deu certo."},
            {"layout": "lista", "kicker": "Produto por produto",
             "titulo": "O grátis perdeu", "fonte": "produtos",
             "texto": "O Pick do Dia fechou {mes} no vermelho, "
                      "e está publicado assim mesmo."},
            {"layout": "lista", "kicker": "Por liga",
             "titulo": "O buraco também aparece", "fonte": "ligas",
             # "tirou -30,48u" sai com o sinal dobrado, porque `liga_pior_lucro`
             # ja' vem com o menos na frente. O verbo neutro resolve.
             "texto": "{liga_pior} fechou o mês em {liga_pior_lucro}."},
            {"layout": "tela", "kicker": "Fechamento de {mes}",
             "titulo": "Confere\nno site",
             "texto": "pickia.com.br/resultados, sem login.",
             "print": "mes-resumo", "cta": "arrasta pra cima"},
        ],
    },
    # ----------------------------------------- o story de todo dia, o mais curto
    "dia": {
        "mes": "2026-09",
        "stories": [
            {"layout": "numero", "kicker": "{dia_data}", "numero": "{dia_lucro}",
             "titulo": "{dia_greens} green, {dia_reds} red",
             "texto": "{dia_picks} picks resolvidos no dia, {dia_acerto} de acerto."},
            {"layout": "lista", "kicker": "{dia_curto}", "titulo": "Como saiu",
             "fonte": "dia",
             "texto": "Cada pick é publicado com odd, stake e resultado."},
            {"layout": "tela", "kicker": "Todo dia",
             "titulo": "Tem pick grátis\ntodo dia",
             "texto": "Sem cartão, e o histórico abre deslogado.",
             "print": "resultados", "cta": "arrasta pra cima"},
        ],
    },
}

FONTES = {
    "dias": linhas_dias,
    "produtos": linhas_produtos,
    "ligas": linhas_ligas,
    "dia": linhas_do_dia,
}

_ESTILO = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:{LARGURA}px; height:{ALTURA}px; background:{FUNDO}; color:{TINTA};
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
  position:relative; overflow:hidden;
}}
/* Brilho da marca, o mesmo dos cartoes do video e dos slides do carrossel. */
body::before {{
  content:''; position:absolute; left:46%; top:44%; width:1500px; height:1500px;
  transform:translate(-50%,-50%);
  background:radial-gradient(circle, rgba(0,204,0,.17) 0%, rgba(0,204,0,0) 64%);
}}
.marca {{
  position:absolute; top:{TOPO_SEGURO + 30}px; left:88px; z-index:3;
  display:flex; align-items:center; gap:18px;
  font-size:36px; font-weight:800; letter-spacing:-.02em;
}}
.marca img {{ width:74px; height:74px; display:block; }}
.marca i {{ font-style:normal; color:{ACENTO}; }}

/* O bloco vive entre as duas faixas que a interface do Instagram cobre. */
.corpo {{
  position:absolute; z-index:2;
  top:{TOPO_SEGURO + 170}px; bottom:{BASE_SEGURA + 150}px; left:88px; right:88px;
  display:flex; flex-direction:column; justify-content:center;
  /* Recorta pra que `scrollHeight` denuncie o transbordo · e' o que `_encaixar`
     mede depois de montar a pagina. */
  overflow:hidden;
}}
.corpo.alto {{ justify-content:flex-start; }}

.kicker {{
  font-size:30px; font-weight:800; letter-spacing:.2em; text-transform:uppercase;
  color:{ACENTO}; margin-bottom:26px;
}}
/* O numero e' o story inteiro: se ele nao for lido de longe, nada mais e'. */
.numero {{
  font-size:210px; font-weight:900; line-height:.92; letter-spacing:-.05em;
}}
.numero.longo {{ font-size:168px; }}
.numero.verde {{ color:{ACENTO}; }}
.numero.vermelho {{ color:{VERMELHO}; }}
.h {{
  font-size:64px; font-weight:900; line-height:1.06; letter-spacing:-.035em;
  white-space:pre-line; margin-top:30px;
}}
.h.solo {{ font-size:86px; margin-top:0; }}
.p {{
  font-size:38px; font-weight:500; line-height:1.38; color:#c7c7cf;
  margin-top:26px; max-width:880px;
}}

/* Lista: rotulo na esquerda, valor na direita, linha fina separando. Nao vira
   tabela de proposito: o alinhamento e a regua ja' dao a leitura em coluna
   sem desenhar grade. */
.lista {{ margin-top:44px; }}
/* Cinco linhas ou mais nao cabem no tamanho cheio: elas passavam por baixo do
   rodape e o aviso legal saia atravessado no meio da tabela. Entao a lista
   longa encolhe em vez de vazar. */
.lista.compacta .linha {{ padding:19px 0; }}
.lista.compacta .rot {{ font-size:38px; }}
.lista.compacta .rot i {{ font-size:27px; margin-top:5px; }}
.lista.compacta .val {{ font-size:42px; }}
.linha {{
  display:flex; align-items:baseline; justify-content:space-between; gap:28px;
  padding:28px 0; border-bottom:2px solid #1e1e24;
}}
.linha:last-child {{ border-bottom:none; }}
.linha .rot {{ font-size:44px; font-weight:700; letter-spacing:-.015em; }}
/* O detalhe desce pra segunda linha, menor: o nome identifica, o detalhe e' a
   conferencia de quem quiser ir no site checar. */
.linha .rot i {{
  display:block; font-style:normal; font-size:30px; font-weight:500;
  color:{TINTA_3}; margin-top:8px;
}}
.linha .val {{
  font-size:48px; font-weight:900; letter-spacing:-.02em; white-space:nowrap;
}}
.linha .val.verde {{ color:{ACENTO}; }}
.linha .val.vermelho {{ color:{VERMELHO}; }}
.linha .val.neutro {{ color:{TINTA_3}; }}

/* Aparelho do padrao "Tela": sangra pela borda de baixo, e aqui pode invadir a
   faixa da interface porque e' imagem, nao texto. */
.aparelho {{
  position:absolute; left:50%; transform:translateX(-50%);
  top:900px; width:640px; height:1020px;
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
/* O veu devolve o rodape, que o aparelho tomaria. Tem que ficar opaco ANTES da
   altura do aviso legal: curto demais, o texto do rodape saia por cima das
   linhas do print e nao se lia nem um nem outro. */
.veu {{
  position:absolute; left:0; right:0; bottom:0; height:760px; z-index:2;
  background:linear-gradient(to bottom, rgba(10,10,12,0) 0%, {FUNDO} 46%);
}}

/* Rodape e aviso empilhados num bloco so'. Ancorados um a um pela borda de
   baixo eles se cruzavam: o aviso quebra em duas linhas e subia por cima da
   assinatura. */
.pe {{
  position:absolute; left:88px; right:88px; bottom:{BASE_SEGURA}px; z-index:4;
  display:flex; flex-direction:column; gap:16px;
}}
.rodape {{
  display:flex; justify-content:space-between; align-items:flex-end;
  font-size:28px; font-weight:600; color:{TINTA_3};
}}
.rodape .cta {{ color:{ACENTO}; font-weight:800; }}
.aviso {{ font-size:24px; font-weight:500; line-height:1.3; color:#5c5c66; }}

/* Conferencia de enquadramento. Nunca sai no arquivo publicado. */
.guia {{
  position:absolute; left:0; right:0; z-index:9;
  background:rgba(242,85,90,.16);
  border-top:2px dashed rgba(242,85,90,.55);
  border-bottom:2px dashed rgba(242,85,90,.55);
}}
"""


def _print_embutido(nome: str) -> str:
    """O print como data URI: a pagina e' renderizada sem servidor."""
    arquivo = PRINTS / f"{nome}.png"
    if not arquivo.exists():
        return f"<div class='vazio'>print de {nome}</div>"
    uri = "data:image/png;base64," + base64.b64encode(arquivo.read_bytes()).decode()
    return f"<img src='{uri}' alt=''>"


def _pagina(story: dict, n: dict, logo: str, mes: str, guias: bool) -> str:
    preencher = lambda t: t.format(**n)  # noqa: E731
    layout = story["layout"]

    kicker = f"<div class='kicker'>{preencher(story['kicker'])}</div>"
    texto = (f"<div class='p'>{preencher(story['texto'])}</div>"
             if story.get("texto") else "")

    if layout == "numero":
        valor = preencher(story["numero"])
        cor = "vermelho" if valor.startswith("-") else "verde"
        # Acima de 7 caracteres o numero encosta nas duas margens e some a
        # respiracao que faz ele parecer grande.
        tamanho = " longo" if len(valor) > 7 else ""
        miolo = (f"<div class='numero {cor}{tamanho}'>{valor}</div>"
                 f"<div class='h'>{preencher(story['titulo'])}</div>{texto}")
        classe_corpo, aparelho, veu = "", "", ""

    elif layout == "lista":
        itens = FONTES[story["fonte"]](mes)
        linhas = "".join(
            f"<div class='linha'><span class='rot'>{rot}</span>"
            f"<span class='val {sinal}'>{val}</span></div>"
            for rot, val, sinal in itens
        )
        compacta = " compacta" if len(itens) >= 5 else ""
        # A linha de apoio vem ANTES da lista aqui. Depois dela, uma lista de
        # seis dias empurrava a frase por cima do rodape: a lista e' o que
        # cresce, entao ela e' que fica na ponta.
        miolo = (f"<div class='h solo'>{preencher(story['titulo'])}</div>"
                 f"{texto}<div class='lista{compacta}'>{linhas}</div>")
        classe_corpo, aparelho, veu = " alto", "", ""

    else:  # tela
        miolo = f"<div class='h solo'>{preencher(story['titulo'])}</div>{texto}"
        classe_corpo = " alto"
        aparelho = f"<div class='aparelho'>{_print_embutido(story['print'])}</div>"
        veu = "<div class='veu'></div>"

    cta = f"<span class='cta'>{story['cta']}</span>" if story.get("cta") else ""
    faixas = (
        f"<div class='guia' style='top:0;height:{TOPO_SEGURO}px'></div>"
        f"<div class='guia' style='bottom:0;height:{BASE_SEGURA}px'></div>"
    ) if guias else ""

    return (
        f"<!doctype html><meta charset='utf-8'><style>{_ESTILO}</style>"
        f"{aparelho}{veu}"
        f"<div class='marca'>{logo}<span>Pick<i>IA</i></span></div>"
        f"<div class='corpo{classe_corpo}'>{kicker}{miolo}</div>"
        f"<div class='pe'>"
        f"<div class='aviso'>Aposta é para maiores de 18 anos. "
        f"Resultado passado não garante resultado futuro.</div>"
        f"<div class='rodape'><span>pickia.com.br</span>{cta}</div>"
        f"</div>"
        f"{faixas}"
    )


# Encolhe a lista ate' o bloco caber na area segura. Roda no navegador porque
# quem sabe a altura real do texto e' quem o desenhou: calcular isso na mao em
# Python era chute, e o chute errava por poucos pixels · a ultima linha saia por
# baixo do aviso legal. Um mes com mais dias, uma liga de nome comprido ou uma
# fonte diferente mudam a conta, e aqui nada disso precisa ser previsto.
_ENCAIXAR = """() => {
  const corpo = document.querySelector('.corpo');
  const lista = document.querySelector('.lista');
  if (!corpo || !lista) return 1;
  let zoom = 1;
  while (corpo.scrollHeight > corpo.clientHeight && zoom > 0.6) {
    zoom -= 0.02;
    lista.style.zoom = zoom;
  }
  return zoom;
}"""


def render(nome: str, destino: Path, guias: bool = False) -> list[Path]:
    seq = SEQUENCIAS[nome]
    destino.mkdir(parents=True, exist_ok=True)
    uri = _logo_embutido()
    logo = f"<img src='{uri}' alt=''>" if uri else ""

    mes = seq["mes"]
    n = dict(numeros(mes))
    n.update(numeros_do_dia(mes))

    gerados: list[Path] = []
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(
            viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1
        )
        for i, story in enumerate(seq["stories"]):
            arquivo = destino / f"{nome}-{i:02d}.png"
            pagina.set_content(_pagina(story, n, logo, mes, guias))
            pagina.evaluate(_ENCAIXAR)
            pagina.screenshot(path=str(arquivo))
            gerados.append(arquivo)
        navegador.close()
    return gerados


def main() -> int:
    p = argparse.ArgumentParser(description="Gera stories 1080x1920 pro Instagram")
    p.add_argument("--sequencia", action="append", default=[])
    p.add_argument("--todos", action="store_true")
    p.add_argument("--listar", action="store_true")
    p.add_argument("--guias", action="store_true",
                   help="marca as faixas que a interface do Instagram cobre")
    p.add_argument("--saida", default=str(AQUI / "stories"))
    args = p.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.listar:
        print("sequências disponíveis:\n")
        for nome, s in SEQUENCIAS.items():
            print(f"  {nome:<12} {len(s['stories'])} telas, {s['mes']}")
        return 0

    escolhidas = list(SEQUENCIAS) if args.todos else args.sequencia
    if not escolhidas:
        print("erro: use --sequencia <nome>, --todos ou --listar", file=sys.stderr)
        return 2

    desconhecidas = [c for c in escolhidas if c not in SEQUENCIAS]
    if desconhecidas:
        print(f"erro: não existe: {', '.join(desconhecidas)}", file=sys.stderr)
        return 2

    saida = Path(args.saida)
    for nome in escolhidas:
        arquivos = render(nome, saida, args.guias)
        print(f"[{nome}] {len(arquivos)} telas em {saida / nome}-NN.png")

    print(f"\npronto em {saida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
