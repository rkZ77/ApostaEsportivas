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
# 32 = Betano
# ============================================================
BR_BOOKMAKERS = {8, 32}



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
    4:   "Handicap Asiático",
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

# Fallback por palavra-chave no nome cru quando o bet_id vem de um mercado
# raro/novo que ainda nao foi cadastrado em BET_ID_PT_MAP acima (ex.:
# "Corners Asian Handicap" vazando em ingles pro reasoning/UI enquanto
# outros mercados do mesmo pick ja saem em PT). Mesmas chaves usadas em
# website/frontend/src/utils/marketTranslate.ts, checadas na ordem abaixo
# (mais especifico primeiro) pra "corners asian handicap" nao cair em
# "asian handicap" antes.
#
# Bug real encontrado em producao (2026-07-24): "Cards Asian Handicap" e
# "Cards European Handicap" nao tinham entrada especifica aqui, entao
# caiam no fallback generico "asian handicap" -> "Handicap Asiático" --
# market_type interno saia certo (handicap_cards, via classify_market()
# que le "card" no nome cru em ingles), mas o texto em PT mostrado pro
# usuario dizia "Handicap Asiático" (implica gols) pra uma aposta que na
# verdade e sobre CARTOES. "Corners European Handicap" tinha o mesmo gap
# (so' a variante Asian de corners estava coberta).
_MARKET_NAME_PT_FALLBACK: list[tuple[str, str]] = [
    ("cards asian handicap", "Cartões Handicap Asiático"),
    ("cards european handicap", "Cartões Handicap Asiático"),
    ("corners asian handicap", "Escanteios Handicap Asiático"),
    ("corners european handicap", "Escanteios Handicap Asiático"),
    ("asian handicap", "Handicap Asiático"),
    # "Odd/Even" nao tinha NENHUMA traducao (nem aqui nem em BET_ID_PT_MAP),
    # entao ia pro site cru em ingles -- confuso porque "odd" em ingles
    # (impar) colide visualmente com "odd" em portugues (a odd/coeficiente
    # da aposta): usuario via "Odd/Even Odd @ 2.02" e nao dava pra saber
    # que o primeiro "Odd" e' a selecao (impar) e o numero e' o coeficiente.
    ("corners odd/even", "Escanteios Par/Ímpar"),
    ("odd/even", "Par/Ímpar"),
    ("odd or even", "Par/Ímpar"),
    ("corners over/under", "Escanteios Mais/Menos"),
    ("corners 1x2", "Escanteios 1x2"),
    ("home corners over/under", "Escanteios Casa Mais/Menos"),
    ("away corners over/under", "Escanteios Visitante Mais/Menos"),
    ("cards over/under", "Cartões Mais/Menos"),
    ("both teams to score", "Ambas as Equipes Marcam"),
    ("both teams score", "Ambas as Equipes Marcam"),
    ("goals over/under", "Gols Mais/Menos"),
    ("over/under", "Gols Mais/Menos"),
    ("double chance", "Dupla Chance"),
    ("match winner", "Resultado Final (1X2)"),
    ("first half winner", "Vencedor do 1º Tempo"),
    ("exact score", "Placar Exato"),
    ("correct score", "Placar Exato"),
]


def _market_pt_fallback(bet_name: str) -> str | None:
    """Traduz pelo nome cru quando o bet_id ainda nao esta em BET_ID_PT_MAP."""
    name = (bet_name or "").strip().lower()
    for key, pt in _MARKET_NAME_PT_FALLBACK:
        if key in name:
            return pt
    return None


def detect_market_type(bet_id: int, bet_name: str) -> str:
    """
    Detecta o tipo de mercado primeiro pelo ID (mais preciso),
    depois pelo nome como fallback.
    """
    if bet_id in MARKET_TYPE_MAP:
        return MARKET_TYPE_MAP[bet_id]

    name = bet_name.lower()
    if "shot" in name:
        return "shots"
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
    # BUSCA ODDS NA API · uma chamada por bookmaker BR
    # --------------------------------------------------------
    def fetch_odds_by_fixture(self, fixture_id: int) -> dict | None:
        merged: list[dict] = []
        seen: set[int] = set()

        for bm_id in sorted(BR_BOOKMAKERS):
            try:
                response = requests.get(
                    self.api_url,
                    headers=HEADERS,
                    params={"fixture": fixture_id, "bookmaker": bm_id},
                    timeout=20,
                )
                response.raise_for_status()
            except requests.RequestException as e:
                print(f"[ODDS API ERROR] fixture {fixture_id} bookmaker {bm_id}: {e}")
                continue

            data = response.json().get("response", [])
            if not data:
                continue

            for bk in data[0].get("bookmakers", []):
                if bk["id"] not in seen:
                    seen.add(bk["id"])
                    merged.append(bk)

        return {"bookmakers": merged} if merged else None

    # --------------------------------------------------------
    # DETECTA SIDE (home / away / total)
    # --------------------------------------------------------
    def _detect_side(self, bet_name: str) -> str:
        name = bet_name.lower()
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
                print(f"[ODDS] Fixture {fixture_id} não encontrado no banco · pulando.")
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
                        BET_ID_PT_MAP.get(bet["id"]) or _market_pt_fallback(bet["name"]),
                    ))

                    market_row_id = cur.fetchone()[0]
                    market_map[(bk["id"], bet["id"])] = market_row_id

            # --------------------------------------------------
            # 3. UPSERT VALUES (ODDS)
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
                    side_team     = self._detect_side(bet["name"])

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
                        handicap  = str(sel.get("handicap", "") or "").strip()

                        # Guarda o value completo da API (ex: "Over 1.5", "Under 0.5").
                        # Assim cada linha é um registro único pelo conflict key (market_row_id, value_name).
                        # line_value vem só do campo handicap quando disponível -- coluna e' numeric,
                        # None vira NULL; string vazia quebra o insert (regressao ja documentada antes).
                        value_name = raw_value
                        line_value = handicap if handicap else None

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
                            BET_ID_PT_MAP.get(bet["id"]) or _market_pt_fallback(bet["name"]),  # market_pt por bet_id, com fallback por nome
                        ))

            if values_batch:
                print(f"[ODDS] Fixture {fixture_id} · inserindo {len(values_batch)} odds...")

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
                        line_value = EXCLUDED.line_value,
                        updated_at = NOW();
                """, values_batch, page_size=500)

                print(f"[ODDS] Fixture {fixture_id} salvo com sucesso · {len(values_batch)} valores.")
            else:
                print(f"[ODDS] Fixture {fixture_id} · nenhuma odd encontrada para salvar.")

            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"[ERRO SAVE ODDS] fixture {fixture_id}: {e}")
            raise

        finally:
            cur.close()
            conn.close()

    # --------------------------------------------------------
    # PROCESSA UM FIXTURE (com retry em deadlock)
    # --------------------------------------------------------
    def process_fixture_odds(self, fixture_id: int, _retry: int = 3):
        import time as _time
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
            print(f"[ODDS] Fixture {fixture_id} · nenhuma casa BR disponível (Bet365/Sportingbet/Betano).")
            return

        print(f"[ODDS] Processando fixture {fixture_id} · {len(br_bookmakers)} casa(s) encontrada(s).")
        for attempt in range(1, _retry + 1):
            try:
                self.save_odds(fixture_id, bookmakers)
                break
            except Exception as e:
                if "deadlock" in str(e).lower() and attempt < _retry:
                    print(f"[ODDS] Deadlock fixture {fixture_id} · tentativa {attempt}/{_retry}, aguardando 2s...")
                    _time.sleep(2)
                else:
                    raise

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

        print(f"\n[ODDS] Concluído · ✅ {success} sucesso(s) | ❌ {failed} erro(s)")