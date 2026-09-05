"""
checar_casas_na_api.py · a casa parou de cotar, ou o problema e' nosso?

SOMENTE LEITURA. Nao grava nada, nao mexe em coleta.

Uso:
  DB_ENV=prod python src/scripts/checar_casas_na_api.py
  DB_ENV=prod python src/scripts/checar_casas_na_api.py --liga 39

Custo: 1 requisicao da API por casa ativa (hoje, 4).

POR QUE ELE EXISTE
------------------
Em 05/09/2026 os quatro motores de pre-jogo passaram o dia sem gerar UM pick.
A causa nao estava em nenhum deles: Betano e Superbet pararam de ser servidas
pela API, sobrou a Bet365 sozinha, e o piso de consenso
(`pick_engine/config.min_bookmakers_count = 2`) reprovou TODA linha.

`resumo_das_casas()` no coletor passou a avisar quando isso acontece, mas ele
so' fala DEPOIS de uma coleta inteira, e so' sabe dizer "esta casa nao veio nos
jogos que eu pedi". Duas perguntas continuavam sem resposta:

    a casa sumiu pra TODO MUNDO ou so' pros jogos que eu pedi?
    ela sumiu HOJE ou faz dias?

Este script responde as duas de uma vez, e responde ANTES de gastar uma coleta.
O truque e' consultar `/odds` por LIGA e TEMPORADA em vez de por fixture: a
resposta traz a janela de datas que aquela casa cobre, e uma casa saudavel
cobre ate' os jogos de amanha.

O QUE A SAIDA SIGNIFICA
-----------------------
    ate' hoje ou depois -> a casa esta viva; se ela nao veio num jogo
                           especifico, e' cobertura daquele jogo
    parou ha' dias      -> a API deixou de servir essa casa pra nos, e nao
                           ha' nada a corrigir no nosso lado

Medido no dia em que este arquivo nasceu, liga 39 temporada 2026:

    Bet365    10 jogos, 3 paginas, 29/08 ate 06/09   viva
    Betano     9 jogos, 1 pagina,  29/08 ate 31/08   parada
    Superbet   9 jogos, 1 pagina,  29/08 ate 31/08   parada

Duas casas com a data congelada no MESMO dia nao e' cobertura de jogo: e' o
provedor. Nenhuma mudanca nossa consegue produzir um corte por casa e por data.
"""
import argparse
import os
import sys
from datetime import date, datetime

import requests
from dotenv import find_dotenv, load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

load_dotenv(find_dotenv())

_URL = "https://v3.football.api-sports.io/odds"
#: Liga usada quando nenhuma e' passada. Premier League tem a maior cobertura
#: de casa que existe -- se a casa nao aparece AQUI, ela nao aparece em lugar
#: nenhum, e o diagnostico fica sem ambiguidade.
_LIGA_PADRAO = 39

#: Mesmas casas de `collectors/odds_collector_service.BR_BOOKMAKERS`. Repetidas
#: aqui de proposito: importar o coletor traria a cadeia inteira dele, e este
#: script precisa rodar mesmo quando o resto nao roda.
_CASAS_PADRAO = ((8, "Bet365"), (11, "1xBet"), (32, "Betano"), (34, "Superbet"))


def _chave() -> str:
    k = (os.getenv("API_FOOTBALL_KEY") or "").strip().strip('"').strip("'")
    if not k:
        raise SystemExit("API_FOOTBALL_KEY nao definida no ambiente.")
    return k


def casas_ativas() -> list:
    """(id, nome) das casas que a coleta usa hoje, da tabela `bookmakers`."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT bookmaker_id, bookmaker_name FROM bookmakers "
                    "WHERE ativo ORDER BY bookmaker_id")
        linhas = cur.fetchall()
        cur.close()
        return linhas or _CASAS_PADRAO
    except Exception:
        # Mesmo fallback do coletor, e pelo mesmo motivo: "nenhuma casa pra
        # checar" e' o diagnostico OPOSTO do verdadeiro, e este script existe
        # justamente pra ser rodado quando alguma coisa ja' esta ruim -- entao
        # ele nao pode depender do banco estar de pe'. A conexao fica DENTRO do
        # try porque ela e' a parte que mais falha.
        # Ver collectors/odds_collector_service.casas_ativas.
        return list(_CASAS_PADRAO)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def janela_da_casa(chave: str, bookmaker_id: int, liga: int, season: int) -> dict:
    r = requests.get(_URL, headers={"x-apisports-key": chave},
                     params={"league": liga, "season": season,
                             "bookmaker": bookmaker_id}, timeout=20)
    r.raise_for_status()
    corpo = r.json() or {}
    # A API recusa com HTTP 200 -- cota, plano, chave. Ver a mesma leitura em
    # services/pick_engine_live/live_feed._get.
    recusa = corpo.get("errors")
    if isinstance(recusa, dict) and recusa:
        return {"erro": "; ".join(f"{k}: {v}" for k, v in recusa.items())}
    datas = sorted((it.get("fixture") or {}).get("date", "")[:10]
                   for it in (corpo.get("response") or []))
    datas = [d for d in datas if d]
    return {
        "jogos": corpo.get("results") or 0,
        "paginas": (corpo.get("paging") or {}).get("total") or 0,
        "primeira": datas[0] if datas else None,
        "ultima": datas[-1] if datas else None,
        "erro": None,
    }


def run(liga: int = _LIGA_PADRAO, season: int | None = None) -> None:
    season = season or date.today().year
    chave = _chave()
    hoje = date.today().isoformat()
    print(f"\nCobertura por casa na API · liga {liga}, temporada {season}")
    print(f"Hoje e' {hoje}. Casa viva cobre ate' hoje ou depois.\n")
    print(f"{'casa':>5}  {'nome':<12} {'jogos':>5} {'pag':>4}  "
          f"{'de':<10} {'ate':<10}  situacao")
    paradas = []
    for bm_id, nome in casas_ativas():
        try:
            j = janela_da_casa(chave, bm_id, liga, season)
        except Exception as e:
            print(f"{bm_id:>5}  {str(nome):<12} {'-':>5} {'-':>4}  "
                  f"{'-':<10} {'-':<10}  FALHA NA CONSULTA: {e}")
            continue
        if j.get("erro"):
            print(f"{bm_id:>5}  {str(nome):<12} {'-':>5} {'-':>4}  "
                  f"{'-':<10} {'-':<10}  API RECUSOU: {j['erro']}")
            continue
        ultima = j["ultima"]
        if not ultima:
            situacao = "SEM NENHUM JOGO"
            paradas.append((bm_id, nome, "nenhum jogo"))
        elif ultima >= hoje:
            situacao = "viva"
        else:
            dias = (datetime.fromisoformat(hoje) - datetime.fromisoformat(ultima)).days
            situacao = f"PARADA ha {dias} dia(s)"
            paradas.append((bm_id, nome, f"ultimo jogo {ultima}"))
        print(f"{bm_id:>5}  {str(nome):<12} {j['jogos']:>5} {j['paginas']:>4}  "
              f"{str(j['primeira'] or '-'):<10} {str(ultima or '-'):<10}  {situacao}")

    print()
    if not paradas:
        print("Todas as casas ativas estao sendo servidas pela API.")
        print("Se uma delas nao veio num jogo especifico, e' cobertura daquele")
        print("jogo -- nao ha' nada a corrigir na coleta.")
        return
    print("A API PAROU DE SERVIR:")
    for bm_id, nome, quando in paradas:
        print(f"  {bm_id} {nome} · {quando}")
    print()
    print("Isso nao e' defeito da coleta: nenhuma mudanca nossa produz um corte")
    print("por casa e por data. O efeito no motor e' o piso de consenso --")
    print("com menos de duas casas por linha, pick_engine/config")
    print("(min_bookmakers_count) reprova todo candidato, e os motores passam o")
    print("dia sem gerar nada sem que nenhum deles esteja errado.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="A casa parou de cotar, ou o problema e' nosso?")
    p.add_argument("--liga", type=int, default=_LIGA_PADRAO)
    p.add_argument("--season", type=int, default=None)
    a = p.parse_args()
    run(liga=a.liga, season=a.season)
