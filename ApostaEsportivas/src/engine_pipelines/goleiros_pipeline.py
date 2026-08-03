"""Picks de DEFESAS DE GOLEIRO via motor deterministico (goalkeeper_model).

E' PROP DE JOGADOR, NAO OVER/UNDER DE TIME
------------------------------------------
Achado com coleta real (Bet365 e Betano, 2026-08-01): o mercado bet_id 267
"Goalkeeper Saves" vem com value_name no formato "<goleiro> - <N>" --
"Everson - 1", "Leo Jardim - 3". Significa "N ou mais defesas DESSE goleiro".
Nao existe linha de time nesse mercado. Por isso este pipeline grava
player_id/player_name em picks_goleiros, e nao um Over/Under de equipe.

"N ou mais" e' P(X >= N), que no goalkeeper_model.prob_over (definido como
P(X > line)) vira prob_over(N - 0.5). Passar N direto contaria uma defesa a
menos e superestimaria o pick.

DE QUE DADO ELE DEPENDE
-----------------------
O sinal forte do modelo e' o volume ofensivo do ADVERSARIO (correlacao 0.88
entre defesas e chutes no alvo sofridos), e esse numero ja existe em
match_statistics. O historico pessoal do goleiro e' opcional -- entra como
segundo sinal quando disponivel, via player_match_stats.saves.

O que NAO e' opcional e' saber por qual time o goleiro joga: sem isso nao da'
pra escolher de qual adversario pegar a media de chutes no alvo, e usar o
lado errado inverte a previsao. Esse vinculo vem de player_match_stats
(posicao G). Enquanto essa tabela estiver vazia o pipeline avisa e nao grava
nada -- e' silencio proposital, nao bug: rodar `python main.py player_stats`
algumas vezes forma o historico.

FREQUENCIA: defesas apareceram em 0.86% das atuacoes medidas, contra 62% das
faltas. Este pipeline naturalmente gera pick em poucos dias -- nao e' sinal de
que esta quebrado.
"""
import json
import re
import unicodedata

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR, data_br
from services.match_stats_service import MatchStatsService
from services.pick_engine import competition_profile as cp
from services.odds_service import OddsService
from services.pick_engine.goalkeeper_model import (
    MIN_OPPONENT_SAMPLE,
    analyze_saves_market,
)
from services.pick_engine.staking import calculate_stake
from services.pick_engine.ai_review import review_gate
from engine_pipelines.decision_log import log_decision

ODD_MIN = 1.35
ODD_MAX = 2.00

# Margem minima pra gravar. Mais exigente que faltas (0.04) porque aqui a
# amostra por goleiro e' pequena e a distribuicao e' superdispersa: erro de
# estimativa da media custa mais caro.
EDGE_MIN = 0.06

NOMES_MERCADO = ("goalkeeper saves", "saves", "player saves")

# "Everson - 1" / "Jandrei Chitolina - 2". O numero e' sempre o ultimo campo.
_VALOR_RE = re.compile(r"^(?P<nome>.+?)\s*-\s*(?P<n>\d+)$")


def _parse_valor(value_name: str) -> tuple[str, int] | None:
    """('Everson', 1) a partir de 'Everson - 1', ou None se nao bater.

    Nunca adivinha: formato diferente do esperado devolve None e o candidato
    e' descartado, em vez de virar um pick com linha errada.
    """
    m = _VALOR_RE.match((value_name or "").strip())
    if not m:
        return None
    nome = m.group("nome").strip()
    if not nome:
        return None
    return nome, int(m.group("n"))


def _normalizar_nome(nome: str) -> str:
    """Chave de comparacao de nome de jogador, sem acento e sem caixa.

    A casa de aposta escreve "Joao Ricardo" e a API-Football grava "Joao
    Ricardo" com til -- comparar cru descartava o goleiro como desconhecido.
    Achado na validacao com dado real (fixture 1546848, Fortaleza).
    """
    sem_acento = unicodedata.normalize("NFKD", nome or "")
    sem_acento = "".join(ch for ch in sem_acento if not unicodedata.combining(ch))
    return " ".join(sem_acento.lower().split())


def _goleiros_conhecidos(cur) -> dict:
    """{nome_normalizado: {player_id, team_id, saves_avg, jogos}} dos goleiros.

    NAO exige saves IS NOT NULL: o que este mapa resolve, e que e'
    obrigatorio, e' o vinculo goleiro->time (sem ele nao da' pra saber de qual
    adversario pegar o volume ofensivo). A media de defesas e' opcional no
    modelo -- entra como segundo sinal quando existe. Exigir saves aqui
    reduzia 112 goleiros conhecidos pra 49, descartando por falta de um dado
    que o modelo nem precisa.

    A media, quando existe, so' conta atuacao com minutos: goleiro reserva que
    nao entrou apareceria com 0 e afundaria o numero.
    """
    cur.execute("""
        SELECT player_id,
               MAX(player_name)                                          AS player_name,
               MAX(team_id)                                              AS team_id,
               MAX(team_name)                                            AS team_name,
               AVG(saves) FILTER (WHERE saves IS NOT NULL
                                    AND COALESCE(minutes, 0) > 0)::numeric(10,3) AS saves_avg,
               COUNT(*)   FILTER (WHERE saves IS NOT NULL
                                    AND COALESCE(minutes, 0) > 0)        AS jogos_com_defesa
        FROM player_match_stats
        WHERE position = 'G'
        GROUP BY player_id
    """)
    out = {}
    for r in cur.fetchall():
        nome = _normalizar_nome(r[1])
        if not nome:
            continue
        out[nome] = {
            "player_id": r[0], "player_name": r[1],
            "team_id": r[2], "team_name": r[3],
            "saves_avg": float(r[4]) if r[4] is not None else None,
            "jogos": int(r[5] or 0),
        }
    return out


def _historico(match_stats: MatchStatsService, fixture: dict, team_id: int) -> list:
    """Historico do time, respeitando o perfil da competicao.

    Mesma correcao do pipeline de faltas: em jogo de copa, filtrar so' pela
    liga do fixture devolvia 1 jogo de historico -- abaixo do minimo de 5 que
    o modelo exige, entao nenhum candidato passava.
    """
    since = match_stats.get_structural_change_date(team_id)
    if cp.uses_all_competitions_history(fixture["league_id"]):
        return match_stats.get_last_n_all_competitions(team_id, since_date=since)
    return match_stats.get_all_matches_full(
        team_id, fixture["season"], fixture["league_id"], since_date=since)


def _media_chutes_no_alvo(historico: list, team_id: int) -> tuple[float | None, int]:
    """Chutes no alvo que o time PRODUZ por jogo (o que o goleiro adversario
    vai ter que defender). Escolhe o lado certo jogo a jogo."""
    valores = []
    for jogo in historico:
        if jogo.get("home_team_id") == team_id:
            v = jogo.get("home_shots_on")
        elif jogo.get("away_team_id") == team_id:
            v = jogo.get("away_shots_on")
        else:
            continue
        if v is not None and v > 0:
            valores.append(float(v))
    if not valores:
        return None, 0
    return round(sum(valores) / len(valores), 3), len(valores)


def _fixtures_de_hoje(cur) -> list:
    cur.execute(f"""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE {data_br('f.match_datetime')} = {HOJE_BR}
          AND f.status IN ('NS', 'TBD')
        ORDER BY f.match_datetime
    """)
    return [
        {
            "fixture_id": r[0], "league_id": r[1], "season": r[2],
            "home_team_id": r[3], "away_team_id": r[4],
            "home_team": r[5], "away_team": r[6], "match_datetime": r[7],
        }
        for r in cur.fetchall()
    ]


def _avaliar_fixture(fixture: dict, goleiros: dict,
                     match_stats: MatchStatsService,
                     odds_service: OddsService) -> list:
    """Candidatos de defesas pra um jogo (pode haver um por goleiro)."""
    # RAW pelo mesmo motivo do pipeline de faltas: load_odds_structured
    # agrupa por line_value e descarta o que nao parear como Over/Under.
    # "Everson - 1" nao e' par de nada e sairia fora.
    structured = odds_service.load_odds_by_fixture(fixture["fixture_id"])
    if not structured:
        return []

    # Media de chutes no alvo de cada lado, calculada uma vez por jogo.
    hist_casa = _historico(match_stats, fixture, fixture["home_team_id"])
    hist_fora = _historico(match_stats, fixture, fixture["away_team_id"])
    chutes_casa, n_casa = _media_chutes_no_alvo(hist_casa, fixture["home_team_id"])
    chutes_fora, n_fora = _media_chutes_no_alvo(hist_fora, fixture["away_team_id"])

    candidatos = []
    for o in structured:
        nome_mercado = (o.get("market_name") or "").strip().lower()
        if nome_mercado not in NOMES_MERCADO:
            continue
        odd = float(o.get("odd") or 0)
        if odd < ODD_MIN or odd > ODD_MAX:
            continue

        parsed = _parse_valor(o.get("value_name"))
        if not parsed:
            continue
        nome_goleiro, n_defesas = parsed

        info = goleiros.get(_normalizar_nome(nome_goleiro))
        if not info:
            # Goleiro que ainda nao aparece em player_match_stats: sem o
            # vinculo com o time nao da' pra saber de qual adversario pegar
            # o volume ofensivo. Descarta em vez de chutar o lado.
            continue

        # De qual lado ele esta -> quem chuta contra ele.
        if info["team_id"] == fixture["home_team_id"]:
            adversario_chutes, adversario_n = chutes_fora, n_fora
        elif info["team_id"] == fixture["away_team_id"]:
            adversario_chutes, adversario_n = chutes_casa, n_casa
        else:
            continue

        analise = analyze_saves_market(
            opponent_shots_on_avg=adversario_chutes,
            keeper_saves_avg=info["saves_avg"],
            sample_size=adversario_n,
            odd=odd,
            # "N ou mais" = P(X >= N) = prob_over(N - 0.5). Ver docstring.
            line=n_defesas - 0.5,
        )
        if not analise:
            continue
        if analise.get("edge", 0) < EDGE_MIN:
            continue

        candidatos.append({
            **analise,
            "fixture": fixture,
            "goleiro": info,
            "n_defesas": n_defesas,
            "adversario_chutes": adversario_chutes,
            "adversario_n": adversario_n,
            "bookmaker": o.get("bookmaker_name") or o.get("bookmaker"),
            "market_id": o.get("market_id"),
            "market_name": o.get("market_name") or "Goalkeeper Saves",
        })

    return candidatos


def _explicar(c: dict) -> str:
    g = c["goleiro"]
    partes = [
        f"{g['player_name']} enfrenta um adversario que produz "
        f"{c['adversario_chutes']} chutes no alvo por jogo "
        f"({c['adversario_n']} jogos de historico)."
    ]
    if g.get("saves_avg"):
        partes.append(
            f"Ele faz {g['saves_avg']} defesas por jogo em {g['jogos']} atuacoes."
        )
    partes.append(f"Defesas esperadas: {c['expected_saves']}.")
    partes.append(
        f"Probabilidade de {c['n_defesas']} ou mais: {c['probability'] * 100:.1f}% "
        f"(odd justa {c['fair_odd']} contra {c['odd']} oferecida, "
        f"margem de {c['edge'] * 100:+.1f}%)."
    )
    return " ".join(partes)


def _salvar(cur, c: dict) -> None:
    f, g = c["fixture"], c["goleiro"]
    stake_pct, stake_units = calculate_stake(
        confidence=c["probability"], odd=c["odd"], ev=c["ev"], pick_type="free",
    )
    engine_debug = json.dumps({
        "modelo": "goalkeeper_model/binomial_negativa",
        "expected_saves": c["expected_saves"],
        "adversario_chutes_no_alvo": c["adversario_chutes"],
        "adversario_amostra": c["adversario_n"],
        "goleiro_saves_avg": g.get("saves_avg"),
        "goleiro_jogos": g.get("jogos"),
        "lift_vs_base": c.get("lift_vs_base"),
        "fair_odd": c["fair_odd"], "edge": c["edge"], "ev": c["ev"],
        "ai_review": c.get("ai_review"),
    }, default=str, ensure_ascii=False)

    cur.execute(f"""
        INSERT INTO picks_goleiros
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id, league_id,
             player_id, player_name, team_id, team_name,
             market, market_type, line, line_value, odd, bet_house, market_id,
             confidence, prob_real, edge, reasoning,
             stake_pct, stake_units, engine_debug)
        VALUES (%s, {HOJE_BR}, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, 'saves', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date, fixture_id, player_id) DO NOTHING
    """, (
        f["fixture_id"], f["home_team"], f["away_team"],
        f["home_team_id"], f["away_team_id"], f["league_id"],
        g["player_id"], g["player_name"], g["team_id"], g["team_name"],
        c["market_name"],
        f"{g['player_name']} · {c['n_defesas']} ou mais defesas", c["n_defesas"],
        c["odd"], c["bookmaker"], c["market_id"],
        c["probability"], c["probability"], c["edge"], _explicar(c),
        stake_pct, stake_units, engine_debug,
    ))


def run_goleiros_engine():
    conn = get_connection()
    cur = conn.cursor()

    goleiros = _goleiros_conhecidos(cur)
    if not goleiros:
        print("[GOLEIROS_ENGINE] player_match_stats nao tem nenhum goleiro ainda.")
        print("[GOLEIROS_ENGINE] Sem esse vinculo goleiro->time nao da' pra saber "
              "de qual adversario pegar o volume ofensivo, e chutar o lado "
              "inverteria a previsao. Rode `python main.py player_stats 50` "
              "algumas vezes pra formar o historico.")
        cur.close()
        conn.close()
        return

    fixtures = _fixtures_de_hoje(cur)
    if not fixtures:
        print("[GOLEIROS_ENGINE] Nenhum jogo de hoje com odds coletadas.")
        cur.close()
        conn.close()
        return

    print(f"[GOLEIROS_ENGINE] Avaliando {len(fixtures)} jogo(s) contra "
          f"{len(goleiros)} goleiro(s) conhecidos "
          f"(minimo {MIN_OPPONENT_SAMPLE} jogos do adversario)...")

    match_stats = MatchStatsService()
    odds_service = OddsService()

    candidatos = []
    for fixture in fixtures:
        try:
            candidatos.extend(_avaliar_fixture(fixture, goleiros, match_stats, odds_service))
        except Exception as e:
            print(f"[GOLEIROS_ENGINE] Erro no fixture {fixture['fixture_id']}: {e}")

    if not candidatos:
        print("[GOLEIROS_ENGINE] Nenhum candidato passou. Lembrete: defesas "
              "apareceram em 0.86% das atuacoes medidas -- dia sem pick e' o "
              "normal desse mercado, nao falha.")
        cur.close()
        conn.close()
        return

    candidatos.sort(key=lambda c: c["edge"], reverse=True)

    gate = review_gate("goleiros")
    salvos = 0
    for c in candidatos:
        log_decision("GOLEIROS_ENGINE", c["fixture"], [c], [c])
        aprovado = gate.apply([c], "goleiros", c["fixture"])
        if not aprovado:
            print(f"[GOLEIROS_ENGINE] {c['goleiro']['player_name']} vetado pela revisao de IA.")
            continue
        _salvar(cur, {**c, "ai_review": aprovado[0].get("ai_review")})
        salvos += 1
        print(f"[GOLEIROS_ENGINE] Salvo: {c['goleiro']['player_name']} "
              f"({c['goleiro']['team_name']}) · {c['n_defesas']}+ defesas @ {c['odd']} "
              f"(prob={c['probability'] * 100:.1f}%, margem={c['edge'] * 100:+.1f}%)")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[GOLEIROS_ENGINE] {salvos} pick(s) de defesas gravado(s).")


if __name__ == "__main__":
    run_goleiros_engine()
