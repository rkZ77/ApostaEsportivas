"""Pipeline do Motor Live V1 -- UMA rodada por execucao, DEV apenas.

DESENHO
-------
Uma execucao faz uma passada e termina. Nao ha laco, nao ha sleep, nao ha
agendamento. A decisao e' explicita: o scheduler do projeto foi deletado em
2026-08-01 por consumo de API, e um motor ao vivo e' justamente o candidato
mais provavel a repetir esse acidente. Enquanto o consumo real nao for medido
rodando na mao, nao existe laco.

ORDEM DAS CHAMADAS, QUE E' A ECONOMIA
-------------------------------------
    1 x /fixtures?live=all           o mundo inteiro, uma vez
    N x /fixtures/statistics         so' dos jogos elegiveis (N <= max_partidas)
    N x /fixtures/events             so' dos mesmos jogos (opcional, ver config)
    M x /odds/live                   so' de quem passou na TRIAGEM (M <= N)

Partida que roda na media da liga nunca tem a odd consultada. E' o freio que
faz a rodada tipica custar menos que o teto.

O QUE CADA RODADA DEIXA PRA A PROXIMA
-------------------------------------
Toda passada grava uma linha em `live_match_observations`, mesmo quando nao
gera pick. E' de graca (o dado ja foi pago) e e' o que constroi janela recente
e tendencia: /fixtures/statistics so' devolve acumulado, entao "escanteios nos
ultimos 10 minutos" nao existe no feed -- existe na diferenca entre duas
leituras nossas.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import traceback
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Permite rodar direto (`python engine_pipelines/live_pipeline.py --fixture N`)
# alem de pelo main.py e pelo /admin, que ja exportam PYTHONPATH. Os pipelines
# do pre-jogo dependem do PYTHONPATH e por isso quebram quando chamados na mao
# de dentro de src/ -- aqui isso e' resolvido, porque testar uma fixture
# especifica na linha de comando e' justamente o caminho previsto pra V1.
_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from utils.db_utils import get_connection  # noqa: E402
from services.match_stats_service import MatchStatsService
from services.standings_service import StandingsService
from services.pick_engine import context_gate, referee_model, stats_model
from services.pick_engine.staking import calculate_stake
from services.pick_engine_live import live_odds, live_state, orchestrator
from services.pick_engine_live.config import (
    ENGINE_VERSION, AmbienteInvalido, LiveEngineConfig, exigir_ambiente_dev,
)
from services.pick_engine import competition_rules_store
from services.pick_engine_live.live_feed import (
    LiveFeed, OrcamentoEsgotado, ler_estatisticas,
)
from services.engine_audit import auditar
from engine_pipelines import decision_log
from engine_pipelines.decision_log import (
    LIVE_DUPLICATA, LIVE_NENHUM_APROVADO, LIVE_REPROVOU_TRIAGEM,
    LIVE_SEM_ESTATISTICA, LIVE_SEM_LINHA, LIVE_SEM_ORCAMENTO, PIPELINE_LIVE,
)

TZ_BR = ZoneInfo("America/Sao_Paulo")


# ─────────────────────────────────────────────────────────────────────────
# ESQUEMA
# ─────────────────────────────────────────────────────────────────────────
def criar_tabelas(cur) -> None:
    """Auto-provisiona o esquema do Live.

    Mesmo padrao de engine_pipelines/multipla_pipeline.py e dos pipelines de
    faltas/goleiros: a tabela nasce quando o pipeline roda. Isso e' o que
    mantem PRODUCAO INTACTA -- `run_migrations()` do main.py nao roda sozinha
    no deploy (gap conhecido) e nao inclui nada disto, e o backend do site nao
    cria nada disto no startup. O banco de producao so' ganha estas tabelas se
    alguem rodar o motor Live apontando pra la', de proposito.
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_live (
            id                      SERIAL PRIMARY KEY,
            fixture_id              INTEGER NOT NULL,
            match_date              DATE,
            league_id               INTEGER,
            league_name             TEXT,
            home_team_id            INTEGER,
            away_team_id            INTEGER,
            home_team_name          TEXT,
            away_team_name          TEXT,

            market                  TEXT,
            market_type             VARCHAR(40),
            line                    TEXT,
            line_value              NUMERIC,
            odd                     NUMERIC,
            bet_house               TEXT,

            -- Snapshot do instante da criacao. NUNCA e' sobrescrito: e' o que
            -- responde "o que o motor sabia quando decidiu".
            minute_at_creation      INTEGER,
            home_goals_at_creation  INTEGER,
            away_goals_at_creation  INTEGER,
            corners_at_creation     INTEGER,
            shots_at_creation       INTEGER,
            shots_on_target_at_creation INTEGER,
            dangerous_attacks_at_creation INTEGER,
            possession_home_at_creation INTEGER,
            yellow_cards_at_creation INTEGER,
            red_cards_at_creation   INTEGER,
            observed_at_creation    INTEGER,
            remaining_minutes       INTEGER,

            -- Leituras derivadas, no instante da criacao.
            pressure_home           NUMERIC,
            pressure_away           NUMERIC,
            pressure_total          NUMERIC,
            rhythm_score            NUMERIC,
            rhythm_level            VARCHAR(20),
            rhythm_trend            VARCHAR(20),
            live_signal_score       NUMERIC,
            data_freshness          VARCHAR(10),
            projected_total         NUMERIC,

            probability             NUMERIC,
            ev                      NUMERIC,
            edge                    NUMERIC,
            confidence              NUMERIC,
            stake_pct               NUMERIC,
            stake_units             INTEGER,
            reasoning               TEXT,

            odd_at_creation         NUMERIC,
            odd_timestamp           TIMESTAMP,
            odd_valid_until         TIMESTAMP,
            status                  VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
            expiration_reason       TEXT,

            engine_version          TEXT,
            engine_debug            JSONB,

            result                  TEXT,
            profit                  NUMERIC,
            created_at              TIMESTAMP DEFAULT NOW(),
            settled_at              TIMESTAMP
        );
    """)
    # ALTER aditivo: instancia que rodou uma versao anterior do motor ja tem a
    # tabela, e CREATE TABLE IF NOT EXISTS nao acrescenta coluna nenhuma
    # (mesmo gap ja documentado no main.py do pre-jogo).
    for coluna, tipo in (
        ("dangerous_attacks_at_creation", "INTEGER"),
        ("possession_home_at_creation", "INTEGER"),
        ("yellow_cards_at_creation", "INTEGER"),
        ("red_cards_at_creation", "INTEGER"),
        ("pressure_home", "NUMERIC"), ("pressure_away", "NUMERIC"),
        ("pressure_total", "NUMERIC"),
        ("rhythm_score", "NUMERIC"), ("rhythm_level", "VARCHAR(20)"),
        ("rhythm_trend", "VARCHAR(20)"), ("live_signal_score", "NUMERIC"),
        ("data_freshness", "VARCHAR(10)"), ("projected_total", "NUMERIC"),
        ("odd_timestamp", "TIMESTAMP"),
    ):
        cur.execute(f"ALTER TABLE picks_live ADD COLUMN IF NOT EXISTS {coluna} {tipo};")

    # Trava de duplicata no BANCO, nao em Python. O check "ja existe pick deste
    # jogo?" em Python e' select-then-insert e nao pega duas execucoes
    # concorrentes -- foi exatamente assim que a multipla duplicou em
    # 2026-07-25. Duas rodadas no mesmo minuto de jogo produzem a mesma chave e
    # a segunda e' absorvida pelo ON CONFLICT.
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_live_unico
        ON picks_live (fixture_id, market_type, line, minute_at_creation);
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_live_fixture ON picks_live (fixture_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_live_data ON picks_live (match_date DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_live_criacao ON picks_live (created_at DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_live_status ON picks_live (status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_live_mercado ON picks_live (market_type);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_picks_live_pendentes "
                "ON picks_live (match_date) WHERE result IS NULL;")

    # Leitura anterior de cada partida. E' o que da' JANELA e TENDENCIA: sem
    # duas leituras nao existe "escanteios nos ultimos 10 minutos", porque
    # /fixtures/statistics devolve so' o acumulado. Custo zero de API -- e'
    # subproduto de uma chamada que ja aconteceu.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS live_match_observations (
            id                        BIGSERIAL PRIMARY KEY,
            fixture_id                INTEGER NOT NULL,
            minuto                    INTEGER,
            status                    VARCHAR(10),
            corners_observado         INTEGER,
            goals_observado           INTEGER,
            shots_observado           INTEGER,
            shots_on_target_observado INTEGER,
            dangerous_attacks_observado INTEGER,
            blocked_shots_observado   INTEGER,
            possession_home           INTEGER,
            red_cards_observado       INTEGER,
            epoch                     DOUBLE PRECISION,
            observed_at               TIMESTAMP DEFAULT NOW()
        );
    """)
    for coluna, tipo in (
        ("dangerous_attacks_observado", "INTEGER"),
        ("blocked_shots_observado", "INTEGER"),
        ("possession_home", "INTEGER"),
        ("red_cards_observado", "INTEGER"),
        ("epoch", "DOUBLE PRECISION"),
    ):
        cur.execute(f"ALTER TABLE live_match_observations "
                    f"ADD COLUMN IF NOT EXISTS {coluna} {tipo};")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_live_obs_fixture
        ON live_match_observations (fixture_id, observed_at DESC);
    """)


# ─────────────────────────────────────────────────────────────────────────
# LEITURA DE APOIO (banco, custo zero de API)
# ─────────────────────────────────────────────────────────────────────────
def ligas_cadastradas(cur) -> set:
    cur.execute("SELECT league_id FROM leagues")
    return {r[0] for r in cur.fetchall()}


def baselines_por_liga(cur, league_id: int | None) -> dict:
    """Media real de escanteios e gols da liga, de `match_statistics`.

    Sem isso o modelo usa a constante global (10.2 escanteios, 2.72 gols), que
    descreve "futebol de clubes em geral" e nao a liga do jogo. Uma consulta,
    zero API. Liga sem amostra minima devolve vazio e o modelo cai na
    constante -- explicitamente, e o rastro registra qual das duas foi usada.
    """
    if not league_id:
        return {}
    try:
        cur.execute("""
            SELECT AVG(NULLIF(total_corners, 0))::float AS corners,
                   AVG(total_goals)::float             AS goals,
                   COUNT(*)                            AS n
            FROM match_statistics
            WHERE league_id = %s
              AND total_corners IS NOT NULL
              AND match_date >= NOW() - INTERVAL '400 days'
        """, (league_id,))
        linha = cur.fetchone()
    except Exception:
        return {}
    if not linha or not linha[2] or int(linha[2]) < 20:
        return {}
    saida = {}
    if linha[0]:
        saida["corners"] = float(linha[0])
    if linha[1]:
        saida["goals"] = float(linha[1])
    return saida


def baseline_do_h2h(cur, estado: dict, baseline_atual: dict) -> dict:
    """O que acontece quando ESTES DOIS times se enfrentam.

    `baselines_por_liga` descreve a liga e `baseline_do_confronto` descreve os
    dois times pelas medias DELES -- nenhuma das duas sabe o que a combinacao
    produz. E' a mesma lacuna que o rivalry_model fechou no pre-jogo, com o caso
    que o originou: "Under cartoes" aprovado num Fluminense x Vasco de volta
    valendo classificacao, porque a media dos 15 jogos de cada time e' de
    campeonato normal e nada no calculo sabia que aquele jogo nao era normal.

    RIVALIDADE MEDIDA, NAO LISTADA. Nao existe cadastro de classico aqui: se o
    par produz 13 escanteios por confronto enquanto a liga promedia 10.2, o
    excesso e' o que aconteceu, nao opiniao sobre rivalidade. Par sem historico
    mede excesso zero e nao sofre ajuste, sem ninguem decidir se "conta como
    classico".

    O ENCOLHIMENTO NAO TEM CONSTANTE NOVA. `shrink_to_baseline` e' a mesma
    funcao que o resto do motor usa pra media de amostra curta: com 2
    confrontos o numero quase nao sai do baseline, com 8 ele manda. Inventar
    aqui um teto de excesso proprio seria escolher um parametro onde ja' existe
    a formula que o projeto usa pra exatamente esta pergunta.

    CARTAO FICA DE FORA de proposito: naquela familia quem manda e' o arbitro
    (baseline_do_arbitro), que roda depois desta e sobrescreveria o valor de
    qualquer jeito. Duas correcoes empilhadas na mesma familia tambem seriam
    dois ajustes pro mesmo fenomeno.
    """
    home_id, away_id = estado.get("home_team_id"), estado.get("away_team_id")
    if not (home_id and away_id):
        return {}
    try:
        cur.execute("""
            SELECT AVG(NULLIF(total_corners, 0))::float AS corners,
                   AVG(total_goals)::float             AS goals,
                   COUNT(*)                            AS n
            FROM match_statistics
            WHERE status IN ('FT', 'AET', 'PEN')
              AND ((home_team_id = %s AND away_team_id = %s)
                OR (home_team_id = %s AND away_team_id = %s))
              AND match_date >= NOW() - INTERVAL '1095 days'
        """, (home_id, away_id, away_id, home_id))
        linha = cur.fetchone()
    except Exception:
        return {}
    if not linha or not linha[2]:
        return {}

    confrontos = int(linha[2])
    saida = {}
    for indice, familia in ((0, "corners"), (1, "goals")):
        media = linha[indice]
        referencia = baseline_atual.get(familia)
        if media is None or referencia is None:
            continue
        encolhido = stats_model.shrink_to_baseline(float(media), confrontos, referencia)
        if encolhido is not None:
            saida[familia] = encolhido
    return saida


def baseline_do_arbitro(cur, estado: dict, config: LiveEngineConfig) -> dict:
    """Pontos de cartao que ESTE arbitro costuma dar, pra usar de baseline.

    E' a mesma ideia que o pre-jogo ja' aplica em referee_model: a media da
    liga descreve a liga, a dos times descreve os times, e nenhuma das duas
    sabe quem vai apitar -- e cartao e' o mercado onde isso pesa mais. O caso
    que motivou o modelo la' (pick VIP #1579, "Cartoes Over 4.5" a 71.8%, RED
    com 4 cartoes) foi exatamente esse: o arbitro estava em 3.60 pontos por
    jogo, ABAIXO da linha, e o numero nunca chegava na conta.

    O nome vem do proprio feed ao vivo ("Nome, Pais") e e' o MESMO formato que
    match_statistics.referee guarda, entao a busca e' por igualdade -- sem
    normalizar, sem LIKE. Normalizar aqui e la' de jeitos diferentes ja' foi
    fonte de junta que nao junta neste projeto.

    Agrega de match_statistics e nao de referee_stats, pela mesma razao que a
    tela de Estatisticas: referee_stats e' por temporada e mistura competicoes,
    e o mesmo arbitro apita liga e estadual com media diferente.

    AMOSTRA CURTA NAO ENTRA INTEIRA. `shrink_to_baseline` e o minimo de jogos
    sao os mesmos do pre-jogo: com 3 jogos apitados a media crua e' ruido, mas
    tambem nao e' desprezivel -- puxar pro ponto neutro e' o meio termo que o
    resto do motor ja' usa. Sem amostra, devolve vazio e a familia cai na
    constante, com o rastro dizendo qual das duas foi usada.
    """
    arbitro = (estado.get("referee") or "").strip()
    league_id = estado.get("league_id")
    if not arbitro or not league_id:
        return {}
    try:
        cur.execute("""
            SELECT AVG(COALESCE(total_yellow_cards, 0))::float AS amarelo,
                   AVG(COALESCE(total_red_cards, 0))::float    AS vermelho,
                   COUNT(*)                                    AS n
            FROM match_statistics
            WHERE referee = %s
              AND league_id = %s
              AND status IN ('FT', 'AET', 'PEN')
              AND total_yellow_cards IS NOT NULL
              AND match_date >= NOW() - INTERVAL '400 days'
        """, (arbitro, league_id))
        linha = cur.fetchone()
    except Exception:
        return {}
    if not linha or not linha[2]:
        return {}
    jogos = int(linha[2])
    if jogos < config.cards_arbitro_min_jogos:
        return {}
    pontos = float(linha[0] or 0) + 2 * float(linha[1] or 0)
    return {"cards": stats_model.shrink_to_baseline(
        pontos, jogos, referee_model._REFEREE_CARD_POINTS_BASELINE)}


def baseline_do_confronto(cur, estado: dict) -> dict:
    """Expectativa PRE-JOGO deste confronto especifico, das medias dos dois
    times em `team_statistics`.

    E' o baseline mais informativo que existe sem gastar API: a media da liga
    descreve a liga, esta descreve os dois times que estao em campo. Cai pra
    media da liga sozinha quando os times nao tem amostra.
    """
    home_id, away_id = estado.get("home_team_id"), estado.get("away_team_id")
    league_id = estado.get("league_id")
    if not (home_id and away_id and league_id):
        return {}
    try:
        cur.execute("""
            SELECT team_id,
                   AVG(NULLIF(total_corners, 0))::float AS corners,
                   AVG(total_goals)::float              AS goals,
                   COUNT(*)                             AS n
            FROM (
                SELECT home_team_id AS team_id, total_corners, total_goals
                FROM match_statistics
                WHERE league_id = %s AND home_team_id IN (%s, %s)
                  AND match_date >= NOW() - INTERVAL '400 days'
                UNION ALL
                SELECT away_team_id AS team_id, total_corners, total_goals
                FROM match_statistics
                WHERE league_id = %s AND away_team_id IN (%s, %s)
                  AND match_date >= NOW() - INTERVAL '400 days'
            ) t
            WHERE total_corners IS NOT NULL
            GROUP BY team_id
        """, (league_id, home_id, away_id, league_id, home_id, away_id))
        linhas = cur.fetchall()
    except Exception:
        return {}

    uteis = [l for l in linhas if l[3] and int(l[3]) >= 6]
    if len(uteis) < 2:
        return {}
    corners = [l[1] for l in uteis if l[1]]
    goals = [l[2] for l in uteis if l[2]]
    saida = {}
    if len(corners) == 2:
        saida["corners"] = sum(corners) / 2
    if len(goals) == 2:
        saida["goals"] = sum(goals) / 2
    return saida


def contexto_pre_jogo(cur, estado: dict) -> dict | None:
    """Regulamento da partida pro motor Live: agregado do mata-mata e
    necessidade de tabela.

    NAO e' a previsao pre-jogo, e a distincao e' o ponto inteiro: daqui saem as
    REGRAS (o placar da ida, quem se classifica com o que, quantos pontos cada
    lado precisa na tabela). Quem responde "e o que esta' acontecendo agora" e'
    need_model, contra o placar em campo, a cada passada.

    So' banco, nenhuma requisicao de API -- o orcamento do Live nao muda por
    causa disto. `round` sai de `fixtures` quando a linha ainda existe (a
    tabela e' efemera e guarda so' jogos NS) e de `match_statistics` como
    segunda fonte, que e' onde ele sobrevive depois do apito inicial.

    None em qualquer falha: contexto e' sinal auxiliar e nunca pode derrubar a
    analise ao vivo de uma partida em andamento.
    """
    fid = estado.get("fixture_id")
    home_id, away_id = estado.get("home_team_id"), estado.get("away_team_id")
    league_id = estado.get("league_id")
    if not (fid and home_id and away_id):
        return None
    try:
        cur.execute(
            "SELECT round, season, match_datetime FROM fixtures WHERE fixture_id = %s", (fid,))
        linha = cur.fetchone()
        if not linha:
            cur.execute(
                "SELECT round, season, match_date FROM match_statistics WHERE fixture_id = %s",
                (fid,))
            linha = cur.fetchone()
        round_str, season, quando = (linha or (None, None, None))

        match_stats = MatchStatsService()
        h2h = match_stats.get_h2h_matches(home_id, away_id)
        tabela = (StandingsService().get_league_table(league_id, season)
                  if league_id and season else [])
        return context_gate.build_context(
            round_str=round_str, home_team_id=home_id, away_team_id=away_id,
            h2h_matches=h2h, league_id=league_id, season=season,
            # O baseline de cartoes alimenta so' o sinal de rivalidade, que o
            # Live nao consome (nao ha mercado de cartao na V1) -- passar None
            # deixa a rivalidade marcada como nao confiavel, que e' o correto.
            baseline_cartoes=None, league_table=tabela,
            # A DATA DESTA PARTIDA, que faltava aqui ate 2026-08-19 e cegava o
            # Live inteiro pro agregado.
            #
            # `encontrar_jogo_de_ida` so' aceita a busca estrita (a que prova
            # qual e' a ida pela inversao de mando) quando tem a janela de dias
            # pra conferir; sem `match_date` ela devolve None de proposito, e a
            # busca estrita e' a UNICA usada quando o rotulo nao traz a perna.
            # Medido no mesmo dia: a API-Football manda "Round of 16" seco pras
            # oitavas de Libertadores e Sul-Americana, entao o rotulo nunca traz
            # a perna nessas competicoes -- o Live tratava toda volta de
            # mata-mata como jogo solto, sem agregado, caindo na necessidade de
            # tabela de uma competicao que nem tem tabela naquela fase.
            match_date=quando,
        )
    except Exception as e:
        print(f"[LIVE] Contexto pre-jogo indisponivel para {fid}: {e}")
        return None


def observacoes_anteriores(cur, fixture_id: int, limite: int = 12) -> list[dict]:
    """Leituras anteriores desta partida, MAIS RECENTE PRIMEIRO."""
    try:
        cur.execute("""
            SELECT minuto, corners_observado, goals_observado, shots_observado,
                   shots_on_target_observado, dangerous_attacks_observado,
                   blocked_shots_observado, red_cards_observado, epoch
            FROM live_match_observations
            WHERE fixture_id = %s
            ORDER BY observed_at DESC
            LIMIT %s
        """, (fixture_id, limite))
        linhas = cur.fetchall()
    except Exception:
        return []
    return [{
        "minuto": r[0], "corners_observado": r[1], "goals_observado": r[2],
        "shots_observado": r[3], "shots_on_target_observado": r[4],
        "dangerous_attacks_observado": r[5], "blocked_shots_observado": r[6],
        "red_cards_observado": r[7], "epoch": r[8],
    } for r in linhas]


def gravar_observacao(cur, estado: dict) -> None:
    cur.execute("""
        INSERT INTO live_match_observations
            (fixture_id, minuto, status, corners_observado, goals_observado,
             shots_observado, shots_on_target_observado,
             dangerous_attacks_observado, blocked_shots_observado,
             possession_home, red_cards_observado, epoch)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        estado["fixture_id"], estado.get("minuto"), estado.get("status"),
        estado.get("corners_total"), estado.get("goals_total"),
        estado.get("shots_total"), estado.get("shots_on_target_total"),
        estado.get("dangerous_attacks_total"), estado.get("blocked_shots_total"),
        estado.get("possession_home"), estado.get("red_cards_total"),
        datetime.now(timezone.utc).timestamp(),
    ))


def picks_da_partida(cur, fixture_id: int) -> list[dict]:
    try:
        cur.execute("""
            SELECT market_type, line, minute_at_creation, status
            FROM picks_live
            WHERE fixture_id = %s
            ORDER BY minute_at_creation
        """, (fixture_id,))
    except Exception:
        return []
    return [{"market_type": r[0], "line": r[1], "minuto": r[2], "status": r[3]}
            for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────
# SELECAO DE PARTIDAS
# ─────────────────────────────────────────────────────────────────────────
def _minuto_de(bruto: dict) -> int | None:
    return ((bruto.get("fixture") or {}).get("status") or {}).get("elapsed")


def _data_br_do_jogo(bruto: dict):
    """Data do jogo em Brasilia. Sai do proprio fixture, nao do relogio da
    maquina: um jogo que comeca 23:30 BR e gera pick 00:10 tem que continuar
    com a data de ONTEM, igual `fixtures.match_datetime` guarda (ver
    collectors/fixture_collector_service.convert_utc_to_br_naive)."""
    iso = (bruto.get("fixture") or {}).get("date")
    if not iso:
        return datetime.now(TZ_BR).date()
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(TZ_BR).date()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_BR).date()


def selecionar_partidas(brutos: list, cur, config: LiveEngineConfig) -> tuple[list, list]:
    """(elegiveis, descartadas com motivo). Custo zero de API.

    O corte por liga cadastrada e' o que impede a rodada de olhar os ~200 jogos
    que /fixtures?live=all devolve do mundo inteiro. Sem ele, o teto de
    partidas seria alcancado por jogos de ligas que o projeto nem acompanha.
    """
    permitidas = ligas_cadastradas(cur)
    if config.ligas_permitidas:
        permitidas &= set(config.ligas_permitidas)

    elegiveis, descartadas = [], []
    for bruto in brutos or []:
        fixture = bruto.get("fixture") or {}
        fid = fixture.get("id")
        liga = (bruto.get("league") or {}).get("id")
        nome = (f"{(bruto.get('teams') or {}).get('home', {}).get('name')} x "
                f"{(bruto.get('teams') or {}).get('away', {}).get('name')}")
        status = (fixture.get("status") or {}).get("short")
        minuto = _minuto_de(bruto)

        # `categoria` separa "nao e' um jogo nosso" de "e' nosso, mas agora
        # nao da'". Sao respostas diferentes pra quem acompanha: a primeira
        # significa que nao ha o que fazer, a segunda que o jogo esta' no radar
        # e a proxima passada pode render.
        #
        # `pode_voltar` e' o que transforma isso em decisao, e por isso e' um
        # campo e nao uma leitura do texto do motivo: minuto 12' entra na janela
        # daqui a pouco, minuto 85' nunca mais volta, e as duas coisas cairiam
        # na mesma categoria "janela". E' esse booleano que alimenta
        # `fixtures_no_radar` no relatorio, que o live_watch usa pra escolher
        # entre a espera curta e a longa.
        def _fora(categoria: str, motivo: str, pode_voltar: bool) -> None:
            descartadas.append({"fixture_id": fid, "jogo": nome, "liga": liga,
                                "minuto": minuto, "categoria": categoria,
                                "motivo": motivo, "pode_voltar": pode_voltar})

        if liga not in permitidas:
            _fora("liga", f"liga {liga} nao cadastrada", False)
            continue
        if status not in ("1H", "2H", "HT"):
            _fora("status", f"status {status}", False)
            continue
        if minuto is None:
            # A API as vezes demora a publicar o minuto de um jogo que ja'
            # comecou; a proxima passada costuma ter.
            _fora("status", "sem minuto publicado", True)
            continue
        if not (config.minuto_inicial <= int(minuto) <= config.minuto_final):
            antes_da_janela = int(minuto) < config.minuto_inicial
            _fora("janela",
                  f"minuto {minuto}' fora da janela "
                  f"{config.minuto_inicial}'-{config.minuto_final}'"
                  + (" (ainda entra)" if antes_da_janela else " (ja passou)"),
                  antes_da_janela)
            continue

        anteriores = picks_da_partida(cur, fid)
        if len(anteriores) >= config.max_picks_por_partida:
            _fora("antiflood",
                  f"ja tem {len(anteriores)} pick(s), teto e' "
                  f"{config.max_picks_por_partida}", False)
            continue
        if anteriores:
            ultimo = max(p["minuto"] or 0 for p in anteriores)
            if int(minuto) - ultimo < config.minutos_entre_picks:
                _fora("antiflood",
                      f"pick recente no minuto {ultimo}' "
                      f"(intervalo minimo {config.minutos_entre_picks}')", True)
                continue

        elegiveis.append(bruto)

    # Mais perto do fim primeiro: quanto mais jogo observado, menos a
    # estimativa depende do baseline e mais ela descreve ESTA partida.
    elegiveis.sort(key=lambda b: -(_minuto_de(b) or 0))
    return elegiveis[:config.max_partidas], descartadas


def resumir_descartes(descartadas: list) -> dict:
    """Descartes agrupados, pra a rodada explicar POR QUE nao saiu sugestao.

    Ate' 2026-08-16 o relatorio imprimia "82 descartadas por liga, status,
    janela ou pick recente" e parava ai'. Como quase toda rodada descarta tudo
    (a API devolve os jogos do mundo inteiro e o projeto acompanha 8 ligas),
    essa linha era o que o usuario via praticamente sempre -- sem nenhuma
    informacao sobre o que fazer a respeito.

    `no_radar` sao os jogos DAS NOSSAS ligas que ainda podem virar pick nesta
    partida (`pode_voltar`). E' o numero acionavel: se ele for maior que zero,
    esperar cinco minutos e rodar de novo tem chance de render.
    """
    por_categoria: dict = {}
    por_liga: dict = {}
    no_radar = []

    for d in descartadas or []:
        categoria = d.get("categoria") or "?"
        por_categoria[categoria] = por_categoria.get(categoria, 0) + 1
        if categoria == "liga":
            por_liga[d.get("liga")] = por_liga.get(d.get("liga"), 0) + 1
        elif d.get("pode_voltar"):
            no_radar.append(d)

    no_radar.sort(key=lambda d: -(d.get("minuto") or 0))
    return {"por_categoria": por_categoria, "por_liga": por_liga,
            "no_radar": no_radar, "total": len(descartadas or [])}


def imprimir_descartes(resumo: dict, limite_radar: int = 8) -> None:
    """O resumo em texto. Silencioso quando nao houve descarte."""
    if not resumo["total"]:
        return

    rotulos = {"liga": "liga nao cadastrada", "status": "status/minuto",
               "janela": "fora da janela", "antiflood": "ja tem pick recente"}
    print(f"  {resumo['total']} descartada(s):")
    for categoria, n in sorted(resumo["por_categoria"].items(), key=lambda kv: -kv[1]):
        print(f"    {n:>4}  {rotulos.get(categoria, categoria)}")

    radar = resumo["no_radar"]
    if not radar:
        print("    nenhuma partida das nossas ligas pode render nesta janela.")
        return

    print(f"  no radar ({len(radar)} das nossas ligas, ainda podem render):")
    for d in radar[:limite_radar]:
        print(f"    {d['jogo']}: {d['motivo']}")
    if len(radar) > limite_radar:
        print(f"    ... e mais {len(radar) - limite_radar}")


def ja_existe_pick_equivalente(anteriores: list, candidato: dict,
                               config: LiveEngineConfig) -> str | None:
    """Este candidato e' repeticao de um pick que a partida ja tem?

    Duas formas de repeticao, e as duas sao spam:

    1. MESMA linha, mesmo mercado -- e' o mesmo pick de novo, com outro minuto.
    2. MESMO mercado, linha vizinha (Over 9.5 depois de Over 10.5 no mesmo
       jogo) -- e' a mesma tese com outra roupa, e publicar as duas faz o
       usuario apostar duas vezes na mesma coisa achando que diversificou.

    A regra de intervalo minimo entre picks (aplicada na selecao) ja corta a
    maioria; isto pega o resto.
    """
    for a in anteriores:
        if a.get("market_type") != candidato["market_type"]:
            continue
        if (a.get("line") or "").strip().lower() == candidato["line"].strip().lower():
            return f"linha identica ja publicada no minuto {a.get('minuto')}'"
        try:
            linha_anterior = float(str(a.get("line", "")).split()[-1])
        except (ValueError, IndexError):
            continue
        if abs(linha_anterior - candidato["linha"]) <= 1.0:
            return (f"linha vizinha de um pick ja publicado "
                    f"({a.get('line')} no minuto {a.get('minuto')}')")
    return None


# ─────────────────────────────────────────────────────────────────────────
# EXPLICACAO
# ─────────────────────────────────────────────────────────────────────────
#: Rotulo interno -> portugues de exibicao. O motor guarda o nivel em caixa
#: alta e sem acento porque e' chave de dado; o texto que chega no card do site
#: e' PROSA, e prosa em portugues leva acento. Sem este mapa o usuario lia
#: "pressao media" e "ritmo muito alto" numa tela onde todo o resto do produto
#: e' escrito corretamente.
_PT_NIVEL = {
    "BAIXA": "baixa", "MEDIA": "média", "ALTA": "alta", "MUITO_ALTA": "muito alta",
    "BAIXO": "baixo", "MEDIO": "médio", "ALTO": "alto", "MUITO_ALTO": "muito alto",
}


def _nivel_pt(bruto: str | None) -> str:
    if not bruto:
        return ""
    return _PT_NIVEL.get(bruto.upper(), bruto.replace("_", " ").lower())


def montar_explicacao(analise: dict, candidato: dict) -> str:
    """Por que ESTE pick, NESTE minuto.

    Descreve o que o motor observou, com numero verificavel -- nao adjetivo. E'
    o texto que separa um pick Live de um pick pre-jogo: um fala de historico,
    o outro fala do jogo que esta na tela do usuario agora.

    ESTE E' O UNICO BLOCO ACENTUADO DO ARQUIVO, e de proposito: o resto sao
    comentarios e log de terminal, mas isto aqui e' texto de PRODUTO. Vai pro
    card, na frente do assinante, num site 100% em portugues.
    """
    estado = analise["estado"]
    familia = candidato["familia"]
    info = analise["familias"][familia]
    lam = candidato["debug"]["lambda"]
    rotulo = "escanteios" if familia == "corners" else "gols"
    partes = []

    partes.append(
        f"Aos {estado['minuto']}' o jogo está {estado.get('home_goals')}x{estado.get('away_goals')} "
        f"com {candidato['observado_na_criacao']} {rotulo}."
    )

    pressao = analise.get("pressao") or {}
    if pressao.get("total") is not None:
        casa = estado.get("home_team") or "casa"
        fora = estado.get("away_team") or "visitante"
        partes.append(
            f"Pressão ofensiva: {casa} {pressao['home']['score']:.2f} "
            f"({_nivel_pt(pressao['home']['nivel'])}), {fora} {pressao['away']['score']:.2f} "
            f"({_nivel_pt(pressao['away']['nivel'])})."
        )

    janela = ((info.get("janelas") or {}).get("principal"))
    if janela:
        partes.append(
            f"Nos últimos {janela['largura_real']} minutos foram {janela['eventos']} {rotulo}."
        )

    tendencia = (info.get("tendencia") or {}).get("rotulo")
    ritmo = analise.get("ritmo") or {}
    if ritmo.get("nivel"):
        texto_tendencia = {
            "ACELERANDO": ", e o ritmo está acelerando",
            "DESACELERANDO": ", mas o ritmo está desacelerando",
        }.get(tendencia, "")
        partes.append(f"Ritmo da partida: {_nivel_pt(ritmo['nivel'])}{texto_tendencia}.")

    eventos = analise.get("eventos") or {}
    if eventos.get("vermelho_minuto") is not None:
        partes.append(f"Há um expulso desde os {eventos['vermelho_minuto']}'.")

    partes.append(
        f"A projeção para os {lam['minutos_restantes']} minutos restantes é de "
        f"{lam['lambda_residual']:.1f} {rotulo}, fechando em {info['projecao_total']:.1f} no total "
        f"contra a linha {candidato['linha']}."
    )

    mercado = candidato.get("prob_mercado")
    partes.append(
        f"A {candidato['line']} sai a {candidato['odd']:.2f}, com probabilidade estimada de "
        f"{candidato['probability']*100:.0f}%"
        + (f" contra {mercado*100:.0f}% do mercado." if mercado else ".")
    )

    conv = candidato["debug"].get("convergencia") or {}
    if conv.get("a_favor"):
        partes.append(
            f"{conv['a_favor']} dos sinais ao vivo sustentam essa direção"
            + (f" e {conv['contra']} apontam contra." if conv.get("contra") else ".")
        )
    return " ".join(partes)


# ─────────────────────────────────────────────────────────────────────────
# GRAVACAO
# ─────────────────────────────────────────────────────────────────────────
def montar_engine_debug(analise: dict, candidato: dict, config: LiveEngineConfig) -> dict:
    """Rastro estruturado. Tem que responder sozinho "por que o motor criou
    isto" meses depois, sem acesso a nenhuma API."""
    estado = analise["estado"]
    familia = candidato["familia"]
    info = analise["familias"][familia]
    return {
        "engine_version": ENGINE_VERSION,
        "config": config.resumo(),
        "baseline": {
            "valor": info.get("baseline"),
            "origem": info.get("baseline_origem"),
            "taxa": info.get("taxa"),
        },
        "current_state": {k: v for k, v in estado.items() if not k.startswith("_")},
        "folha_bruta": {"home": estado.get("_folha_home"), "away": estado.get("_folha_away")},
        "freshness": analise.get("freshness"),
        "pressure": analise.get("pressao"),
        "rhythm": analise.get("ritmo"),
        "recent_windows": info.get("janelas"),
        "trend": info.get("tendencia"),
        "events": analise.get("eventos"),
        "projection": {
            "lambda": candidato["debug"]["lambda"],
            "fator_ritmo": info.get("fator_ritmo"),
            "ajuste_estado": info.get("ajuste_estado"),
            "projecao_total": info.get("projecao_total"),
        },
        "market": {
            "line": candidato["line"],
            "line_value": candidato["linha"],
            "odd": candidato["odd"],
            "prob_mercado": candidato.get("prob_mercado"),
            "origem_prob_mercado": candidato.get("origem_prob_mercado"),
            "tem_par": candidato.get("tem_par"),
        },
        "convergence": candidato["debug"].get("convergencia"),
        "probability": candidato["probability"],
        "probability_pre_shrink": candidato.get("prob_modelo_puro"),
        "ev": candidato["ev"],
        "edge": candidato["edge"],
        "confidence": candidato["confidence"],
        "confidence_breakdown": candidato["debug"].get("confianca"),
        "decision": "PICK" if candidato["aprovado"] else "NO_PICK",
        "motivos_reprovacao": candidato.get("motivos_reprovacao"),
    }


def salvar_pick(cur, analise: dict, candidato: dict, config: LiveEngineConfig,
                match_date, casa: str | None = None) -> int | None:
    """Grava o pick com o snapshot do instante. Devolve o id, ou None quando a
    trava de duplicata absorveu a insercao."""
    estado = analise["estado"]
    familia = candidato["familia"]
    info = analise["familias"][familia]
    pressao = analise.get("pressao") or {}
    ritmo = analise.get("ritmo") or {}

    stake_pct, stake_units = calculate_stake(
        confidence=candidato["confidence"], odd=candidato["odd"],
        ev=candidato["ev"], pick_type="live",
    )
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    valido_ate = agora + timedelta(seconds=config.validade_odd_segundos)
    debug = json.dumps(montar_engine_debug(analise, candidato, config),
                       default=str, ensure_ascii=False)

    def _amarelos():
        casa_a, fora_a = estado.get("yellow_home"), estado.get("yellow_away")
        return None if casa_a is None or fora_a is None else casa_a + fora_a

    cur.execute("""
        INSERT INTO picks_live (
            fixture_id, match_date, league_id, league_name,
            home_team_id, away_team_id, home_team_name, away_team_name,
            market, market_type, line, line_value, odd, bet_house,
            minute_at_creation, home_goals_at_creation, away_goals_at_creation,
            corners_at_creation, shots_at_creation, shots_on_target_at_creation,
            dangerous_attacks_at_creation, possession_home_at_creation,
            yellow_cards_at_creation, red_cards_at_creation,
            observed_at_creation, remaining_minutes,
            pressure_home, pressure_away, pressure_total,
            rhythm_score, rhythm_level, rhythm_trend,
            live_signal_score, data_freshness, projected_total,
            probability, ev, edge, confidence, stake_pct, stake_units, reasoning,
            odd_at_creation, odd_timestamp, odd_valid_until, status,
            engine_version, engine_debug, created_at
        ) VALUES (
            %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,%s,%s,
            %s,%s,%s, %s,%s,%s, %s,%s, %s,%s, %s,%s,
            %s,%s,%s, %s,%s,%s, %s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,'ACTIVE', %s,%s, NOW()
        )
        ON CONFLICT (fixture_id, market_type, line, minute_at_creation) DO NOTHING
        RETURNING id
    """, (
        estado["fixture_id"], match_date, estado.get("league_id"), estado.get("league_name"),
        estado.get("home_team_id"), estado.get("away_team_id"),
        estado.get("home_team"), estado.get("away_team"),
        candidato["market"], candidato["market_type"], candidato["line"],
        candidato["linha"], candidato["odd"], casa,
        estado.get("minuto"), estado.get("home_goals"), estado.get("away_goals"),
        estado.get("corners_total"), estado.get("shots_total"),
        estado.get("shots_on_target_total"), estado.get("dangerous_attacks_total"),
        estado.get("possession_home"), _amarelos(), estado.get("red_cards_total"),
        candidato["observado_na_criacao"], candidato["debug"]["lambda"]["minutos_restantes"],
        (pressao.get("home") or {}).get("score"), (pressao.get("away") or {}).get("score"),
        pressao.get("total"),
        ritmo.get("score"), ritmo.get("nivel"),
        (info.get("tendencia") or {}).get("rotulo"),
        candidato.get("live_signal_score"),
        (analise.get("freshness") or {}).get("nivel"),
        info.get("projecao_total"),
        candidato["probability"], candidato["ev"], candidato["edge"],
        candidato["confidence"], stake_pct, stake_units,
        montar_explicacao(analise, candidato),
        candidato["odd"], agora, valido_ate,
        ENGINE_VERSION, debug,
    ))
    linha = cur.fetchone()
    return linha[0] if linha else None


# ─────────────────────────────────────────────────────────────────────────
# RODADA
# ─────────────────────────────────────────────────────────────────────────
# AUDITORIA (2026-08-27). Uma execucao POR RODADA, e isso e' o ponto: o motor
# ao vivo roda em laco (uma noite de 23/08 deu 91 rodadas) e ate' aqui so' a
# ULTIMA sobrevivia, em memoria no processo do site. Com um run_id por rodada,
# "em que minuto a partida morreu" passa a ter resposta em SQL.
@auditar("LIVE", "live")
def run_live_engine(fixture_id: int | None = None,
                    dry_run: bool | None = None,
                    max_partidas: int | None = None,
                    config: LiveEngineConfig | None = None) -> dict:
    """Uma passada. Devolve o relatorio da rodada (tambem impresso no stdout).

    `fixture_id`, `dry_run` e `max_partidas` sobrescrevem a config de ambiente
    -- e' o que permite `--fixture 123456 --dry-run` testar uma partida
    especifica sem varrer o mundo nem sujar o banco.
    """
    config = config or LiveEngineConfig.do_ambiente()
    if dry_run is not None:
        config = LiveEngineConfig(**{**config.__dict__, "dry_run": dry_run})
    if max_partidas is not None:
        config = LiveEngineConfig(**{**config.__dict__, "max_partidas": max_partidas})

    relatorio: dict = {
        "ok": False, "dry_run": config.dry_run, "engine_version": ENGINE_VERSION,
        "requisicoes": 0, "limite_requisicoes": config.max_requisicoes,
        "fixtures_encontradas": 0, "fixtures_elegiveis": 0,
        # Jogos das nossas ligas que nao qualificaram AGORA mas ainda podem
        # nesta partida. Nasce zerado aqui pra existir mesmo nos retornos
        # antecipados (motor desligado, ambiente errado) -- quem le nao precisa
        # saber por onde a rodada saiu.
        "fixtures_no_radar": 0, "descartes": {},
        "partidas": [], "picks_criados": [], "erros": [], "orcamento_esgotado": False,
    }

    print("\n" + "=" * 62)
    print(f"LIVE ENGINE RUN · {ENGINE_VERSION}")
    print(f"  {config.resumo()}")
    if config.dry_run:
        print("  DRY RUN: calcula e loga, nao grava pick.")
    print("=" * 62)

    if not config.habilitado:
        print("[LIVE] LIVE_ENGINE_ENABLED nao esta ligado. Nada a fazer.")
        relatorio["motivo"] = "LIVE_ENGINE_ENABLED=false"
        return relatorio

    try:
        exigir_ambiente_dev()
    except AmbienteInvalido as e:
        print(f"[LIVE] {e}")
        relatorio["motivo"] = str(e)
        relatorio["erros"].append(str(e))
        return relatorio

    feed = LiveFeed(limite_requisicoes=config.max_requisicoes)
    conn = get_connection()
    cur = conn.cursor()
    # Regulamento de mata-mata das competicoes nao cadastradas a mao, do
    # banco pra memoria, UMA vez por rodada. Sem isto o motor devolve
    # DESCONHECIDO pro formato dessas competicoes, que e' o comportamento
    # de antes -- nada quebra, so' se sabe menos.
    competition_rules_store.carregar(cur)

    try:
        criar_tabelas(cur)
        conn.commit()

        if fixture_id:
            bruto = feed.partida(int(fixture_id))
            brutos = [bruto] if bruto else []
            print(f"\nModo dirigido: fixture {fixture_id}")
        else:
            brutos = feed.partidas_ao_vivo()
        relatorio["fixtures_encontradas"] = len(brutos)

        elegiveis, descartadas = selecionar_partidas(brutos, cur, config)
        relatorio["fixtures_elegiveis"] = len(elegiveis)
        print(f"\nFixtures encontradas: {len(brutos)}")
        print(f"Fixtures elegiveis:   {len(elegiveis)}   (limite {config.max_partidas})")

        resumo_descartes = resumir_descartes(descartadas)
        relatorio["fixtures_no_radar"] = len(resumo_descartes["no_radar"])
        relatorio["descartes"] = resumo_descartes
        imprimir_descartes(resumo_descartes)

        for indice, bruto in enumerate(elegiveis, start=1):
            relatorio["partidas"].append(
                _processar_partida(indice, bruto, cur, conn, feed, config, relatorio))

    except OrcamentoEsgotado as e:
        relatorio["orcamento_esgotado"] = True
        print(f"\n[LIVE] ORCAMENTO ESGOTADO · {e}")
        print("[LIVE] Rodada encerrada sem novas chamadas.")
    except Exception as e:
        relatorio["erros"].append(str(e))
        print(f"\n[LIVE] Erro na rodada: {e}")
        print(textwrap.indent(traceback.format_exc(), "    "))
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        relatorio["requisicoes"] = feed.usadas
        relatorio["trilha_api"] = feed.trilha()
        relatorio["ok"] = not relatorio["erros"]
        cur.close()
        conn.close()

    # RETRATO DA RODADA, uma linha por passada que nao gerou nada.
    #
    # As linhas `avaliado` acima explicam a PARTIDA; esta explica a RODADA, e
    # e' a unica que responde as duas perguntas de orcamento: quantas
    # requisicoes a passada custou, e onde as partidas morreram por categoria.
    # Sem ela, uma rodada em que nenhum jogo chegou a ser elegivel nao deixa
    # rastro nenhum -- que era o caso mais comum das 91 rodadas de 23/08.
    #
    # So' e' gravada quando a rodada TERMINA SEM PICK, que e' a semantica de
    # `log_run` nos outros seis pipelines. Rodada com pick ja' esta' contada
    # nas linhas `avaliado` e em picks_live.
    if not relatorio["picks_criados"]:
        if relatorio.get("motivo"):
            motivo_rodada = relatorio["motivo"]
        elif relatorio["orcamento_esgotado"]:
            motivo_rodada = "orcamento de API esgotado no meio da rodada"
        elif not relatorio["fixtures_elegiveis"]:
            motivo_rodada = "nenhuma partida elegivel nesta passada"
        else:
            motivo_rodada = "rodou e nenhuma partida virou pick"
        decision_log.log_run(PIPELINE_LIVE, motivo_rodada, {
            "dry_run": relatorio["dry_run"],
            "engine_version": relatorio["engine_version"],
            "fixtures_encontradas": relatorio["fixtures_encontradas"],
            "fixtures_elegiveis": relatorio["fixtures_elegiveis"],
            "fixtures_no_radar": relatorio["fixtures_no_radar"],
            "descartes": (relatorio.get("descartes") or {}).get("por_categoria"),
            "requisicoes": relatorio["requisicoes"],
            "limite_requisicoes": relatorio["limite_requisicoes"],
            "erros": relatorio["erros"],
            "partidas": relatorio["partidas"],
        })

    print("\n" + "-" * 62)
    print(f"Requisicoes usadas: {feed.usadas}/{config.max_requisicoes}")
    print(f"Picks criados:      {len(relatorio['picks_criados'])}"
          + (" (dry run, nada gravado)" if config.dry_run else ""))
    if relatorio["erros"]:
        print(f"Erros:              {len(relatorio['erros'])}")
    print("-" * 62 + "\n")
    return relatorio


def _fixture_do_log(estado: dict, nome: str) -> dict:
    """A partida no formato que `decision_log` espera (mesmo dos outros seis
    pipelines), pra a consulta "o que aconteceu com este jogo" nao precisar de
    um SELECT diferente por causa do motor ao vivo."""
    casa, _, fora = nome.partition(" x ")
    return {"fixture_id": estado.get("fixture_id"),
            "home_team": casa or None, "away_team": fora or None}


def _contexto_do_log(estado: dict, fresh: dict | None = None,
                     analise: dict | None = None, **extra) -> dict:
    """O que muda de uma rodada pra outra na MESMA partida.

    Sem isto o log ao vivo seria ilegivel: a mesma partida aparece 20 vezes
    numa noite, e duas linhas identicas aos 20' e aos 70' descrevem decisoes
    completamente diferentes. Minuto e placar sao o que separa uma da outra.
    """
    ctx = {
        "minuto": estado.get("minuto"),
        "status": estado.get("status"),
        "placar": f"{estado.get('home_goals')}x{estado.get('away_goals')}",
        "league_id": estado.get("league_id"),
    }
    if fresh:
        ctx["freshness"] = fresh.get("nivel")
    if analise:
        ritmo = analise.get("ritmo") or {}
        pressao = analise.get("pressao") or {}
        ctx["ritmo"] = ritmo.get("nivel")
        ctx["ritmo_score"] = ritmo.get("score")
        ctx["pressao_total"] = pressao.get("total")
        # Observado e projecao por familia: e' o que responde "o jogo estava
        # acelerando?" sem abrir os candidatos.
        ctx["familias"] = {
            f: {"observado": i.get("observado"), "projecao": i.get("projecao_total"),
                "baseline": i.get("baseline")}
            for f, i in (analise.get("familias") or {}).items() if i.get("disponivel")
        }
    ctx.update(extra)
    return ctx


def _processar_partida(indice: int, bruto: dict, cur, conn, feed: LiveFeed,
                       config: LiveEngineConfig, relatorio: dict) -> dict:
    """Uma partida: estatistica, eventos, analise, triagem, odd (se valer),
    decisao."""
    fixture = bruto.get("fixture") or {}
    fid = fixture.get("id")
    times = bruto.get("teams") or {}
    nome = f"{(times.get('home') or {}).get('name')} x {(times.get('away') or {}).get('name')}"

    print(f"\n[{indice}] {nome}")

    resumo = {"fixture_id": fid, "jogo": nome, "decisao": "SKIP",
              "mercados_avaliados": 0, "oportunidades": 0, "odd_consultada": False}

    stats_brutas = feed.estatisticas(fid)
    home_stats, away_stats = ler_estatisticas(
        stats_brutas, (times.get("home") or {}).get("id"), (times.get("away") or {}).get("id"))

    eventos_brutos = []
    if config.buscar_eventos and feed.tem_orcamento(2):
        eventos_brutos = feed.eventos(fid)
    minuto_bruto = _minuto_de(bruto)
    eventos_lidos = live_state.ler_eventos(eventos_brutos, minuto_bruto)
    eventos = live_state.resumo_de_eventos(eventos_lidos, minuto_bruto)

    estado = live_state.montar_estado(bruto, home_stats, away_stats, eventos_lidos)
    print(f"Minuto: {estado.get('minuto')}   Placar: "
          f"{estado.get('home_goals')}x{estado.get('away_goals')}")

    # FAMILIA QUE FALTA SAI SOZINHA · nao leva a partida junto.
    #
    # Isto era tudo-ou-nada: bastava UMA familia sem dado e o jogo inteiro era
    # descartado. Era desperdicio puro, porque o orchestrator ja' e' construido
    # pra conviver com familia ausente -- ele marca `disponivel: False` com o
    # motivo e a triagem simplesmente nao considera aquela familia.
    #
    # E o custo era concreto: `goals_total` NAO sai de /fixtures/statistics, sai
    # do placar no feed de fixtures. Ou seja, mesmo com o provedor publicando
    # ZERO estatistica, gols continua sendo um numero real -- e o gate antigo
    # jogava fora a partida por causa de escanteio, levando gols junto.
    faltando = [f for f in config.familias
                if orchestrator.observado_da_familia(estado, f) is None]
    disponiveis = [f for f in config.familias if f not in faltando]

    # Fora do `if` de proposito: o log de descarte precisa dizer QUAL dos dois
    # casos foi, e a variavel so' existia dentro do ramo que imprime.
    folha_vazia = not home_stats and not away_stats
    if faltando:
        # "Nao publicou NADA" e "faltou uma familia" sao problemas diferentes: o
        # primeiro e' cobertura da partida no provedor, o segundo e' buraco de
        # mercado. Dizer sempre "corners nao publicado" escondia o primeiro
        # caso, que e' o que realmente derruba a rodada.
        motivo = ("o provedor nao publicou estatistica nenhuma desta partida"
                  if folha_vazia else f"{', '.join(faltando)} sem numero publicado")
        print(f"Sem {', '.join(faltando)}: {motivo}")

    if not disponiveis:
        print("DECISAO: SKIP")
        resumo["motivo"] = f"estatistica ausente: {', '.join(faltando)}"
        _observar(cur, conn, estado)
        decision_log.log_skip(
            PIPELINE_LIVE, _fixture_do_log(estado, nome), LIVE_SEM_ESTATISTICA,
            _contexto_do_log(estado, faltando=faltando, folha_vazia=folha_vazia))
        return resumo

    if faltando:
        print(f"Analisando so' {', '.join(disponiveis)}")

    observacoes = observacoes_anteriores(cur, fid)
    fresh = live_state.freshness(estado, observacoes, config)
    print(f"Dados: {fresh['nivel']}"
          + (f" ({'; '.join(fresh['motivos'])})" if fresh.get("motivos") else ""))

    do_arbitro = baseline_do_arbitro(cur, estado, config)
    baselines = {**baselines_por_liga(cur, estado.get("league_id")),
                 **baseline_do_confronto(cur, estado),
                 # Por ultimo de proposito: em cartao, quem apita manda mais
                 # que a media da liga e a dos times. Nas outras familias esta
                 # chamada devolve vazio e nao sobrescreve nada.
                 **do_arbitro}
    # O confronto direto refina o que sobrou · precisa do baseline ja' montado
    # como referencia do encolhimento, por isso vem depois e nao no literal.
    baselines.update(baseline_do_h2h(cur, estado, baselines))

    # CARTAO SO' COM ARBITRO CONHECIDO · a outra metade da regra do pre-jogo.
    #
    # referee_model.cards_market_eligible reprova o mercado de cartoes quando
    # nao ha arbitro confiavel, e o motivo nao e' zelo: sem quem apita, a conta
    # cai no ponto neutro (4.1) e vira "o cartao medio do futebol", que nao
    # descreve partida nenhuma. Foi assim que o pre-jogo produziu o pick #1579
    # -- e la' o arbitro ate' existia, so' nao entrava na probabilidade.
    #
    # Ao vivo o buraco seria maior: parte das ligas nem publica `referee` no
    # feed (medido em 2026-08-22: 4 de 10 partidas ao vivo tinham o campo), e
    # sem esta porta o motor cotaria cartao sem ideia nenhuma de quem esta com
    # o apito. A familia sai desta partida, e so' dela -- escanteios e gols
    # seguem normalmente.
    if "cards" in config.familias and "cards" not in do_arbitro:
        config = replace(config, familias=tuple(
            f for f in config.familias if f != "cards"))
        arbitro = (estado.get("referee") or "").strip()
        print("Cartoes fora: " + ("arbitro sem amostra minima nesta liga"
                                  if arbitro else "a partida nao publicou o arbitro"))
    pre_jogo = contexto_pre_jogo(cur, estado)
    analise = orchestrator.analisar(estado, observacoes, config, baselines, eventos, fresh,
                                    contexto_pre_jogo=pre_jogo)
    _observar(cur, conn, estado)

    pressao = analise.get("pressao") or {}
    if pressao.get("total") is not None:
        print(f"Pressao: casa {pressao['home']['score']:.2f} ({pressao['home']['nivel']}) · "
              f"fora {pressao['away']['score']:.2f} ({pressao['away']['nivel']})")
    ritmo = analise.get("ritmo") or {}
    if ritmo.get("score") is not None:
        print(f"Ritmo: {ritmo['nivel']} ({ritmo['score']:.2f}x o esperado)")
    if eventos.get("disponivel"):
        print(f"Eventos: {eventos['gols']} gol(s), {eventos['vermelhos']} vermelho(s)"
              + (f", expulsao aos {eventos['vermelho_minuto']}'"
                 if eventos.get("vermelho_minuto") is not None else ""))
    nec = analise.get("necessidade") or {}
    if nec.get("intensidade"):
        print(f"Necessidade: {nec['quem_precisa']} ({nec['origem']}), "
              f"intensidade {nec['intensidade']:.2f} · "
              + "; ".join(nec.get("descricao") or []))
        confirmacao = analise.get("confirmacao_do_contexto") or {}
        if confirmacao.get("aplicavel") and not confirmacao.get("alinhado"):
            print(f"  ATENCAO: {confirmacao['motivo']} "
                  f"(projecao descontada em {(1 - confirmacao['fator']) * 100:.0f}%)")

    for familia, info in analise["familias"].items():
        if not info.get("disponivel"):
            print(f"  {familia}: {info.get('motivo')}")
            continue
        tend = (info.get("tendencia") or {}).get("rotulo")
        janela = (info.get("janelas") or {}).get("principal")
        extra = ""
        if janela:
            extra = f" · ultimos {janela['largura_real']}': {janela['eventos']}"
        print(f"  {familia}: {info['observado']} agora · projecao {info['projecao_total']} "
              f"vs baseline {info['baseline']} ({info['baseline_origem']}) · "
              f"tendencia {tend}{extra}")

    tri = orchestrator.triagem(analise, config)
    if not tri["vale"]:
        print(f"Odd consultada: NAO ({tri['motivo']})")
        print("DECISAO: NO PICK")
        resumo.update({"decisao": "NO PICK", "motivo": tri["motivo"]})
        # A triagem e' o freio de API: aqui a partida morre SEM a odd ter sido
        # consultada. Registrar o `detalhe` (desvio por familia) e' o que
        # permite depois medir se DESVIO_MINIMO_TRIAGEM esta' frouxo ou
        # apertado, que e' a pergunta de orcamento do motor ao vivo.
        decision_log.log_skip(
            PIPELINE_LIVE, _fixture_do_log(estado, nome), LIVE_REPROVOU_TRIAGEM,
            _contexto_do_log(estado, fresh, analise, motivo_triagem=tri["motivo"],
                             triagem=tri.get("detalhes")))
        return resumo

    if not feed.tem_orcamento():
        print("Odd consultada: NAO (orcamento esgotado)")
        print("DECISAO: NO PICK")
        resumo.update({"decisao": "NO PICK", "motivo": "orcamento esgotado antes da odd"})
        decision_log.log_skip(
            PIPELINE_LIVE, _fixture_do_log(estado, nome), LIVE_SEM_ORCAMENTO,
            _contexto_do_log(estado, fresh, analise, requisicoes=feed.usadas))
        return resumo

    odds_brutas = feed.odds_ao_vivo(fid)
    resumo["odd_consultada"] = True
    cotacoes = live_odds.extrair_linhas(odds_brutas, tuple(tri["familias"]))
    print(f"Odd consultada: SIM ({len(cotacoes)} linha(s) ativa(s))")
    if not cotacoes:
        print("DECISAO: NO PICK (mercado suspenso ou nao cotado)")
        resumo.update({"decisao": "NO PICK", "motivo": "sem linha ativa nas familias triadas"})
        # Este descarte custou uma requisicao de odd. E' o unico que gasta cota
        # sem produzir candidato, entao separa-lo dos outros e' o que diz se a
        # perda vem do modelo ou do provedor.
        decision_log.log_skip(
            PIPELINE_LIVE, _fixture_do_log(estado, nome), LIVE_SEM_LINHA,
            _contexto_do_log(estado, fresh, analise,
                             familias_triadas=list(tri["familias"])))
        return resumo

    avaliados = orchestrator.avaliar(analise, cotacoes, config)
    aprovados = [c for c in avaliados if c["aprovado"]]
    resumo["mercados_avaliados"] = len(avaliados)
    resumo["oportunidades"] = len(aprovados)
    print(f"Mercados avaliados: {len(avaliados)}   Oportunidades: {len(aprovados)}")

    for c in avaliados[:6]:
        marca = "OK " if c["aprovado"] else "-- "
        motivo = "" if c["aprovado"] else f" | {c['motivos_reprovacao'][0]}"
        print(f"  {marca}{c['market']} {c['line']} @ {c['odd']:.2f} "
              f"p={c['probability']*100:.0f}% ev={c['ev']:+.1%} "
              f"conf={c['confidence']*100:.0f}% sinal={(c['live_signal_score'] or 0)*100:.0f}%{motivo}")

    melhor = orchestrator.melhor_candidato(avaliados, config)
    # Antes de `melhor` existir a consulta seria desperdicio; depois dela o
    # resultado e' necessario pro log saber o desfecho.
    repetido = (ja_existe_pick_equivalente(picks_da_partida(cur, fid), melhor, config)
                if melhor else None)

    if not melhor:
        desfecho = LIVE_NENHUM_APROVADO
    elif repetido:
        desfecho = LIVE_DUPLICATA
    else:
        desfecho = "pick (dry run)" if config.dry_run else "pick gravado"

    # UMA linha por partida avaliada, com TODOS os candidatos e o motivo de
    # reprovacao de cada um. Gravada aqui, antes dos returns, pra valer igual
    # nos quatro desfechos -- e em DRY RUN e' a unica prova de que o motor
    # teria gerado alguma coisa, porque `picks_live` fica vazia por construcao
    # e a tabela de picks nao distingue "nao achou nada" de "achou e nao podia
    # gravar".
    decision_log.log_live_decision(
        _fixture_do_log(estado, nome), avaliados,
        _contexto_do_log(estado, fresh, analise, dry_run=config.dry_run,
                         desfecho=desfecho, duplicata=repetido,
                         aprovados=len([c for c in avaliados if c["aprovado"]]),
                         requisicoes=feed.usadas),
        escolhido=melhor)

    if not melhor:
        print("DECISAO: NO PICK")
        resumo["decisao"] = "NO PICK"
        return resumo

    if repetido:
        print(f"DECISAO: NO PICK ({repetido})")
        resumo.update({"decisao": "NO PICK", "motivo": repetido})
        return resumo

    print(f"EV: {melhor['ev']:+.1%}   Confianca: {melhor['confidence']*100:.0f}%")
    if config.dry_run:
        print("DECISAO: PICK LIVE (dry run · nao gravado)")
        resumo.update({"decisao": "PICK LIVE (dry run)", "pick": _resumo_pick(melhor)})
        relatorio["picks_criados"].append({"fixture_id": fid, "dry_run": True,
                                           **_resumo_pick(melhor)})
        return resumo

    try:
        pick_id = salvar_pick(cur, analise, melhor, config, _data_br_do_jogo(bruto))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"DECISAO: ERRO ao gravar ({e})")
        resumo["decisao"] = "ERRO"
        relatorio["erros"].append(f"fixture {fid}: {e}")
        return resumo

    if pick_id is None:
        print("DECISAO: NO PICK (duplicata absorvida pela trava do banco)")
        resumo.update({"decisao": "NO PICK", "motivo": "duplicata"})
        return resumo

    print(f"DECISAO: PICK LIVE #{pick_id}")
    resumo.update({"decisao": "PICK LIVE", "pick_id": pick_id, "pick": _resumo_pick(melhor)})
    relatorio["picks_criados"].append({"pick_id": pick_id, "fixture_id": fid,
                                       "dry_run": False, **_resumo_pick(melhor)})
    return resumo


def _resumo_pick(c: dict) -> dict:
    return {
        "market": c["market"], "line": c["line"], "odd": c["odd"],
        "probability": c["probability"], "ev": c["ev"],
        "confidence": c["confidence"], "live_signal_score": c.get("live_signal_score"),
    }


def _observar(cur, conn, estado: dict) -> None:
    """Grava a leitura pra a proxima rodada ter janela e tendencia.
    Best-effort: falhar aqui nao pode derrubar a analise -- perde-se o ritmo,
    nao a rodada."""
    try:
        gravar_observacao(cur, estado)
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"  (aviso: observacao nao gravada, ritmo indisponivel na proxima: {e})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Motor de Picks Ao Vivo · uma rodada")
    parser.add_argument("--fixture", type=int, default=None,
                        help="analisa somente esta partida")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=None,
                        help="calcula e loga, nao grava")
    parser.add_argument("--gravar", dest="dry_run", action="store_false",
                        help="grava de verdade (sobrescreve LIVE_ENGINE_DRY_RUN)")
    parser.add_argument("--max", type=int, default=None, help="teto de partidas nesta rodada")
    args = parser.parse_args()
    run_live_engine(fixture_id=args.fixture, dry_run=args.dry_run, max_partidas=args.max)
