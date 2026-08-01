import os
import sys
import psycopg2
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida")

HEADERS = {"x-apisports-key": API_KEY}

FIXTURES_URL = "https://v3.football.api-sports.io/fixtures"
STATS_URL = "https://v3.football.api-sports.io/fixtures/statistics"


def load_leagues_from_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT league_id, season FROM leagues;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"league_id": r[0], "season": r[1]} for r in rows]


def extract_stat(stats, stat_name):
    if not stats:
        return 0

    for s in stats:
        if s["type"] == stat_name:
            val = s["value"]

            if val is None:
                return 0

            if isinstance(val, str):
                val = val.replace("%", "")
                try:
                    return float(val)
                except:
                    return 0

            return val

    return 0


class MatchStatisticsSyncService:

    def __init__(self):
        self.conn = None
        self.cur = None

    def _open(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor()

    def _close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    # ---------------------------------------------------------
    # LOAD FIXTURES (COM GOLS)
    # ---------------------------------------------------------
    def _load_fixtures(self, use_date_filter=True, days=3):
        leagues = load_leagues_from_db()
        league_ids = tuple([l["league_id"] for l in leagues])

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
        self.cur.execute("""
            SELECT fixture_id FROM match_statistics
            WHERE last_updated IS NOT NULL
              AND last_updated > match_date + INTERVAL '24 hours'
        """)
        settled_fixture_ids = {row[0] for row in self.cur.fetchall()}

        fixtures = []
        skipped = 0

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

                if fixture["id"] in settled_fixture_ids:
                    skipped += 1
                    continue

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
                    "referee": fixture.get("referee"),
                })

        print(f"[INFO] {len(fixtures)} jogos carregados "
              f"({skipped} pulados · estatística já estabilizada no banco)")
        return fixtures

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

        home_corners = extract_stat(home_stats, "Corner Kicks")
        away_corners = extract_stat(away_stats, "Corner Kicks")

        home_yellow = extract_stat(home_stats, "Yellow Cards")
        away_yellow = extract_stat(away_stats, "Yellow Cards")

        home_red = extract_stat(home_stats, "Red Cards")
        away_red = extract_stat(away_stats, "Red Cards")

        home_shots_on = extract_stat(home_stats, "Shots on Goal")
        away_shots_on = extract_stat(away_stats, "Shots on Goal")

        home_shots_off = extract_stat(home_stats, "Shots off Goal")
        away_shots_off = extract_stat(away_stats, "Shots off Goal")

        home_total_shots = extract_stat(home_stats, "Total Shots")
        away_total_shots = extract_stat(away_stats, "Total Shots")

        home_blocked = extract_stat(home_stats, "Blocked Shots")
        away_blocked = extract_stat(away_stats, "Blocked Shots")

        home_saves = extract_stat(home_stats, "Goalkeeper Saves")
        away_saves = extract_stat(away_stats, "Goalkeeper Saves")

        home_fouls = extract_stat(home_stats, "Fouls")
        away_fouls = extract_stat(away_stats, "Fouls")

        home_offsides = extract_stat(home_stats, "Offsides")
        away_offsides = extract_stat(away_stats, "Offsides")

        home_possession = extract_stat(home_stats, "Ball Possession")
        away_possession = extract_stat(away_stats, "Ball Possession")

        home_passes = extract_stat(home_stats, "Total passes")
        away_passes = extract_stat(away_stats, "Total passes")

        home_pass_acc = extract_stat(home_stats, "Passes %")
        away_pass_acc = extract_stat(away_stats, "Passes %")

        self.cur.execute("""
            INSERT INTO match_statistics (
                fixture_id, league_id, season,
                home_team_id, away_team_id,
                home_goals, away_goals, total_goals,
                home_goals_ht, away_goals_ht,
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

                home_corners = EXCLUDED.home_corners,
                away_corners = EXCLUDED.away_corners,
                total_corners = EXCLUDED.total_corners,

                home_yellow_cards = EXCLUDED.home_yellow_cards,
                away_yellow_cards = EXCLUDED.away_yellow_cards,
                total_yellow_cards = EXCLUDED.total_yellow_cards,

                home_red_cards = EXCLUDED.home_red_cards,
                away_red_cards = EXCLUDED.away_red_cards,
                total_red_cards = EXCLUDED.total_red_cards,

                status = EXCLUDED.status,
                match_date = EXCLUDED.match_date,

                home_shots_on = EXCLUDED.home_shots_on,
                away_shots_on = EXCLUDED.away_shots_on,
                home_shots_off = EXCLUDED.home_shots_off,
                away_shots_off = EXCLUDED.away_shots_off,
                home_total_shots = EXCLUDED.home_total_shots,
                away_total_shots = EXCLUDED.away_total_shots,
                home_blocked_shots = EXCLUDED.home_blocked_shots,
                away_blocked_shots = EXCLUDED.away_blocked_shots,
                home_goalkeeper_saves = EXCLUDED.home_goalkeeper_saves,
                away_goalkeeper_saves = EXCLUDED.away_goalkeeper_saves,
                home_fouls = EXCLUDED.home_fouls,
                away_fouls = EXCLUDED.away_fouls,
                home_offsides = EXCLUDED.home_offsides,
                away_offsides = EXCLUDED.away_offsides,
                home_possession = EXCLUDED.home_possession,
                away_possession = EXCLUDED.away_possession,
                home_passes = EXCLUDED.home_passes,
                away_passes = EXCLUDED.away_passes,
                home_passes_accuracy = EXCLUDED.home_passes_accuracy,
                away_passes_accuracy = EXCLUDED.away_passes_accuracy,

                referee = EXCLUDED.referee,
                last_updated = NOW();
        """, (
            fx["fixture_id"], fx["league_id"], fx["season"],
            fx["home_id"], fx["away_id"],
            home_goals, away_goals, total_goals,
            fx.get("home_goals_ht"), fx.get("away_goals_ht"),
            home_corners, away_corners, home_corners + away_corners,
            home_yellow, away_yellow, home_yellow + away_yellow,
            home_red, away_red, home_red + away_red,
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
    def sync_pending_fixtures(self):
        print("[MATCH_STATS] Sincronizando fixtures pendentes das sugestões...")

        self._open()

        # Coleta fixture_ids pendentes das tabelas de sugestões
        pending_ids = set()
        import json as _json

        for table in ("picks_vip", "picks_free"):
            self.cur.execute(f"SELECT DISTINCT fixture_id FROM {table} WHERE result IS NULL AND fixture_id IS NOT NULL;")
            for row in self.cur.fetchall():
                if row[0] is not None:
                    pending_ids.add(row[0])

        # Alavancagem: dois fixtures por pick
        self.cur.execute("SELECT fixture_id_1, fixture_id_2 FROM picks_alavancagem WHERE result IS NULL;")
        for row in self.cur.fetchall():
            for fid in (row[0], row[1]):
                if fid is not None:
                    pending_ids.add(fid)

        # Múltiplas: extrai fixture_ids do JSON das legs
        self.cur.execute("SELECT games FROM picks_multiplas WHERE result IS NULL;")
        for (games_raw,) in self.cur.fetchall():
            try:
                games = _json.loads(games_raw) if isinstance(games_raw, str) else games_raw
                for leg in (games if isinstance(games, list) else []):
                    fid = leg.get("fixture_id")
                    if fid is not None:
                        pending_ids.add(fid)
            except Exception:
                pass

        # Remove os que já têm stats
        if pending_ids:
            self.cur.execute(
                "SELECT fixture_id FROM match_statistics WHERE fixture_id = ANY(%s);",
                (list(pending_ids),)
            )
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

                score = item.get("score", {})
                ht = score.get("halftime", {})
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
    def sync_all_finished_fixtures(self, use_date_filter=True, days=3):
        print("[MATCH_STATS] START")

        self._open()

        fixtures = self._load_fixtures(use_date_filter, days)
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