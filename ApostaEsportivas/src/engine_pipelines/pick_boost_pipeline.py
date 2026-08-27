"""Pick Boost -- escolhe os melhores JOGOS do dia para uma combinacao fixa.

    Over 1.5 gols FT  +  Under 2.5 gols HT

DIFERENCA ESTRUTURAL PROS OUTROS PIPELINES
------------------------------------------
Os pipelines de pre-jogo avaliam um jogo, ranqueiam MERCADOS dentro dele e
publicam o melhor. Este faz o contrario: o mercado ja' esta' definido, e o que
se ranqueia sao os JOGOS. Consequencias praticas:

  · nao ha' exclusividade de partida nem "melhor pick do jogo" -- todo jogo
    que passar no corte vira pick, ate' o teto da rodada;
  · a ordenacao e' pelo Score Estatistico, NAO por EV nem por odd. Odd, odd
    justa e EV sao gravados e exibidos como informacao secundaria;
  · o dia com varias oportunidades e' o caso esperado, nao anomalia.

TODO JOGO AVALIADO VIRA LINHA DE AUDITORIA
------------------------------------------
Inclusive os descartados, com o motivo. Era pedido explicito: "entender por
que o motor escolheu uma partida em vez de outra" so' e' possivel se a partida
NAO escolhida tambem tiver registro. O registro sai da mesma passada que
decide -- nao ha' segunda analise so' pra auditar (ver services/engine_audit).

FASE 1: ADMIN. Este motor grava em `picks_boost` e aparece na Auditoria dos
Motores, mas nao publica no site. Decisao do usuario em 27/08: medir alguns
dias antes de expor. Publicar depois e' ligar a leitura, nada aqui muda.
"""
import json
import re
import textwrap
import traceback

from services.engine_audit import EngineRun, amostra
from services.match_stats_service import MatchStatsService
from services.odds_service import OddsService
from services.pick_engine import context_gate
from services.pick_engine.staking import calculate_stake
from services.pick_engine_boost import config as cfg
from services.pick_engine_boost import explanation, goals_history, score as scoring
from services.pick_engine_boost import stats_model
from utils.data_br import HOJE_BR
from utils.db_utils import get_connection

MOTOR = "PICK_BOOST"
METODO = "over15_under25ht"

_OVER_RE = re.compile(r"^over\s+([\d.,]+)$", re.IGNORECASE)
_UNDER_RE = re.compile(r"^under\s+([\d.,]+)$", re.IGNORECASE)

# Motivos de descarte -- curtos e estaveis, viram GROUP BY no painel.
MOTIVO_SEM_ODD_FT = "sem odd de Over 1.5 no jogo completo"
MOTIVO_SEM_ODD_HT = "sem odd de Under 2.5 no primeiro tempo"
MOTIVO_ODD_FORA = "odd fora da faixa de sanidade"
MOTIVO_SEM_HISTORICO = "histórico insuficiente de um dos times"
MOTIVO_SEM_HT = "sem placar de intervalo publicado o bastante"
MOTIVO_PROB_BAIXA = "probabilidade abaixo do mínimo de uma das pernas"
MOTIVO_TETO = "fora do teto de picks da rodada"


def _fixtures_de_hoje(cur) -> list:
    """Jogos de hoje que ja' tem odds coletadas.

    Mesmo recorte de data dos outros pipelines (`match_datetime::date =
    HOJE_BR`) -- se divergir daqui, o coletor de odds (que usa o mesmo
    predicado) nao tera' baixado odd pro jogo.
    """
    cur.execute(f"""
        SELECT DISTINCT
            f.fixture_id, f.league_id, f.season,
            f.home_team_id, f.away_team_id, f.home_team, f.away_team,
            f.match_datetime, f.round, l.name
        FROM fixtures f
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        LEFT JOIN leagues l ON l.league_id = f.league_id
        WHERE f.match_datetime::date = {HOJE_BR}
          AND f.status IN ('NS', 'TBD')
        ORDER BY f.match_datetime
    """)
    return [
        {"fixture_id": r[0], "league_id": r[1], "season": r[2],
         "home_team_id": r[3], "away_team_id": r[4],
         "home_team": r[5], "away_team": r[6],
         "match_datetime": r[7], "round": r[8], "league_name": r[9]}
        for r in cur.fetchall()
    ]


def _melhor_odd(odds_cruas: list, nomes_mercado, regex, linha_alvo: float) -> dict | None:
    """Melhor odd oferecida pra uma linha exata, entre as casas.

    Le a linha do TEXTO do value_name ("Over 1.5") e nao da coluna line_value:
    a coleta real mostrou line_value vindo NULL em mercados inteiros, e ler
    dali produz um pipeline que roda sem erro e sem gerar pick -- o pior tipo
    de falha (ver faltas_pipeline._odds_over_faltas, mesma armadilha).
    """
    melhor = None
    for o in odds_cruas:
        nome = (o.get("market_name") or "").strip().lower()
        if nome not in nomes_mercado:
            continue
        m = regex.match((o.get("value_name") or "").strip())
        if not m:
            continue
        try:
            linha = float(m.group(1).replace(",", "."))
            odd = float(o.get("odd") or 0)
        except (TypeError, ValueError):
            continue
        if abs(linha - linha_alvo) > 1e-9 or odd <= 1.0:
            continue
        if melhor is None or odd > melhor["odd"]:
            melhor = {
                "odd": odd, "linha": linha,
                "bookmaker": o.get("bookmaker_name") or o.get("bookmaker"),
                "market_id": o.get("market_id"),
                # PT primeiro, ingles como reserva -- mesma ordem do
                # orchestrator. Sem isto o nome cru da casa vai pra tela.
                "market_name": o.get("market_pt") or o.get("market_name"),
            }
    return melhor


def _avaliar_fixture(fixture: dict, cur, match_stats: MatchStatsService,
                     odds_service: OddsService) -> dict:
    """Retrato completo de um jogo: aprovado ou nao, sempre com o porque.

    Devolve SEMPRE um dicionario -- nunca None. A auditoria precisa da linha
    do jogo descartado tanto quanto da do escolhido, e um `return None` no
    meio do caminho e' exatamente o `continue` mudo que o decision_log foi
    criado pra acabar em 07/08.
    """
    resultado = {"fixture": fixture, "aprovado": False, "motivo": None,
                 "score": None, "indicadores": None, "amostra": None}

    # -- odds das duas pernas ------------------------------------------------
    # RAW e nao load_odds_structured: aquele valida pares Over/Under por
    # probabilidade implicita e descarta a linha inteira quando so' um lado
    # foi coletado. Aqui interessa UM lado de cada mercado.
    odds_cruas = odds_service.load_odds_by_fixture(fixture["fixture_id"])
    if not odds_cruas:
        resultado["motivo"] = MOTIVO_SEM_ODD_FT
        return resultado

    perna_ft = _melhor_odd(odds_cruas, cfg.NOMES_MERCADO_FT, _OVER_RE, cfg.LINHA_OVER_FT)
    if not perna_ft:
        resultado["motivo"] = MOTIVO_SEM_ODD_FT
        return resultado
    perna_ht = _melhor_odd(odds_cruas, cfg.NOMES_MERCADO_HT, _UNDER_RE, cfg.LINHA_UNDER_HT)
    if not perna_ht:
        resultado["motivo"] = MOTIVO_SEM_ODD_HT
        return resultado

    odd_combinada = round(perna_ft["odd"] * perna_ht["odd"], 3)
    resultado["odd"] = odd_combinada
    fora_da_faixa = (
        not (cfg.ODD_MIN_FT <= perna_ft["odd"] <= cfg.ODD_MAX_FT)
        or not (cfg.ODD_MIN_HT <= perna_ht["odd"] <= cfg.ODD_MAX_HT)
        or not (cfg.ODD_MIN_COMBINADA <= odd_combinada <= cfg.ODD_MAX_COMBINADA)
    )
    if fora_da_faixa:
        resultado["motivo"] = (f"{MOTIVO_ODD_FORA} (FT {perna_ft['odd']}, "
                               f"HT {perna_ht['odd']}, par {odd_combinada})")
        return resultado

    # -- historico -----------------------------------------------------------
    since_home = match_stats.get_structural_change_date(fixture["home_team_id"])
    since_away = match_stats.get_structural_change_date(fixture["away_team_id"])
    hist_home = goals_history.carregar(cur, fixture["home_team_id"], fixture["league_id"],
                                       fixture["season"], since_date=since_home)
    hist_away = goals_history.carregar(cur, fixture["away_team_id"], fixture["league_id"],
                                       fixture["season"], since_date=since_away)
    if (len(hist_home) < cfg.MIN_JOGOS_FT) or (len(hist_away) < cfg.MIN_JOGOS_FT):
        resultado["motivo"] = (f"{MOTIVO_SEM_HISTORICO} "
                               f"({len(hist_home)} x {len(hist_away)} jogos)")
        return resultado
    ht_home, ht_away = goals_history.com_ht(hist_home), goals_history.com_ht(hist_away)
    if (len(ht_home) < cfg.MIN_JOGOS_HT) or (len(ht_away) < cfg.MIN_JOGOS_HT):
        resultado["motivo"] = (f"{MOTIVO_SEM_HT} "
                               f"({len(ht_home)} x {len(ht_away)} jogos com HT)")
        return resultado

    # -- indicadores ---------------------------------------------------------
    perfil_home = stats_model.perfil_do_time(hist_home, fixture["home_team_id"], "home")
    perfil_away = stats_model.perfil_do_time(hist_away, fixture["away_team_id"], "away")
    confronto = stats_model.analisar_confronto(perfil_home, perfil_away)

    # Contexto do confronto (mata-mata, perna, agregado, rivalidade). Nao
    # entra no Score -- entra na AMOSTRA e na explicacao, que era o pedido:
    # saber se e' classico, se e' o segundo jogo e o que aconteceu no primeiro.
    match_context = context_gate.build_for_fixture(match_stats, fixture)

    resultado["amostra"] = amostra.build(
        home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
        historico_home=hist_home, historico_away=hist_away,
        home_team=fixture.get("home_team"), away_team=fixture.get("away_team"),
        match_context=match_context,
    )

    calculo = scoring.calcular(confronto, perfil_home, perfil_away)
    resultado["score"] = calculo["score"]
    resultado["indicadores"] = {
        "confronto": confronto, "mandante": perfil_home, "visitante": perfil_away,
        "parcelas": calculo["parcelas"], "pontos_fracos": calculo["pontos_fracos"],
    }
    resultado["pernas"] = {"ft": perna_ft, "ht": perna_ht}
    resultado["probabilidade"] = confronto.get("prob_combinada")

    # -- cortes duros --------------------------------------------------------
    prob_ft, prob_ht = confronto.get("prob_over15_ft"), confronto.get("prob_under25_ht")
    if prob_ft is None or prob_ht is None:
        resultado["motivo"] = MOTIVO_PROB_BAIXA
        return resultado
    if prob_ft < cfg.PROB_MINIMA_FT or prob_ht < cfg.PROB_MINIMA_HT:
        resultado["motivo"] = (f"{MOTIVO_PROB_BAIXA} "
                               f"(FT {prob_ft * 100:.0f}%, HT {prob_ht * 100:.0f}%)")
        return resultado
    if calculo["score"] < cfg.SCORE_MINIMO:
        resultado["motivo"] = scoring.motivo_do_descarte(calculo)
        return resultado

    # -- odd justa e EV, informacao SECUNDARIA -------------------------------
    prob_par = confronto.get("prob_combinada")
    resultado["fair_odd"] = round(1 / prob_par, 3) if prob_par else None
    resultado["ev"] = (round(prob_par * odd_combinada - 1, 4) if prob_par else None)
    resultado["edge"] = (round(prob_par - 1 / odd_combinada, 4) if prob_par else None)
    resultado["aprovado"] = True
    return resultado


def _engine_debug(c: dict) -> str:
    ind = c.get("indicadores") or {}
    return json.dumps({
        "modelo": "pick_engine_boost/poisson_gols",
        "score": c.get("score"),
        "parcelas": ind.get("parcelas"),
        "pontos_fracos": ind.get("pontos_fracos"),
        "confronto": ind.get("confronto"),
        "mandante": ind.get("mandante"),
        "visitante": ind.get("visitante"),
        # A AMOSTRA: quais jogos entraram na conta, ate' 10 por time, com o
        # contexto do confronto. E' o que a tela "Entenda esta analise" exibe,
        # e a razao de ela nao poder divergir do que decidiu -- e' o mesmo
        # objeto (ver services/engine_audit/amostra.py).
        "amostra": c.get("amostra"),
        "fair_odd": c.get("fair_odd"), "ev": c.get("ev"), "edge": c.get("edge"),
        "pernas": c.get("pernas"),
    }, default=str, ensure_ascii=False)


def _salvar(cur, c: dict) -> int | None:
    """Grava o pick e devolve o id, ou None se ja' existia."""
    f, pernas = c["fixture"], c["pernas"]
    prob = c.get("probabilidade")
    stake_pct, stake_units = calculate_stake(
        confidence=prob, odd=c["odd"], ev=c.get("ev") or 0, pick_type="free",
    )
    cur.execute(f"""
        INSERT INTO picks_boost
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id, league_id, league_name,
             market, market_type, line,
             odd, odd_ft, odd_ht, bet_house_ft, bet_house_ht,
             market_id_ft, market_id_ht,
             score, confidence, prob_real, prob_ft, prob_ht, fair_odd, ev, edge,
             reasoning, stake_pct, stake_units, engine_debug)
        VALUES (%s, {HOJE_BR}, %s, %s, %s, %s, %s, %s,
                %s, 'boost_over15_under25ht', %s,
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s)
        ON CONFLICT (match_date, fixture_id) DO NOTHING
        RETURNING id
    """, (
        f["fixture_id"], f["home_team"], f["away_team"],
        f["home_team_id"], f["away_team_id"], f["league_id"], f.get("league_name"),
        "Over 1.5 FT + Under 2.5 HT",
        f"Over {cfg.LINHA_OVER_FT} FT · Under {cfg.LINHA_UNDER_HT} HT",
        c["odd"], pernas["ft"]["odd"], pernas["ht"]["odd"],
        pernas["ft"]["bookmaker"], pernas["ht"]["bookmaker"],
        pernas["ft"]["market_id"], pernas["ht"]["market_id"],
        c["score"], prob, prob,
        (c.get("indicadores") or {}).get("confronto", {}).get("prob_over15_ft"),
        (c.get("indicadores") or {}).get("confronto", {}).get("prob_under25_ht"),
        c.get("fair_odd"), c.get("ev"), c.get("edge"),
        explanation.frase(c["score"], (c.get("indicadores") or {}).get("confronto") or {},
                          (c.get("indicadores") or {}).get("mandante") or {},
                          (c.get("indicadores") or {}).get("visitante") or {}, f),
        stake_pct, stake_units, _engine_debug(c),
    ))
    linha = cur.fetchone()
    if not linha:
        return None
    return linha["id"] if isinstance(linha, dict) else linha[0]


def _dados_da_auditoria(c: dict) -> dict:
    """O que fica em engine_decisions.context -- o suficiente pra explicar.

    NAO e' o engine_debug inteiro: perfis completos dos dois times, jogo a
    jogo, em toda linha de jogo DESCARTADO, transformariam a auditoria no "log
    gigante" que o usuario pediu pra nao existir. Aqui vai o resumo
    estruturado (o que a tela mostra) mais a amostra, que e' o pedido novo.
    """
    ind = c.get("indicadores") or {}
    confronto = ind.get("confronto") or {}
    return {
        "resumo": explanation.resumo_estruturado(
            confronto, ind.get("mandante") or {}, ind.get("visitante") or {},
            c["fixture"]) if confronto else None,
        "conclusao": (explanation.conclusao(c["score"], confronto)
                      if c.get("aprovado") and confronto else c.get("motivo")),
        "parcelas": ind.get("parcelas"),
        "pontos_fracos": ind.get("pontos_fracos"),
        "amostra": c.get("amostra"),
    }


def run_pick_boost_engine():
    conn = get_connection()
    cur = conn.cursor()

    with EngineRun(MOTOR, METODO, resumo={
        "score_minimo": cfg.SCORE_MINIMO,
        "prob_minima_ft": cfg.PROB_MINIMA_FT,
        "prob_minima_ht": cfg.PROB_MINIMA_HT,
        "faixa_odd_combinada": [cfg.ODD_MIN_COMBINADA, cfg.ODD_MAX_COMBINADA],
        "teto_picks": cfg.MAX_PICKS_POR_RODADA,
    }) as run:
        fixtures = _fixtures_de_hoje(cur)
        if not fixtures:
            print("[PICK_BOOST] Nenhum jogo de hoje com odds coletadas.")
            cur.close()
            conn.close()
            return

        print(f"[PICK_BOOST] Avaliando {len(fixtures)} jogo(s) para "
              f"Over {cfg.LINHA_OVER_FT} FT + Under {cfg.LINHA_UNDER_HT} HT...")

        match_stats = MatchStatsService()
        odds_service = OddsService()

        avaliados = []
        for fixture in fixtures:
            try:
                avaliados.append(_avaliar_fixture(fixture, cur, match_stats, odds_service))
            except Exception as e:
                run.erro(e, contexto=f"{fixture.get('home_team')} x {fixture.get('away_team')}",
                         fixture_id=fixture.get("fixture_id"))
                print(textwrap.indent(traceback.format_exc(), "    "))

        # Ordenacao pelo SCORE, nao por EV nem por odd. E' a regra do metodo.
        aprovados = sorted([a for a in avaliados if a["aprovado"]],
                           key=lambda a: a["score"], reverse=True)
        reprovados = [a for a in avaliados if not a["aprovado"]]

        # Teto da rodada: quem ficou de fora vira descarte com motivo proprio,
        # e nao some. "Score 91 e nao publicou" precisa ter resposta.
        publicaveis, excedentes = (aprovados[:cfg.MAX_PICKS_POR_RODADA],
                                   aprovados[cfg.MAX_PICKS_POR_RODADA:])

        salvos = 0
        for c in publicaveis:
            pick_id = None
            try:
                pick_id = _salvar(cur, c)
                conn.commit()
            except Exception as e:
                conn.rollback()
                run.erro(e, contexto="gravacao do pick",
                         fixture_id=c["fixture"].get("fixture_id"))
            if pick_id:
                salvos += 1
                print(f"[PICK_BOOST] Score {c['score']:.0f} · {c['fixture']['home_team']} x "
                      f"{c['fixture']['away_team']} @ {c['odd']} "
                      f"(prob={(c.get('probabilidade') or 0) * 100:.0f}%)")
            run.analisado(c["fixture"], selecionado=bool(pick_id), score=c["score"],
                          probabilidade=c.get("probabilidade"), odd=c.get("odd"),
                          motivo=None if pick_id else "pick do dia já existia para esta partida",
                          dados=_dados_da_auditoria(c), pick_id=pick_id)

        for c in excedentes:
            run.analisado(c["fixture"], selecionado=False, score=c["score"],
                          probabilidade=c.get("probabilidade"), odd=c.get("odd"),
                          motivo=f"{MOTIVO_TETO} (teto {cfg.MAX_PICKS_POR_RODADA})",
                          dados=_dados_da_auditoria(c))

        for c in reprovados:
            run.analisado(c["fixture"], selecionado=False, score=c.get("score"),
                          probabilidade=c.get("probabilidade"), odd=c.get("odd"),
                          motivo=c.get("motivo"), dados=_dados_da_auditoria(c))

        run.anotar(picks_salvos=salvos, aprovados=len(aprovados))
        print(f"[PICK_BOOST] {salvos} pick(s) salvos de {len(avaliados)} jogo(s) avaliados.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    run_pick_boost_engine()
