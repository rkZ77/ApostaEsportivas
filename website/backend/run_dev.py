"""Sobe o backend do site apontando pro banco de DEV.

POR QUE ISTO PRECISA EXISTIR
----------------------------
`database.get_connection()` resolve o host como `_env("DB_HOST",
"DB_HOST_PROD")` -- ele conhece a variavel do Railway e a de producao, e nao
conhece `DB_HOST_DEV`. Como `DB_HOST` nao esta no `.env`, rodar
`uvicorn main:app` na maquina local conecta em PRODUCAO sem avisar nada.

Isso e' anterior ao motor Live e vale pra qualquer teste local do site. Mas
quebra o Live de um jeito especialmente confuso: o motor grava `picks_live` no
banco de DEV, o site le' o de PROD (onde a tabela nem existe), a aba Ao Vivo
mostra "motor nao esta ativo neste ambiente" e nada no erro aponta pra causa.

O QUE ELE FAZ
-------------
O mesmo que `ApostaEsportivas/src/run_dev.py` faz pro motor: mapeia
`DB_*_DEV` -> `DB_*` ANTES de qualquer import que abra conexao, e liga o modo
de desenvolvimento. Nenhuma linha de `database.py` muda -- o codigo de
producao continua exatamente como esta'.

    python run_dev.py                 # porta 8000
    python run_dev.py --port 8010     # outra porta
    python run_dev.py --prod-db       # DEV com banco de PROD (leitura, cuidado)

USO
---
Rode DAQUI (website/backend), nao de uvicorn direto. Se aparecer
"Conectando ao banco" com o host de producao, foi uvicorn direto.
"""
import argparse
import os
import sys

from dotenv import find_dotenv, load_dotenv

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
_env_dir = os.path.dirname(_dotenv_path) if _dotenv_path else "."
load_dotenv(os.path.join(_env_dir, ".env.dev"), override=False)
load_dotenv(os.path.join(_env_dir, ".env.prod"), override=False)

_CHAVES = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASS", "DB_SSLMODE")


def _apontar_para_dev() -> str:
    """Mapeia DB_*_DEV -> DB_*. Devolve o host resolvido, pra imprimir."""
    faltando = [k for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASS")
                if not os.getenv(f"{k}_DEV")]
    if faltando:
        nomes = ", ".join(f"{k}_DEV" for k in faltando)
        raise SystemExit(
            f"[DEV] Faltam variaveis de banco de desenvolvimento: {nomes}.\n"
            f"      Elas vivem em .env.dev na raiz do repositorio.\n"
            f"      Sem elas este wrapper cairia no banco de PRODUCAO, que e'\n"
            f"      exatamente o que ele existe pra impedir."
        )
    for chave in _CHAVES:
        valor = os.getenv(f"{chave}_DEV")
        if valor:
            os.environ[chave] = valor
    # DATABASE_URL tem prioridade sobre DB_HOST em database.get_connection() --
    # se ela estiver setada (herdada do Railway, por exemplo), o mapeamento
    # acima seria ignorado em silencio.
    os.environ.pop("DATABASE_URL", None)
    return os.environ["DB_HOST"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backend do site em modo DEV")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true",
                        help="recarrega ao salvar (mais lento pra subir)")
    parser.add_argument("--prod-db", action="store_true",
                        help="NAO aponta pro banco de dev; use so' pra reproduzir "
                             "um bug que so' acontece com dado real")
    args = parser.parse_args()

    if args.prod_db:
        destino = os.getenv("DB_HOST") or os.getenv("DB_HOST_PROD") or "?"
        print(f"[DEV] ATENCAO: --prod-db ligado. Banco: {destino}")
        print("[DEV] O motor Live grava em DEV, entao a aba Ao Vivo vai aparecer vazia.")
    else:
        destino = _apontar_para_dev()

    # APP_ENV=development libera o disparo manual do motor Live pelo /admin
    # (routers/live_picks.rodar_motor recusa quando is_production()) e mantem
    # a varredura automatica de resultados desligada -- ela so' roda em
    # producao de proposito, pra nao gastar cota da API a partir da maquina
    # de quem esta desenvolvendo.
    os.environ["APP_ENV"] = "development"
    os.environ.setdefault("PICK_SWEEP", "off")

    print(f"[DEV] Banco:  {destino}")
    print(f"[DEV] APP_ENV: development  ·  varredura automatica: off")
    print(f"[DEV] http://{args.host}:{args.port}")
    print(f"[DEV] Frontend: cd ../frontend && npm run dev  (proxy ja aponta pra :8000)\n")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import uvicorn  # noqa: E402  (import depois de resolver o ambiente)

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
