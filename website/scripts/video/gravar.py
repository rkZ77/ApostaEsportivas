"""
Grava os vídeos curtos do site. Saída: um .webm 1080x1920 por cena.

    python gravar.py --listar
    python gravar.py --cena convite
    python gravar.py --todas --ver

A URL vem de --url ou da variável PICKIA_URL. Login da conta demo vem de
--usuario/--senha ou de PICKIA_DEMO_USER/PICKIA_DEMO_SENHA.

Nenhuma cena escreve no banco · ver o cabeçalho de `cenas.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from cenas import CENAS
from estudio import Estudio

AQUI = Path(__file__).parent


def main() -> int:
    p = argparse.ArgumentParser(
        description="Gravador de vídeos 9:16 do Pick IA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", default=os.getenv("PICKIA_URL", ""),
                   help="base do site (ex: https://noprod.seudominio.com)")
    p.add_argument("--cena", action="append", default=[],
                   help="nome da cena, pode repetir")
    p.add_argument("--todas", action="store_true", help="grava todas as cenas")
    p.add_argument("--listar", action="store_true", help="lista as cenas e sai")
    p.add_argument("--saida", default=str(AQUI / "saida"), help="pasta de saída")
    p.add_argument("--voz", default=str(AQUI / "voz"),
                   help="pasta da narração gerada por narracao.py")
    p.add_argument("--usuario", default=os.getenv("PICKIA_DEMO_USER", ""),
                   help="email ou usuário da conta demo VIP")
    p.add_argument("--senha", default=os.getenv("PICKIA_DEMO_SENHA", ""))
    p.add_argument("--ver", action="store_true",
                   help="abre o navegador visível (bom pra depurar cena)")
    p.add_argument("--chat-fake", action="store_true",
                   help="usa resposta canned do agente em vez de chamar a IA")
    args = p.parse_args()

    if args.listar:
        print("cenas disponíveis:\n")
        for nome, (desc, _, precisa_login) in CENAS.items():
            selo = "  [login]" if precisa_login else ""
            print(f"  {nome:<14} {desc}{selo}")
        return 0

    if not args.url:
        print("erro: informe --url ou defina PICKIA_URL", file=sys.stderr)
        return 2

    escolhidas = list(CENAS) if args.todas else args.cena
    if not escolhidas:
        print("erro: use --cena <nome>, --todas ou --listar", file=sys.stderr)
        return 2

    desconhecidas = [c for c in escolhidas if c not in CENAS]
    if desconhecidas:
        print(f"erro: cena desconhecida: {', '.join(desconhecidas)}", file=sys.stderr)
        print(f"      disponíveis: {', '.join(CENAS)}", file=sys.stderr)
        return 2

    precisa_login = any(CENAS[c][2] for c in escolhidas)
    if precisa_login and not (args.usuario and args.senha):
        faltando = [c for c in escolhidas if CENAS[c][2]]
        print(f"erro: as cenas {', '.join(faltando)} exigem login.", file=sys.stderr)
        print("      passe --usuario e --senha da conta demo VIP,", file=sys.stderr)
        print("      ou defina PICKIA_DEMO_USER e PICKIA_DEMO_SENHA.", file=sys.stderr)
        return 2

    saida = Path(args.saida)
    ctx = {"chat_fake": args.chat_fake}
    falhas = []

    # A duração real de cada mp3 é o que define quanto a tela segura em cada
    # fala. Sem isso a gravação usa um tempo de leitura estimado e a narração
    # não vai encaixar · por isso o aviso é explícito.
    arquivo_tempos = Path(args.voz) / "tempos.json"
    tempos: dict[str, float] = {}
    if arquivo_tempos.exists():
        tempos = json.loads(arquivo_tempos.read_text(encoding="utf-8"))
        print(f"tempos de narração: {len(tempos)} falas de {arquivo_tempos}")
    else:
        print(f"[aviso] {arquivo_tempos} não existe · rode narracao.py antes,")
        print("        senão a tela usa tempo estimado e a voz não encaixa.")

    for nome in escolhidas:
        desc, funcao, com_login = CENAS[nome]
        print(f"\n[{nome}] {desc}")
        try:
            with Estudio(args.url, saida, nome,
                         headless=not args.ver, tempos=tempos) as e:
                if com_login and not e.logar(args.usuario, args.senha):
                    print(f"  [erro] login falhou · cena {nome} pulada")
                    falhas.append(nome)
                    continue
                funcao(e, ctx)
        except Exception:
            print(f"  [erro] cena {nome} quebrou:")
            traceback.print_exc()
            falhas.append(nome)

    print()
    if falhas:
        print(f"terminou com problema em: {', '.join(falhas)}")
        return 1
    print(f"pronto. arquivos em {saida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
