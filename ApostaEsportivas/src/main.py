"""
main.py · Orquestrador único do ApostaEsportivas (sem website).

Uso:
  python main.py dados            # Atualiza jogos, stats e classificação
  python main.py dados full       # Temporada completa (liga nova)
  python main.py odds             # Coleta odds pré-jogo
  python main.py vip              # Gera picks VIP do dia
  python main.py dica             # Gera pick free (Dica do Dia)
  python main.py multiplas        # Gera múltipla do dia
  python main.py alavancagem      # Gera pick de alavancagem
  python main.py resultados       # Atualiza resultados de todos os picks
  python main.py ligas            # Atualiza perfis de ligas (IA)
  python main.py tudo             # Pipeline completo: dados → odds → picks → resultados
  python main.py tudo full        # Pipeline completo com coleta total de stats
  python main.py setup            # Só roda as migrações do banco
"""

import sys
import os
import time
import textwrap
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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


def cmd_goleiros():
    from engine_pipelines.goleiros_pipeline import run_goleiros_engine
    run_goleiros_engine()


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
    etapas = [
        ("DADOS",               lambda: cmd_dados(mode=mode)),
        ("ODDS",                cmd_odds),
        ("PICKS VIP",           cmd_vip),
        ("DICA DO DIA",         cmd_dica),
        ("MÚLTIPLA",            cmd_multiplas),
        ("ALAVANCAGEM",         cmd_alavancagem),
        ("FALTAS",              cmd_faltas),
        ("DEFESAS DE GOLEIRO",  cmd_goleiros),
        ("RESULTADOS",          cmd_resultados),
    ]

    falhas = []
    total_etapas = len(etapas)
    for i, (label, funcao) in enumerate(etapas, start=1):
        print(f"\n─── [{i}/{total_etapas}] {label} " + "─" * max(0, 38 - len(label)))
        try:
            funcao()
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
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
HELP = """
Comandos disponíveis:
  dados [full]     Atualiza jogos, stats, classificação
  odds             Coleta odds pré-jogo
  vip              Gera picks VIP do dia
  dica             Gera pick free (Dica do Dia)
  multiplas        Gera múltipla do dia
  alavancagem      Gera pick de alavancagem
  faltas           Gera picks de faltas (Over 22.5 total do jogo)
  goleiros         Gera picks de defesas por goleiro (prop de jogador)
  resultados       Atualiza resultados de todos os picks
  ligas            Atualiza perfis de ligas (IA)
  tudo [full]      Pipeline completo na ordem correta
  setup            Roda apenas as migrações do banco
  shadow           Motor de picks em modo sombra (só log, não afeta picks)
"""

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        sys.exit(0)

    cmd = args[0].lower()
    extra = args[1].lower() if len(args) > 1 else ""

    run_migrations()

    if cmd == "setup":
        pass  # migrações já rodaram acima

    elif cmd == "dados":
        cmd_dados(mode="full" if extra == "full" else "fast")

    elif cmd == "odds":
        cmd_odds()

    elif cmd == "player_stats":
        cmd_player_stats(extra or "50")

    elif cmd == "vip":
        cmd_vip()

    elif cmd == "dica":
        cmd_dica()

    elif cmd == "multiplas":
        cmd_multiplas()

    elif cmd == "alavancagem":
        cmd_alavancagem()

    elif cmd == "faltas":
        cmd_faltas()

    elif cmd == "goleiros":
        cmd_goleiros()

    elif cmd == "resultados":
        cmd_resultados()

    elif cmd == "shadow":
        cmd_shadow()

    elif cmd == "ligas":
        cmd_ligas()

    elif cmd == "tudo":
        # Sai com codigo != 0 quando alguma etapa falhou: as etapas agora sao
        # isoladas (o pipeline nao aborta mais no meio), entao sem isso um
        # "tudo" com falha sairia 0 e quem chama por subprocesso -- admin,
        # scripts -- leria como sucesso.
        if cmd_tudo(mode="full" if extra == "full" else "fast"):
            sys.exit(1)

    else:
        print(f"Comando desconhecido: '{cmd}'\n{HELP}")
        sys.exit(1)
