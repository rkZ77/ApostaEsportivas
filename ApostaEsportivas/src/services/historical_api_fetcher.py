import os
import requests
from dotenv import load_dotenv, find_dotenv

from utils.stat_sheet import folha_publicada, ler_valor, somar

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"x-apisports-key": API_KEY}
FIXTURES_URL  = "https://v3.football.api-sports.io/fixtures"
STATS_URL     = "https://v3.football.api-sports.io/fixtures/statistics"

FINISHED = {"FT", "AET", "PEN"}


class HistoricalApiFetcher:
    """
    Busca histórico recente de um time direto na API (qualquer competição).
    Usado como fallback quando não há jogos no banco · ex: início de Copa,
    amistosos de seleções, primeiro jogo de uma competição nova.
    """

    # --------------------------------------------------------
    # BUSCA ÚLTIMOS N JOGOS FINALIZADOS DO TIME (qualquer comp.)
    # Retorna lista no mesmo formato que match_stats_service.py
    # --------------------------------------------------------
    def get_recent_matches(self, team_id: int, n: int = 8) -> list[dict]:
        try:
            r = requests.get(
                FIXTURES_URL,
                headers=HEADERS,
                params={"team": team_id, "last": n},
                timeout=15,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"[HIST_API] Erro ao buscar fixtures do time {team_id}: {e}")
            return []

        matches = []
        for item in r.json().get("response", []):
            fixture = item["fixture"]
            status  = fixture["status"]["short"]

            if status not in FINISHED:
                continue

            teams  = item["teams"]
            goals  = item["goals"]
            league = item["league"]

            home_id   = teams["home"]["id"]
            away_id   = teams["away"]["id"]
            # Placar ausente derruba o jogo em vez de virar 0x0 (2026-08-27).
            # Este leitor nao passa por _save_stats -- ele alimenta o motor
            # direto -- entao o descarte precisa ser aqui: um 0x0 inventado no
            # meio do historico e' media errada sem nenhum rastro.
            home_goals = goals["home"]
            away_goals = goals["away"]
            if home_goals is None or away_goals is None:
                continue

            matches.append({
                "match_date":   fixture["date"][:10],
                "competition":  f"{league['name']} ({league['country']})",
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_goals":   home_goals,
                "away_goals":   away_goals,
                "total_goals":  home_goals + away_goals,
                # corners/cards/fouls precisam de chamada extra · ver get_recent_with_stats()
                "home_corners": None,
                "away_corners": None,
                "total_corners": None,
                "home_yellow_cards": None,
                "away_yellow_cards": None,
                "total_yellow_cards": None,
                "home_red_cards": None,
                "away_red_cards": None,
                "total_red_cards": None,
                "home_fouls": None,
                "away_fouls": None,
            })

        return matches

    # --------------------------------------------------------
    # VERSÃO COMPLETA: busca stats de cada jogo (corners, cards, fouls)
    # CUIDADO: faz 1 chamada de API por jogo · use só quando necessário
    # --------------------------------------------------------
    def get_recent_with_stats(self, team_id: int, n: int = 15) -> list[dict]:
        matches = self.get_recent_matches(team_id, n)
        if not matches:
            return []

        # Busca fixture_ids para depois pegar stats
        try:
            r = requests.get(
                FIXTURES_URL,
                headers=HEADERS,
                params={"team": team_id, "last": n},
                timeout=15,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"[HIST_API] Erro ao buscar fixture_ids para stats: {e}")
            return matches  # retorna sem stats se falhar

        fixture_ids = []
        for item in r.json().get("response", []):
            if item["fixture"]["status"]["short"] in FINISHED:
                fixture_ids.append(item["fixture"]["id"])

        for i, (fx_id, match) in enumerate(zip(fixture_ids, matches)):
            try:
                rs = requests.get(
                    STATS_URL,
                    headers=HEADERS,
                    params={"fixture": fx_id},
                    timeout=15,
                )
                rs.raise_for_status()
                stats_list = rs.json().get("response", [])

                if len(stats_list) < 2:
                    continue

                # Descobre qual é casa/fora
                if stats_list[0]["team"]["id"] == match["home_team_id"]:
                    home_s, away_s = stats_list[0]["statistics"], stats_list[1]["statistics"]
                else:
                    home_s, away_s = stats_list[1]["statistics"], stats_list[0]["statistics"]

                # Este leitor devolvia 0 em TODOS os casos de ausencia --
                # folha vazia, tipo fora da folha, valor null -- e alimentava
                # o motor com jogo inteiro zerado como se fosse contagem real.
                # E' o mesmo defeito que o coletor principal corrigiu em
                # 2026-07-25 e que aqui sobreviveu 13 meses. A regra unica
                # mora em utils/stat_sheet.
                pub_home = folha_publicada(home_s)
                pub_away = folha_publicada(away_s)

                def get_stat(stats, name, publicada):
                    return ler_valor(stats, name, publicada)

                match["home_corners"]       = get_stat(home_s, "Corner Kicks", pub_home)
                match["away_corners"]       = get_stat(away_s, "Corner Kicks", pub_away)
                match["total_corners"]      = somar(match["home_corners"], match["away_corners"])
                match["home_yellow_cards"]  = get_stat(home_s, "Yellow Cards", pub_home)
                match["away_yellow_cards"]  = get_stat(away_s, "Yellow Cards", pub_away)
                match["total_yellow_cards"] = somar(match["home_yellow_cards"], match["away_yellow_cards"])
                match["home_red_cards"]     = get_stat(home_s, "Red Cards", pub_home)
                match["away_red_cards"]     = get_stat(away_s, "Red Cards", pub_away)
                match["total_red_cards"]    = somar(match["home_red_cards"], match["away_red_cards"])
                match["home_fouls"]         = get_stat(home_s, "Fouls", pub_home)
                match["away_fouls"]         = get_stat(away_s, "Fouls", pub_away)

            except Exception as e:
                print(f"[HIST_API] Erro ao buscar stats do fixture {fx_id}: {e}")

        return matches
