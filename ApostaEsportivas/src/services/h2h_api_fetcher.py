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

CUSTO DE COTA
-------------
1 requisição por par de times por execução. Os pipelines chamam
build_for_fixture() uma vez por fixture, e build_for_fixture() chama
get_h2h() uma vez --- logo 1 requisição por jogo analisado onde o banco
não tem H2H suficiente. Nenhum fixture de liga precisará disso: os confrontos
diretos na liga atual são raros, e o banco já tem pelo menos o histórico
recente de cada time. O custo real é em Copa/mata-mata, onde a amostra
do banco é curta por definição.

TRATAMENTO DE FALHA
-------------------
Nunca levanta. Falha de rede, timeout, cota zerada --- devolve lista vazia.
O chamador (context_gate.build_for_fixture) já trata lista vazia como
"rivalidade desconhecida", que é o comportamento antes desta funcionalidade.
Ausência de dado nunca vira evidência de calma.
"""
from __future__ import annotations

import os

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


def get_h2h(team_a: int, team_b: int,
            limit: int = H2H_LIMIT,
            before_date: str | None = None) -> list[dict]:
    """Confrontos diretos entre team_a e team_b via API-Football.

    `before_date` (YYYY-MM-DD): não retorna jogos desta data em diante.
    Mantém o mesmo contrato de MatchStatsService.get_h2h_matches() para
    evitar vazamento em backtest.

    Devolve lista no mesmo formato que get_h2h_matches(), incluindo os
    campos de estatística (cartões, escanteios, faltas) via chamada extra
    ao endpoint /fixtures/statistics --- 1 requisição por jogo retornado.
    """
    if not _API_KEY:
        return []

    params: dict = {
        "h2h": f"{team_a}-{team_b}",
        "last": limit,
        "status": "FT",
    }
    if before_date:
        params["to"] = before_date

    try:
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

        # Busca folha de estatísticas do jogo (cartões, escanteios, faltas)
        fx_id = fx.get("id")
        if fx_id:
            try:
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

    return matches
