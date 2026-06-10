from services.leagues_service import LeaguesService
from services.league_analysis_service import LeagueAnalysisService
from utils.db_utils import get_connection


class AILeagueUpdateMain:

    def __init__(self):
        self.league_service = LeaguesService()
        self.league_generator = LeagueAnalysisService()

    ##########################################################################
    # LIMPAR TABELA league_analysis
    ##########################################################################
    def clear_league_analysis(self):
        print("[AI_LEAGUE_MAIN] Limpando tabela league_analysis...")

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("TRUNCATE TABLE league_analysis;")

        conn.commit()
        cur.close()
        conn.close()

        print("[AI_LEAGUE_MAIN] Tabela league_analysis limpa.\n")

    ##########################################################################
    # IA-1 → AGORA GERA PERFIL POR LIGA, NÃO POR FIXTURE
    ##########################################################################
    def generate_league_profiles(self):
        print("[AI_LEAGUE_MAIN] Gerando análises das ligas (IA 1)...")

        leagues = self.league_service.get_all_leagues()

        if not leagues:
            print("[AI_LEAGUE_MAIN] Nenhuma liga encontrada no banco.")
            return

        for league in leagues:
            league_id = league["league_id"]
            league_name = league["name"]
            season = str(league["season"])

            print(
                f"[AI_LEAGUE_MAIN] Analisando liga: {league_name} ({season})")

            try:
                self.league_generator.generate_and_save(
                    league_id=league_id,
                    league_name=league_name,
                    season=season
                )
                print(
                    f"[AI_LEAGUE_MAIN] ✓ OK → Liga {league_name} ({season}) atualizada."
                )
            except Exception as e:
                print(
                    f"[AI_LEAGUE_MAIN] ERRO ao analisar liga {league_name}: {e}")

        print("[AI_LEAGUE_MAIN] Todas análises atualizadas.\n")


if __name__ == "__main__":
    ai = AILeagueUpdateMain()
    ai.clear_league_analysis()
    ai.generate_league_profiles()
