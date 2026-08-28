from contextlib import contextmanager

from utils.db_utils import get_connection
from services.team_stats_reader import TeamStatsReader
from services.match_stats_service_media import MatchStatsServiceMedia


class TeamStatsAggregatorService:

    def __init__(self):
        self.reader = TeamStatsReader()
        self.match_stats = MatchStatsServiceMedia()

    ##########################################################################
    # Uma conexão pro lote inteiro
    ##########################################################################
    def _compartilhaveis(self):
        """Os objetos que sabem receber uma conexão de fora."""
        return [o for o in (getattr(self, "reader", None),
                            getattr(self, "match_stats", None))
                if o is not None and hasattr(o, "_abrir")]

    def _recuperar(self):
        """Desfaz a transação da conexão de lote depois de um erro."""
        alvos = self._compartilhaveis()
        conn = next((o._conn for o in alvos if getattr(o, "_conn", None)), None)
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:
            # Conexão perdida de vez: volta pro modo uma-por-consulta em vez
            # de reprovar todo o resto do lote.
            for alvo in alvos:
                alvo._conn = None

    @contextmanager
    def _em_lote(self):
        """Troca as conexões por-consulta por UMA, pela duração do lote.

        Abrir conexão com o Supabase custa ~1000ms medidos, contra ~150ms da
        consulta (e menos de 1ms de plano: o custo é handshake). Cada time
        custava 3 aberturas -- ler os jogos e gravar os dois contextos -- então
        uma passada de 50 times abria 150 conexões pra fazer 150 consultas
        baratas.

        E isso não roda só na mão: `website/backend/stats_sweep` chama
        `update_stale_teams_statistics()` numa VISITA ao site, em thread de
        fundo. As conexões saem das mesmas ~57 que o projeto Supabase dá pro
        site inteiro (ver website/backend/database), então a rajada tirava
        capacidade de quem estava navegando -- tela que carrega na hora e tela
        que fica pendurada, dependendo de cair no meio de uma varredura.

        Falha ao abrir NÃO derruba o lote: sem conexão compartilhada cada
        chamada volta a abrir a sua, que é o comportamento de antes.
        """
        try:
            conn = get_connection()
        except Exception as e:
            print(f"[TeamStatsAggregatorService] sem conexao de lote ({e}) · "
                  "seguindo com uma por consulta.")
            yield
            return
        # setattr defensivo: `reader`/`match_stats` sao substituidos por dubles
        # nos testes, e um duble nao precisa conhecer conexao nenhuma.
        for alvo in self._compartilhaveis():
            alvo._conn = conn
        try:
            yield
        finally:
            for alvo in self._compartilhaveis():
                alvo._conn = None
            try:
                conn.close()
            except Exception:
                pass

    ##########################################################################
    # Processa UM time
    ##########################################################################
    def process_single_team(self, team_id, league_id, season):

        print(
            f"-> Processando | Team {team_id} | Liga {league_id} | Season {season}")

        stats_list = self.match_stats.calculate_team_season_averages(
            team_id=team_id,
            league_id=league_id,
            season=season
        )

        if not stats_list:
            print("   -- Nenhum jogo FT encontrado\n")
            return

        for stats in stats_list:

            self.reader.upsert_team_statistics(
                team_id=team_id,
                league_id=league_id,
                season=season,
                stats=stats
            )

            print(
                f"   ok Salvo | {stats['context_type']} | Jogos: {stats['games_count']}"
            )

        print()

    ##########################################################################
    # Atualiza só times com fixtures recentes (padrão do pipeline)
    ##########################################################################
    def update_recent_teams_statistics(self, days=3):

        with self._em_lote():
            print(
                f"\n[TeamStatsAggregatorService] Atualizando times com fixtures dos últimos {days} dias...\n")

            teams = self.reader.get_teams_with_recent_fixtures(days=days)

            if not teams:
                print("[TeamStatsAggregatorService] Nenhum time com fixtures recentes.\n")
                return

            total = len(teams)
            processed = 0

            for t in teams:

                self.process_single_team(
                    team_id=t["team_id"],
                    league_id=t["league_id"],
                    season=t["season"]
                )

                processed += 1
                print(f"Progresso: {processed}/{total}\n")

            print("\n[TeamStatsAggregatorService] Finalizado.\n")

    ##########################################################################
    # Atualiza SÓ o que ficou desatualizado (2026-08-27)
    ##########################################################################
    def update_stale_teams_statistics(self, limite: int = 0, progresso=None) -> dict:
        """Recalcula a média só dos times cuja partida é mais nova que a média.

        É o meio-termo que faltava entre reprocessar a temporada inteira
        (`update_full_season_statistics`, que APAGA a tabela) e reprocessar todo
        time que jogou nos últimos dias (`update_recent_teams_statistics`, que
        refaz a conta de quem não mudou). Ver a docstring de
        `TeamStatsReader.get_teams_with_stale_statistics`.

        `progresso(feitos, total)` é chamado a cada time · o /admin usa pra
        mostrar a barra sem precisar ler o stdout.

        Não custa requisição de API nenhuma: tudo sai do banco.
        """
        with self._em_lote():
            alvos = self.reader.get_teams_with_stale_statistics(limite=limite)
            total = len(alvos)
            print(f"\n[TeamStatsAggregatorService] {total} time(s) com média desatualizada.\n")

            feitos, falhas = 0, 0
            for t in alvos:
                try:
                    self.process_single_team(
                        team_id=t["team_id"], league_id=t["league_id"], season=t["season"])
                except Exception as e:
                    # Um time que falha não pode derrubar o lote · a média dele
                    # continua velha e ele volta na próxima passada, porque o
                    # critério é o estado do banco e não uma lista guardada.
                    falhas += 1
                    print(f"   -- Falha no time {t['team_id']}: {e}")
                    # Com a conexão compartilhada, o erro deixa a transação
                    # abortada e TODO time seguinte falharia com "current
                    # transaction is aborted". Com uma conexão por consulta
                    # isso não acontecia · é a contrapartida do lote, e o
                    # rollback é o preço dela.
                    self._recuperar()
                feitos += 1
                if progresso:
                    progresso(feitos, total)

            print(f"\n[TeamStatsAggregatorService] {feitos - falhas} de {total} atualizados.\n")
            return {"total": total, "feitos": feitos, "falhas": falhas}

    ##########################################################################
    # Processa seleção nacional · últimos N jogos (amistosos + Copa)
    ##########################################################################
    def process_national_team(self, team_id, season=2026, last_n=10):

        print(f"-> Seleção | Team {team_id} | Copa {season} | Últimos {last_n} jogos")

        stats_list = self.match_stats.calculate_national_team_averages(
            team_id=team_id,
            last_n=last_n
        )

        if not stats_list:
            print("   -- Nenhum jogo encontrado\n")
            return

        for stats in stats_list:

            self.reader.upsert_team_statistics(
                team_id=team_id,
                league_id=1,  # Copa do Mundo
                season=season,
                stats=stats
            )

            print(f"   ok Salvo | {stats['context_type']} | Jogos: {stats['games_count']}")

        print()

    ##########################################################################
    # Reprocessa TODOS os times (rebuild completo)
    ##########################################################################
    def update_full_season_statistics(self):

        with self._em_lote():
            print(
                "\n[TeamStatsAggregatorService] Reprocessando temporada completa...\n")

            self.reader.delete_all_team_statistics()

            teams = self.reader.get_all_teams()

            total = len(teams)
            processed = 0

            for t in teams:

                self.process_single_team(
                    team_id=t["team_id"],
                    league_id=t["league_id"],
                    season=t["season"]
                )

                processed += 1
                print(f"Progresso: {processed}/{total}\n")

            print("\n[TeamStatsAggregatorService] Finalizado.\n")
