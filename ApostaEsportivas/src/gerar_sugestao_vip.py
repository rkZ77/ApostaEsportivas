import sys
sys.stdout.reconfigure(encoding="utf-8")

from services.fixtures_service import FixturesService
from ai.ai_tipster_orchestrator import AITipsterOrchestrator


class AIVipSuggestionsMain:

    def __init__(self):
        self.fixture_service = FixturesService()
        self.orchestrator = AITipsterOrchestrator()

    ##########################################################################
    # IA-2 → SUGESTÕES POR FIXTURE
    ##########################################################################
    def generate_vip_suggestions(self):
        fixtures = self.fixture_service.get_ns_without_suggestions()

        if not fixtures:
            print("[AI_VIP_MAIN] Nenhum fixture pendente.\n")
            return

        print(
            f"[AI_VIP_MAIN] Executando IA-2 para {len(fixtures)} fixtures...\n")

        print("=== FIXTURES ENVIADOS PARA A IA ===")
        for f in fixtures:
            print(
                f"ID {f['fixture_id']} | "
                f"{f['home_team']} vs {f['away_team']} | "
                f"{f['match_datetime']} | "
                f"Liga: {f['league_id']} | "
                f"Season: {f['season']}"
            )
        print("====================================\n")

        # Executa IA
        self.orchestrator.run_for_fixtures(fixtures)


if __name__ == "__main__":
    ai = AIVipSuggestionsMain()
    ai.generate_vip_suggestions()
