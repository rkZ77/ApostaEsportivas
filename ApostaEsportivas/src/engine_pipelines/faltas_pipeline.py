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

LINHAS: as que tem faixa medida em fouls_model.LINHAS_SUPORTADAS (hoje 22.5,
24.5, 25.5 e 26.5). A primeira coleta real de odds (Bet365 e Betano,
2026-08-02) mostrou que o mercado NAO oferece 22.5 -- "Fouls. Total" sai em
24.5, 25.5, 26.5, 28.5 e 29.5. O modelo so' conhecia 22.5, entao a primeira
validacao com dado real gerou zero pick. As linhas do mercado foram medidas e
entraram na tabela; 28.5 e 29.5 ficaram de fora (taxa baixa demais, o erro da
estimativa pesa mais que a margem).

Quando o mesmo jogo tem varias linhas, o pipeline avalia todas e fica com a de
maior margem -- escolher a linha faz parte da decisao.
"""
import json
import re

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.referee_stats_service import RefereeStatsService
from services.pick_engine import competition_profile as cp
from services.pick_engine.fouls_model import (
    LINHAS_SUPORTADAS,
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

# Edge minimo pra gravar. Abaixo disso a margem nao cobre o erro do proprio
# modelo -- a faixa mais forte da tabela empirica foi medida em 159 jogos, o
# que ja carrega incerteza de alguns pontos percentuais.
EDGE_MIN = 0.04


def _historico(match_stats: MatchStatsService, fixture: dict, team_id: int) -> list:
    """Historico do time, respeitando o perfil da competicao.

    Copa (de clube ou selecao) nao acumula jogo suficiente pra sustentar
    analise so' com os jogos DELA -- validacao com dado real mostrou media de
    faltas saindo de 1 unico jogo em fixtures da Copa do Brasil, muito abaixo
    do minimo de 5 do modelo. Mesma decisao que dica/vip ja tomam via
    competition_profile.
    """
    since = match_stats.get_structural_change_date(team_id)
    if cp.uses_all_competitions_history(fixture["league_id"]):
        return match_stats.get_last_n_all_competitions(team_id, since_date=since)
    return match_stats.get_all_matches_full(
        team_id, fixture["season"], fixture["league_id"], since_date=since)

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


_OVER_RE = re.compile(r"^over\s+([\d.,]+)$", re.IGNORECASE)


def _odds_over_faltas(structured_odds: list) -> dict[float, dict]:
    """Melhor odd de Over por LINHA no mercado de faltas totais.

    A linha sai do texto do value_name ("Over 24.5"), NAO da coluna
    line_value: na coleta real (2026-08-02) line_value vem NULL em todas as
    linhas de faltas, entao ler dali nunca casava nada -- o pipeline rodava
    sem erro e sem gerar pick, o pior tipo de falha.
    """
    melhores: dict[float, dict] = {}
    for o in structured_odds:
        nome = (o.get("market_name") or "").strip().lower()
        if nome not in NOMES_MERCADO_TOTAL:
            continue
        m = _OVER_RE.match((o.get("value_name") or "").strip())
        if not m:
            continue
        try:
            linha = float(m.group(1).replace(",", "."))
            odd = float(o.get("odd") or 0)
        except (TypeError, ValueError):
            continue
        if linha not in LINHAS_SUPORTADAS:
            continue
        if odd < ODD_MIN or odd > ODD_MAX:
            continue
        atual = melhores.get(linha)
        if atual is None or odd > atual["odd"]:
            melhores[linha] = {
                "odd": odd,
                "linha": linha,
                "bookmaker": o.get("bookmaker_name") or o.get("bookmaker"),
                "market_id": o.get("market_id"),
                "market_name": o.get("market_name"),
            }
    return melhores


def _fixtures_de_hoje(cur) -> list:
    """Jogos de hoje que ja tem odds coletadas.

    Mesmo recorte de data dos outros pipelines (`match_datetime::date =
    CURRENT_DATE`) -- se divergir daqui, o coletor de odds (que usa o mesmo
    predicado) nao tera' baixado odd pro jogo.
    """
    cur.execute(f"""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, f.referee, l.name
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        LEFT JOIN leagues l ON l.league_id = f.league_id
        WHERE f.match_datetime::date = {HOJE_BR}
          AND f.status IN ('NS', 'TBD')
        ORDER BY f.match_datetime
    """)
    return [
        {
            "fixture_id": r[0], "league_id": r[1], "season": r[2],
            "home_team_id": r[3], "away_team_id": r[4],
            "home_team": r[5], "away_team": r[6],
            "match_datetime": r[7], "referee": r[8], "league_name": r[9],
        }
        for r in cur.fetchall()
    ]


def _avaliar_fixture(fixture: dict, match_stats: MatchStatsService,
                     odds_service: OddsService,
                     referee_service: RefereeStatsService) -> dict | None:
    """Candidato de faltas pra um jogo, ou None se nao der pra avaliar."""
    # load_odds_by_fixture (RAW), nao load_odds_structured: aquele agrupa por
    # line_value e valida pares Over/Under por probabilidade implicita. Em
    # faltas o line_value vem NULL (a linha esta no texto do value_name),
    # entao o pareamento falha e ele descarta o mercado inteiro -- medido no
    # fixture 1546846: 12 entradas no raw viram 0 depois dele. A escolha da
    # melhor odd por linha, que era o servico dele, ja e' feita em
    # _odds_over_faltas.
    structured = odds_service.load_odds_by_fixture(fixture["fixture_id"])
    if not structured:
        return None

    ofertas = _odds_over_faltas(structured)
    if not ofertas:
        return None

    hist_casa = _historico(match_stats, fixture, fixture["home_team_id"])
    hist_fora = _historico(match_stats, fixture, fixture["away_team_id"])

    media_casa, n_casa = _media_faltas(hist_casa, fixture["home_team_id"])
    media_fora, n_fora = _media_faltas(hist_fora, fixture["away_team_id"])

    arbitro = referee_service.get_stats(fixture.get("referee"), fixture["season"])
    media_arbitro = float(arbitro["avg_fouls"]) if arbitro and arbitro.get("avg_fouls") else None
    n_arbitro = int(arbitro["games"]) if arbitro and arbitro.get("games") else None

    # Avalia TODAS as linhas oferecidas e fica com a de maior margem. As casas
    # publicam 24.5 a 29.5 no mesmo jogo, e a margem varia bastante entre elas
    # -- escolher a linha faz parte da decisao, nao e' detalhe de formatacao.
    melhor = None
    for linha, oferta in sorted(ofertas.items()):
        analise = analyze_fouls_market(
            media_casa=media_casa, media_fora=media_fora,
            media_arbitro=media_arbitro,
            n_casa=n_casa, n_fora=n_fora, n_arbitro=n_arbitro,
            odd=oferta["odd"], linha=linha,
        )
        if not analise or analise.get("edge", 0) < EDGE_MIN:
            continue
        if melhor is None or analise["edge"] > melhor[0]["edge"]:
            melhor = (analise, oferta)

    if melhor is None:
        return None
    analise, oferta = melhor

    return {
        **analise,
        "fixture": fixture,
        "bookmaker": oferta["bookmaker"],
        "market_id": oferta["market_id"],
        "market_name": oferta["market_name"] or "Fouls. Total",
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
        f"Nessa faixa de previsao, Over {c['line']} bateu em "
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

    cur.execute(f"""
        INSERT INTO picks_faltas
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id, league_id, league_name,
             market, market_type, line, odd, bet_house, market_id,
             confidence, prob_real, edge, reasoning,
             stake_pct, stake_units, engine_debug)
        VALUES (%s, {HOJE_BR}, %s, %s, %s, %s, %s, %s, %s, 'fouls', %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date, fixture_id) DO NOTHING
    """, (
        f["fixture_id"], f["home_team"], f["away_team"],
        f["home_team_id"], f["away_team_id"], f["league_id"], f.get("league_name"),
        c["market_name"], f"Over {c['line']}", c["odd"], c["bookmaker"], c["market_id"],
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
          f"(linhas {', '.join(str(l) for l in LINHAS_SUPORTADAS)}, "
          f"minimo {MIN_JOGOS_TIME} jogos por time "
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
        # candidato unico e ja' escolhido: marca explicitamente pro resumo do
        # decision_log sinalizar "<== ESCOLHIDO" como nos outros pipelines.
        log_decision("FALTAS_ENGINE", c["fixture"], [{**c, "is_best_pick": True}], [c])
        aprovado = gate.apply([c], "faltas", c["fixture"])
        if not aprovado:
            print(f"[FALTAS_ENGINE] Fixture {c['fixture']['fixture_id']} vetado pela revisao de IA.")
            continue
        _salvar(cur, {**c, "ai_review": aprovado[0].get("ai_review")})
        salvos += 1
        print(f"[FALTAS_ENGINE] Salvo: {c['fixture']['home_team']} x {c['fixture']['away_team']} "
              f"· Over {c['line']} faltas @ {c['odd']} "
              f"(prob={c['probability'] * 100:.1f}%, margem={c['edge'] * 100:+.1f}%)")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[FALTAS_ENGINE] {salvos} pick(s) de faltas gravado(s).")


if __name__ == "__main__":
    run_faltas_engine()
