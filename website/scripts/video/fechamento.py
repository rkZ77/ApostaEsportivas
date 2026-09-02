"""
Fechamento mensal: os numeros publicos do mes, prontos pro carrossel.

    python fechamento.py 2026-08
    python fechamento.py 2026-08 --atualizar

Le `GET /api/public/results?month=YYYY-MM` do site e guarda a resposta crua em
`fechamentos/<mes>.json`. A rota e' publica (a pagina /resultados abre
deslogada), entao nao existe conta de robo em producao e nada e' escrito la'.

O cache existe por dois motivos. Primeiro, o post tem que sair sempre com o
mesmo numero: se o carrossel for regerado semana que vem e a rota tiver
resolvido mais um pick pendente do mes, o slide muda sozinho depois de
publicado. Segundo, cada chamada dispara tres varreduras em background no
servidor -- e' o que qualquer visitante faz, mas nao ha' motivo pra repetir a
cada render.

`numeros()` devolve tudo ja' formatado em pt-BR, porque numero de post nao pode
sair com ponto decimal americano nem com "12.5%".
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://pickia.com.br"
DADOS = Path(__file__).parent / "fechamentos"

# Nome de vitrine de cada pipeline. "vip"/"live" sao nomes de dentro de casa;
# no post o leitor precisa de algo que diga o que a coisa faz.
NOMES_FONTE = {
    "vip": "Pick VIP",
    "free": "Pick do Dia",
    "live": "Radar Ao Vivo",
    "multiplas": "Múltipla",
    "alavancagem": "Alavancagem",
    "faltas": "Faltas",
    "goleiros": "Defesas de Goleiro",
    "player_stats": "Números do Jogador",
    "boost": "Pick Boost",
}

MESES = {
    "01": "janeiro", "02": "fevereiro", "03": "marco", "04": "abril",
    "05": "maio", "06": "junho", "07": "julho", "08": "agosto",
    "09": "setembro", "10": "outubro", "11": "novembro", "12": "dezembro",
}


# A Cloudflare na frente do site devolve 403 pro user-agent do urllib. Nao e'
# bloqueio de robo de IA (esse esta' no painel, e vale pra ClaudeBot/GPTBot),
# e' a regra generica de cliente sem cara de navegador.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def baixar(mes: str) -> dict:
    url = f"{BASE}/api/public/results?month={mes}"
    req = urllib.request.Request(
        url, headers={"accept": "application/json", "user-agent": _UA}
    )
    with urllib.request.urlopen(req, timeout=90) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def dados(mes: str, atualizar: bool = False) -> dict:
    """A resposta do mes, do cache ou do site."""
    DADOS.mkdir(parents=True, exist_ok=True)
    arquivo = DADOS / f"{mes}.json"
    if arquivo.exists() and not atualizar:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    bruto = baixar(mes)
    arquivo.write_text(
        json.dumps(bruto, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return bruto


def _n(valor: float, casas: int = 2) -> str:
    """Numero em pt-BR: virgula decimal, ponto de milhar."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", " ").replace(".", ",").replace(" ", ".")


def _u(valor: float) -> str:
    """Unidades com sinal, do jeito que o site escreve."""
    return f"{'+' if valor >= 0 else '-'}{_n(abs(valor))}u"


def _pct(valor: float) -> str:
    return f"{_n(valor, 1)}%"


def numeros(mes: str, atualizar: bool = False) -> dict[str, str]:
    """Tudo que um slide pode querer citar, ja' formatado."""
    d = dados(mes, atualizar)
    s = d["summary"]
    ano, num = mes.split("-")

    # Acerto sobre o TOTAL, que e' a mesma conta do "Win Rate" da pagina de
    # Resultados. Sobre green+red daria 67,3% em agosto contra os 65% que o
    # print mostra -- e o slide fica ao lado do print no mesmo post.
    acerto = (s["greens"] / s["total"] * 100) if s["total"] else 0.0

    ligas = sorted(d["by_league"], key=lambda x: x["profit"], reverse=True)
    fontes = {f["source"]: f for f in d["by_source"]}

    saida = {
        "mes": MESES[num],
        "mes_ano": f"{MESES[num]} de {ano}",
        "picks": str(s["total"]),
        "greens": str(s["greens"]),
        "reds": str(s["reds"]),
        "acerto": _pct(acerto),
        "lucro": _u(s["profit"]),
        "roi": _pct(s["roi"]),
        "stake": f"{_n(s['stake_total'], 0)}u",
        "ligas": str(s["leagues_count"]),
        "dias": str(len(d["by_day"])),
        # O rotulo vem do site com ponto do meio separando os itens, e ponto
        # do meio nao entra em texto nosso. Vira virgula.
        "stake_label": d.get("stake_label", "").replace(" · ", ", "),
    }

    if ligas:
        melhor, pior = ligas[0], ligas[-1]
        saida.update({
            "liga_melhor": melhor["league_name"],
            "liga_melhor_lucro": _u(melhor["profit"]),
            "liga_pior": pior["league_name"],
            "liga_pior_lucro": _u(pior["profit"]),
        })

    # Versao com inicial maiuscula pra quando o mes abre a frase. Sem isso o
    # titulo do slide sai "agosto de 2026 fechou em...", com minuscula.
    saida["Mes"] = saida["mes"].capitalize()
    saida["Mes_ano"] = saida["mes_ano"].capitalize()

    for chave, f in fontes.items():
        saida[f"{chave}_picks"] = str(f["total"])
        saida[f"{chave}_roi"] = _pct(f["roi"])
        saida[f"{chave}_lucro"] = _u(f["profit"])
        saida[f"{chave}_acerto"] = _pct(f["win_rate"])
        saida[f"{chave}_nome"] = NOMES_FONTE.get(chave, chave)

    return saida


def main() -> int:
    p = argparse.ArgumentParser(description="Numeros do fechamento mensal")
    p.add_argument("mes", help="AAAA-MM, ex: 2026-08")
    p.add_argument("--atualizar", action="store_true", help="ignora o cache")
    args = p.parse_args()

    try:
        n = numeros(args.mes, args.atualizar)
    except Exception as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    largura = max(len(k) for k in n)
    for chave, valor in n.items():
        print(f"  {chave:<{largura}}  {valor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
