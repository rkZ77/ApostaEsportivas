"""A contagem elegivel de cartoes da partida, buscada UMA vez e guardada.

## Por que existe, e por que e' preguicoso

`ai_result_checker_service` liquida Over/Under de cartao com
`home_yellow_cards` + `away_yellow_cards` da folha -- numeros que somam o
amarelo do tecnico e o do reserva que nem entrou. Um amarelo de area tecnica
num "Over 7.5" e' a diferenca entre GREEN e RED, e a casa nao paga pelo numero
da folha (ver services/cartoes_validos).

Corrigir isso exige `/fixtures/events` e `/fixtures/lineups`, que a folha nao
traz. Pagar essas duas requisicoes pra TODA partida encerrada triplicaria o
custo da varredura historica, e a esmagadora maioria dessas partidas nunca
sustenta um pick de cartao. Entao a validacao acontece onde ela muda dinheiro:
na hora de liquidar, so' pra partida que tem mercado de cartao pendente, e o
resultado fica gravado -- a segunda pergunta sobre a mesma partida nao custa
nada.

## O que fica gravado, e o que significa NULL

`cards_validation` guarda o veredito: `VALIDADO`, `INCERTO` ou `SEM_EVENTOS`.
NULL ali quer dizer "ninguem perguntou ainda", que e' diferente de "perguntei e
nao deu" -- sem essa distincao a partida sem cobertura seria reperguntada pra
sempre, uma requisicao por rodada de liquidacao.

Fora de `VALIDADO`, quem liquida NAO liquida: e' a invariante 1 de
services/settlement.py aplicada a cartao. Pick de cartao sem contagem confiavel
fica pendente, e quem o resolve e' a regra de anulacao por falta de estatistica
-- nao um palpite nosso.
"""
from __future__ import annotations

import os

import requests

from services import api_quota, cartoes_validos

BASE = "https://v3.football.api-sports.io"

SEM_EVENTOS = "SEM_EVENTOS"

#: Colunas que este modulo mantem em `match_statistics`. Ficam aqui, e nao
#: espalhadas nos SELECTs, porque quem le' (o liquidador) le' com `SELECT *`.
COLUNAS = (
    "valid_yellow_home", "valid_yellow_away",
    "valid_red_home", "valid_red_away",
    "cards_excluded", "cards_validation",
)


def _headers() -> dict | None:
    chave = os.getenv("API_FOOTBALL_KEY")
    return {"x-apisports-key": chave} if chave else None


def garantir_colunas(cur) -> None:
    """Auto-provisiona as colunas.

    Mesmo motivo do `_ensure_columns` do coletor: migracao em PROD nao roda
    sozinha depois do merge, e o liquidador nao pode quebrar com
    ProgrammingError por causa de uma coluna que ainda nao existe.
    """
    for coluna in ("valid_yellow_home", "valid_yellow_away",
                   "valid_red_home", "valid_red_away", "cards_excluded"):
        cur.execute(
            f"ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS {coluna} INTEGER;")
    cur.execute(
        "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS cards_validation TEXT;")


def _buscar(endpoint: str, fixture_id: int, headers: dict, origem: str) -> list:
    r = requests.get(f"{BASE}/{endpoint}", headers=headers,
                     params={"fixture": fixture_id}, timeout=15)
    api_quota.registrar(getattr(r, "headers", None), origem)
    r.raise_for_status()
    return r.json().get("response", []) or []


def validar_e_gravar(fixture_id: int, cur, home_id=None, away_id=None,
                     total_bruto=None) -> dict | None:
    """Busca evento e escalacao, classifica cada cartao e grava o resultado.

    Devolve o relatorio de `cartoes_validos.validar_cartoes`, ou `None` quando
    nao deu pra perguntar (sem chave de API, ou a API recusou). `None` NAO e'
    gravado: falha de rede nao pode virar "esta partida nao tem cobertura", que
    e' uma afirmacao permanente.
    """
    headers = _headers()
    if headers is None:
        return None

    try:
        eventos = _buscar("fixtures/events", fixture_id, headers, "liquidacao_cartoes")
        if not eventos:
            # Cobertura de evento inexistente pra esta partida. Grava o
            # veredito pra nao reperguntar toda rodada, e nao gasta a
            # requisicao de escalacao -- sem evento nao ha' o que classificar.
            cur.execute("UPDATE match_statistics SET cards_validation = %s "
                        "WHERE fixture_id = %s;", (SEM_EVENTOS, fixture_id))
            return cartoes_validos.validar_cartoes(None, None, home_id, away_id,
                                                   total_bruto)
        tem_cartao = any((e.get("type") or "").strip().lower() == "card"
                         for e in eventos)
        # Sem cartao nenhum a escalacao nao muda resposta nenhuma: a contagem
        # elegivel e' zero de qualquer jeito, e zero aqui e' medido, nao
        # suposto -- ha' cobertura de evento e nenhum cartao nela.
        escalacoes = (_buscar("fixtures/lineups", fixture_id, headers,
                              "liquidacao_cartoes") if tem_cartao else [])
    except requests.RequestException:
        return None

    relatorio = cartoes_validos.validar_cartoes(eventos, escalacoes, home_id,
                                                away_id, total_bruto)
    por_time = relatorio.get("por_time") or {}
    cur.execute("""
        UPDATE match_statistics
           SET valid_yellow_home = %s, valid_yellow_away = %s,
               valid_red_home = %s, valid_red_away = %s,
               cards_excluded = %s, cards_validation = %s
         WHERE fixture_id = %s;
    """, (por_time.get("yellow_home"), por_time.get("yellow_away"),
          por_time.get("red_home"), por_time.get("red_away"),
          relatorio.get("cartoes_excluidos"),
          relatorio.get("status_validacao"), fixture_id))
    return relatorio
