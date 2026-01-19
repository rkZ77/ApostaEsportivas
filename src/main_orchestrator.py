import datetime
from src.collectors.fixture_collector_service import FixtureCollectorService
from src.services.pre_game_suggestion_service import PreGameSuggestionService
from src.services.post_game_evaluation_service import evaluate_recommendations
from src.services.metrics_service import get_metrics

from dotenv import load_dotenv
load_dotenv()


class MainOrchestrator:

    def __init__(self):
        self.fixture_collector = FixtureCollectorService()
        self.pre_game = PreGameSuggestionService()

        # Ligas suportadas pelo sistema
        self.SUPPORTED_LEAGUES = {
            39,     # Premier League
            71,     # Brasileirão Série A
            475,    # Paulistão (A1)
            140,    # La Liga
            78      # Bundesliga
        }

    # ---------------------------
    # ETAPA 1 - FIXTURES
    # ---------------------------
    def run_fixtures(self):
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)

        print("========== ETAPA 1: FIXTURES ==========")
        print(f"[FIXTURES] Buscando jogos {today} e {tomorrow}")

        fixtures_today = self.fixture_collector.get_fixtures_by_date(today)
        fixtures_tomorrow = self.fixture_collector.get_fixtures_by_date(
            tomorrow)

        fixtures = fixtures_today + fixtures_tomorrow

        # Filtrar apenas ligas suportadas
        fixtures = [
            f for f in fixtures
            if f["league_id"] in self.SUPPORTED_LEAGUES
        ]

        print(
            f"[FIXTURES] Encontrados {len(fixtures)} jogos das ligas suportadas.")

        # Salvar no banco
        self.fixture_collector.save_fixtures(fixtures)

        return fixtures

    # ---------------------------
    # ETAPA 2 - PRE GAME
    # ---------------------------
    def run_pre_game(self):
        print("\n========== ETAPA 2: PRÉ-JOGO ==========")
        fixtures = self.run_fixtures()

        if not fixtures:
            print("[PRE-JOGO] Nenhum jogo encontrado das ligas suportadas.")
            return

        for fx in fixtures:
            self.pre_game.generate_pre_game(fx)

    # ---------------------------
    # ETAPA 3 - PÓS-JOGO
    # ---------------------------
    def run_post_game(self):
        print("\n========== ETAPA 3: PÓS-JOGO ==========")
        evaluate_recommendations()

    # ---------------------------
    # ETAPA 4 - METRICS
    # ---------------------------
    def run_metrics(self):
        print("\n========== ETAPA 4: MÉTRICAS ==========")
        get_metrics()

    # ---------------------------
    # EXECUTAR TUDO
    # ---------------------------
    def run_all(self):
        print("\n========== ORCHESTRATOR INICIADO ==========")

        self.run_pre_game()
        self.run_post_game()
        self.run_metrics()


if __name__ == "__main__":
    orchestrator = MainOrchestrator()
    orchestrator.run_all()
