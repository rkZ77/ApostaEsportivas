import os
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv, find_dotenv
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from utils.db_utils import get_connection

load_dotenv(find_dotenv())

# ============================================================
# CONFIG
# ============================================================
API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida no .env")

API_URL = "https://v3.football.api-sports.io/fixtures"
HEADERS = {"x-apisports-key": API_KEY}

# ============================================================
# TIMEZONE BR
# ============================================================
try:
    TZ_LOCAL = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    print("[WARN] zoneinfo não encontrado, usando UTC-3 fixo")
    TZ_LOCAL = timezone(timedelta(hours=-3))


# ============================================================
# CONVERSÃO UTC -> BR (NAIVE · sem tzinfo, para salvar no banco)
# ============================================================
def convert_utc_to_br_naive(dt_str: str) -> datetime:
    dt_utc   = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    dt_local = dt_utc.astimezone(TZ_LOCAL)
    return dt_local.replace(tzinfo=None)



# ============================================================
# CARREGA LIGAS DO BANCO
# ============================================================
def load_leagues_from_db() -> dict:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT league_id, season FROM leagues;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: r[1] for r in rows}


# ============================================================
# SERVICE
# ============================================================
class FixtureCollectorService:

    # --------------------------------------------------------
    # CARREGA IDs DOS TIMES MONITORADOS
    # --------------------------------------------------------
    def _get_all_team_ids(self) -> set:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT team_id FROM teams;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {r[0] for r in rows}

    # --------------------------------------------------------
    # CARREGA IDS JÁ EXISTENTES NO BANCO
    # --------------------------------------------------------
    def _get_existing_fixture_ids(self) -> set:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT fixture_id FROM fixtures;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {r[0] for r in rows}

    # --------------------------------------------------------
    # BUSCA FIXTURES NA API PARA UMA DATA (UTC)
    # Retorna apenas jogos com status NS (não iniciados)
    # dos times e ligas cadastrados no banco.
    # --------------------------------------------------------
    def get_fixtures_by_date(self, target_date) -> list:
        date_str = target_date.strftime("%Y-%m-%d")
        print(f"\n🔎 Buscando fixtures para: {date_str} (UTC)")

        leagues        = load_leagues_from_db()
        valid_team_ids = self._get_all_team_ids()

        if not leagues:
            print("[WARN] Nenhuma liga cadastrada no banco.")
            return []

        if not valid_team_ids:
            print("[WARN] Tabela 'teams' está vazia · nenhum jogo será coletado.")
            print("[WARN] Execute o Stage 1 (sync de times) primeiro.")
            return []

        try:
            response = requests.get(
                API_URL,
                headers=HEADERS,
                params={"date": date_str},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[ERRO] Falha na API: {e}")
            return []

        data     = response.json().get("response", [])
        fixtures = []

        for item in data:
            fixture   = item["fixture"]
            league    = item["league"]
            league_id = league["id"]
            season    = league["season"]
            home_id   = item["teams"]["home"]["id"]
            away_id   = item["teams"]["away"]["id"]
            status    = fixture["status"]["short"]

            # Filtra por liga cadastrada
            if league_id not in leagues:
                continue

            # Filtra por temporada correta
            if season != leagues[league_id]:
                continue

            # Filtra por time monitorado (pelo menos um dos dois)
            if home_id not in valid_team_ids and away_id not in valid_team_ids:
                continue

            # Apenas jogos ainda não iniciados
            if status != "NS":
                continue

            dt_local = convert_utc_to_br_naive(fixture["date"])

            fixtures.append({
                "fixture_id":     fixture["id"],
                "league_id":      league_id,
                "season":         season,
                "home_team_id":   home_id,
                "away_team_id":   away_id,
                "home_team":      item["teams"]["home"]["name"],
                "away_team":      item["teams"]["away"]["name"],
                "match_datetime": dt_local,
                "status":         status,
                "referee":        fixture.get("referee"),
                "round":          league.get("round"),
            })

        print(f"📊 Jogos NS válidos encontrados: {len(fixtures)}")
        return fixtures

    # --------------------------------------------------------
    # COLETA FIXTURES DO DIA DE HOJE (HORÁRIO BRASÍLIA)
    #
    # Por que consultar três datas UTC?
    # Brasília é UTC-3. Jogos noturnos (ex: 21h BR = 00h UTC)
    # aparecem na API com a data UTC do dia SEGUINTE.
    # Adicionamos uma terceira data UTC para capturar jogos que
    # começam às 00:00-02:59 BRT do PRÓXIMO dia, evitando que
    # a pipeline de meia-noite perca esses jogos.
    # --------------------------------------------------------
    # Quantos dias de Brasilia manter, contando hoje. 3 = hoje, amanha e
    # depois. Antes so' hoje era mantido (mais os jogos de 00:xx de amanha),
    # e a tabela `fixtures` ficava sem nada pra frente -- entao qualquer tela
    # de "proximos jogos" dependia de chamar a API na hora.
    DIAS_BR = 3

    def collect_fixtures_today_br(self) -> list:
        now_br   = datetime.now(TZ_LOCAL)
        today_br = now_br.date()
        dias_br  = [today_br + timedelta(days=i) for i in range(self.DIAS_BR)]

        # Brasilia e' UTC-3, entao a janela BR [hoje 00:00, hoje+N 23:59] cai
        # em UTC entre hoje 03:00 e (hoje+N)+1 02:59 -- por isso um dia UTC a
        # mais que o numero de dias BR.
        #
        # O inicio e' a DATA BR, nao "agora convertido pra UTC". Era esse o
        # calculo antigo, e ele furava depois das 21:00 de Brasilia: as 22:00
        # BR o "agora em UTC" ja e' o dia seguinte, entao a consulta comecava
        # em D+1 e perdia todos os jogos de hoje anteriores as 21:00.
        datas_utc = [today_br + timedelta(days=i) for i in range(self.DIAS_BR + 1)]

        print("\n" + "=" * 50)
        print(f"🕒 Execução  : {now_br.strftime('%Y-%m-%d %H:%M:%S')} (horário Brasília)")
        print(f"📅 Dias alvo : {dias_br[0]} a {dias_br[-1]} (Brasília)")
        print(f"🌐 Datas UTC consultadas: {', '.join(str(d) for d in datas_utc)}")

        all_raw = []
        for utc_date in datas_utc:
            all_raw.extend(self.get_fixtures_by_date(utc_date))

        # Remove duplicatas por fixture_id (pode aparecer em mais de uma consulta)
        seen     = set()
        deduped  = []
        for f in all_raw:
            if f["fixture_id"] not in seen:
                seen.add(f["fixture_id"])
                deduped.append(f)

        # match_datetime ja vem convertido pra Brasilia (convert_utc_to_br_naive),
        # entao a comparacao com as datas BR e' direta.
        janela_br = set(dias_br)

        fixtures  = [f for f in deduped if f["match_datetime"].date() in janela_br]
        discarded = len(deduped) - len(fixtures)

        if discarded:
            print(f"[INFO] {discarded} jogo(s) fora da janela descartados após conversão de timezone.")

        print()
        for dia in dias_br:
            n = sum(1 for f in fixtures if f["match_datetime"].date() == dia)
            rotulo = "hoje" if dia == today_br else dia.strftime("%d/%m")
            print(f"✅ Jogos de {rotulo} ({dia}): {n}")
        print("=" * 50)
        return fixtures

    # --------------------------------------------------------
    # SALVA OU ATUALIZA FIXTURES NO BANCO
    # Usa lógica de upsert: insere novos, atualiza existentes.
    # --------------------------------------------------------
    def save_fixtures(self, fixtures: list):
        if not fixtures:
            print("\n⚠️ Nenhum fixture para salvar.")
            return

        conn = get_connection()
        cur  = conn.cursor()

        try:
            existing_ids = self._get_existing_fixture_ids()
            inserts      = 0
            updates      = 0

            for f in fixtures:
                fid = f["fixture_id"]

                if fid in existing_ids:
                    cur.execute("""
                        UPDATE fixtures SET
                            league_id       = %s,
                            season          = %s,
                            home_team_id    = %s,
                            away_team_id    = %s,
                            home_team       = %s,
                            away_team       = %s,
                            match_datetime  = %s,
                            status          = %s,
                            referee         = COALESCE(%s, referee),
                            round           = COALESCE(%s, round),
                            last_updated    = NOW()
                        WHERE fixture_id = %s;
                    """, (
                        f["league_id"],
                        f["season"],
                        f["home_team_id"],
                        f["away_team_id"],
                        f["home_team"],
                        f["away_team"],
                        f["match_datetime"],
                        f["status"],
                        f.get("referee"),
                        f.get("round"),
                        fid,
                    ))
                    updates += 1
                else:
                    cur.execute("""
                        INSERT INTO fixtures (
                            fixture_id, league_id, season,
                            home_team_id, away_team_id,
                            home_team, away_team,
                            match_datetime, status, referee, round,
                            created_at, last_updated
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW());
                    """, (
                        fid,
                        f["league_id"],
                        f["season"],
                        f["home_team_id"],
                        f["away_team_id"],
                        f["home_team"],
                        f["away_team"],
                        f["match_datetime"],
                        f["status"],
                        f.get("referee"),
                        f.get("round"),
                    ))
                    inserts += 1

            conn.commit()

            print("\n💾 Fixtures salvos no banco:")
            print(f"   ➕ Inseridos  : {inserts}")
            print(f"   🔄 Atualizados: {updates}")
            print(f"   📊 Total       : {len(fixtures)}")
            print("-" * 50)

        except Exception as e:
            conn.rollback()
            print(f"\n❌ ERRO ao salvar fixtures: {e}")
            raise

        finally:
            cur.close()
            conn.close()

    # --------------------------------------------------------
    # PIPELINE COMPLETO
    # Busca apenas os jogos de hoje no horário de Brasília
    # e salva no banco.
    # --------------------------------------------------------
    def run(self):
        fixtures = self.collect_fixtures_today_br()
        self.save_fixtures(fixtures)
        return fixtures