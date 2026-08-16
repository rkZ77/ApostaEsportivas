"""
Gera a narração das cenas com as vozes neurais do Edge.

    python narracao.py --todas
    python narracao.py --cena convite --voz pt-BR-FranciscaNeural
    python narracao.py --vozes

Por que edge-tts: as vozes neurais pt-BR são boas o bastante pra publicar e não
pedem conta nem chave de API. A única voz pt-BR instalada no Windows é a
"Microsoft Maria Desktop", robótica demais pra Instagram.

A ordem importa. Isto roda ANTES de `gravar.py`: a duração real de cada mp3 é
o que define quanto tempo a tela segura em cada fala. Mudou a frase, rode de
novo antes de regravar.

Saída:
    voz/<cena>/<chave>.mp3
    voz/tempos.json      chave -> duração em segundos
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

import ferramentas
from cenas import CENAS, NARRACAO, falas_da_cena

AQUI = Path(__file__).parent
# Thalita é o modelo multilíngue, mais novo que Antonio e Francisca, e soa
# menos sintético. Trocar com --voz; `--vozes` lista as opções.
VOZ_PADRAO = "pt-BR-ThalitaMultilingualNeural"

# Um pouco mais devagar que o padrão: o texto tem número e nome de time, e a
# leitura corrida come a dicção justamente nessas partes.
RITMO = "-6%"
TOM = "+0Hz"


async def _listar_vozes() -> None:
    vozes = await edge_tts.list_voices()
    br = sorted((v for v in vozes if v["Locale"].startswith("pt-")),
                key=lambda v: v["ShortName"])
    print("vozes em português:\n")
    for v in br:
        print(f"  {v['ShortName']:<34} {v['Gender']:<7} {v['Locale']}")


async def _gerar(chave: str, texto: str, destino: Path, voz: str) -> None:
    fala = edge_tts.Communicate(texto, voz, rate=RITMO, pitch=TOM)
    await fala.save(str(destino))


async def _gerar_cena(nome: str, voz: str, raiz: Path, forcar: bool) -> dict[str, float]:
    pasta = raiz / nome
    pasta.mkdir(parents=True, exist_ok=True)
    tempos: dict[str, float] = {}

    for chave in falas_da_cena(nome):
        texto = NARRACAO[chave][0]
        destino = pasta / f"{chave}.mp3"
        if forcar or not destino.exists():
            await _gerar(chave, texto, destino, voz)
            marca = "gerado"
        else:
            marca = "reusado"
        tempos[chave] = round(ferramentas.duracao(destino), 3)
        print(f"  {chave:<14} {tempos[chave]:>5.2f}s  {marca}  \"{texto[:52]}...\"")

    return tempos


async def principal(args) -> int:
    if args.vozes:
        await _listar_vozes()
        return 0

    escolhidas = list(CENAS) if args.todas else args.cena
    if not escolhidas:
        print("erro: use --cena <nome>, --todas ou --vozes", file=sys.stderr)
        return 2

    desconhecidas = [c for c in escolhidas if c not in CENAS]
    if desconhecidas:
        print(f"erro: cena desconhecida: {', '.join(desconhecidas)}", file=sys.stderr)
        return 2

    raiz = Path(args.saida)
    raiz.mkdir(parents=True, exist_ok=True)
    arquivo_tempos = raiz / "tempos.json"

    # Preserva o que já foi gerado pra outras cenas.
    tempos: dict[str, float] = {}
    if arquivo_tempos.exists():
        tempos = json.loads(arquivo_tempos.read_text(encoding="utf-8"))

    for nome in escolhidas:
        print(f"\n[{nome}] voz {args.voz}")
        tempos.update(await _gerar_cena(nome, args.voz, raiz, args.forcar))

    arquivo_tempos.write_text(
        json.dumps(tempos, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = sum(tempos[k] for c in escolhidas for k in falas_da_cena(c))
    print(f"\ntempos em {arquivo_tempos}")
    print(f"narração das cenas escolhidas: {total:.1f}s")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Gera a narração das cenas")
    p.add_argument("--cena", action="append", default=[])
    p.add_argument("--todas", action="store_true")
    p.add_argument("--vozes", action="store_true", help="lista as vozes e sai")
    p.add_argument("--voz", default=VOZ_PADRAO)
    p.add_argument("--saida", default=str(AQUI / "voz"))
    p.add_argument("--forcar", action="store_true",
                   help="regera mp3 que já existe")
    return asyncio.run(principal(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
