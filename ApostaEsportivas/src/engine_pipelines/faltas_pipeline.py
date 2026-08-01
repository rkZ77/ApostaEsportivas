"""Picks de FALTAS via motor deterministico (services/pick_engine/fouls_model).

Por que este pipeline nao usa analyze_fixture_markets() como os outros
-----------------------------------------------------------------------
O caminho generico do motor (vip/dica/multipla/alavancagem) calcula taxa
historica por mercado e ranqueia entre familias. Faltas nao cabe ali: o
fouls_model nao e' parametrico, ele estima a MEDIA condicional (times +
arbitro) e le a probabilidade de uma tabela empirica medida contra 946 jogos.
Passar isso pelo ranking generico jogaria fora justamente o que foi medido.

Ver a docstring de fouls_model.py -- especialmente o aviso de nao trocar a
tabela de faixas por um numero de correlacao.

LIMITE CONHECIDO: so' a linha Over 22.5 do TOTAL do jogo. E' a unica com faixa
medida no backtest, e a relacao nao e' parametrica, entao nao da' pra
interpolar pra 24.5 ou 20.5 -- cada linha nova exige refazer a tabela. As
odds coletadas de verdade (Bet365 e Betano, 2026-08-01) vem em "Fouls. Total"
com over/under legitimo e caem na faixa 1.35-2.00.
"""
import json

from utils.db_utils import get_connection
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.referee_stats_service import RefereeStatsService
from services.pick_engine.fouls_model import (
    MIN_JOGOS_ARBITRO,
    MIN_JOGOS_TIME,
    analyze_fouls_market,
)
from services.pick_engine.staking import calculate_stake
from services.pick_engine.ai_review import review_gate
from engine_pipelines.decision_log import log_decision

# Mesma faixa de odd dos outros pipelines: fora dela o pick nao interessa
# comercialmente (odd baixa demais nao paga, alta demais e' loteria).
ODD_MIN = 1.35
ODD_MAX = 2.00

# Linha unica suportada pelo modelo (ver docstring).
LINHA = 22.5

# Edge minimo pra gravar. Abaixo disso a margem nao cobre o erro do proprio
# modelo -- a faixa mais forte da tabela empirica (73.4%) foi medida em 301
# jogos, o que ja carrega incerteza de alguns pontos percentuais.
EDGE_MIN = 0.04

# Nomes do mercado de faltas TOTAL do jogo, como a API-Football entrega.
# So' o total: "Fouls. Home Total"/"Away Total" sao por time e o modelo mede
# o total do jogo (a tabela de faixas soma os dois lados).
NOMES_MERCADO_TOTAL = ("fouls. total", "total fouls", "fouls")


def _media_faltas(historico: list, team_id: int) -> tuple[float | None, int]:
    """Faltas por jogo que o time comete, no historico dele.

    O historico traz a linha do jogo inteiro (home_fouls e away_fouls), entao
    precisa escolher o lado certo jogo a jogo -- o time joga em casa e fora.
    Jogo sem a coluna preenchida e' descartado em vez de virar zero: zero
    falta nao existe e puxaria a media pra baixo.
    """
    valores = []
    for jogo in historico:
        if jogo.get("home_team_id") == team_id:
            v = jogo.get("home_fouls")
        elif jogo.get("away_team_id") == team_id:
            v = jogo.get("away_fouls")
        else:
            continue
        if v is not None and v > 0:
            valores.append(float(v))
    if not valores:
        return None, 0
    return round(sum(valores) / len(valores), 3), len(valores)


def _odd_over_faltas(structured_odds: list) -> dict | None:
    """Melhor odd de Over 22.5 no mercado de faltas totais, ou None.

    Casa a linha por valor numerico (nao por texto) porque o mesmo mercado
    aparece como "Over 22.5" na Bet365 e pode vir com formatacao diferente em
    outra casa.
    """
    melhor = None
    for o in structured_odds:
        nome = (o.get("market_name") or "").strip().lower()
        if nome not in NOMES_MERCADO_TOTAL:
            continue
        valor = (o.get("value_name") or "").strip().lower()
        if not valor.startswith("over"):
            continue
        try:
            linha = float(str(o.get("line_value") or "").replace(",", "."))
        except (TypeError, ValueError):
            continue
        if abs(linha - LINHA) > 0.01:
            continue
        odd = float(o.get("odd") or 0)
        if odd < ODD_MIN or odd > ODD_MAX:
            continue
        if melhor is None or odd > melhor["odd"]:
            melhor = {
                "odd": odd,
                "bookmaker": o.get("bookmaker_name") or o.get("bookmaker"),
                "market_id": o.get("market_id"),
                "market_name": o.get("market_name"),
            }
    return melhor


def _fixtures_de_hoje(cur) -> list:
    """Jogos de hoje que ja tem odds coletadas.

    Mesmo recorte de data dos outros pipelines (`match_datetime::date =
    CURRENT_DATE`) -- se divergir daqui, o coletor de odds (que usa o mesmo
    predicado) nao tera' baixado odd pro jogo.
    """
    cur.execute("""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, f.referee
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE f.match_datetime::date = CURRENT_DATE
          AND f.status IN ('NS', 'TBD')
        ORDER BY f.match_datetime
    """)
    return [
        {
            "fixture_id": r[0], "league_id": r[1], "season": r[2],
            "home_team_id": r[3], "away_team_id": r[4],
            "home_team": r[5], "away_team": r[6],
            "match_datetime": r[7], "referee": r[8],
        }
        for r in cur.fetchall()
    ]


def _avaliar_fixture(fixture: dict, match_stats: MatchStatsService,
                     odds_service: OddsService,
                     referee_service: RefereeStatsService) -> dict | None:
    """Candidato de faltas pra um jogo, ou None se nao der pra avaliar."""
    structured = odds_service.load_odds_structured(fixture["fixture_id"])
    if not structured:
        return None

    melhor_odd = _odd_over_faltas(structured)
    if not melhor_odd:
        return None

    hist_casa = match_stats.get_all_matches_full(
        fixture["home_team_id"], fixture["season"], fixture["league_id"])
    hist_fora = match_stats.get_all_matches_full(
        fixture["away_team_id"], fixture["season"], fixture["league_id"])

    media_casa, n_casa = _media_faltas(hist_casa, fixture["home_team_id"])
    media_fora, n_fora = _media_faltas(hist_fora, fixture["away_team_id"])

    arbitro = referee_service.get_stats(fixture.get("referee"), fixture["season"])
    media_arbitro = float(arbitro["avg_fouls"]) if arbitro and arbitro.get("avg_fouls") else None
    n_arbitro = int(arbitro["games"]) if arbitro and arbitro.get("games") else None

    analise = analyze_fouls_market(
        media_casa=media_casa, media_fora=media_fora,
        media_arbitro=media_arbitro,
        n_casa=n_casa, n_fora=n_fora, n_arbitro=n_arbitro,
        odd=melhor_odd["odd"],
    )
    if not analise:
        return None
    if analise.get("edge", 0) < EDGE_MIN:
        return None

    return {
        **analise,
        "fixture": fixture,
        "bookmaker": melhor_odd["bookmaker"],
        "market_id": melhor_odd["market_id"],
        "market_name": melhor_odd["market_name"] or "Fouls. Total",
        "n_casa": n_casa, "n_fora": n_fora,
        "media_casa": media_casa, "media_fora": media_fora,
        "media_arbitro": media_arbitro, "n_arbitro": n_arbitro,
    }


def _explicar(c: dict) -> str:
    partes = [
        f"Faltas esperadas no jogo: {c['expected_fouls']} "
        f"({c['fixture']['home_team']} {c['media_casa']} + "
        f"{c['fixture']['away_team']} {c['media_fora']} por jogo)."
    ]
    if c.get("usou_arbitro"):
        partes.append(
            f"O arbitro marca {c['media_arbitro']} faltas por jogo em "
            f"{c['n_arbitro']} jogos apitados."
        )
    partes.append(
        f"Nessa faixa de previsao, Over {LINHA} bateu em "
        f"{c['probability'] * 100:.1f}% dos {c['faixa_amostra']} jogos medidos."
    )
    partes.append(
        f"Odd justa {c['fair_odd']} contra {c['odd']} oferecida "
        f"(margem de {c['edge'] * 100:+.1f}%)."
    )
    return " ".join(partes)


def _salvar(cur, c: dict) -> None:
    f = c["fixture"]
    # confidence aqui e' a propria probabilidade empirica: diferente dos
    # outros pipelines, nao ha score composto pra derivar: a tabela de faixas
    # JA E' a medida de confianca, medida em jogo real.
    stake_pct, stake_units = calculate_stake(
        confidence=c["probability"], odd=c["odd"], ev=c["ev"], pick_type="free",
    )
    engine_debug = json.dumps({
        "modelo": "fouls_model/empirico_condicional",
        "expected_fouls": c["expected_fouls"],
        "faixa_amostra": c["faixa_amostra"],
        "usou_arbitro": c["usou_arbitro"],
        "media_casa": c["media_casa"], "n_casa": c["n_casa"],
        "media_fora": c["media_fora"], "n_fora": c["n_fora"],
        "media_arbitro": c["media_arbitro"], "n_arbitro": c["n_arbitro"],
        "fair_odd": c["fair_odd"], "edge": c["edge"], "ev": c["ev"],
        "ai_review": c.get("ai_review"),
    }, default=str, ensure_ascii=False)

    cur.execute("""
        INSERT INTO picks_faltas
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id, league_id,
             market, market_type, line, odd, bet_house, market_id,
             confidence, prob_real, edge, reasoning,
             stake_pct, stake_units, engine_debug)
        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, 'fouls', %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date, fixture_id) DO NOTHING
    """, (
        f["fixture_id"], f["home_team"], f["away_team"],
        f["home_team_id"], f["away_team_id"], f["league_id"],
        c["market_name"], f"Over {LINHA}", c["odd"], c["bookmaker"], c["market_id"],
        c["probability"], c["probability"], c["edge"], _explicar(c),
        stake_pct, stake_units, engine_debug,
    ))


def run_faltas_engine():
    conn = get_connection()
    cur = conn.cursor()

    fixtures = _fixtures_de_hoje(cur)
    if not fixtures:
        print("[FALTAS_ENGINE] Nenhum jogo de hoje com odds coletadas.")
        cur.close()
        conn.close()
        return

    print(f"[FALTAS_ENGINE] Avaliando {len(fixtures)} jogo(s) "
          f"(linha unica Over {LINHA}, minimo {MIN_JOGOS_TIME} jogos por time "
          f"ou {MIN_JOGOS_ARBITRO} do arbitro)...")

    match_stats = MatchStatsService()
    odds_service = OddsService()
    referee_service = RefereeStatsService()

    candidatos = []
    for fixture in fixtures:
        try:
            c = _avaliar_fixture(fixture, match_stats, odds_service, referee_service)
        except Exception as e:
            print(f"[FALTAS_ENGINE] Erro no fixture {fixture['fixture_id']}: {e}")
            continue
        if c:
            candidatos.append(c)

    if not candidatos:
        print("[FALTAS_ENGINE] Nenhum candidato passou (odd fora da faixa, "
              "historico curto ou margem abaixo do minimo).")
        cur.close()
        conn.close()
        return

    # Maior margem primeiro: com linha unica, edge e' o unico criterio que
    # separa dois candidatos (probabilidade sai da mesma tabela de faixas).
    candidatos.sort(key=lambda c: c["edge"], reverse=True)

    gate = review_gate("faltas")
    salvos = 0
    for c in candidatos:
        log_decision("FALTAS_ENGINE", c["fixture"], [c], [c])
        aprovado = gate.apply([c], "faltas", c["fixture"])
        if not aprovado:
            print(f"[FALTAS_ENGINE] Fixture {c['fixture']['fixture_id']} vetado pela revisao de IA.")
            continue
        _salvar(cur, {**c, "ai_review": aprovado[0].get("ai_review")})
        salvos += 1
        print(f"[FALTAS_ENGINE] Salvo: {c['fixture']['home_team']} x {c['fixture']['away_team']} "
              f"· Over {LINHA} faltas @ {c['odd']} "
              f"(prob={c['probability'] * 100:.1f}%, margem={c['edge'] * 100:+.1f}%)")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[FALTAS_ENGINE] {salvos} pick(s) de faltas gravado(s).")


if __name__ == "__main__":
    run_faltas_engine()
