import os

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_KEY  = os.getenv("API_FOOTBALL_KEY", "")
API_FOOTBALL_HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY,
    "x-rapidapi-host": "v3.football.api-sports.io",
    "x-rapidapi-key":  API_FOOTBALL_KEY,
}
API_TIMEZONE = "America/Sao_Paulo"

LEAGUES = {
    "brasileirao_a":  71,
    "brasileirao_b":  72,
    "copa_do_brasil": 73,
    "libertadores":   13,
    "sul_americana":  11,
    "copa_do_mundo":   1,
}

LEAGUE_SEASONS: dict[int, int] = {
    71: 2026, 72: 2026, 73: 2026,
    13: 2026, 11: 2026, 1:  2026,
}

FEATURED_LEAGUE_IDS = set(LEAGUES.values())

def chat_model() -> str:
    """Modelo OpenAI do agente: CHAT_AGENT_MODEL, senao o modelo OpenAI do
    projeto (ver ia_openai.modelo). Desde 09/11/2026 a IA do site e' so' OpenAI."""
    import ia_openai
    return ia_openai.modelo("CHAT_AGENT_MODEL")


MAX_TOKENS   = int(os.getenv("CHAT_AGENT_MAX_TOKENS", "2000"))
MAX_HISTORY_MESSAGES = 6

ODDS_MIN = 1.40
ODDS_MAX = 2.20


def season_for(league_id: int) -> int:
    return LEAGUE_SEASONS.get(league_id, 2026)
