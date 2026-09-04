"""
main.py · Orquestrador único do ApostaEsportivas (sem website).

  python main.py            # lista os comandos disponíveis
  python main.py tudo       # pipeline completo do dia
  python main.py setup      # só roda as migrações do banco

A lista de comandos NÃO é repetida aqui de propósito: ela sai do registro
COMANDOS (mais abaixo), que também alimenta o HELP, o `tudo` e os menus de
run_dev.py / run_prod.py. Esta docstring já ficou desatualizada uma vez --
listava `ligas` e ignorava faltas, goleiros, player_stats e live.

ARQUITETURA DE MOTORES (2026-08-27) -- quatro motores, nao sete pipelines:

    PRE_LIVE      vip, dica, multiplas, alavancagem, faltas
    LIVE          live
    PICK_BOOST    pickboost
    PLAYER_STATS  playerstats (saves, shots_on, shots, fouls, tackles, passes)

`goleiros` FOI APAGADO em 2026-08-28, por decisao do usuario -- o comando e o
goleiros_pipeline.py que dormia no disco como rollback.

O PRODUTO NAO SAIU JUNTO, e essa e' a distincao que importa: defesas de goleiro
continua sendo gerada TODO DIA, como o metodo `saves` do Player Stats, dentro
da etapa `playerstats-diario`. O que sumiu foi um APELIDO -- `goleiros` era um
atalho pra rodar aquele unico metodo, e `playerstats saves` faz o mesmo. Dois
nomes pro mesmo trabalho e' exatamente como esta lista ja' saiu de sincronia
antes.

`picks_goleiros` tambem fica: a tabela guarda o passado do produto e continua
entrando no placar publico e na banca de quem apostou.

CUIDADO COM DOIS NOMES PARECIDOS: `player_stats` (com underline) e' o COLETOR
que busca estatistica de jogador na API e gasta cota; `playerstats` e' o MOTOR
que gera pick a partir do que ja' esta' no banco. Um custa requisicao, o outro
nao.
"""

import sys
import os
import time
import textwrap
import traceback
from dataclasses import dataclass
from typing import Callable

_AQUI = os.path.dirname(os.path.abspath(__file__))
if _AQUI not in sys.path:
    # APPEND, e nao insert(0) -- corrigido em 2026-09-04.
    #
    # Este arquivo nao roda so' como CLI. O /admin do site carrega ele POR
    # CAMINHO (`routers/admin.py::_passos_do_motor`, via exec_module) pra ler
    # `COMANDOS` e montar a sequencia do botao "Rodar Tudo" -- e um insert(0)
    # de modulo e' permanente no processo que fez isso. Dentro do backend, o
    # `src/` do motor na frente do path sombreia os modulos de topo do site
    # com nome igual: `main`, `run_dev`. A partir dai `import main` devolvia
    # ESTE arquivo em vez do app FastAPI, e 22 testes de tres arquivos
    # quebravam com "module 'main' has no attribute 'app'".
    #
    # Rodando como CLI o efeito e' o mesmo de antes: `python main.py` ja' poe
    # o proprio diretorio em sys.path[0] sozinho, entao a linha nunca foi o
    # que fazia `services`/`utils` resolverem -- ela so' cobria o caso de
    # alguem importar este arquivo de fora, que e' exatamente o caso que ela
    # estragava.
    sys.path.append(_AQUI)
os.environ.setdefault("PYTHONUNBUFFERED", "1")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from utils.db_utils import get_connection


# ─────────────────────────────────────────────────────────────
# MIGRAÇÕES
# ─────────────────────────────────────────────────────────────
def run_migrations():
    """Aplica ALTER TABLE seguros (IF NOT EXISTS) para colunas novas."""
    migrations = [
        # HORA DO JOGO NA TABELA QUE NAO SOME (2026-08-30, pedido do usuario).
        #
        # `fixtures` era a unica tabela com hora, e ela e' EFEMERA: carrega a
        # fila operacional e a linha some depois que o jogo passa. Resultado, no
        # historico publico: so' o jogo mais recente mostrava horario, o resto
        # so' a data.
        #
        # `match_statistics` e' o registro permanente (sem FK, nunca deletado),
        # entao e' onde a hora tem que morar pra sobreviver.
        #
        # EM BRASILIA SEM FUSO, igual `fixtures.match_datetime` -- e ao
        # contrario de `match_statistics.match_date`, que este mesmo collector
        # grava em UTC (ver o aviso das duas convencoes em utils/data_br.py).
        # A escolha e' pela coluna com que ela vai ser comparada e exibida, nao
        # pela vizinha de tabela.
        "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS match_datetime TIMESTAMP;",
        "ALTER TABLE picks_vip   ADD COLUMN IF NOT EXISTS market_id INTEGER;",
        "ALTER TABLE picks_free  ADD COLUMN IF NOT EXISTS market_id INTEGER;",
        "ALTER TABLE picks_vip   ADD COLUMN IF NOT EXISTS stake_units INTEGER;",
        "ALTER TABLE picks_free  ADD COLUMN IF NOT EXISTS stake_pct NUMERIC;",
        "ALTER TABLE picks_free  ADD COLUMN IF NOT EXISTS stake_units INTEGER;",
        "ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS ev_combined NUMERIC;",
        "ALTER TABLE picks_vip   ADD COLUMN IF NOT EXISTS engine_debug JSONB;",
        "ALTER TABLE picks_free  ADD COLUMN IF NOT EXISTS engine_debug JSONB;",
        # Trava contra duplicata de multipla (achado real 2026-07-25: pipeline
        # rodou 2x quase simultaneo, o check "ja existe multipla hoje" em
        # Python e' select-then-insert e nao pega corrida entre 2 execucoes
        # concorrentes -- so um indice unico no banco impede de verdade,
        # ON CONFLICT no INSERT absorve a segunda tentativa sem erro).
        # PARCIAL de proposito (so' multipla_name='MULTIPLA_ENGINE'): o
        # historico anterior a 2026-07-17 tem MULTIPLA_1 e MULTIPLA_2
        # LEGITIMOS no mesmo match_date (2 slots do sistema antigo baseado
        # em IA, nao duplicata) -- indice global quebraria contra esse
        # historico real. So o motor novo (1 multipla/dia por design) precisa
        # da trava.
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_multiplas_match_date_unique ON picks_multiplas (match_date) WHERE multipla_name = 'MULTIPLA_ENGINE';",
        # Fase 1.6 do plano de implementacao (2026-07-25): flag manual de
        # mudanca estrutural (troca de tecnico/elenco relevante) -- jogos
        # anteriores a essa data saem do historico usado pra taxa (ver
        # MatchStatsService.get_structural_change_date). NULL = sem mudanca
        # marcada, comportamento identico a hoje.
        "ALTER TABLE teams ADD COLUMN IF NOT EXISTS structural_change_date DATE;",
        # Fase 1.5 do plano de implementacao (2026-07-25): captura de
        # Closing Line Value -- tabela append-only (odds_values e' upsert e
        # perderia o valor de fechamento). Ver capture_closing_odds.py.
        """CREATE TABLE IF NOT EXISTS closing_odds (
            id            SERIAL PRIMARY KEY,
            fixture_id    INTEGER NOT NULL,
            market_id     INTEGER,
            market_type   TEXT,
            line          TEXT,
            closing_odd   NUMERIC,
            bookmaker     TEXT,
            captured_at   TIMESTAMP DEFAULT NOW()
        );""",
        "CREATE INDEX IF NOT EXISTS idx_closing_odds_fixture ON closing_odds (fixture_id);",
        """CREATE TABLE IF NOT EXISTS ai_pick_reviews (
            cache_key TEXT PRIMARY KEY,
            pipeline TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            review JSONB NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );""",
        "CREATE INDEX IF NOT EXISTS idx_ai_pick_reviews_expiry ON ai_pick_reviews (expires_at);",
        """CREATE TABLE IF NOT EXISTS ai_pick_review_events (
            id BIGSERIAL PRIMARY KEY,
            cache_key TEXT NOT NULL,
            pipeline TEXT NOT NULL,
            mode TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            decision TEXT NOT NULL,
            risk_level TEXT,
            cached BOOLEAN NOT NULL DEFAULT FALSE,
            review JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );""",
        "CREATE INDEX IF NOT EXISTS idx_ai_pick_review_events_created ON ai_pick_review_events (created_at DESC);",
        # Fase 1.7 do plano de implementacao (2026-07-25): historico de
        # execucoes de backtest, pra comparar metricas entre mudancas de
        # config/pesos ao longo do tempo em vez de so o resultado da
        # ultima rodada.
        """CREATE TABLE IF NOT EXISTS backtest_runs (
            id              SERIAL PRIMARY KEY,
            run_label       TEXT,
            commit_sha      TEXT,
            date_range_start DATE,
            date_range_end   DATE,
            config_snapshot JSONB,
            brier_score     NUMERIC,
            log_loss        NUMERIC,
            ece             NUMERIC,
            roi             NUMERIC,
            yield_pct       NUMERIC,
            n_picks         INTEGER,
            created_at      TIMESTAMP DEFAULT NOW()
        );""",
        # Pedido do usuario 2026-07-26: nao quer mercado nenhum ficando de
        # fora silenciosamente -- odds_collector_service.py agora registra
        # aqui todo bet_name pra o qual stats_model.classify_market()
        # devolve None (inclui tanto mercado novo/renomeado da API quanto
        # os ja excluidos de proposito, ex. placar exato -- a tabela nao
        # distingue os dois casos, revisao periodica que decide). Serve pra
        # revisao periodica (dashboard/consulta manual) em vez de precisar
        # descobrir mercado novo da API na unha, olhando fixture por fixture
        # como foi feito nesta sessao.
        """CREATE TABLE IF NOT EXISTS pick_engine_unclassified_markets (
            bet_name          TEXT PRIMARY KEY,
            times_seen        INTEGER DEFAULT 1,
            sample_fixture_id INTEGER,
            first_seen        TIMESTAMP DEFAULT NOW(),
            last_seen         TIMESTAMP DEFAULT NOW()
        );""",
        # Estatistica POR JOGADOR por jogo (2026-08-01). Ate agora o projeto
        # so tinha numero agregado por time em match_statistics -- nao existia
        # nenhuma entidade de jogador no banco. Vem de /fixtures/players da
        # API-Football.
        #
        # Destrava dois mercados pedidos pelo usuario:
        # - faltas por jogador (fouls_committed / fouls_drawn)
        # - defesas POR GOLEIRO (saves), hoje so' disponivel somado por time
        #   em match_statistics.home_goalkeeper_saves -- com isso o
        #   goalkeeper_model deixa de assumir que o time so' usou um goleiro.
        #
        # raw guarda o bloco de statistics original: a API muda/adiciona campo
        # sem avisar, e reprocessar do raw e' mais barato que recoletar.
        """CREATE TABLE IF NOT EXISTS player_match_stats (
            id               BIGSERIAL PRIMARY KEY,
            fixture_id       BIGINT  NOT NULL,
            player_id        BIGINT  NOT NULL,
            player_name      TEXT,
            team_id          BIGINT,
            team_name        TEXT,
            league_id        INTEGER,
            season           INTEGER,
            match_date       DATE,
            position         TEXT,
            minutes          INTEGER,
            rating           NUMERIC,
            is_substitute    BOOLEAN,
            shots_total      INTEGER,
            shots_on         INTEGER,
            goals_total      INTEGER,
            goals_conceded   INTEGER,
            assists          INTEGER,
            saves            INTEGER,
            passes_total     INTEGER,
            passes_key       INTEGER,
            tackles_total    INTEGER,
            blocks           INTEGER,
            interceptions    INTEGER,
            duels_total      INTEGER,
            duels_won        INTEGER,
            dribbles_attempts INTEGER,
            dribbles_success INTEGER,
            fouls_drawn      INTEGER,
            fouls_committed  INTEGER,
            cards_yellow     INTEGER,
            cards_red        INTEGER,
            raw              JSONB,
            created_at       TIMESTAMP DEFAULT NOW(),
            UNIQUE (fixture_id, player_id)
        );""",
        # LAST_UPDATED E MANUAL_STATS (2026-09-02). `match_statistics` tinha as
        # duas ha' tempos e `player_match_stats` nao tinha nenhuma, entao aqui
        # nao dava pra responder nem "quando este numero mudou pela ultima vez"
        # nem "este numero veio da API ou foi digitado".
        #
        # `manual_stats` guarda O QUE foi preenchido a mao, POR QUEM e QUANDO --
        # mesmo formato do gemeo em match_statistics. Ele nao substitui a coluna
        # do valor: a coluna continua sendo o numero que o motor le', e este
        # JSONB e' a procedencia. Sem isso, media de goleiro passaria a misturar
        # dado da API com dado digitado sem nenhum jeito de separar depois.
        "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP;",
        "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS manual_stats JSONB;",
        "CREATE INDEX IF NOT EXISTS idx_pms_player_date ON player_match_stats (player_id, match_date DESC);",
        "CREATE INDEX IF NOT EXISTS idx_pms_team_date   ON player_match_stats (team_id, match_date DESC);",
        "CREATE INDEX IF NOT EXISTS idx_pms_fixture     ON player_match_stats (fixture_id);",
        # Goleiro com defesas > 0 e' o recorte quente do modelo de defesas.
        "CREATE INDEX IF NOT EXISTS idx_pms_saves ON player_match_stats (player_id, match_date DESC) WHERE saves IS NOT NULL;",
        # ── Pipelines proprios de FALTAS e DEFESAS (2026-08-01) ──────────────
        # Tabelas separadas em vez de mais linhas em picks_vip/picks_free: os
        # dois mercados tem chave de negocio diferente (faltas e' por jogo,
        # defesa e' por GOLEIRO) e nao disputam o slot unico diario da Dica.
        #
        # Colunas espelham picks_free de proposito -- e' o formato que o
        # frontend, o ledger e o resolvedor de resultado ja sabem ler.
        """CREATE TABLE IF NOT EXISTS picks_faltas (
            id            SERIAL PRIMARY KEY,
            fixture_id    INTEGER,
            match_date    DATE,
            home_team     TEXT,
            away_team     TEXT,
            home_team_id  INTEGER,
            away_team_id  INTEGER,
            league_id     INTEGER,
            league_name   TEXT,
            market        TEXT,
            market_type   VARCHAR(40) DEFAULT 'fouls',
            line          TEXT,
            odd           NUMERIC,
            bet_house     TEXT,
            market_id     INTEGER,
            confidence    NUMERIC,
            prob_real     NUMERIC,
            edge          NUMERIC,
            reasoning     TEXT,
            stake_pct     NUMERIC,
            stake_units   INTEGER,
            engine_debug  JSONB,
            result        TEXT,
            profit        NUMERIC,
            created_at    TIMESTAMP DEFAULT NOW()
        );""",
        # Um pick de faltas por jogo por dia. O motor avalia varios fixtures,
        # mas nao pode gravar o mesmo jogo duas vezes se rodar de novo --
        # mesma trava (indice unico, nao check em Python) que resolveu a
        # duplicata de multipla em 2026-07-25.
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_faltas_dia_fixture ON picks_faltas (match_date, fixture_id);",
        "CREATE INDEX IF NOT EXISTS idx_picks_faltas_pendentes ON picks_faltas (match_date) WHERE result IS NULL;",
        # Defesas e' prop de JOGADOR (achado com coleta real em 2026-08-01: a
        # Betano manda bet_id 267 como "<goleiro> - <N>", nunca linha de time).
        # Por isso esta tabela tem player_id/player_name/team_id, que
        # picks_faltas nao precisa.
        """CREATE TABLE IF NOT EXISTS picks_goleiros (
            id            SERIAL PRIMARY KEY,
            fixture_id    INTEGER,
            match_date    DATE,
            home_team     TEXT,
            away_team     TEXT,
            home_team_id  INTEGER,
            away_team_id  INTEGER,
            league_id     INTEGER,
            league_name   TEXT,
            player_id     BIGINT,
            player_name   TEXT,
            team_id       INTEGER,
            team_name     TEXT,
            market        TEXT,
            market_type   VARCHAR(40) DEFAULT 'saves',
            line          TEXT,
            line_value    NUMERIC,
            odd           NUMERIC,
            bet_house     TEXT,
            market_id     INTEGER,
            confidence    NUMERIC,
            prob_real     NUMERIC,
            edge          NUMERIC,
            reasoning     TEXT,
            stake_pct     NUMERIC,
            stake_units   INTEGER,
            engine_debug  JSONB,
            result        TEXT,
            profit        NUMERIC,
            created_at    TIMESTAMP DEFAULT NOW()
        );""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_goleiros_dia_jogador ON picks_goleiros (match_date, fixture_id, player_id);",
        "CREATE INDEX IF NOT EXISTS idx_picks_goleiros_pendentes ON picks_goleiros (match_date) WHERE result IS NULL;",
        # ── Reparo do CLV cruzado (2026-08-20) ────────────────────────────
        # Ate' aqui o fechamento de uma perna era procurado em
        # `odds_snapshots` so' por (fixture_id, value_name). 'Over 4.5' existe
        # em ate' 19 mercados DIFERENTES da mesma partida, entao a consulta
        # trazia a odd de outro mercado -- escanteios Over 4.5 (odd 1.67)
        # ficava com "fechamento" 10.00, que e' a odd de Over 4.5 GOLS. O CLV
        # de escanteios saia -83% e a leitura obvia disso ("o mercado andou
        # contra o motor") era falsa.
        #
        # `market_id` e' a chave que faltava. Nulificar o que ja' foi gravado
        # e' obrigatorio: nao da' pra separar o que casou certo por acaso, e
        # dado falso alimenta decisao. As linhas voltam corrigidas (ou NULL)
        # no proximo sync do ledger.
        #
        # Idempotente: depois do primeiro sync, market_id fica preenchido nas
        # pernas que TEM mercado identificado, e a limpeza passa a atingir so'
        # multipla/alavancagem -- que sob o codigo novo ja' gravam NULL.
        "ALTER TABLE picks_ledger ADD COLUMN IF NOT EXISTS market_id INTEGER;",
        """UPDATE picks_ledger SET closing_odd = NULL, clv = NULL
           WHERE market_id IS NULL
             AND (closing_odd IS NOT NULL OR clv IS NOT NULL);""",

        # ── Arquitetura de motores (2026-08-27) ───────────────────────────
        #
        # PICK BOOST -- combinacao FIXA de dois mercados (Over 1.5 FT + Under
        # 2.5 HT). Uma linha por partida escolhida, com as duas pernas
        # abertas: `odd` e' o produto, e odd_ft/odd_ht sao as pernas, porque
        # cada uma e' apostada numa casa possivelmente diferente e cada uma
        # liquida por conta propria.
        #
        # `score` e' coluna, e nao so' um campo dentro de engine_debug: e' o
        # criterio de ORDENACAO deste motor, e criterio de ordenacao dentro de
        # JSONB nao se indexa nem se agrega direito.
        """CREATE TABLE IF NOT EXISTS picks_boost (
            id            SERIAL PRIMARY KEY,
            fixture_id    INTEGER,
            match_date    DATE,
            home_team     TEXT,
            away_team     TEXT,
            home_team_id  INTEGER,
            away_team_id  INTEGER,
            league_id     INTEGER,
            league_name   TEXT,
            market        TEXT,
            market_type   VARCHAR(40) DEFAULT 'boost_over15_under25ht',
            line          TEXT,
            odd           NUMERIC,
            odd_ft        NUMERIC,
            odd_ht        NUMERIC,
            bet_house_ft  TEXT,
            bet_house_ht  TEXT,
            market_id_ft  INTEGER,
            market_id_ht  INTEGER,
            score         NUMERIC,
            confidence    NUMERIC,
            prob_real     NUMERIC,
            prob_ft       NUMERIC,
            prob_ht       NUMERIC,
            fair_odd      NUMERIC,
            ev            NUMERIC,
            edge          NUMERIC,
            reasoning     TEXT,
            stake_pct     NUMERIC,
            stake_units   INTEGER,
            engine_debug  JSONB,
            -- Resultado das duas pernas separado do resultado do bilhete: uma
            -- perna GREEN e outra RED nao e' "meio verde", e' RED -- mas sem
            -- as duas colunas nao da' pra saber QUAL perna quebrou, que e' a
            -- unica pergunta util depois de um RED.
            result_ft     TEXT,
            result_ht     TEXT,
            result        TEXT,
            profit        NUMERIC,
            created_at    TIMESTAMP DEFAULT NOW()
        );""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_boost_dia_jogo ON picks_boost (match_date, fixture_id);",
        "CREATE INDEX IF NOT EXISTS idx_picks_boost_pendentes ON picks_boost (match_date) WHERE result IS NULL;",

        # PLAYER STATS -- props de jogador, um metodo por estatistica.
        #
        # Tabela nova e nao reuso de picks_goleiros: aquela nasceu pra UM
        # contador e o nome dela diz isso em todo lugar que a le. `method` e
        # `stat_column` sao o que a torna generica -- a liquidacao le a coluna
        # que o proprio pick nomeia, entao um metodo novo nao exige um ramo
        # novo em quem resolve resultado.
        #
        # picks_goleiros fica intacta, com o historico dela. Ela para de
        # crescer (o pipeline antigo sai do registro de comandos), e quem le
        # defesas passa a ler daqui.
        """CREATE TABLE IF NOT EXISTS picks_player_stats (
            id            SERIAL PRIMARY KEY,
            fixture_id    INTEGER,
            match_date    DATE,
            home_team     TEXT,
            away_team     TEXT,
            home_team_id  INTEGER,
            away_team_id  INTEGER,
            league_id     INTEGER,
            league_name   TEXT,
            player_id     BIGINT,
            player_name   TEXT,
            team_id       INTEGER,
            team_name     TEXT,
            position      TEXT,
            -- O metodo do motor ("saves", "shots_on", ...) e a coluna de
            -- player_match_stats que o liquida. As duas: o metodo e' o nome
            -- de produto, a coluna e' o contrato com o dado.
            method        VARCHAR(40),
            stat_column   VARCHAR(40),
            market        TEXT,
            market_type   VARCHAR(40),
            line          TEXT,
            line_value    NUMERIC,
            odd           NUMERIC,
            bet_house     TEXT,
            market_id     INTEGER,
            score         NUMERIC,
            confidence    NUMERIC,
            prob_real     NUMERIC,
            fair_odd      NUMERIC,
            edge          NUMERIC,
            ev            NUMERIC,
            reasoning     TEXT,
            stake_pct     NUMERIC,
            stake_units   INTEGER,
            engine_debug  JSONB,
            result        TEXT,
            profit        NUMERIC,
            created_at    TIMESTAMP DEFAULT NOW()
        );""",
        # `method` entra na chave: o mesmo jogador pode ter pick de chutes e de
        # faltas no mesmo jogo -- sao apostas diferentes, nao duplicata.
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_player_stats_unico ON picks_player_stats (match_date, fixture_id, player_id, method);",
        "CREATE INDEX IF NOT EXISTS idx_picks_player_stats_pendentes ON picks_player_stats (match_date) WHERE result IS NULL;",
        "CREATE INDEX IF NOT EXISTS idx_picks_player_stats_metodo ON picks_player_stats (method, match_date DESC);",

        # AUDITORIA -- as tabelas sao criadas pelo proprio Engine Audit na
        # primeira execucao (services/engine_audit/audit.py::_ensure_tables).
        # Ficam aqui tambem porque `python main.py setup` tem que deixar o
        # banco pronto SEM precisar rodar um motor antes -- e porque o painel
        # do site le estas tabelas e nao pode depender de o motor ter rodado.
        """CREATE TABLE IF NOT EXISTS engine_runs (
            run_id          TEXT PRIMARY KEY,
            engine          TEXT NOT NULL,
            method          TEXT NOT NULL,
            engine_version  TEXT NOT NULL,
            match_date      DATE NOT NULL,
            started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            finished_at     TIMESTAMP,
            status          TEXT NOT NULL,
            analisados      INTEGER NOT NULL DEFAULT 0,
            selecionados    INTEGER NOT NULL DEFAULT 0,
            descartados     INTEGER NOT NULL DEFAULT 0,
            erros           INTEGER NOT NULL DEFAULT 0,
            resumo          JSONB
        );""",
        "CREATE INDEX IF NOT EXISTS idx_engine_runs_recentes ON engine_runs (started_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_engine_runs_motor ON engine_runs (engine, method, match_date DESC);",
        """CREATE TABLE IF NOT EXISTS engine_errors (
            id          BIGSERIAL PRIMARY KEY,
            run_id      TEXT,
            engine      TEXT,
            method      TEXT,
            fixture_id  INTEGER,
            contexto    TEXT,
            erro        TEXT NOT NULL,
            traceback   TEXT,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW()
        );""",
        "CREATE INDEX IF NOT EXISTS idx_engine_errors_run ON engine_errors (run_id, created_at DESC);",
        # engine_decisions ja' existe desde 07/08 (criada pelo decision_log).
        # O CREATE aqui e' pra `setup` num banco novo: sem ele os ALTER abaixo
        # falhariam um a um num banco que ainda nao rodou pipeline nenhum --
        # nao quebraria nada (cada migracao tem rollback proprio), mas
        # imprimiria nove ERRO que nao sao erro.
        """CREATE TABLE IF NOT EXISTS engine_decisions (
            id          BIGSERIAL PRIMARY KEY,
            match_date  DATE NOT NULL,
            pipeline    TEXT NOT NULL,
            fixture_id  INTEGER,
            home_team   TEXT,
            away_team   TEXT,
            status      TEXT NOT NULL,
            reason      TEXT,
            candidates  JSONB NOT NULL DEFAULT '[]'::jsonb,
            matchup     JSONB,
            context     JSONB,
            created_at  TIMESTAMP DEFAULT NOW()
        );""",
        # Estas colunas sao o que a promove de "log de decisao" a camada de
        # analise da auditoria, sem uma tabela paralela com a mesma linha.
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS run_id TEXT;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS engine TEXT;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS method TEXT;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS engine_version TEXT;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS score NUMERIC;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS probability NUMERIC;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS odd NUMERIC;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS pick_table TEXT;",
        "ALTER TABLE engine_decisions ADD COLUMN IF NOT EXISTS pick_id BIGINT;",
        "CREATE INDEX IF NOT EXISTS idx_engine_decisions_run ON engine_decisions (run_id);",

        # -- Amostra por metrica na media do time (2026-08-28) --------------
        # `games_count` conta os jogos do time NAQUELE MANDO; esta coluna conta
        # quantos deles sustentaram CADA metrica. Os dois numeros divergem
        # sempre que a folha da partida vem incompleta, e ate' aqui o motor so'
        # tinha o primeiro -- entao o encolhimento de stats_model pesava a
        # media de escanteio por uma amostra que incluia jogo sem escanteio
        # publicado. Ver a docstring de _aggregate_games.
        "ALTER TABLE team_statistics ADD COLUMN IF NOT EXISTS games_by_stat JSONB;",
    ]
    conn = get_connection()
    cur = conn.cursor()
    for sql in migrations:
        try:
            cur.execute(sql)
            conn.commit()
            print(f"[MIGRATE] OK: {sql.strip()}")
        except Exception as e:
            # Bug real corrigido 2026-07-25: sem rollback aqui, uma falha
            # (ex.: indice unico batendo em dado duplicado preexistente)
            # deixava a transacao inteira "abortada" no Postgres -- toda
            # migracao SEGUINTE na lista falhava em cascata com "current
            # transaction is aborted", mesmo sendo um ALTER TABLE
            # completamente independente e valido.
            conn.rollback()
            print(f"[MIGRATE] ERRO: {e}")
    cur.close()
    conn.close()
    print("[MIGRATE] Migrações concluídas.\n")


# ─────────────────────────────────────────────────────────────
# COMANDOS
# ─────────────────────────────────────────────────────────────
def cmd_dados(mode: str = "fast"):
    """Coleta completa. `full` percorre a temporada inteira (liga nova/backfill).

    BUG CORRIGIDO 2026-08-06: o ramo `full` passava wc_mode="full" pra
    run_stage_4, parametro que deixou de existir quando a coleta de amistosos
    das selecoes da Copa saiu (2026-08-01) -- a assinatura virou
    run_stage_4(mode, days) e o chamador nunca foi atualizado. Resultado:
    `python main.py dados full` levantava TypeError antes de coletar
    qualquer estatistica, e as etapas 0-3 rodavam a toa. O ramo `fast`
    (run_all) nao passa por aqui, entao a rodada diaria escondia o defeito.
    """
    from atualizar_jogos import DataCollectorMain
    c = DataCollectorMain()
    if mode == "full":
        # Mesma sequencia de run_all(), so' que em modo temporada inteira --
        # delega pra run_all(mode="full") em vez de repetir a lista de etapas,
        # que foi como as duas versoes saíram de sincronia.
        c.run_all(mode="full")
    else:
        c.run_all()


def cmd_odds():
    from capturar_odds import OddsMain
    OddsMain().run()


def cmd_player_stats(limite: str = "50"):
    """Estatistica por jogador dos jogos ja encerrados que ainda nao tem.

    Fora do cmd_tudo de proposito: consome 1 requisicao da API por fixture, e
    a cota diaria ja e' disputada com a coleta de odds. Rodar sob demanda,
    ajustando o limite conforme a cota disponivel no dia.
    """
    from collectors.player_stats_collector_service import PlayerStatsCollectorService
    PlayerStatsCollectorService().coletar_pendentes(limite=int(limite))


def cmd_historico(*args):
    """Backfill de historico por time (Stage 6), sob demanda.

    Ja roda dentro de `dados`; este comando existe pra ajustar os dois numeros
    sem editar codigo -- tipicamente num dia de mata-mata de Conmebol, em que
    vale gastar mais cota pra nao analisar meio jogo.
    """
    from collectors.team_history_backfill_service import (
        TeamHistoryBackfillService, MIN_JOGOS_PADRAO, TETO_REQUISICOES_PADRAO,
    )
    min_jogos = int(args[0]) if len(args) > 0 and args[0] else MIN_JOGOS_PADRAO
    teto = int(args[1]) if len(args) > 1 and args[1] else TETO_REQUISICOES_PADRAO
    TeamHistoryBackfillService(min_jogos=min_jogos, teto_requisicoes=teto).run()


def cmd_vip():
    # Motor deterministico (pick_engine) -- decisao explicita do usuario
    # (2026-07-17) de cortar a geracao de picks pra IA em produção tambem,
    # nao so em dev. Pipelines de IA (gerar_sugestao_vip.py) ficam no
    # disco, sem uso, pra reverter rapido se precisar -- ja aconteceu
    # antes (ver memoria de projeto).
    from engine_pipelines.vip_pipeline import run_vip_engine
    run_vip_engine()


def cmd_dica():
    from engine_pipelines.dica_pipeline import run_dica_engine
    run_dica_engine()


def cmd_multiplas():
    from engine_pipelines.multipla_pipeline import run_multipla_engine
    run_multipla_engine()


def cmd_alavancagem():
    from engine_pipelines.alavancagem_pipeline import run_alavancagem_engine
    run_alavancagem_engine()


def cmd_faltas():
    from engine_pipelines.faltas_pipeline import run_faltas_engine
    run_faltas_engine()


def cmd_pick_boost():
    """Pick Boost -- Over 1.5 FT + Under 2.5 HT, escolhendo JOGOS.

    Fase 1 (27/08): grava em picks_boost e aparece na aba Auditoria dos
    Motores, mas nao publica no site. Decisao do usuario: medir alguns dias
    antes de expor.
    """
    from engine_pipelines.pick_boost_pipeline import run_pick_boost_engine
    run_pick_boost_engine()


def _metodos_diarios():
    """Metodos do Player Stats marcados pra rodar no `tudo`.

    Importado tarde pra o registro de comandos nao puxar o motor inteiro no
    import do main.py -- mesma razao de todo `cmd_*` importar dentro da funcao.
    """
    from services.player_stats_engine import methods as _cat
    return _cat.DIARIOS


def cmd_playerstats(*args):
    """Player Stats -- props de jogador (saves, chutes, faltas, desarmes...).

    Sem argumento roda os seis metodos, cada um com o proprio run_id. Com
    argumento roda so' os metodos citados: `playerstats saves shots_on`.

    ABSORVEU O MOTOR DE GOLEIROS (27/08). `cmd_goleiros` saiu do registro; o
    metodo `saves` daqui usa o MESMO goalkeeper_model, sem alteracao. O
    pipeline antigo continua no disco pra rollback.
    """
    from engine_pipelines.player_stats_pipeline import run_player_stats_engine
    from services.player_stats_engine import methods as _cat

    pedidos = [a.lower() for a in args if a]
    if not pedidos:
        run_player_stats_engine()
        return
    alvos = tuple(m for m in _cat.METODOS if m.slug in pedidos)
    desconhecidos = [p for p in pedidos if p not in _cat.POR_SLUG]
    if desconhecidos:
        print(f"[PLAYER_STATS] Metodo(s) desconhecido(s): {', '.join(desconhecidos)}. "
              f"Disponiveis: {', '.join(m.slug for m in _cat.METODOS)}")
    if alvos:
        run_player_stats_engine(alvos)


def cmd_live(*args):
    """Motor de Picks Ao Vivo · UMA rodada.

    FORA do cmd_tudo de proposito, e nao por esquecimento: o Live nao e' uma
    etapa do pipeline diario, e' um motor que so' faz sentido rodando DURANTE
    os jogos. Rodar de manha junto com o resto so' gastaria cota lendo partida
    que nem comecou. E' a unica razao que sobrou pra ele estar fora -- a antiga
    ("ainda esta em validacao") caducou em 28/08, quando a aba foi publicada.

    A trava de DB_ENV=dev saiu na mesma data, junto com as variaveis do Live no
    Railway: a rodada grava no banco pra onde o ambiente ja' aponta, e nasce
    GRAVANDO. Pra uma rodada de teste, peca o dry run na mao.

    Pra acompanhar varios jogos seguidos, o laco e'
    `engine_pipelines/live_watch.py`, que tem teto de requisicoes por sessao.

      python main.py live                    uma rodada (respeita o .env)
      python main.py live gravar             sai do dry run nesta rodada
      python main.py live fixture 123456     analisa so' essa partida
    """
    from engine_pipelines.live_pipeline import run_live_engine
    fixture_id = None
    dry_run = None
    lista = [a.lower() for a in args if a]
    if "gravar" in lista:
        dry_run = False
    if "dry" in lista or "dry-run" in lista or "dry_run" in lista:
        dry_run = True
    if "fixture" in lista:
        i = lista.index("fixture")
        if i + 1 < len(lista) and lista[i + 1].isdigit():
            fixture_id = int(lista[i + 1])
    run_live_engine(fixture_id=fixture_id, dry_run=dry_run)


def cmd_resultados():
    from atualizar_resultados_sugestoes import AIUpdateResultsMain
    AIUpdateResultsMain().update_all_results()


def cmd_shadow():
    """Modo sombra do motor de picks (Fase 3): roda pick_engine em paralelo
    aos picks já salvos pela IA hoje, só para registrar a comparação em
    logs/shadow_consensus.jsonl. Nunca escreve em tabela de produção."""
    from shadow_consensus import run_shadow_comparison
    run_shadow_comparison()


def cmd_ligas():
    from atualizar_ligas import AILeagueUpdateMain
    ai = AILeagueUpdateMain()
    ai.clear_league_analysis()
    ai.generate_league_profiles()


def cmd_tudo(mode: str = "fast"):
    """Pipeline completo diário na ordem correta.

    Cada etapa roda isolada: uma que quebre é reportada no fim e as seguintes
    continuam. Antes era chamada direta em sequência, então qualquer exceção
    abortava o resto -- em 2026-08-02 a alavancagem passou a levantar erro de
    SQL e, com ela, faltas, defesas de goleiro e a atualização de RESULTADOS
    (que nem depende das anteriores) deixariam de rodar junto, sem nenhum
    aviso além do traceback no meio do log. O admin já chamava cada pipeline
    como subprocesso separado e por isso não sofria disso; aqui a proteção
    equivalente faltava.
    """
    t0 = time.perf_counter()
    print("\n" + "="*60)
    print("PIPELINE COMPLETO · ApostaEsportivas")
    print("="*60 + "\n")

    # Goleiros entra no pipeline mesmo dependendo de player_match_stats: se a
    # tabela estiver vazia ele avisa e sai sem gravar (custo zero, nenhuma
    # chamada de API). Deixar de fora exigiria lembrar de rodar na mao no dia
    # em que o historico ficasse pronto.
    #
    # As etapas sao os proprios COMANDOS que declaram `etapa`, na ordem em que
    # aparecem no registro -- ordem do registro E ordem do pipeline. Antes esta
    # lista era escrita a mao aqui, o que ja deixou faltas e goleiros de fora
    # do `tudo` por um tempo depois de existirem.
    etapas = [c for c in COMANDOS if c.etapa]
    # So' `dados` olha pro modo; os demais adaptadores ignoram o que nao usam.
    extra_args = ("full",) if mode == "full" else ()

    falhas = []
    total_etapas = len(etapas)
    for i, comando in enumerate(etapas, start=1):
        label = comando.etapa
        print(f"\n─── [{i}/{total_etapas}] {label} " + "─" * max(0, 38 - len(label)))
        try:
            comando.executar(*extra_args)
        except Exception as e:
            falhas.append(label)
            print(f"\n[PIPELINE] Etapa {label} FALHOU: {e}")
            print(textwrap.indent(traceback.format_exc(), "    "))
            print(f"[PIPELINE] Seguindo para a próxima etapa.")

    total = time.perf_counter() - t0
    print(f"\n{'='*60}")
    if falhas:
        print(f"PIPELINE CONCLUÍDO em {total:.1f}s · {len(falhas)} etapa(s) FALHARAM: "
              f"{', '.join(falhas)}")
    else:
        print(f"PIPELINE CONCLUÍDO em {total:.1f}s · todas as etapas OK")
    print("="*60 + "\n")

    return falhas


# ─────────────────────────────────────────────────────────────
# REGISTRO DE COMANDOS · fonte única
# ─────────────────────────────────────────────────────────────
# Até 2026-08-11 a lista de comandos vivia copiada em cinco lugares: o if/elif
# do dispatch aqui embaixo, o texto do HELP, a lista de etapas do cmd_tudo, e o
# par OPCOES + run() de run_dev.py e de run_prod.py. Toda etapa nova exigia
# editar os cinco, e o que acontecia na prática era esquecer alguns:
#
#   · `faltas` e `goleiros` rodavam dentro do `tudo` mas só ganharam opção
#     avulsa nos wrappers semanas depois -- em prod não dava pra rodar um dos
#     dois sem passar o pipeline inteiro;
#   · `player_stats` respondia no dispatch mas nunca apareceu no HELP;
#   · `shadow` existia só no run_dev, `ligas` em nenhum dos dois wrappers;
#   · `live` (2026-08-11) nasceu inalcançável pelo run_dev, justamente o
#     wrapper do único ambiente onde ele aceita rodar.
#
# Agora a lista mora aqui e os outros quatro derivam dela: acrescentar um
# Comando basta pra ele aparecer no HELP, no dispatch, no `tudo` (se declarar
# `etapa`) e nos menus dos ambientes que ele declarar em `ambientes`.
@dataclass(frozen=True)
class Comando:
    nome: str                    # como se digita: `python main.py <nome>`
    label: str                   # rótulo no menu de run_dev.py / run_prod.py
    ajuda: str                   # linha correspondente do HELP
    executar: Callable           # recebe os args crus que vieram depois do nome
    etapa: str = ""              # rótulo dentro do `tudo`; vazio = fora dele
    ambientes: tuple = ("dev", "prod")
    uso: str = ""                # forma no HELP quando difere do nome ("dados [full]")
    detalhe: str = ""            # linhas extras do HELP, uma por linha


def _tem(args: tuple, palavra: str) -> bool:
    return any(a and a.lower() == palavra for a in args)


COMANDOS: tuple = (
    # --- Etapas do pipeline diário, NESTA ordem (é a ordem do `tudo`) --------
    Comando("dados", "Atualizar jogos (completo)",
            "Atualiza jogos, stats, classificação",
            lambda *a: cmd_dados(mode="full" if _tem(a, "full") else "fast"),
            etapa="DADOS", uso="dados [full]"),
    # COLETA DE ESTATISTICA DE JOGADOR · entrou no `tudo` em 2026-08-28.
    #
    # A razao que a mantinha fora se inverteu. O comentario antigo dizia "1
    # requisicao por fixture, disputa a cota das odds, por isso roda sob
    # demanda" -- e continua verdade sobre o CUSTO. O que mudou e' o que o
    # custo compra: enquanto nada lia `player_match_stats`, coletar era gasto
    # puro. Agora o motor de jogador roda TODO DIA (etapa PICKS DE JOGADOR) e a
    # aba Jogadores esta' publicada pro assinante.
    #
    # Deixar o coletor de fora era rodar o motor sobre uma tabela que so' enche
    # quando alguem lembra de clicar -- e o sintoma seria o pior tipo: aba
    # vazia, sem erro nenhum, indistinguivel de "hoje nao teve oportunidade".
    #
    # O CUSTO E' LIMITADO E PREVISIVEL: teto de 50 fixtures por rodada, e o
    # rodizio por liga reparte esse teto entre as ligas com fila em vez de
    # gastar tudo nas duas que jogaram ontem (ver coletar_pendentes).
    #
    # ANTES DAS ODDS (28/08, ordem pedida pelo usuario).
    #
    # Nasceu depois, com a justificativa de que odd alimenta TODOS os motores e
    # estatistica de jogador alimenta um, entao quem devia ficar sem cota era o
    # segundo. O usuario inverteu, e a inversao tem uma razao propria: esta
    # etapa e' a UNICA com teto fixo (50 fixtures) e fila que so' cresce. A
    # coleta de odds nao tem teto -- ela pede o que o dia tiver -- entao numa
    # ordem ela cede um pedaco previsivel, e na outra ela toma um pedaco que
    # varia com o tamanho da rodada. Com o teto na frente, o custo de jogador e'
    # conhecido antes de a coleta grande comecar.
    #
    # A ordem tambem casa com a dependencia: a estatistica coletada aqui e' o
    # historico que o motor de jogador vai ler algumas etapas abaixo, e ela e'
    # de jogo JA ENCERRADO. Odd e' do jogo de hoje. Sao filas diferentes, e
    # nenhuma delas espera pela outra.
    Comando("player_stats", "Estatistica de jogador (API)",
            "Coleta estatística por jogador dos jogos encerrados (limite: 50)",
            lambda *a: cmd_player_stats(a[0] if a else "50"),
            uso="player_stats [limite]", etapa="ESTATISTICA DE JOGADOR"),
    Comando("odds", "Capturar odds",
            "Coleta odds pré-jogo",
            lambda *a: cmd_odds(), etapa="ODDS"),
    Comando("vip", "Gerar picks VIP (motor)",
            "Gera picks VIP do dia",
            lambda *a: cmd_vip(), etapa="PICKS VIP"),
    Comando("dica", "Gerar pick Free (motor)",
            "Gera pick free (Dica do Dia)",
            lambda *a: cmd_dica(), etapa="DICA DO DIA"),
    Comando("multiplas", "Gerar múltipla (motor)",
            "Gera múltipla do dia",
            lambda *a: cmd_multiplas(), etapa="MÚLTIPLA"),
    Comando("alavancagem", "Gerar alavancagem (motor)",
            "Gera pick de alavancagem",
            lambda *a: cmd_alavancagem(), etapa="ALAVANCAGEM"),
    # Faltas e' METODO do Pre Live desde 27/08, nao motor independente. O
    # pipeline continua sendo um arquivo proprio por razao tecnica (o
    # fouls_model nao e' parametrico e nao cabe no ranking generico -- ver a
    # docstring dele), e o rotulo aqui reflete a taxonomia nova.
    Comando("faltas", "Pré Live · mercado de faltas",
            "Gera picks de faltas (método do Pré Live)",
            lambda *a: cmd_faltas(), etapa="FALTAS"),
    # A ETAPA DEIXOU DE SER SO' DEFESAS (2026-08-28, decisao do usuario).
    #
    # `goleiros` continuava sendo o unico metodo do Player Stats na rodada
    # diaria -- heranca de quando defesas era um motor inteiro. Agora a etapa e'
    # o Player Stats com os metodos marcados `diario=True` no catalogo: defesas,
    # chutes no alvo e chutes.
    #
    # O COMANDO `goleiros` FOI APAGADO no mesmo dia, junto com o
    # goleiros_pipeline.py. Ele era um atalho pra rodar UM metodo do Player
    # Stats, e `playerstats saves` ja' faz exatamente isso -- manter os dois
    # era manter dois nomes pro mesmo trabalho, que e' como a lista de comandos
    # ja' saiu de sincronia antes. Defesas continua sendo gerada todo dia
    # dentro de `playerstats-diario`; o que sumiu foi o apelido.
    Comando("playerstats-diario", "Player Stats · os metodos do dia",
            "Gera props de jogador dos métodos que rodam todo dia "
            "(defesas, chutes no alvo, chutes)",
            lambda *a: cmd_playerstats(*[m.slug for m in _metodos_diarios()]),
            etapa="PICKS DE JOGADOR"),
    # Pick Boost e' etapa desde 2026-08-28 (publicado pro assinante, com um pick
    # gratuito por dia). A POSICAO importa: tem que ser antes de `resultados`,
    # senao o pick nasce depois da liquidacao e fica pendente ate' o dia
    # seguinte. Ele estava no fim do registro, na secao "fora do pipeline", e
    # so' declarar `etapa` o colocaria DEPOIS de resultados na ordem do `tudo`.
    Comando("pickboost", "Pick Boost · Over 1.5 FT + Under 2.5 HT",
            "Escolhe os melhores JOGOS do dia para a combinação fixa",
            lambda *a: cmd_pick_boost(), etapa="PICK BOOST"),
    Comando("resultados", "Atualizar resultados (VIP+Free+Mult+Alav)",
            "Atualiza resultados de todos os picks",
            lambda *a: cmd_resultados(), etapa="RESULTADOS"),

    # --- O comando que roda todas as etapas acima de uma vez ----------------
    # Fica logo depois delas pra cair no numero 10 dos menus, que e' onde os
    # wrappers ja o tinham.
    Comando("tudo", "Tudo: jogos + odds + picks + resultados",
            "Pipeline completo na ordem correta",
            lambda *a: cmd_tudo(mode="full" if _tem(a, "full") else "fast"),
            uso="tudo [full]"),

    # --- Fora do pipeline diário (sem `etapa`) ------------------------------
    #
    # PLAYER STATS (completo) fica FORA do `tudo`, e nao por esquecimento --
    # e' o mesmo criterio que ja' mantem o `live` de fora: motor sem historico
    # medido nao vira custo fixo da rodada diaria, e os outros cinco metodos do
    # Player Stats nunca geraram um pick real.
    #
    # PICK BOOST SAIU DESTA LISTA em 2026-08-28: ele foi publicado pro
    # assinante (com um pick gratuito por dia), e produto publicado tem que ser
    # gerado todo dia -- senao a aba abre vazia sem ninguem saber por que. Ele
    # subiu pra etapa do `tudo`, la' em cima.
    #
    # A excecao e' `goleiros`, que segue como etapa la' em cima: aquele metodo
    # JA' rodava em producao todo dia, e tira-lo do `tudo` seria uma regressao
    # de produto disfarcada de reorganizacao.
    #
    # Entram no `tudo` quando tiverem resultado medido. Ate' la', na mao.
    Comando("playerstats", "Player Stats · props de jogador",
            "Gera props de jogador (saves, chutes, faltas, desarmes, passes)",
            lambda *a: cmd_playerstats(*a),
            uso="playerstats [metodo ...]",
            detalhe="playerstats             roda os seis métodos\n"
                    "playerstats saves       roda só defesas de goleiro"),
    Comando("shadow", "Modo sombra (log IA vs motor)",
            "Motor de picks em modo sombra (só log, não afeta picks)",
            lambda *a: cmd_shadow(), ambientes=("dev",)),
    # Roda sozinho dentro do `dados` (Stage 6). Aqui é a versão sob demanda,
    # para forçar um limiar maior ou liberar mais cota num dia de mata-mata.
    Comando("historico", "Historico por time (API)",
            "Busca os últimos jogos de quem está abaixo do mínimo no banco",
            lambda *a: cmd_historico(*a),
            uso="historico [min_jogos] [teto]",
            detalhe="historico               padrão: abaixo de 10 jogos, teto de 60 requisições\n"
                    "historico 15 200        exige 15 jogos e libera 200 requisições"),
    # Só dev: cmd_live recusa rodar sem DB_ENV=dev (pick_engine_live/config).
    # Estar no menu do run_prod seria oferecer um botão que só sabe recusar.
    Comando("live", "Motor Ao Vivo · uma rodada (dry run)",
            "Motor Ao Vivo · UMA rodada (DEV apenas, dry run por padrão)",
            lambda *a: cmd_live(*a), ambientes=("dev",),
            detalhe="live                    respeita o .env\n"
                    "live gravar             grava de verdade nesta rodada\n"
                    "live fixture 123456     analisa só essa partida"),
    Comando("ligas", "Atualizar perfis de ligas (IA)",
            "Atualiza perfis de ligas (IA · consome crédito da Anthropic)",
            lambda *a: cmd_ligas()),
)

COMANDOS_POR_NOME = {c.nome: c for c in COMANDOS}


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
def _montar_help() -> str:
    largura = max([len(c.uso or c.nome) for c in COMANDOS] + [len("setup")])
    linhas = ["", "Comandos disponíveis:"]
    for c in COMANDOS:
        linhas.append(f"  {(c.uso or c.nome).ljust(largura)}  {c.ajuda}")
        for extra in c.detalhe.splitlines():
            linhas.append(f"  {' ' * largura}    {extra}")
    linhas.append(f"  {'setup'.ljust(largura)}  Roda apenas as migrações do banco")
    return "\n".join(linhas) + "\n"


HELP = _montar_help()

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        sys.exit(0)

    cmd = args[0].lower()
    alvo = COMANDOS_POR_NOME.get(cmd)

    if cmd != "setup" and alvo is None:
        print(f"Comando desconhecido: '{cmd}'\n{HELP}")
        sys.exit(1)

    # Migracao so' pelo `setup` (2026-08-28). Antes toda etapa rodava a lista
    # inteira de ALTER TABLE antes de trabalhar: dezenas de comandos DDL e um
    # commit cada, a cada `pickboost`/`vip`/`dados`, pra um esquema que ja'
    # esta criado ha' meses. O `live` ja' era excecao pela mesma razao (o
    # motor Live provisiona o proprio esquema); agora a regra vale pra todos.
    # O preco e' explicito: coluna nova so' entra depois de rodar
    # `python main.py setup` na mao no ambiente -- inclusive em PROD.
    if cmd == "setup":
        run_migrations()

    if cmd != "setup":
        # Sai com codigo != 0 quando o comando reporta falha -- hoje so' o
        # `tudo` devolve algo (a lista de etapas que quebraram). As etapas dele
        # sao isoladas e o pipeline nao aborta no meio, entao sem isso um
        # "tudo" com falha sairia 0 e quem chama por subprocesso -- admin,
        # scripts -- leria como sucesso.
        if alvo.executar(*args[1:]):
            sys.exit(1)
