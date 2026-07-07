"""Modelo de Noticias (lesoes/suspensoes): sinal de desfalques ponderado
por titularidade recente, nao so volume cru. Fonte real: endpoint
/injuries e /fixtures/lineups da API-Football, ja usados de forma
Copa-especifica em world_cup_squad_service.py (classe nao tocada aqui) --
aqui viram funcoes genericas (team_id/league_id/season quaisquer),
reutilizaveis por clube e selecao.

Nao existe hoje nenhuma fonte real de "noticias" (transferencia, tecnico,
sentimento) -- fora de escopo ate existir dado real. O cruzamento de nome
entre /injuries e /fixtures/lineups pode falhar por grafia (acento,
abreviacao); nesse caso o jogador cai como "nao confirmado como titular
recente" em vez de quebrar -- sinal sempre rotulado como aproximacao."""
import os
import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"x-apisports-key": API_KEY}
BASE = "https://v3.football.api-sports.io"


def fetch_injuries(team_id: int, fixture_id: int = None, season: int = None,
                    league_id: int = None) -> list:
    """Retorna lesionados/suspensos do time. Usa fixture_id para precisao
    maxima; cai em nivel de temporada se nao fornecido. Formato:
    [{"name": "Player", "type": "Injured", "reason": "Hamstring"}, ...]"""
    try:
        if fixture_id:
            params = {"fixture": fixture_id, "team": team_id}
        else:
            params = {"team": team_id, "season": season, "league": league_id}

        r = requests.get(f"{BASE}/injuries", headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()

        result = []
        for item in r.json().get("response", []):
            player = item.get("player", {})
            name = player.get("name", "")
            if not name:
                continue
            result.append({
                "name": name,
                "type": item.get("type", ""),
                "reason": item.get("reason", "") or "",
            })
        return result

    except Exception as e:
        print(f"[NEWS_MODEL] Erro ao buscar lesionados/suspensos team {team_id}: {e}")
        return []


def fetch_recent_starters(team_id: int, last: int = 5) -> dict:
    """Conta quantas vezes cada nome apareceu no startXI dos ultimos `last`
    jogos do time. Retorna {"Nome Jogador": count}."""
    starters_count: dict = {}
    try:
        r = requests.get(f"{BASE}/fixtures", headers=HEADERS,
                          params={"team": team_id, "last": last}, timeout=15)
        r.raise_for_status()
        fixtures = r.json().get("response", [])

        for fx_item in fixtures:
            fx_id = fx_item["fixture"]["id"]
            try:
                lr = requests.get(f"{BASE}/fixtures/lineups", headers=HEADERS,
                                   params={"fixture": fx_id, "team": team_id}, timeout=15)
                lr.raise_for_status()
                lineups = lr.json().get("response", [])
                if not lineups:
                    continue
                for entry in lineups[0].get("startXI", []):
                    name = entry.get("player", {}).get("name", "")
                    if name:
                        starters_count[name] = starters_count.get(name, 0) + 1
            except Exception as e:
                print(f"[NEWS_MODEL] Erro ao buscar lineup do fixture {fx_id}: {e}")
                continue

    except Exception as e:
        print(f"[NEWS_MODEL] Erro ao buscar fixtures recentes team {team_id}: {e}")

    return starters_count


def injury_signal(injuries_home: list, starters_home: dict,
                   injuries_away: list, starters_away: dict) -> dict:
    """Cruza lesionados/suspensos com a contagem de titularidade recente.
    Separa titulares_desfalcados (apareceu >=1x no startXI recente) de
    outros_desfalcados (nao encontrado nas escalacoes recentes -- pode ser
    reserva OU falha de cruzamento de nome, por isso is_approximation).
    Sempre expoe as listas cruas, nada de numero oculto.

    Deduplica por nome -- sem fixture_id, /injuries devolve uma linha por
    jogo perdido na temporada (o mesmo jogador aparece varias vezes), o que
    infla a contagem se nao for filtrado aqui."""
    def _split(injuries, starters):
        seen = set()
        titulares, outros = [], []
        for inj in injuries:
            name = inj["name"]
            if name in seen:
                continue
            seen.add(name)
            entry = {**inj, "starts_recentes": starters.get(name, 0)}
            (titulares if starters.get(name, 0) > 0 else outros).append(entry)
        return titulares, outros

    tit_home, out_home = _split(injuries_home, starters_home)
    tit_away, out_away = _split(injuries_away, starters_away)

    return {
        "is_approximation": True,
        "home": {
            "titulares_desfalcados": tit_home,
            "outros_desfalcados": out_home,
        },
        "away": {
            "titulares_desfalcados": tit_away,
            "outros_desfalcados": out_away,
        },
    }


def news_score(signal: dict | None) -> float | None:
    """Reduz o sinal de desfalques a um score 0-1 (0.5=neutro) para uso no
    Score Final -- titular desfalcado pesa mais que reserva/nao-confirmado.
    Time desfalcado tende a jogar pior -> favorece o adversario, entao o
    score aqui e simetrico (nao aponta lado, so intensidade combinada;
    quem usa o score no ranking ja sabe pra qual candidato/mercado aplicar)."""
    if not signal:
        return None

    home_weight = (len(signal["home"]["titulares_desfalcados"]) * 0.08
                   + len(signal["home"]["outros_desfalcados"]) * 0.02)
    away_weight = (len(signal["away"]["titulares_desfalcados"]) * 0.08
                   + len(signal["away"]["outros_desfalcados"]) * 0.02)

    total = min(home_weight + away_weight, 0.5)
    return round(0.5 + total, 4)
