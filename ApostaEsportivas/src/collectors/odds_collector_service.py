import os
import re
import requests

from psycopg2.extras import execute_batch
from utils.db_utils import get_connection
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida no .env")

HEADERS = {"x-apisports-key": API_KEY}

# ============================================================
# CASAS DE APOSTAS PERMITIDAS
# 8  = Bet365
# 32 = Sportingbet
# 34 = Betano
# ============================================================
BR_BOOKMAKERS = {8, 32, 34}

# ============================================================
# MERCADOS PERMITIDOS
#
# Critério de seleção:
# - Mercados que a IA consegue analisar com dados estatísticos
# - Baixa a média variância
# - Suporte em médias, frequências e xG disponíveis na API
#
# REMOVIDOS intencionalmente:
# - SHOTS (211, 221, 220, 87, 88, 89, 340, 176): alta variância,
#   IA não tem dados suficientes para analisar com consistência
# - CARDS HT (155) e CARDS 2H (156): altíssima variância
# - CARDS HOME/AWAY individuais por tempo: ruído estatístico
# ============================================================

# -----------------------------------------------------------
# GOLS — TEMPO NORMAL (FT)
# id 5  = Goals Over/Under
# id 16 = Total - Home (gols time da casa)
# id 17 = Total - Away (gols time visitante)
# id 8  = Both Teams Score (BTTS)
# id 12 = Double Chance (1X, 12, X2)
# id 1  = Match Winner (1X2)
# -----------------------------------------------------------
GOALS_FT = {5, 16, 17}
BTTS_FT  = {8}
MATCH    = {1, 12}

# -----------------------------------------------------------
# GOLS — PRIMEIRO TEMPO (HT)
# id 6   = Goals Over/Under First Half
# id 105 = Home Team Total Goals (1st Half)
# id 106 = Away Team Total Goals (1st Half)
# id 34  = Both Teams Score - First Half
# id 13  = First Half Winner
# -----------------------------------------------------------
GOALS_HT = {6, 105, 106, 34, 13}

# -----------------------------------------------------------
# GOLS — SEGUNDO TEMPO (2H)
# id 26  = Goals Over/Under Second Half
# id 107 = Home Team Total Goals (2nd Half)
# id 108 = Away Team Total Goals (2nd Half)
# id 35  = Both Teams To Score - Second Half
# -----------------------------------------------------------
GOALS_2H = {26, 107, 108, 35}

# -----------------------------------------------------------
# ESCANTEIOS — TEMPO NORMAL (FT)
# id 45 = Corners Over/Under
# id 57 = Home Corners Over/Under
# id 58 = Away Corners Over/Under
# id 55 = Corners 1x2
# -----------------------------------------------------------
CORNERS_FT = {45, 57, 58, 55}

# -----------------------------------------------------------
# ESCANTEIOS — PRIMEIRO TEMPO (HT)
# id 77  = Total Corners (1st Half)
# id 132 = Home Total Corners (1st Half)
# id 134 = Away Total Corners (1st Half)
# -----------------------------------------------------------
CORNERS_HT = {77, 132, 134}

# -----------------------------------------------------------
# ESCANTEIOS — SEGUNDO TEMPO (2H)
# id 127 = Total Corners (2nd Half)
# id 133 = Home Total Corners (2nd Half)
# id 135 = Away Total Corners (2nd Half)
# -----------------------------------------------------------
CORNERS_2H = {127, 133, 135}

# -----------------------------------------------------------
# CARTÕES — TEMPO NORMAL (FT) APENAS
# id 80  = Cards Over/Under (total da partida)
# id 82  = Home Team Total Cards
# id 83  = Away Team Total Cards
#
# HT e 2H removidos — variância muito alta,
# IA não consegue analisar com consistência.
# -----------------------------------------------------------
CARDS_FT = {80, 82, 83}

# -----------------------------------------------------------
# PLACAR EXATO
# id 10 = Exact Score (ex: "3:0", "2:1", "0:0")
# -----------------------------------------------------------
CORRECT_SCORE = {10}

# -----------------------------------------------------------
# TODOS OS MERCADOS VÁLIDOS
# -----------------------------------------------------------
VALID_BET_IDS = (
    GOALS_FT
    | BTTS_FT
    | MATCH
    | GOALS_HT
    | GOALS_2H
    | CORNERS_FT
    | CORNERS_HT
    | CORNERS_2H
    | CARDS_FT
    | CORRECT_SCORE
)

# Log dos IDs para referência
print(f"[ODDS] Mercados monitorados: {sorted(VALID_BET_IDS)}")


# ============================================================
# MAPEAMENTO DE MERCADO → TIPO
# Usado pela IA para categorizar e penalizar por variância.
# ============================================================
MARKET_TYPE_MAP = {
    # Gols FT
    5:   "goals",
    16:  "goals",
    17:  "goals",
    8:   "btts",
    1:   "result",
    12:  "result",
    # Gols HT
    6:   "goals",
    105: "goals",
    106: "goals",
    34:  "btts",
    13:  "result",
    # Gols 2H
    26:  "goals",
    35:  "btts",
    107: "goals",
    108: "goals",
    # Escanteios FT
    45:  "corners",
    57:  "corners",
    58:  "corners",
    55:  "corners",
    # Escanteios HT
    77:  "corners",
    132: "corners",
    134: "corners",
    # Escanteios 2H
    127: "corners",
    133: "corners",
    135: "corners",
    # Cartões FT
    80:  "cards",
    82:  "cards",
    83:  "cards",
    # Placar Exato
    10:  "correct_score",
}

# Nome em português canônico por bet_id (mais confiável que traduzir o nome inglês)
BET_ID_PT_MAP: dict[int, str] = {
    1:   "Resultado Final (1X2)",
    12:  "Dupla Chance",
    13:  "Vencedor do 1º Tempo",
    4:   "Ambas as Equipes Marcam",
    8:   "Ambas as Equipes Marcam",
    34:  "Ambas Marcam - 1º Tempo",
    5:   "Gols Mais/Menos",
    6:   "Gols Mais/Menos - 1º Tempo",
    26:  "Gols Mais/Menos - 2º Tempo",
    35:  "Ambas Marcam - 2º Tempo",
    107: "Total de Gols Casa (2º Tempo)",
    108: "Total de Gols Visitante (2º Tempo)",
    16:  "Total de Gols Casa",
    17:  "Total de Gols Visitante",
    105: "Total de Gols Casa (1º Tempo)",
    106: "Total de Gols Visitante (1º Tempo)",
    45:  "Escanteios Mais/Menos",
    55:  "Escanteios 1x2",
    57:  "Escanteios Casa Mais/Menos",
    58:  "Escanteios Visitante Mais/Menos",
    77:  "Total de Escanteios (1º Tempo)",
    127: "Total de Escanteios (2º Tempo)",
    133: "Escanteios Casa (2º Tempo)",
    135: "Escanteios Visitante (2º Tempo)",
    132: "Escanteios Casa (1º Tempo)",
    134: "Escanteios Visitante (1º Tempo)",
    80:  "Cartões Mais/Menos",
    82:  "Total de Cartões Casa",
    83:  "Total de Cartões Visitante",
    10:  "Placar Exato",
}


def detect_market_type(bet_id: int, bet_name: str) -> str:
    """
    Detecta o tipo de mercado primeiro pelo ID (mais preciso),
    depois pelo nome como fallback.
    """
    if bet_id in MARKET_TYPE_MAP:
        return MARKET_TYPE_MAP[bet_id]

    name = bet_name.lower()
    if "corner" in name:
        return "corners"
    if "card" in name or "yellow" in name:
        return "cards"
    if "goal" in name or "total - home" in name or "total - away" in name:
        return "goals"
    if "both teams score" in name or "btts" in name:
        return "btts"
    if "double chance" in name or "match winner" in name or "1x2" in name:
        return "result"
    return "unknown"


# ============================================================
# SERVICE
# ============================================================
class OddsCollectorService:

    def __init__(self):
        self.api_url = "https://v3.football.api-sports.io/odds"

    # --------------------------------------------------------
    # BUSCA ODDS NA API
    # --------------------------------------------------------
    def fetch_odds_by_fixture(self, fixture_id: int) -> dict | None:
        try:
            response = requests.get(
                self.api_url,
                headers=HEADERS,
                params={"fixture": fixture_id},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[ODDS API ERROR] fixture {fixture_id}: {e}")
            return None

        data = response.json().get("response", [])
        return data[0] if data else None

    # --------------------------------------------------------
    # DETECTA SIDE (home / away / total)
    # --------------------------------------------------------
    def _detect_side(self, bet_id: int, bet_name: str) -> str:
        name = bet_name.lower()
        if bet_id in CORNERS_HT and "home" in name:
            return "home"
        if bet_id in CORNERS_HT and "away" in name:
            return "away"
        if "home" in name or "team 1" in name:
            return "home"
        if "away" in name or "team 2" in name:
            return "away"
        return "total"

    # --------------------------------------------------------
    # SALVA ODDS NO BANCO
    # --------------------------------------------------------
    def save_odds(self, fixture_id: int, bookmakers: list):
        conn = get_connection()
        cur  = conn.cursor()

        try:
            # Carrega dados do fixture
            cur.execute("""
                SELECT league_id, season, match_datetime,
                       home_team_id, home_team,
                       away_team_id, away_team
                FROM fixtures
                WHERE fixture_id = %s
            """, (fixture_id,))

            row = cur.fetchone()
            if not row:
                print(f"[ODDS] Fixture {fixture_id} não encontrado no banco — pulando.")
                return

            league_id, season, match_datetime, home_id, home_name, away_id, away_name = row

            bookmaker_map = {}  # bookmaker_id → bookmaker_row_id no banco
            market_map    = {}  # (bookmaker_id, bet_id) → market_row_id no banco

            # --------------------------------------------------
            # 1. UPSERT BOOKMAKERS
            # --------------------------------------------------
            for bk in bookmakers:
                if bk["id"] not in BR_BOOKMAKERS:
                    continue

                cur.execute("""
                    INSERT INTO odds_bookmakers (
                        fixture_id, bookmaker_id, bookmaker_name,
                        last_update, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, NOW(), NOW(), NOW())
                    ON CONFLICT (fixture_id, bookmaker_id)
                    DO UPDATE SET
                        bookmaker_name = EXCLUDED.bookmaker_name,
                        updated_at     = NOW()
                    RETURNING id;
                """, (fixture_id, bk["id"], bk["name"]))

                bk_row_id = cur.fetchone()[0]
                bookmaker_map[bk["id"]] = bk_row_id

            # --------------------------------------------------
            # 2. UPSERT MARKETS
            # --------------------------------------------------
            for bk in bookmakers:
                if bk["id"] not in bookmaker_map:
                    continue

                bk_row_id = bookmaker_map[bk["id"]]

                for bet in bk.get("bets", []):

                    if bet.get("id") not in VALID_BET_IDS:
                        continue

                    cur.execute("""
                        INSERT INTO odds_markets (
                            bookmaker_row_id, bet_id, bet_name,
                            fixture_id, market_pt,
                            created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT (bookmaker_row_id, bet_id)
                        DO UPDATE SET
                            bet_name   = EXCLUDED.bet_name,
                            market_pt  = EXCLUDED.market_pt,
                            updated_at = NOW()
                        RETURNING id;
                    """, (
                        bk_row_id,
                        bet["id"],
                        bet["name"],
                        fixture_id,
                        BET_ID_PT_MAP.get(bet["id"]),
                    ))

                    market_row_id = cur.fetchone()[0]
                    market_map[(bk["id"], bet["id"])] = market_row_id

            # --------------------------------------------------
            # 3. UPSERT VALUES (ODDS)
            #
            # Coleta odds em range amplo (1.05–2.50) para permitir
            # cálculo correto de no-vig probability:
            # - Precisamos do lado oposto do mercado (ex: Under quando
            #   queremos Over) para remover a margem do bookmaker.
            # - O filtro final de 1.05–1.80 é aplicado na IA,
            #   não aqui — assim o EVCalculator tem dados completos.
            # --------------------------------------------------
            values_batch = []

            for bk in bookmakers:
                if bk["id"] not in bookmaker_map:
                    continue

                for bet in bk.get("bets", []):

                    key = (bk["id"], bet["id"])
                    if key not in market_map:
                        continue

                    market_row_id = market_map[key]
                    market_type   = detect_market_type(bet["id"], bet["name"])
                    side_team     = self._detect_side(bet["id"], bet["name"])

                    team_id   = None
                    team_name = None
                    if side_team == "home":
                        team_id, team_name = home_id, home_name
                    elif side_team == "away":
                        team_id, team_name = away_id, away_name

                    for sel in bet.get("values", []):
                        try:
                            odd_value = float(sel["odd"])
                        except (ValueError, TypeError):
                            continue

                        raw_value = str(sel.get("value", "")).strip()

                        # Separa o lado do mercado (Over/Under/Home/Away/Yes/No)
                        # do valor numérico da linha (2.5 / 3.5 / 1 / etc.)
                        # para que o EVCalculator consiga parear os dois lados
                        # do mesmo mercado e calcular a probabilidade no-vig.
                        #
                        # Exemplos:
                        #   "Over 2.5"  → value_name="Over",  line_value="2.5"
                        #   "Under 3.5" → value_name="Under", line_value="3.5"
                        #   "Home"      → value_name="Home",  line_value=""
                        #   "Yes"       → value_name="Yes",   line_value=""
                        #
                        # O campo handicap da API (quando presente) tem precedência.
                        handicap = str(sel.get("handicap", "") or "").strip()

                        if handicap:
                            value_name = raw_value
                            line_value = handicap
                        else:
                            _m = re.match(
                                r'^(Over|Under|Yes|No|Home|Away|1|X|2)\s*([\d.]+)?$',
                                raw_value, re.IGNORECASE
                            )
                            if _m:
                                value_name = _m.group(1)
                                line_value = _m.group(2) or ""
                            else:
                                value_name = raw_value
                                line_value = ""

                        values_batch.append((
                            market_row_id,
                            value_name,
                            odd_value,
                            fixture_id,
                            league_id,
                            season,
                            match_datetime,
                            home_id,
                            home_name,
                            away_id,
                            away_name,
                            bk["id"],
                            bk["name"],
                            bet["id"],
                            bet["name"],
                            market_type,
                            side_team,
                            team_id,
                            team_name,
                            line_value,
                            BET_ID_PT_MAP.get(bet["id"]),  # market_pt por bet_id
                        ))

            if values_batch:
                print(f"[ODDS] Fixture {fixture_id} — inserindo {len(values_batch)} odds...")

                execute_batch(cur, """
                    INSERT INTO odds_values (
                        market_row_id, value_name, odd_value,
                        fixture_id, league_id, season, match_datetime,
                        home_team_id, home_team,
                        away_team_id, away_team,
                        bookmaker_id, bookmaker_name,
                        market_id, market_name,
                        market_type, side_team,
                        team_id, team_name,
                        line_value, market_pt,
                        created_at, updated_at
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        NOW(), NOW()
                    )
                    ON CONFLICT (market_row_id, value_name)
                    DO UPDATE SET
                        odd_value  = EXCLUDED.odd_value,
                        updated_at = NOW();
                """, values_batch, page_size=500)

                print(f"[ODDS] Fixture {fixture_id} salvo com sucesso — {len(values_batch)} valores.")
            else:
                print(f"[ODDS] Fixture {fixture_id} — nenhuma odd encontrada para salvar.")

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"[ERRO SAVE ODDS] fixture {fixture_id}: {e}")
            raise

        finally:
            cur.close()
            conn.close()

    # --------------------------------------------------------
    # PROCESSA UM FIXTURE
    # --------------------------------------------------------
    def process_fixture_odds(self, fixture_id: int):
        data = self.fetch_odds_by_fixture(fixture_id)

        if not data:
            print(f"[ODDS] Nenhuma odd encontrada para fixture {fixture_id}.")
            return

        bookmakers = data.get("bookmakers", [])
        if not bookmakers:
            print(f"[ODDS] Fixture {fixture_id} sem bookmakers disponíveis.")
            return

        # Filtra só as casas permitidas antes de processar
        br_bookmakers = [bk for bk in bookmakers if bk["id"] in BR_BOOKMAKERS]
        if not br_bookmakers:
            print(f"[ODDS] Fixture {fixture_id} — nenhuma casa BR disponível (Bet365/Sportingbet/Betano).")
            return

        print(f"[ODDS] Processando fixture {fixture_id} — {len(br_bookmakers)} casa(s) encontrada(s).")
        self.save_odds(fixture_id, bookmakers)

    # --------------------------------------------------------
    # PROCESSA LISTA DE FIXTURES
    # --------------------------------------------------------
    def process_multiple_fixtures(self, fixture_ids: list):
        total   = len(fixture_ids)
        success = 0
        failed  = 0

        print(f"\n[ODDS] Iniciando coleta para {total} fixture(s)...")

        for i, fid in enumerate(fixture_ids, 1):
            print(f"\n[ODDS] ({i}/{total}) Processando fixture {fid}...")
            try:
                self.process_fixture_odds(fid)
                success += 1
            except Exception as e:
                print(f"[ODDS] Erro no fixture {fid}: {e}")
                failed += 1

        print(f"\n[ODDS] Concluído — ✅ {success} sucesso(s) | ❌ {failed} erro(s)")