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
from services.pick_engine.config import DEFAULT_CONFIG
from services.pick_engine.fouls_model import (
    LINHAS_SUPORTADAS,
    MIN_JOGOS_ARBITRO,
    MIN_JOGOS_TIME,
    analyze_fouls_market,
)
from services.pick_engine.fouls_calibration import recalibrar
from services.pick_engine.market_pick_score import faixa_config, pick_score
from services.pick_engine.staking import calculate_stake
from services.pick_engine.ai_review import review_gate
from engine_pipelines.decision_log import (
    MOTIVO_ERRO, MOTIVO_SEM_CANDIDATO,
    log_decision, log_run, log_skip, registrar_selecao,
)
from services.engine_audit import amostra, auditar

# FAIXA DE ODD [1.10, 2.00], reposta em 2026-08-16 a pedido do usuario.
#
# HISTORICO: era [1.35, 2.00], removida em 2026-08-07 junto com a mesma remocao
# em goleiros, com a justificativa de que fora dela "o pick nao interessa
# comercialmente". Volta com o piso mais baixo porque a pergunta do produto
# mudou: nao e' onde a odd esta' generosa, e' onde a estatistica ganha -- e
# estatistica forte sai em odd BAIXA, nao alta.
#
# O TETO E' A PARTE QUE MAIS IMPORTA AQUI, e este bloco ja' avisava disso
# enquanto ele nao existia. A probabilidade de faltas NAO e' calculada por jogo:
# sai de uma tabela empirica cujo menor valor e' 0.26 (linha 26.5, faixa ate
# 22.0 de previsao). Com EDGE_MIN de 0.04, qualquer odd a partir de ~4.00
# passava no corte de edge SOZINHA, so' pela aritmetica (0.26 * 4.00 - 1 =
# +0.04), sem o modelo ter opinado nada a favor. O PROB_MIN abaixo fechou esse
# buraco pelo lado da probabilidade; o teto fecha pelo lado do preco e devolve a
# rede contra dado ruim (odd digitada errada, mercado mapeado no lugar errado)
# que existia por acidente e sumiu junto com a faixa antiga.
#
# O PISO DE 1.10 NAO BINDA NESTE PIPELINE, e isso e' conhecido: a maior taxa da
# tabela e' 0.893, entao com EDGE_MIN 0.04 a menor odd alcancavel e'
# 1/(0.893-0.04) = 1.17, e nas duas faixas mais comuns (0.792 e 0.716) o piso
# real ja' e' 1.33 e 1.48. Quem limita o lado barato aqui e' o EDGE_MIN, nao
# este numero. Fica declarado assim mesmo, pra a faixa ser a mesma dos dois
# mercados e pra o dia em que a tabela for remedida com faixas melhores.
ODD_MIN = 1.10
ODD_MAX = 2.00

# Edge minimo pra gravar. Abaixo disso a margem nao cobre o erro do proprio
# modelo -- a faixa mais forte da tabela empirica foi medida em 159 jogos, o
# que ja carrega incerteza de alguns pontos percentuais.
EDGE_MIN = 0.04

# PISO DE PROBABILIDADE (2026-08-08). Fecha exatamente o buraco descrito no
# bloco ODD_MIN/ODD_MAX acima: sem teto de odd, "qualquer odd a partir de ~4.00
# passa no corte de edge SOZINHA, so' pela aritmetica". Com o piso, a faixa de
# 0.26 da tabela nunca mais vira pick, por mais generosa que a odd esteja --
# porque 26% de chance nao e' um pick, e' um bilhete.
#
# Mesmo numero e mesmo motivo do PROB_MIN de goleiros: e' o
# PickEngineConfig.min_taxa que ranking.py ja aplica em VIP, free, multipla e
# alavancagem. Faltas e goleiros nunca passaram por ali (pipeline proprio) e
# ficaram sem piso por acidente de arquitetura. Pedido do usuario em 2026-08-08:
# "quero picks que ganham estatisticamente, nao achar onde tem valor de odd".
#
# Consequencia direta na tabela de fouls_model: so' as faixas com taxa medida
# >= 0.65 continuam podendo gerar pick. Se isso zerar a frequencia do pipeline,
# a resposta certa e' medir faixas melhores, nao baixar o piso.
PROB_MIN = DEFAULT_CONFIG.min_taxa

# Ordenacao dos candidatos aprovados (2026-08-16). Antes disto a escolha da
# linha e a ordem entre jogos saiam do MAIOR EDGE, que e' o criterio que o motor
# generico abandonou em 14/08 por medicao -- ver a docstring de
# market_pick_score. Os cortes nao mudaram: quem aprova continua sendo a faixa
# de odd, o PROB_MIN e o EDGE_MIN acima.
SCORE_CONFIG = faixa_config(ODD_MIN, ODD_MAX)

# Satura no maior n da tabela de faixas de fouls_model (159 jogos). A faixa de
# 50 jogos nao merece a mesma confianca que a de 159, e essa diferenca ja' era
# devolvida por prob_over() desde sempre -- so' nunca tinha sido usada pra nada.
AMOSTRA_SATURACAO = 159

# MANDO SEPARADO NA MEDIA DE FALTAS (interruptor, 2026-08-16).
#
# False = comportamento historico: os jogos do time em casa e fora entram no
# mesmo balde. True = so' os jogos no mando em que ele vai jogar, igual ao que
# stats_model.pool_and_field faz no motor generico desde 08/08 e ao que
# goleiros_pipeline passou a fazer em 16/08.
#
# POR QUE UM INTERRUPTOR, E NAO SIMPLESMENTE LIGADO. Duas perguntas diferentes:
#
#   consistencia  a tabela empirica precisa ter sido calibrada pelo MESMO
#                 metodo, senao o mapeamento faixa -> taxa nao vale. Isso a
#                 recalibragem automatica resolve: ela recebe este mesmo
#                 booleano, entao os dois lados sempre andam juntos.
#   qualidade     separar por mando PREVE MELHOR? Isso e' medicao, e a resposta
#                 esta' na Parte A de scripts/medir_faltas_mando_e_pressao.py
#                 (compara o erro medio dos dois metodos na mesma amostra).
#
# Fica em False ate' essa medicao existir. Ligar depois e' trocar este booleano:
# a tabela se recalibra sozinha junto, sem nenhuma outra mudanca de codigo.
USAR_MANDO = False


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


def _media_faltas(historico: list, team_id: int,
                  mando: str | None = None) -> tuple[float | None, int]:
    """Faltas por jogo que o time comete, no historico dele.

    O historico traz a linha do jogo inteiro (home_fouls e away_fouls), entao
    precisa escolher o lado certo jogo a jogo -- o time joga em casa e fora.
    Jogo sem a coluna preenchida e' descartado em vez de virar zero: zero
    falta nao existe e puxaria a media pra baixo.

    `mando` None conta os dois mandos no mesmo balde (comportamento historico).
    "home"/"away" conta so' os jogos naquele mando -- ver USAR_MANDO, e lembrar
    que a tabela empirica precisa ter sido calibrada do mesmo jeito.
    """
    valores = []
    for jogo in historico:
        if jogo.get("home_team_id") == team_id:
            lado, v = "home", jogo.get("home_fouls")
        elif jogo.get("away_team_id") == team_id:
            lado, v = "away", jogo.get("away_fouls")
        else:
            continue
        if mando is not None and lado != mando:
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
        if (ODD_MIN is not None and odd < ODD_MIN) or (ODD_MAX is not None and odd > ODD_MAX):
            continue
        atual = melhores.get(linha)
        if atual is None or odd > atual["odd"]:
            melhores[linha] = {
                "odd": odd,
                "linha": linha,
                "bookmaker": o.get("bookmaker_name") or o.get("bookmaker"),
                "market_id": o.get("market_id"),
                # PT primeiro, ingles como reserva -- mesma ordem que
                # pick_engine/orchestrator.py usa pra montar market_name. Sem o
                # market_pt aqui, "Fouls. Total" ia CRU pra picks_faltas.market
                # e dali pra tela (2 picks em producao antes desta correcao,
                # achados na auditoria de 2026-08-17). O nome gravado tambem e' a
                # chave que o front usa pra explicar a regra do mercado
                # (chaveCanonica em marketTranslate.ts), entao nome cru nao e'
                # so' feio: cai no texto generico "conforme as condicoes do
                # mercado", que e' justamente o que nao ajuda ninguem.
                "market_pt": o.get("market_pt"),
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
                     referee_service: RefereeStatsService,
                     faixas: dict | None = None) -> dict | None:
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

    media_casa, n_casa = _media_faltas(
        hist_casa, fixture["home_team_id"], "home" if USAR_MANDO else None)
    media_fora, n_fora = _media_faltas(
        hist_fora, fixture["away_team_id"], "away" if USAR_MANDO else None)

    # Contexto de confronto (2026-08-20). Faltas era um dos dois pipelines
    # cegos ao agregado, e e' o mercado com o efeito MEDIDO mais forte de
    # todos: o lado que precisa reverter comete 2.48 faltas A MENOS por jogo
    # (3.9 erros-padrao), e o que administra tambem cai. Como aqui so' se
    # publica OVER, o agregado aberto joga direto contra o pick.
    contexto = context_gate.build_for_fixture(match_stats, fixture)

    arbitro = referee_service.get_stats(fixture.get("referee"), fixture["season"])
    media_arbitro = float(arbitro["avg_fouls"]) if arbitro and arbitro.get("avg_fouls") else None
    n_arbitro = int(arbitro["games"]) if arbitro and arbitro.get("games") else None

    # Avalia TODAS as linhas oferecidas e fica com a de maior SCORE. As casas
    # publicam 24.5 a 29.5 no mesmo jogo -- escolher a linha faz parte da
    # decisao, nao e' detalhe de formatacao.
    #
    # Era "maior margem" ate' 2026-08-16, e trocar isso muda a linha escolhida na
    # pratica: entre duas linhas do mesmo jogo, a mais alta sempre tem odd maior
    # e por construcao tende a ter edge maior, entao o criterio antigo subia a
    # linha sozinho. O score pesa a probabilidade (0.45) e a seguranca do preco
    # (0.28) acima do edge (0.10), que e' o mesmo desenho do motor generico.
    melhor = None
    for linha, oferta in sorted(ofertas.items()):
        analise = analyze_fouls_market(
            media_casa=media_casa, media_fora=media_fora,
            media_arbitro=media_arbitro,
            n_casa=n_casa, n_fora=n_fora, n_arbitro=n_arbitro,
            odd=oferta["odd"], linha=linha, faixas=faixas,
        )
        if not analise:
            continue
        # ANTES dos cortes, nao depois: o contexto tem que poder REPROVAR uma
        # linha, e nao so' enfeitar a explicacao de uma ja aprovada.
        analise = tie_effect.aplicar_em_analise(
            analise, contexto, familia="fouls", escopo="total", direcao="over",
            linha=linha, lambda_esperado=analise.get("expected_fouls"))
        if analise.get("probability", 0) < PROB_MIN:
            continue
        if analise.get("edge", 0) < EDGE_MIN:
            continue
        analise["pick_score"] = pick_score(
            probability=analise["probability"], odd=oferta["odd"],
            edge=analise["edge"], amostra=analise.get("faixa_amostra"),
            amostra_saturacao=AMOSTRA_SATURACAO, config=SCORE_CONFIG,
        )
        if melhor is None or analise["pick_score"] > melhor[0]["pick_score"]:
            melhor = (analise, oferta)

    if melhor is None:
        return None
    analise, oferta = melhor

    return {
        **analise,
        "fixture": fixture,
        "bookmaker": oferta["bookmaker"],
        "market_id": oferta["market_id"],
        "market_name": (oferta.get("market_pt") or oferta.get("market_name")
                        or "Faltas Mais/Menos"),
        "n_casa": n_casa, "n_fora": n_fora,
        "media_casa": media_casa, "media_fora": media_fora,
        "media_arbitro": media_arbitro, "n_arbitro": n_arbitro,
        # A AMOSTRA (2026-08-27): os jogos que o motor leu, ate' 10 por time,
        # mais o contexto do confronto que ele ja' montou logo acima. Nao
        # entra em nenhum calculo -- e' o que a tela "Entenda esta analise"
        # exibe, lendo o MESMO objeto que decidiu.
        "amostra": amostra.build(
            home_team_id=fixture["home_team_id"],
            away_team_id=fixture["away_team_id"],
            historico_home=hist_casa, historico_away=hist_fora,
            home_team=fixture.get("home_team"), away_team=fixture.get("away_team"),
            match_context=contexto),
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
    for frase in tie_effect.descrever(c.get("tie_effect")):
        partes.append(frase.capitalize() + ".")
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
        "pick_score": c.get("pick_score"),
        # De QUAL tabela saiu a probabilidade deste pick. Sem isto, dois picks
        # com a mesma faixa e taxas diferentes ficariam inexplicaveis meses
        # depois -- a lista de mudancas fica so' no log da rodada, aqui vai o
        # resumo que identifica a versao da tabela.
        "calibragem": {k: v for k, v in (c.get("calibragem") or {}).items()
                       if k != "mudancas"},
        "amostra": c.get("amostra"),
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


# AUDITORIA (2026-08-27). Duas linhas, e nenhuma no corpo da funcao: o Pre
# Live esta' congelado. O decorador abre a execucao (run_id, contagens,
# status) e o decision_log carimba esse run_id sozinho nas linhas que ja'
# gravava -- ver services/engine_audit/audit.py::auditar.
@auditar("PRE_LIVE", "faltas")
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

    # RECALIBRAGEM A CADA RODADA (2026-08-16, pedido do usuario: "adiciona no
    # fluxo dos pipelines pra fazer isso sempre"). Remede a tabela empirica
    # contra os jogos que existem HOJE, em vez de usar pra sempre a foto tirada
    # em 01/08. Celula sem amostra nova suficiente mantem o valor congelado, e
    # falha de banco devolve a tabela antiga inteira -- ver fouls_calibration.
    faixas, calibragem = recalibrar(cur, usar_mando=USAR_MANDO)
    print(f"[FALTAS_ENGINE] Tabela {calibragem['origem']}: "
          f"{calibragem['jogos']} jogos, {calibragem['amostras']} amostras, "
          f"{calibragem['celulas_trocadas']} celula(s) atualizada(s) "
          f"(mando {'separado' if USAR_MANDO else 'misturado'}).")
    if calibragem.get("erro"):
        print(f"[FALTAS_ENGINE] Recalibragem falhou ({calibragem['erro']}); "
              f"seguindo com a tabela congelada.")
    for mudanca in calibragem.get("mudancas", []):
        print(f"[FALTAS_ENGINE]   {mudanca}")

    match_stats = MatchStatsService()
    odds_service = OddsService()
    referee_service = RefereeStatsService()

    candidatos = []
    for fixture in fixtures:
        try:
            c = _avaliar_fixture(fixture, match_stats, odds_service,
                                 referee_service, faixas=faixas)
        except Exception as e:
            print(f"[FALTAS_ENGINE] Erro no fixture {fixture['fixture_id']}: {e}")
            log_skip("FALTAS_ENGINE", fixture, f"{MOTIVO_ERRO}: {e}")
            continue
        if c:
            candidatos.append(c)
        else:
            # Ate 2026-08-07 o jogo que nao virava candidato saia daqui sem
            # deixar rastro: log_decision so' era chamado no loop de baixo, com
            # os aprovados. Dia sem pick era indistinguivel de dia sem rodar.
            log_skip("FALTAS_ENGINE", fixture, MOTIVO_SEM_CANDIDATO)

    if not candidatos:
        motivo = ("nenhum candidato passou (historico curto, probabilidade "
                  "abaixo do piso ou margem abaixo do minimo)")
        print(f"[FALTAS_ENGINE] {motivo.capitalize()}.")
        log_run("FALTAS_ENGINE", motivo)
        cur.close()
        conn.close()
        return

    # Maior score primeiro (era maior edge ate' 2026-08-16). Aqui a ordem decide
    # de verdade: cada jogo ja' entrou com um candidato so', entao esta e' a fila
    # que a revisao de IA percorre e a que define quais picks o dia publica.
    candidatos.sort(key=lambda c: c["pick_score"], reverse=True)

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
        _salvar(cur, {**c, "ai_review": aprovado[0].get("ai_review"),
                      "calibragem": calibragem})
        salvos += 1
        # Aba de Auditoria: o decision_log ja' somou este jogo como
        # analisado/descartado, aqui a pick salva move a contagem.
        registrar_selecao("FALTAS_ENGINE", 1)
        print(f"[FALTAS_ENGINE] Salvo: {c['fixture']['home_team']} x {c['fixture']['away_team']} "
              f"· Over {c['line']} faltas @ {c['odd']} "
              f"(prob={c['probability'] * 100:.1f}%, margem={c['edge'] * 100:+.1f}%)")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[FALTAS_ENGINE] {salvos} pick(s) de faltas gravado(s).")


if __name__ == "__main__":
    run_faltas_engine()
