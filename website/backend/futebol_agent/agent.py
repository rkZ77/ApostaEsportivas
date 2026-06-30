import asyncio
import logging
import os
from typing import Any
import anthropic

from futebol_agent.config import CLAUDE_MODEL, MAX_TOKENS, MAX_HISTORY_MESSAGES
from futebol_agent.prompts import SYSTEM_PROMPT
from futebol_agent.tools.live_matches import get_live_matches, get_today_matches
from futebol_agent.tools.match_stats import (
    get_match_full_stats, find_and_get_stats, get_match_injuries,
    get_match_prediction, get_match_lineups, get_match_player_stats,
)
from futebol_agent.tools.odds import get_prematch_odds, get_live_match_odds
from futebol_agent.tools.standings import get_league_standings
from futebol_agent.tools.head_to_head import (
    get_h2h, get_team_recent_form, get_team_stats_season,
    get_team_historical_stats, get_team_historical_stats_any,
    get_team_halftime_record,
)
from futebol_agent.tools.formatters import (
    fmt_live_matches, fmt_today_matches, fmt_match_stats,
    fmt_odds, fmt_live_odds, fmt_standings, fmt_h2h, fmt_team_form,
    fmt_injuries, fmt_prediction, fmt_team_season_stats, fmt_lineups,
    fmt_team_historical_stats, fmt_player_stats, fmt_team_historical_stats_any,
    fmt_team_halftime_record,
)

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    return _client


TOOLS: list[dict] = [
    {
        "name": "get_live_matches",
        "description": "Lista todas as partidas de futebol ao vivo agora. Retorna fixture_id, times, placar, minuto e liga.",
        "input_schema": {"type": "object", "properties": {"only_featured": {"type": "boolean"}}, "required": []},
    },
    {
        "name": "get_today_matches",
        "description": "Lista os jogos programados para hoje, ao vivo ou não.",
        "input_schema": {"type": "object", "properties": {"league_id": {"type": "integer"}}, "required": []},
    },
    {
        "name": "get_match_stats",
        "description": "Retorna estatísticas detalhadas de uma partida pelo fixture_id: posse, chutes, escanteios, cartões, faltas e eventos.",
        "input_schema": {"type": "object", "properties": {"fixture_id": {"type": "integer"}}, "required": ["fixture_id"]},
    },
    {
        "name": "find_match_stats",
        "description": "Busca uma partida ao vivo pelo nome dos dois times e retorna estatísticas completas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team1": {"type": "string"},
                "team2": {"type": "string"},
            },
            "required": ["team1", "team2"],
        },
    },
    {
        "name": "get_prematch_odds",
        "description": "Retorna as odds pré-jogo de uma partida: 1x2, ambas marcam, over/under, etc.",
        "input_schema": {"type": "object", "properties": {"fixture_id": {"type": "integer"}}, "required": ["fixture_id"]},
    },
    {
        "name": "get_live_odds",
        "description": "Retorna as odds ao vivo de uma partida em andamento.",
        "input_schema": {"type": "object", "properties": {"fixture_id": {"type": "integer"}}, "required": ["fixture_id"]},
    },
    {
        "name": "get_standings",
        "description": "Retorna a classificação de uma liga. Ligas: brasileirao_a, brasileirao_b, copa_do_brasil, libertadores, sul_americana, copa_do_mundo.",
        "input_schema": {"type": "object", "properties": {"league_name": {"type": "string"}}, "required": ["league_name"]},
    },
    {
        "name": "get_h2h",
        "description": "Retorna o histórico de confrontos diretos (H2H) entre dois times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team1": {"type": "string"},
                "team2": {"type": "string"},
                "last":  {"type": "integer"},
            },
            "required": ["team1", "team2"],
        },
    },
    {
        "name": "get_team_form",
        "description": "Retorna a forma recente de um time (últimos jogos: V/E/D).",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {"type": "string"},
                "last":      {"type": "integer"},
            },
            "required": ["team_name"],
        },
    },
    {
        "name": "get_injuries",
        "description": "Retorna jogadores lesionados e suspensos de uma partida.",
        "input_schema": {"type": "object", "properties": {"fixture_id": {"type": "integer"}}, "required": ["fixture_id"]},
    },
    {
        "name": "get_prediction",
        "description": "Retorna a previsão da API para uma partida: vencedor sugerido, probabilidades e gols esperados.",
        "input_schema": {"type": "object", "properties": {"fixture_id": {"type": "integer"}}, "required": ["fixture_id"]},
    },
    {
        "name": "get_lineups",
        "description": "Retorna as escalações confirmadas de uma partida. Disponível ~1h antes do jogo.",
        "input_schema": {"type": "object", "properties": {"fixture_id": {"type": "integer"}}, "required": ["fixture_id"]},
    },
    {
        "name": "get_team_season_stats",
        "description": "Estatísticas do time na temporada atual: média de gols, clean sheets, forma recente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name":   {"type": "string"},
                "league_name": {"type": "string"},
            },
            "required": ["team_name", "league_name"],
        },
    },
    {
        "name": "get_team_historical_stats",
        "description": "Stats reais dos últimos N jogos do time na liga: escanteios, chutes, posse, gols, cartões e faltas com breakdown 1ºT/2ºT.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name":   {"type": "string"},
                "league_name": {"type": "string"},
                "last":        {"type": "integer"},
                "venue":       {"type": "string", "enum": ["home", "away", "all"]},
            },
            "required": ["team_name", "league_name"],
        },
    },
    {
        "name": "get_player_stats",
        "description": "Stats individuais de todos os jogadores de uma partida: rating, gols, assistências, chutes, passes-chave, desarmes.",
        "input_schema": {"type": "object", "properties": {"fixture_id": {"type": "integer"}}, "required": ["fixture_id"]},
    },
    {
        "name": "get_team_halftime_record",
        "description": "Conta quantos jogos um time venceu, empatou ou perdeu no intervalo (1º tempo) nos últimos N jogos, com o placar parcial jogo a jogo. Use para perguntas como 'quantos jogos perdeu o primeiro tempo' ou 'em quantos jogos estava ganhando no intervalo'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name":   {"type": "string"},
                "league_name": {"type": "string", "description": "Opcional. Se omitido, busca em qualquer competição."},
                "last":        {"type": "integer"},
            },
            "required": ["team_name"],
        },
    },
    {
        "name": "get_team_stats_any_league",
        "description": "Stats reais dos últimos N jogos do time em QUALQUER competição. Use como fallback quando não há dados suficientes na liga do jogo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {"type": "string"},
                "last":      {"type": "integer"},
                "venue":     {"type": "string", "enum": ["home", "away", "all"]},
            },
            "required": ["team_name"],
        },
    },
]


async def _execute_tool(tool_name: str, tool_input: dict) -> Any:
    if tool_name == "get_live_matches":
        return fmt_live_matches(await get_live_matches(tool_input.get("only_featured", True)))
    elif tool_name == "get_today_matches":
        return fmt_today_matches(await get_today_matches(tool_input.get("league_id")))
    elif tool_name == "get_match_stats":
        return fmt_match_stats(await get_match_full_stats(tool_input["fixture_id"]))
    elif tool_name == "find_match_stats":
        return fmt_match_stats(await find_and_get_stats(tool_input["team1"], tool_input["team2"]))
    elif tool_name == "get_prematch_odds":
        return fmt_odds(await get_prematch_odds(tool_input["fixture_id"]))
    elif tool_name == "get_live_odds":
        return fmt_live_odds(await get_live_match_odds(tool_input["fixture_id"]))
    elif tool_name == "get_standings":
        return fmt_standings(await get_league_standings(tool_input["league_name"]))
    elif tool_name == "get_h2h":
        return fmt_h2h(await get_h2h(tool_input["team1"], tool_input["team2"], tool_input.get("last", 8)))
    elif tool_name == "get_team_form":
        return fmt_team_form(await get_team_recent_form(tool_input["team_name"], tool_input.get("last", 5)))
    elif tool_name == "get_injuries":
        return fmt_injuries(await get_match_injuries(tool_input["fixture_id"]))
    elif tool_name == "get_lineups":
        return fmt_lineups(await get_match_lineups(tool_input["fixture_id"]))
    elif tool_name == "get_prediction":
        return fmt_prediction(await get_match_prediction(tool_input["fixture_id"]))
    elif tool_name == "get_team_season_stats":
        return fmt_team_season_stats(await get_team_stats_season(tool_input["team_name"], tool_input["league_name"]))
    elif tool_name == "get_player_stats":
        return fmt_player_stats(await get_match_player_stats(tool_input["fixture_id"]))
    elif tool_name == "get_team_historical_stats":
        return fmt_team_historical_stats(await get_team_historical_stats(
            tool_input["team_name"], tool_input["league_name"],
            tool_input.get("last", 8), tool_input.get("venue", "all"),
        ))
    elif tool_name == "get_team_halftime_record":
        return fmt_team_halftime_record(await get_team_halftime_record(
            tool_input["team_name"], tool_input.get("league_name"), tool_input.get("last", 10),
        ))
    elif tool_name == "get_team_stats_any_league":
        return fmt_team_historical_stats_any(await get_team_historical_stats_any(
            tool_input["team_name"], tool_input.get("last", 8), tool_input.get("venue", "all"),
        ))
    else:
        return f"Tool desconhecida: {tool_name}"


def _clean_history(messages: list[dict]) -> list[dict]:
    result = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str) and content:
            result.append(msg)
            continue
        if not isinstance(content, list):
            continue
        if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
            continue
        text_blocks = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                text_blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, dict) and block.get("type") == "text":
                text_blocks.append(block)
        if text_blocks:
            result.append({"role": msg["role"], "content": text_blocks})
    return result


async def run_agent(user_message: str, history: list[dict]) -> tuple[str, list[dict]]:
    history  = history[-MAX_HISTORY_MESSAGES:]
    messages = history + [{"role": "user", "content": user_message}]
    client   = get_client()

    while True:
        response = await asyncio.to_thread(
            client.messages.create,
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        usage = response.usage
        logger.debug(
            f"[TOKENS] input={usage.input_tokens} "
            f"cache_read={getattr(usage,'cache_read_input_tokens',0)} "
            f"output={usage.output_tokens}"
        )

        if response.stop_reason == "end_turn":
            text = next(
                (block.text for block in response.content if hasattr(block, "text")),
                "Sem resposta.",
            )
            updated_history = _clean_history(messages)[-MAX_HISTORY_MESSAGES:]
            return text, updated_history

        if response.stop_reason == "tool_use":
            tool_calls = [b for b in response.content if b.type == "tool_use"]
            results    = await asyncio.gather(
                *[_execute_tool(tc.name, tc.input) for tc in tool_calls],
                return_exceptions=True,
            )
            tool_results = []
            for tc, result in zip(tool_calls, results):
                content = f"ERRO: {result}" if isinstance(result, Exception) else str(result)
                tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": content})
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return "Não foi possível gerar uma resposta.", history
