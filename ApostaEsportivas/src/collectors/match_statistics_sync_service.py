import os
import sys
import psycopg2
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection
from utils.stat_sheet import folha_publicada, ler_valor, somar

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida")

HEADERS = {"x-apisports-key": API_KEY}

FIXTURES_URL = "https://v3.football.api-sports.io/fixtures"
STATS_URL = "https://v3.football.api-sports.io/fixtures/statistics"


def load_leagues_from_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT league_id, season FROM leagues WHERE COALESCE(ativa, TRUE);")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"league_id": r[0], "season": r[1]} for r in rows]


def extract_stat(stats, stat_name, publicada=None):
    """Valor do contador, ou None quando a API nao publicou esse numero.

    A regra mora em utils/stat_sheet -- inclusive a distincao que faltava aqui
    e' que custou 87% da amostra de cartoes: numa folha PUBLICADA, `value:
    null` num contador significa ZERO, e "Red Cards" e' o unico tipo que a API
    escreve assim. Devolver None nesse caso apagava o vermelho de todo jogo em
    que ninguem foi expulso (agosto/2026: 95 jogos FT, 12 com vermelho no
    banco, ZERO com vermelho igual a zero).

    Folha ausente continua virando None em tudo -- e' o bug de 2026-07-25, que
    deixou 99 jogos FT com escanteio, falta e chute todos em 0, e a invariante
    1 de services/settlement.py.
    """
    return ler_valor(stats, stat_name, publicada)


def _sum_stats(*parts):
    """Total que respeita ausencia: parcela desconhecida -> total desconhecido."""
    return somar(*parts)


class MatchStatisticsSyncService:

    def __init__(self):
        self.conn = None
        self.cur = None

    def _open(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor()
        self._ensure_columns()

    def _ensure_columns(self):
        """Colunas que nasceram depois da tabela.

        PLACAR DOS 90 MINUTOS, separado do placar final.

        `goals` da API-Football e' o placar do jogo inteiro: num jogo decidido
        na prorrogacao ele ja' inclui os gols do tempo extra (Belgium x
        Senegal, fixture 1567308: goals 3x2, mas score.fulltime 2x2). Casa de
        aposta liquida Over/Under e 1X2 pelos 90 minutos -- liquidar pelo 3x2
        e' liquidar por um jogo que o apostador nao apostou.

        Auto-provisionado aqui (mesmo padrao de
        services/picks_ledger_sync_service.py::_create_table_if_needed) porque
        migracao em PROD nao roda sozinha depois do merge.
        """
        for coluna in ("home_goals_90", "away_goals_90"):
            self.cur.execute(
                f"ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS {coluna} INTEGER;")

        # RODADA (2026-08-11). `fixtures.round` sempre existiu, mas
        # fixture_status_sync DELETA a linha da fixture assim que o jogo acaba
        # -- entao a rodada existia enquanto o jogo era futuro e sumia depois.
        # match_statistics e' o registro permanente e nao tinha onde guardar.
        #
        # Sem ela nao da' pra dizer de que fase foi um jogo passado: a
        # inferencia de ida/volta precisou virar heuristica de data, e a tela de
        # estatistica nao consegue recortar por rodada.
        self.cur.execute(
            "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS round TEXT;")
        self.conn.commit()

    def _close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    # ---------------------------------------------------------
    # LOAD FIXTURES (COM GOLS)
    # ---------------------------------------------------------
    def _load_fixtures(self, use_date_filter=True, days=3, apenas_liga=None):
        leagues = load_leagues_from_db()
        league_ids = tuple([l["league_id"] for l in leagues])
        if apenas_liga is not None:
            # Backfill de liga recem-cadastrada: sem esse recorte, "temporada
            # inteira" significa a temporada inteira de TODAS as ligas, e o
            # custo em requisicao (uma por jogo) e' o que ja' estourou a cota
            # uma vez -- ver o comentario da coleta de amistosos em
            # atualizar_jogos.py.
            league_ids = tuple(lid for lid in league_ids if lid == apenas_liga)
            if not league_ids:
                print(f"[MATCH_STATS] Liga {apenas_liga} nao esta cadastrada em `leagues`.")
                return []

        self.cur.execute(
            "SELECT team_id FROM teams WHERE league_id IN %s;", (league_ids,))
        valid_team_ids = {row[0] for row in self.cur.fetchall()}

        if not valid_team_ids:
            print("[MATCH_STATS] AVISO: tabela 'teams' está vazia ou sem times para as ligas cadastradas · nenhum jogo será carregado.")
            print("[MATCH_STATS] Execute o Stage 1 (sync de times) antes do Stage 4.")

        # Jogos cuja estatística já está no banco E já estabilizou. Sem isso o
        # Stage 4 rebaixava /fixtures/statistics de TODO jogo finalizado da
        # janela (ATUALIZAR_JOGOS_DAYS, padrão 7), todo dia -- o mesmo jogo era
        # baixado 7 vezes, uma requisição cada.
        #
        # O corte é `last_updated > match_date + 24h` em vez de "existe no
        # banco" porque a API-Football revisa contagem de escanteios/cartões
        # algumas horas depois do apito final (é a razão de existir o
        # reverify_recent_stats_results em routers/live.py). Com essa regra cada
        # jogo é coletado no máximo 2 vezes: logo após o FT e uma vez no dia
        # seguinte, que é quando o número já não muda mais.
        #
        # A folha tem que estar COMPLETA pra o jogo contar como estabilizado:
        # linha com escanteios/faltas/chutes em NULL e' justamente aquela em
        # que a API respondeu sem estatistica, e e' a que mais precisa de uma
        # segunda passada. Sem essa condicao o jogo seria pulado pra sempre
        # com a folha vazia.
        self.cur.execute("""
            SELECT fixture_id FROM match_statistics
            WHERE last_updated IS NOT NULL
              AND last_updated > match_date + INTERVAL '24 hours'
              AND total_corners IS NOT NULL
              AND total_yellow_cards IS NOT NULL
              -- VERMELHO entra na definicao de "folha completa" desde
              -- 2026-08-26. Sem ele, o jogo cuja unica lacuna era o vermelho
              -- era pulado PRA SEMPRE (a coleta so' volta em folha
              -- incompleta) -- e essa era a lacuna de 87% dos jogos.
              AND total_red_cards IS NOT NULL
              AND home_fouls IS NOT NULL
              AND home_total_shots IS NOT NULL
        """)
        settled_fixture_ids = {row[0] for row in self.cur.fetchall()}

        fixtures = []
        skipped = 0
        rodadas_a_gravar: list = []

        if use_date_filter:
            limit_date = datetime.now(timezone.utc) - timedelta(days=days)

        for lg in leagues:
            params = {
                "league": lg["league_id"],
                "season": lg["season"]
            }

            r = requests.get(FIXTURES_URL, headers=HEADERS, params=params)
            r.raise_for_status()

            response = r.json().get("response", [])

            for fx in response:
                fixture = fx["fixture"]
                teams = fx["teams"]
                goals = fx["goals"]

                status = fixture["status"]["short"]

                if status not in ("FT", "AET", "PEN"):
                    continue

                match_date = datetime.fromisoformat(
                    fixture["date"].replace("Z", "+00:00")
                )

                if use_date_filter and match_date < limit_date:
                    continue

                home_id = teams["home"]["id"]
                away_id = teams["away"]["id"]

                if home_id not in valid_team_ids or away_id not in valid_team_ids:
                    continue

                # A RODADA E' GRAVADA MESMO NO JOGO JA ESTABILIZADO.
                #
                # `league.round` vem nesta mesma resposta e ate' 2026-08-11 era
                # descartado: ficava so' em `fixtures`, e fixture_status_sync
                # DELETA a linha assim que o jogo acaba (FT/AET/PEN e afins).
                # Ou seja, a rodada existia enquanto o jogo era futuro e sumia
                # depois -- match_statistics, que e' o registro permanente, nao
                # tinha a coluna. Sem ela nao da' pra dizer de que fase foi um
                # jogo passado, e a inferencia de ida/volta precisou virar
                # heuristica de data (ver match_context_model.inferir_leg).
                #
                # Fica ANTES do `continue` de propósito: preenche o historico
                # inteiro na proxima passada, sem UMA requisicao a mais.
                rodada = (fx.get("league") or {}).get("round")
                if rodada:
                    rodadas_a_gravar.append((rodada, fixture["id"]))

                if fixture["id"] in settled_fixture_ids:
                    skipped += 1
                    continue

                score = fx.get("score", {}) or {}
                ht = score.get("halftime") or {}
                ft90 = score.get("fulltime") or {}

                fixtures.append({
                    "fixture_id": fixture["id"],
                    "league_id": lg["league_id"],
                    "season": lg["season"],
                    "home_id": home_id,
                    "away_id": away_id,
                    "match_date": match_date,
                    "status": status,
                    "home_goals": goals["home"] or 0,
                    "away_goals": goals["away"] or 0,
                    "home_goals_ht": ht.get("home"),
                    "away_goals_ht": ht.get("away"),
                    "home_goals_90": ft90.get("home"),
                    "away_goals_90": ft90.get("away"),
                    "referee": fixture.get("referee"),
                })

        self._gravar_rodadas(rodadas_a_gravar)

        print(f"[INFO] {len(fixtures)} jogos carregados "
              f"({skipped} pulados · estatística já estabilizada no banco)")
        return fixtures

    def _gravar_rodadas(self, pares: list):
        """Grava `round` nos jogos que ainda nao tem, em lote.

        Idempotente e barato: nao chama API nenhuma (o dado ja veio junto da
        listagem de fixtures) e so' escreve onde esta faltando, entao rodar
        todo dia nao gera escrita a toa."""
        if not pares:
            return
        from psycopg2.extras import execute_values
        execute_values(self.cur, """
            UPDATE match_statistics ms
               SET round = dados.round
              FROM (VALUES %s) AS dados(round, fixture_id)
             WHERE ms.fixture_id = dados.fixture_id
               AND ms.round IS DISTINCT FROM dados.round
        """, pares)
        if self.cur.rowcount > 0:
            print(f"[MATCH_STATS] rodada gravada em {self.cur.rowcount} jogo(s).")
        self.conn.commit()

    def _fetch_match_stats(self, fixture_id):
        r = requests.get(STATS_URL, headers=HEADERS,
                         params={"fixture": fixture_id}, timeout=15)
        r.raise_for_status()
        return r.json().get("response", [])

    # ---------------------------------------------------------
    # SAVE COMPLETO
    # ---------------------------------------------------------
    def _save_stats(self, fx, home_stats, away_stats):

        home_goals = fx["home_goals"]
        away_goals = fx["away_goals"]
        total_goals = home_goals + away_goals

        # A folha e' classificada UMA vez, antes de ler campo nenhum: e' essa
        # classificacao que separa "a API nao respondeu" (tudo None) de "a API
        # respondeu e o contador e' zero". Ver utils/stat_sheet.
        pub_home = folha_publicada(home_stats)
        pub_away = folha_publicada(away_stats)

        home_corners = extract_stat(home_stats, "Corner Kicks", pub_home)
        away_corners = extract_stat(away_stats, "Corner Kicks", pub_away)

        home_yellow = extract_stat(home_stats, "Yellow Cards", pub_home)
        away_yellow = extract_stat(away_stats, "Yellow Cards", pub_away)

        home_red = extract_stat(home_stats, "Red Cards", pub_home)
        away_red = extract_stat(away_stats, "Red Cards", pub_away)

        home_shots_on = extract_stat(home_stats, "Shots on Goal", pub_home)
        away_shots_on = extract_stat(away_stats, "Shots on Goal", pub_away)

        home_shots_off = extract_stat(home_stats, "Shots off Goal", pub_home)
        away_shots_off = extract_stat(away_stats, "Shots off Goal", pub_away)

        home_total_shots = extract_stat(home_stats, "Total Shots", pub_home)
        away_total_shots = extract_stat(away_stats, "Total Shots", pub_away)

        home_blocked = extract_stat(home_stats, "Blocked Shots", pub_home)
        away_blocked = extract_stat(away_stats, "Blocked Shots", pub_away)

        home_saves = extract_stat(home_stats, "Goalkeeper Saves", pub_home)
        away_saves = extract_stat(away_stats, "Goalkeeper Saves", pub_away)

        home_fouls = extract_stat(home_stats, "Fouls", pub_home)
        away_fouls = extract_stat(away_stats, "Fouls", pub_away)

        home_offsides = extract_stat(home_stats, "Offsides", pub_home)
        away_offsides = extract_stat(away_stats, "Offsides", pub_away)

        home_possession = extract_stat(home_stats, "Ball Possession", pub_home)
        away_possession = extract_stat(away_stats, "Ball Possession", pub_away)

        home_passes = extract_stat(home_stats, "Total passes", pub_home)
        away_passes = extract_stat(away_stats, "Total passes", pub_away)

        home_pass_acc = extract_stat(home_stats, "Passes %", pub_home)
        away_pass_acc = extract_stat(away_stats, "Passes %", pub_away)

        self.cur.execute("""
            INSERT INTO match_statistics (
                fixture_id, league_id, season,
                home_team_id, away_team_id,
                home_goals, away_goals, total_goals,
                home_goals_ht, away_goals_ht,
                home_goals_90, away_goals_90,
                home_corners, away_corners, total_corners,
                home_yellow_cards, away_yellow_cards, total_yellow_cards,
                home_red_cards, away_red_cards, total_red_cards,
                status, match_date,

                home_shots_on, away_shots_on,
                home_shots_off, away_shots_off,
                home_total_shots, away_total_shots,
                home_blocked_shots, away_blocked_shots,
                home_goalkeeper_saves, away_goalkeeper_saves,
                home_fouls, away_fouls,
                home_offsides, away_offsides,
                home_possession, away_possession,
                home_passes, away_passes,
                home_passes_accuracy, away_passes_accuracy,

                referee,
                last_updated
            )
            VALUES (
                %s,%s,%s,
                %s,%s,
                %s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,

                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,

                %s,
                NOW()
            )
            ON CONFLICT (fixture_id)
            DO UPDATE SET
                home_goals = EXCLUDED.home_goals,
                away_goals = EXCLUDED.away_goals,
                total_goals = EXCLUDED.total_goals,
                home_goals_ht = COALESCE(EXCLUDED.home_goals_ht, match_statistics.home_goals_ht),
                away_goals_ht = COALESCE(EXCLUDED.away_goals_ht, match_statistics.away_goals_ht),
                home_goals_90 = COALESCE(EXCLUDED.home_goals_90, match_statistics.home_goals_90),
                away_goals_90 = COALESCE(EXCLUDED.away_goals_90, match_statistics.away_goals_90),

                -- COALESCE em toda estatistica: agora que "nao publicado" chega
                -- como NULL (ver extract_stat), uma coleta em que a API
                -- respondeu incompleta nao pode apagar o numero certo ja
                -- gravado numa coleta anterior. Placar e status seguem
                -- sobrescrevendo direto: vem de /fixtures, nao da folha de
                -- estatistica, e sao sempre confiaveis.
                home_corners = COALESCE(EXCLUDED.home_corners, match_statistics.home_corners),
                away_corners = COALESCE(EXCLUDED.away_corners, match_statistics.away_corners),
                total_corners = COALESCE(EXCLUDED.total_corners, match_statistics.total_corners),

                home_yellow_cards = COALESCE(EXCLUDED.home_yellow_cards, match_statistics.home_yellow_cards),
                away_yellow_cards = COALESCE(EXCLUDED.away_yellow_cards, match_statistics.away_yellow_cards),
                total_yellow_cards = COALESCE(EXCLUDED.total_yellow_cards, match_statistics.total_yellow_cards),

                home_red_cards = COALESCE(EXCLUDED.home_red_cards, match_statistics.home_red_cards),
                away_red_cards = COALESCE(EXCLUDED.away_red_cards, match_statistics.away_red_cards),
                total_red_cards = COALESCE(EXCLUDED.total_red_cards, match_statistics.total_red_cards),

                status = EXCLUDED.status,
                match_date = EXCLUDED.match_date,

                home_shots_on = COALESCE(EXCLUDED.home_shots_on, match_statistics.home_shots_on),
                away_shots_on = COALESCE(EXCLUDED.away_shots_on, match_statistics.away_shots_on),
                home_shots_off = COALESCE(EXCLUDED.home_shots_off, match_statistics.home_shots_off),
                away_shots_off = COALESCE(EXCLUDED.away_shots_off, match_statistics.away_shots_off),
                home_total_shots = COALESCE(EXCLUDED.home_total_shots, match_statistics.home_total_shots),
                away_total_shots = COALESCE(EXCLUDED.away_total_shots, match_statistics.away_total_shots),
                home_blocked_shots = COALESCE(EXCLUDED.home_blocked_shots, match_statistics.home_blocked_shots),
                away_blocked_shots = COALESCE(EXCLUDED.away_blocked_shots, match_statistics.away_blocked_shots),
                home_goalkeeper_saves = COALESCE(EXCLUDED.home_goalkeeper_saves, match_statistics.home_goalkeeper_saves),
                away_goalkeeper_saves = COALESCE(EXCLUDED.away_goalkeeper_saves, match_statistics.away_goalkeeper_saves),
                home_fouls = COALESCE(EXCLUDED.home_fouls, match_statistics.home_fouls),
                away_fouls = COALESCE(EXCLUDED.away_fouls, match_statistics.away_fouls),
                home_offsides = COALESCE(EXCLUDED.home_offsides, match_statistics.home_offsides),
                away_offsides = COALESCE(EXCLUDED.away_offsides, match_statistics.away_offsides),
                home_possession = COALESCE(EXCLUDED.home_possession, match_statistics.home_possession),
                away_possession = COALESCE(EXCLUDED.away_possession, match_statistics.away_possession),
                home_passes = COALESCE(EXCLUDED.home_passes, match_statistics.home_passes),
                away_passes = COALESCE(EXCLUDED.away_passes, match_statistics.away_passes),
                home_passes_accuracy = COALESCE(EXCLUDED.home_passes_accuracy, match_statistics.home_passes_accuracy),
                away_passes_accuracy = COALESCE(EXCLUDED.away_passes_accuracy, match_statistics.away_passes_accuracy),

                referee = COALESCE(EXCLUDED.referee, match_statistics.referee),
                last_updated = NOW();
        """, (
            fx["fixture_id"], fx["league_id"], fx["season"],
            fx["home_id"], fx["away_id"],
            home_goals, away_goals, total_goals,
            fx.get("home_goals_ht"), fx.get("away_goals_ht"),
            fx.get("home_goals_90"), fx.get("away_goals_90"),
            home_corners, away_corners, _sum_stats(home_corners, away_corners),
            home_yellow, away_yellow, _sum_stats(home_yellow, away_yellow),
            home_red, away_red, _sum_stats(home_red, away_red),
            fx["status"], fx["match_date"],

            home_shots_on, away_shots_on,
            home_shots_off, away_shots_off,
            home_total_shots, away_total_shots,
            home_blocked, away_blocked,
            home_saves, away_saves,
            home_fouls, away_fouls,
            home_offsides, away_offsides,
            home_possession, away_possession,
            home_passes, away_passes,
            home_pass_acc, away_pass_acc,

            fx.get("referee"),
        ))

        self.conn.commit()
        print(f"[OK] {fx['fixture_id']}")

    # ---------------------------------------------------------
    # UPSERT ÁRBITRO → retorna referee_id (ou None se sem nome)
    # ---------------------------------------------------------
    def _upsert_referee(self, name: str) -> int | None:
        if not name:
            return None
        self.cur.execute("""
            INSERT INTO referees (name, created_at, last_updated)
            VALUES (%s, NOW(), NOW())
            ON CONFLICT (name) DO UPDATE SET last_updated = NOW()
            RETURNING referee_id;
        """, (name,))
        return self.cur.fetchone()[0]

    # ---------------------------------------------------------
    # RECALCULA MÉDIAS DO ÁRBITRO PARA UMA TEMPORADA
    # ---------------------------------------------------------
    def _recalculate_referee_stats(self, referee_id: int, referee_name: str, season: int):
        self.cur.execute("""
            INSERT INTO referee_stats (
                referee_id, season,
                games, avg_yellow, avg_red, avg_fouls,
                avg_corners, avg_goals,
                max_yellow, min_yellow,
                last_updated
            )
            SELECT
                %s, %s,
                COUNT(*),
                ROUND(AVG(ms.total_yellow_cards)::numeric, 2),
                ROUND(AVG(ms.total_red_cards)::numeric, 2),
                ROUND(AVG(ms.home_fouls + ms.away_fouls)::numeric, 2),
                ROUND(AVG(ms.total_corners)::numeric, 2),
                ROUND(AVG(ms.total_goals)::numeric, 2),
                MAX(ms.total_yellow_cards),
                MIN(ms.total_yellow_cards),
                NOW()
            FROM match_statistics ms
            WHERE ms.referee = %s
              AND ms.season  = %s
            ON CONFLICT (referee_id, season) DO UPDATE SET
                games        = EXCLUDED.games,
                avg_yellow   = EXCLUDED.avg_yellow,
                avg_red      = EXCLUDED.avg_red,
                avg_fouls    = EXCLUDED.avg_fouls,
                avg_corners  = EXCLUDED.avg_corners,
                avg_goals    = EXCLUDED.avg_goals,
                max_yellow   = EXCLUDED.max_yellow,
                min_yellow   = EXCLUDED.min_yellow,
                last_updated = NOW();
        """, (referee_id, season, referee_name, season))

    # ---------------------------------------------------------
    # PROCESSA LOTE DE ÁRBITROS AO FINAL DO SYNC
    # referee_batch = set of (referee_name, season)
    # ---------------------------------------------------------
    def _sync_referee_stats(self, referee_batch: set):
        if not referee_batch:
            return
        print(f"[REFEREE] Atualizando stats de {len(referee_batch)} árbitro(s)...")
        for referee_name, season in referee_batch:
            referee_id = self._upsert_referee(referee_name)
            if referee_id:
                self._recalculate_referee_stats(referee_id, referee_name, season)
        self.conn.commit()
        print("[REFEREE] Stats de árbitros atualizados.")

    # ---------------------------------------------------------
    # SYNC DIRETO POR FIXTURE_ID (para pendentes em picks_vip)
    # Não depende da tabela teams · busca tudo via API por ID.
    # ---------------------------------------------------------
    def sync_pending_fixtures(self, include_resolved: bool = False):
        """Busca a folha de estatistica dos jogos que sustentam picks.

        include_resolved=True inclui tambem picks JA' resolvidos cuja folha
        esta ausente ou incompleta. E' o que quebra o circulo vicioso que
        deixou o caso Fortaleza x Palmeiras (fixture 1546854) sem folha
        nenhuma no banco: o caminho ao vivo gravou um resultado a partir de
        estatistica vazia, e a partir dai o pick nao era mais "pendente",
        entao a coleta nunca ia buscar o numero certo. Usado pela
        re-resolucao (scripts/reauditar_resultados.py).
        """
        print("[MATCH_STATS] Sincronizando fixtures pendentes das sugestões...")

        self._open()

        # Coleta fixture_ids pendentes das tabelas de sugestões
        pending_ids = set()
        import json as _json

        filtro = "" if include_resolved else "AND result IS NULL"

        for table in ("picks_vip", "picks_free", "picks_faltas", "picks_goleiros"):
            try:
                self.cur.execute(
                    f"SELECT DISTINCT fixture_id FROM {table} "
                    f"WHERE fixture_id IS NOT NULL {filtro};")
            except Exception as e:
                print(f"[MATCH_STATS] Aviso: {table} indisponivel ({e})")
                self.conn.rollback()
                continue
            for row in self.cur.fetchall():
                if row[0] is not None:
                    pending_ids.add(row[0])

        # Alavancagem: ate' tres fixtures por pick (a perna 3 nao era lida aqui)
        self.cur.execute(
            f"SELECT fixture_id_1, fixture_id_2, fixture_id_3 FROM picks_alavancagem "
            f"WHERE TRUE {filtro};")
        for row in self.cur.fetchall():
            for fid in row:
                if fid is not None:
                    pending_ids.add(fid)

        # Múltiplas: extrai fixture_ids do JSON das legs
        self.cur.execute(f"SELECT games FROM picks_multiplas WHERE TRUE {filtro};")
        for (games_raw,) in self.cur.fetchall():
            try:
                games = _json.loads(games_raw) if isinstance(games_raw, str) else games_raw
                for leg in (games if isinstance(games, list) else []):
                    fid = leg.get("fixture_id")
                    if fid is not None:
                        pending_ids.add(fid)
            except Exception:
                pass

        # Remove os que já têm a folha COMPLETA. Antes bastava existir a linha:
        # um jogo gravado com a folha vazia nunca era rebuscado.
        if pending_ids:
            self.cur.execute("""
                SELECT fixture_id FROM match_statistics
                WHERE fixture_id = ANY(%s)
                  AND total_corners IS NOT NULL
                  AND total_yellow_cards IS NOT NULL
                  AND total_red_cards IS NOT NULL
                  AND home_fouls IS NOT NULL
                  AND home_total_shots IS NOT NULL;
            """, (list(pending_ids),))
            already = {row[0] for row in self.cur.fetchall()}
            pending_ids -= already

        if not pending_ids:
            print("[MATCH_STATS] Nenhum fixture pendente sem stats.")
            self._close()
            return

        print(f"[MATCH_STATS] {len(pending_ids)} fixture(s) sem stats · buscando na API...")

        FINISHED = {"FT", "AET", "PEN"}
        referee_batch = set()

        for fixture_id in pending_ids:
            try:
                r = requests.get(FIXTURES_URL, headers=HEADERS, params={"id": fixture_id}, timeout=15)
                r.raise_for_status()
                response = r.json().get("response", [])

                if not response:
                    print(f"[MATCH_STATS] fixture_id={fixture_id} não encontrado na API.")
                    continue

                item = response[0]
                fixture_info = item["fixture"]
                status = fixture_info["status"]["short"]

                if status not in FINISHED:
                    print(f"[MATCH_STATS] fixture_id={fixture_id} status={status} · jogo ainda não finalizado.")
                    continue

                league_id = item["league"]["id"]
                season = item["league"]["season"]
                home_id = item["teams"]["home"]["id"]
                away_id = item["teams"]["away"]["id"]
                goals = item["goals"]
                match_date = datetime.fromisoformat(fixture_info["date"].replace("Z", "+00:00"))

                score = item.get("score", {}) or {}
                ht = score.get("halftime") or {}
                ft90 = score.get("fulltime") or {}
                fx = {
                    "fixture_id": fixture_id,
                    "league_id": league_id,
                    "season": season,
                    "home_id": home_id,
                    "away_id": away_id,
                    "match_date": match_date,
                    "status": status,
                    "home_goals": goals["home"] or 0,
                    "away_goals": goals["away"] or 0,
                    "home_goals_ht": ht.get("home"),
                    "away_goals_ht": ht.get("away"),
                    "home_goals_90": ft90.get("home"),
                    "away_goals_90": ft90.get("away"),
                    "referee": fixture_info.get("referee"),
                }

                stats = self._fetch_match_stats(fixture_id)

                if not stats or len(stats) < 2:
                    print(f"[MATCH_STATS] fixture_id={fixture_id} sem stats de jogo na API.")
                    continue

                if stats[0]["team"]["id"] == home_id:
                    home_stats = stats[0]["statistics"]
                    away_stats = stats[1]["statistics"]
                else:
                    home_stats = stats[1]["statistics"]
                    away_stats = stats[0]["statistics"]

                self._save_stats(fx, home_stats, away_stats)

                if fx.get("referee"):
                    referee_batch.add((fx["referee"], fx["season"]))

            except Exception as e:
                print(f"[MATCH_STATS] Erro ao processar fixture_id={fixture_id}: {e}")

        self._sync_referee_stats(referee_batch)
        self._close()
        print("[MATCH_STATS] Sync de pendentes concluído.")

    # ---------------------------------------------------------
    # MAIN
    # ---------------------------------------------------------
    def sync_all_finished_fixtures(self, use_date_filter=True, days=3, apenas_liga=None):
        print("[MATCH_STATS] START")

        self._open()

        fixtures = self._load_fixtures(use_date_filter, days, apenas_liga=apenas_liga)
        referee_batch = set()

        for fx in fixtures:
            stats = self._fetch_match_stats(fx["fixture_id"])

            if not stats or len(stats) < 2:
                continue

            if stats[0]["team"]["id"] == fx["home_id"]:
                home_stats = stats[0]["statistics"]
                away_stats = stats[1]["statistics"]
            else:
                home_stats = stats[1]["statistics"]
                away_stats = stats[0]["statistics"]

            self._save_stats(fx, home_stats, away_stats)

            if fx.get("referee"):
                referee_batch.add((fx["referee"], fx["season"]))

        self._sync_referee_stats(referee_batch)
        self._close()
        print("[MATCH_STATS] DONE")