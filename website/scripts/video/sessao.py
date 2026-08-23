"""
Monta `sessao.json` a partir do cookie do seu navegador normal.

    python sessao.py --url https://pickia-no-prod.up.railway.app --cookie COLE_AQUI

Por que isto existe: o Turnstile recusa o Chromium do Playwright mesmo com uma
pessoa digitando nele · a detecção é do navegador instrumentado, não da
interação. Então o login acontece no SEU Chrome/Edge, como sempre, e só a
sessão já autenticada é trazida pra cá. Nada de captcha é contornado: ele foi
resolvido por um humano num navegador de verdade.

Como pegar o valor:

  1. Abra o site no seu navegador e faça login normalmente.
  2. F12 → aba "Application" (ou "Aplicativo") → Storage → Cookies →
     escolha o domínio do site.
  3. Copie o valor do cookie `access_token`. É uma string longa com dois
     pontos, tipo `eyJhbGci...`.

O cookie é httpOnly, então ele NÃO aparece no console via `document.cookie` ·
tem que ser pelo painel de Cookies mesmo.

`sessao.json` é credencial. Está no .gitignore e é bom que continue.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

COOKIE = "access_token"


def main() -> int:
    p = argparse.ArgumentParser(description="Cria sessao.json a partir do cookie")
    p.add_argument("--url", required=True, help="base do site")
    p.add_argument("--cookie", required=True, help=f"valor do cookie {COOKIE}")
    p.add_argument("--saida", default=str(Path(__file__).parent / "sessao.json"))
    args = p.parse_args()

    dominio = urlparse(args.url).hostname
    if not dominio:
        print(f"erro: URL inválida: {args.url}", file=sys.stderr)
        return 2

    valor = args.cookie.strip().strip('"').strip("'")
    if valor.lower().startswith(f"{COOKIE}="):
        valor = valor[len(COOKIE) + 1:]
    if valor.count(".") < 2:
        print(f"erro: isso não parece um JWT (esperava dois pontos no valor).",
              file=sys.stderr)
        print(f"      copie o VALOR do cookie {COOKIE}, não o nome.", file=sys.stderr)
        return 2

    estado = {
        "cookies": [{
            "name": COOKIE,
            "value": valor,
            "domain": dominio,
            "path": "/",
            "expires": -1,          # cookie de sessão · vale enquanto o JWT valer
            "httpOnly": True,
            "secure": True,
            "sameSite": "Strict",
        }],
        "origins": [],
    }

    destino = Path(args.saida)
    destino.write_text(json.dumps(estado, indent=2), encoding="utf-8")
    print(f"sessão gravada em {destino}")
    print(f"domínio: {dominio}")
    print("\nteste agora:")
    print(f"  python gravar.py --url {args.url.rstrip('/')} --cena picks-de-hoje")
    print("\nse der 'sessão expirada', pegue o cookie de novo · e não faça login")
    print("em outro lugar no meio, que o backend só aceita uma sessão por usuário.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
