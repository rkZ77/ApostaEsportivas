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
from futebol_agent.tools.pickia_db import (
    desempenho_da_ia, ligas_cobertas, meus_picks, picks_publicados,
)
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


#: Ferramentas que leem o BANCO DO SITE. As demais falam com a API-Football.
#:
#: A separacao importa na hora de ler o codigo: as de API respondem sobre
#: futebol, estas respondem sobre o Pick IA. Sem elas o agente sabia tudo de
#: jogo e nada de pick, que e' justamente o que a pessoa foi perguntar.
FERRAMENTAS_DO_SITE = frozenset({
    "get_picks_publicados", "get_desempenho_da_ia", "get_meus_picks",
    "get_ligas_cobertas",
})

TOOLS: list[dict] = [
    {
        "name": "get_picks_publicados",
        "description": (
            "Picks do Pick IA publicados num dia, VIP e gratuitos, com o "
            "resultado quando ja' resolvido. Use para 'que picks sairam hoje', "
            "'teve pick ontem', 'qual foi o pick de sexta'. Nao confunda com "
            "jogos: isto e' o que a IA ESCOLHEU, nao a agenda."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dia": {"type": "string",
                        "description": "YYYY-MM-DD. Omitido, usa hoje."},
            },
        },
    },
    {
        "name": "get_desempenho_da_ia",
        "description": (
            "Acerto, lucro em unidades e contagem de green/red dos picks ja' "
            "resolvidos. Use para 'como a IA foi este mes', 'qual o acerto', "
            "'quanto lucrou em julho'. So' conta pick com resultado fechado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mes": {"type": "string",
                        "description": "YYYY-MM. Omitido, historico inteiro."},
                "tipo": {"type": "string", "enum": ["vip", "free"],
                         "description": "Omitido, devolve os dois."},
            },
        },
    },
    {
        "name": "get_meus_picks",
        "description": (
            "Os picks que ESTE usuario seguiu, com resultado. Use para 'quais "
            "picks eu segui', 'como estou indo', 'tenho pick em aberto'. O "
            "usuario e' sempre o da sessao."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "apenas_pendentes": {
                    "type": "boolean",
                    "description": "true devolve so' os que ainda nao resolveram.",
                },
            },
        },
    },
    {
        "name": "get_ligas_cobertas",
        "description": (
            "Ligas que a IA analisa hoje, e quais estao no banco so' como "
            "historico. Use para 'voces cobrem a Premier League', 'que "
            "campeonatos entram'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
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


async def _execute_tool(tool_name: str, tool_input: dict,
                        contexto: dict | None = None) -> Any:
    """Executa uma ferramenta. `contexto` traz quem esta perguntando.

    O `user_id` e o `plano` vem do TOKEN, em chat.py, e atravessam ate' aqui
    por parametro -- nunca pelo texto da conversa. E' o que faz "me mostre os
    picks do usuario 42" continuar devolvendo os do proprio.

    As de banco sao sincronas (psycopg2 bloqueia), entao vao pro threadpool:
    rodar no event loop com WEB_CONCURRENCY=1 seguraria o processo inteiro.
    """
    ctx = contexto or {}

    if tool_name in FERRAMENTAS_DO_SITE:
        plano = ctx.get("plano")
        if tool_name == "get_picks_publicados":
            return await asyncio.to_thread(
                picks_publicados, tool_input.get("dia"), plano)
        if tool_name == "get_desempenho_da_ia":
            return await asyncio.to_thread(
                desempenho_da_ia, tool_input.get("mes"), tool_input.get("tipo"))
        if tool_name == "get_meus_picks":
            return await asyncio.to_thread(
                meus_picks, ctx.get("user_id"),
                bool(tool_input.get("apenas_pendentes")), plano)
        if tool_name == "get_ligas_cobertas":
            return await asyncio.to_thread(ligas_cobertas)

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


async def run_agent(user_message: str, history: list[dict],
                    contexto: dict | None = None) -> tuple[str, list[dict]]:
    """`contexto`: {"user_id": int, "plano": str} de quem esta perguntando.

    Opcional pra nao quebrar quem ja' chama sem ele · sem contexto, as
    ferramentas pessoais respondem que nao ha sessao em vez de vazar dado de
    outra conta.
    """
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
                *[_execute_tool(tc.name, tc.input, contexto) for tc in tool_calls],
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
