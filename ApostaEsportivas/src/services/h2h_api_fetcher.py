"""Busca H2H direto na API-Football, sem persistir no banco.

POR QUE NAO PERSISTIR
---------------------
H2H é dado pontual de dois times específicos. Persistir exigiria tabela,
índice, limpeza periódica e backfill --- tudo isso pra um dado que a API
entrega em ~300ms por par. Lido no momento da análise, descartado depois.

ENDPOINT
--------
GET /fixtures/headtohead?h2h=TEAM_A-TEAM_B&last=N&status=FT

A API devolve os últimos N confrontos finalizados entre os dois times,
em QUALQUER competição --- exatamente o que o rivalry_model quer.

FORMATO DE RETORNO
------------------
Mesmo dicionário que MatchStatsService.get_h2h_matches() devolve, campo
a campo. O rivalry_model, o match_context_model e o context_gate.build_context
consomem esta lista diretamente, sem saber de onde veio.

CUSTO DE COTA --- CORRIGIDO EM 2026-09-05
-----------------------------------------
Este bloco dizia "1 requisição por par de times por execução". Estava errado
desde o dia em que a folha de estatística entrou na função: o H2H em si é 1
requisição, mas cada jogo devolvido custa mais uma a `/fixtures/statistics`.
Com H2H_LIMIT = 6, o custo real era 7, não 1 --- e o motor ao vivo, que chama
isto uma vez por partida analisada, gastava 21 requisições por rodada de 3
jogos SEM que nenhuma delas aparecesse no seu próprio teto
(`LiveEngineConfig.max_requisicoes` só conta o que passa por `LiveFeed`).

Duas coisas mudaram por causa disso, e nenhuma delas remove dado de quem
usava:

  1. `com_estatisticas=False` busca só o H2H (1 requisição). Quem só precisa
     saber QUAIS foram os confrontos --- `match_context_model.encontrar_jogo_
     de_ida`, que lê data, times e placar --- não tem uso nenhum pra folha.
     Quem decide é `context_gate`, pela regra do consumidor: sem baseline de
     cartões, `rivalry_model.rivalry_signal` devolve "desconhecido" antes de
     olhar a média do confronto, então a folha seria comprada pra ser jogada
     fora.
  2. Cache em processo, com TTL. H2H de dois times é um fato do passado ---
     não muda enquanto os dois não se enfrentarem de novo. O `live_watch` roda
     em laço e repagava o par inteiro a cada passada.

O custo continua sendo real em Copa/mata-mata, que é onde a amostra do banco
é curta por definição. O que não existe mais é pagá-lo em silêncio e duas
vezes pelo mesmo par.

TRATAMENTO DE FALHA
-------------------
Nunca levanta. Falha de rede, timeout, cota zerada --- devolve lista vazia.
O chamador (context_gate.build_for_fixture) já trata lista vazia como
"rivalidade desconhecida", que é o comportamento antes desta funcionalidade.
Ausência de dado nunca vira evidência de calma.
"""
from __future__ import annotations

import os
import time

import requests
from dotenv import find_dotenv, load_dotenv

from utils.stat_sheet import folha_publicada, ler_valor, somar

load_dotenv(find_dotenv())

_API_KEY = os.getenv("API_FOOTBALL_KEY")
_HEADERS = {"x-apisports-key": _API_KEY}
_H2H_URL = "https://v3.football.api-sports.io/fixtures/headtohead"
_STATS_URL = "https://v3.football.api-sports.io/fixtures/statistics"
_FINISHED = {"FT", "AET", "PEN"}

# Quantos confrontos buscar. 6 cobre ~3 temporadas de clássico nacional
# (2 por ano) com margem pra jogo suspenso/adiado. Abaixo de 4 o
# rivalry_model já marca como não confiável; acima de 8 mistura elencos
# de 4+ anos atrás que não descrevem mais a rivalidade atual.
H2H_LIMIT = 6

#: Quanto tempo uma resposta vale em memória. H2H é fato consumado: só muda
#: quando os dois times jogam de novo, o que não acontece dentro de uma
#: sessão. 6h é generoso e ainda garante que um processo longo (live_watch)
#: releia no dia seguinte.
_CACHE_TTL_SEGUNDOS = 6 * 3600

#: (par, data-limite, com-folha) -> (epoch, resultado). Em processo, de
#: propósito: persistir isto era o que a decisão de não criar tabela recusou,
#: e o problema que existia era repetição dentro da mesma execução.
_cache: dict[tuple, tuple] = {}

#: Requisições que ESTE módulo fez à API-Football. Existe porque o teto do
#: motor ao vivo não enxerga nada daqui, e um consumo invisível é um consumo
#: que ninguém corrige. Quem quiser medir uma rodada chama `zerar_contador()`
#: no início e lê `requisicoes_feitas()` no fim.
_requisicoes = 0


def zerar_contador() -> None:
    global _requisicoes
    _requisicoes = 0


def requisicoes_feitas() -> int:
    return _requisicoes


def get_h2h(team_a: int, team_b: int,
            limit: int = H2H_LIMIT,
            before_date: str | None = None,
            com_estatisticas: bool = True) -> list[dict]:
    """Confrontos diretos entre team_a e team_b via API-Football.

    `before_date` (YYYY-MM-DD): não retorna jogos desta data em diante.
    Mantém o mesmo contrato de MatchStatsService.get_h2h_matches() para
    evitar vazamento em backtest.

    `com_estatisticas`: quando True (padrão, o comportamento de sempre), busca
    a folha de cada jogo devolvido --- escanteios, cartões e faltas --- ao
    custo de 1 requisição POR JOGO. Quando False, devolve os mesmos jogos com
    esses campos em None e gasta 1 requisição no total. None aqui é ausência
    de leitura, não zero, exatamente como em toda a base: quem consome já
    trata `None` como "não sei" (ver `_media_cartoes` em rivalry_model).

    O resultado fica em cache por `_CACHE_TTL_SEGUNDOS`. Uma resposta sem
    folha NÃO satisfaz um pedido com folha; o contrário sim, porque a lista
    completa contém a magra.
    """
    if not _API_KEY:
        return []

    global _requisicoes
    agora = time.time()
    chave = (min(team_a, team_b), max(team_a, team_b), before_date, limit)
    guardado = _cache.get(chave)
    if guardado and agora - guardado[0] < _CACHE_TTL_SEGUNDOS:
        # Só serve se tiver pelo menos tanto quanto está sendo pedido.
        if guardado[1] or not com_estatisticas:
            return guardado[2]

    params: dict = {
        "h2h": f"{team_a}-{team_b}",
        "last": limit,
        "status": "FT",
    }
    if before_date:
        params["to"] = before_date

    try:
        _requisicoes += 1
        r = requests.get(_H2H_URL, headers=_HEADERS, params=params, timeout=15)
        r.raise_for_status()
        itens = r.json().get("response", [])
    except Exception as e:
        print(f"[H2H_API] Erro ao buscar H2H {team_a}-{team_b}: {e}")
        return []

    matches: list[dict] = []
    for item in itens:
        fx = item.get("fixture", {})
        status = fx.get("status", {}).get("short", "")
        if status not in _FINISHED:
            continue

        teams = item.get("teams", {})
        goals = item.get("goals", {})
        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")
        home_goals = goals.get("home")
        away_goals = goals.get("away")
        if home_goals is None or away_goals is None:
            continue

        match: dict = {
            "match_date":           fx.get("date", "")[:10],
            "league_id":            item.get("league", {}).get("id"),
            "home_team_id":         home_id,
            "away_team_id":         away_id,
            "home_goals":           home_goals,
            "away_goals":           away_goals,
            "total_goals":          home_goals + away_goals,
            # estatísticas preenchidas abaixo via /fixtures/statistics
            "home_corners":         None,
            "away_corners":         None,
            "total_corners":        None,
            "home_yellow_cards":    None,
            "away_yellow_cards":    None,
            "total_yellow_cards":   None,
            "home_red_cards":       None,
            "away_red_cards":       None,
            "total_red_cards":      None,
            "home_fouls":           None,
            "away_fouls":           None,
        }

        # Busca folha de estatísticas do jogo (cartões, escanteios, faltas).
        # 1 requisição por jogo: é o custo que `com_estatisticas=False`
        # dispensa para quem só precisa saber quais foram os confrontos.
        fx_id = fx.get("id")
        if fx_id and com_estatisticas:
            try:
                _requisicoes += 1
                rs = requests.get(
                    _STATS_URL, headers=_HEADERS,
                    params={"fixture": fx_id}, timeout=15,
                )
                rs.raise_for_status()
                stats_list = rs.json().get("response", [])
                if len(stats_list) >= 2:
                    if stats_list[0]["team"]["id"] == home_id:
                        home_s, away_s = stats_list[0]["statistics"], stats_list[1]["statistics"]
                    else:
                        home_s, away_s = stats_list[1]["statistics"], stats_list[0]["statistics"]

                    pub_home = folha_publicada(home_s)
                    pub_away = folha_publicada(away_s)

                    match["home_corners"]       = ler_valor(home_s, "Corner Kicks", pub_home)
                    match["away_corners"]       = ler_valor(away_s, "Corner Kicks", pub_away)
                    match["total_corners"]      = somar(match["home_corners"], match["away_corners"])
                    match["home_yellow_cards"]  = ler_valor(home_s, "Yellow Cards", pub_home)
                    match["away_yellow_cards"]  = ler_valor(away_s, "Yellow Cards", pub_away)
                    match["total_yellow_cards"] = somar(match["home_yellow_cards"], match["away_yellow_cards"])
                    match["home_red_cards"]     = ler_valor(home_s, "Red Cards", pub_home)
                    match["away_red_cards"]     = ler_valor(away_s, "Red Cards", pub_away)
                    match["total_red_cards"]    = somar(match["home_red_cards"], match["away_red_cards"])
                    match["home_fouls"]         = ler_valor(home_s, "Fouls", pub_home)
                    match["away_fouls"]         = ler_valor(away_s, "Fouls", pub_away)
            except Exception as e:
                print(f"[H2H_API] Erro ao buscar stats fixture {fx_id}: {e}")

        matches.append(match)

    # Guarda com a marca de o que foi comprado: uma lista sem folha não pode
    # servir depois a quem precisa dela.
    _cache[chave] = (agora, com_estatisticas, matches)
    return matches
