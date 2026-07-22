import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.ai_result_checker_service import AIResultCheckerService
from services.ai_result_checker_multiplas import AIMultiplasCheckerService
from services.ai_result_checker_alavancagem import AIResultCheckerAlavancagem
from services.ai_result_checker_free import AIResultCheckerFree
from collectors.match_statistics_sync_service import MatchStatisticsSyncService
from services.picks_ledger_sync_service import sync as sync_picks_ledger


class AIUpdateResultsMain:

    def __init__(self):
        # SINGLE VIP
        self.result_checker_vip = AIResultCheckerService("picks_vip")

        # FREE (Pick do Dia)
        self.result_checker_free = AIResultCheckerFree()

        # MULTIPLAS
        self.result_checker_multiplas = AIMultiplasCheckerService("picks_multiplas")

        # ALAVANCAGEM
        self.result_checker_alavancagem = AIResultCheckerAlavancagem()

        # STATS SYNC
        self.stats_sync = MatchStatisticsSyncService()

    ##########################################################################
    # ATUALIZA RESULTADOS
    ##########################################################################
    def update_all_results(self):
        print("[AI_UPDATE_MAIN] Atualizando resultados...")

        # Garante que fixtures pendentes têm stats antes de checar
        self.stats_sync.sync_pending_fixtures()

        # VIP
        updated_vip = self.result_checker_vip.check_all_results()

        # FREE
        updated_free = self.result_checker_free.check_all_results()

        # MULTIPLAS
        updated_multiplas = self.result_checker_multiplas.check_all_results()

        # ALAVANCAGEM
        updated_alav = self.result_checker_alavancagem.check_all_results()

        print(
            f"[AI_UPDATE_MAIN] VIP: {updated_vip} | Free: {updated_free} | "
            f"Multiplas: {updated_multiplas} | Alavancagem: {updated_alav}"
        )

        # Sincroniza a tabela unificada (picks_ledger) -- nunca escreve nas
        # 4 tabelas acima, so le delas. Falha aqui nunca derruba a checagem
        # de resultado em si (ja concluida nas linhas anteriores).
        try:
            sync_picks_ledger()
        except Exception as e:
            print(f"[AI_UPDATE_MAIN] Aviso: falha ao sincronizar picks_ledger (nao afeta resultados): {e}")


if __name__ == "__main__":
    ai = AIUpdateResultsMain()
    ai.update_all_results()
