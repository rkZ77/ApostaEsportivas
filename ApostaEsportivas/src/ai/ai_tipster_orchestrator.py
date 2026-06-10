import time
from services.team_stats_service import TeamStatsService
from services.match_stats_service import MatchStatsService
from services.standings_service import StandingsService
from services.referee_stats_service import RefereeStatsService
from services.ai_performance_service import AIPerformanceService
from services.historical_api_fetcher import HistoricalApiFetcher
from services.national_team_profile_service import NationalTeamProfileService
from ai.ai_suggestions_service import AISuggestionsService
from ai.prompts.team_prompt_builder import TeamPromptBuilder
from ai.prompts import get_prompt


class AITipsterOrchestrator:

    def __init__(self):
        self.team_stats = TeamStatsService()
        self.match_stats = MatchStatsService()
        self.standings = StandingsService()
        self.referee_stats = RefereeStatsService()
        self.performance = AIPerformanceService()
        self.historical_api = HistoricalApiFetcher()
        self.national_team_profile = NationalTeamProfileService()
        self.prompt_builder = TeamPromptBuilder()
        self.ai = AISuggestionsService()

    ##########################################################################
    # Processa 1 fixture
    ##########################################################################
    def run_single_fixture(self, fx, performance_str: str | None = None):

        fixture_id = fx["fixture_id"]
        season = fx["season"]
        league_id = fx["league_id"]

        print(f"[TIPSTER] Processando fixture {fixture_id}...")

        try:
            home_id = fx["home_team_id"]
            away_id = fx["away_team_id"]
            
            # ========== SISTEMA DE SELEÇÕES PARA COPA DO MUNDO ==========
            if league_id == 1:  # Copa do Mundo
                print(f"[TIPSTER] 🏆 Copa do Mundo detectada - usando sistema de seleções")
                return self._process_world_cup_fixture(fx, performance_str)
            # =============================================================

            # =====================
            # CLASSIFICAÇÃO (opcional — não bloqueia a análise)
            # =====================
            try:
                home_standing = self.standings.get_team_standing(
                    team_id=home_id,
                    league_id=league_id,
                    season=season
                )
            except Exception:
                home_standing = None

            try:
                away_standing = self.standings.get_team_standing(
                    team_id=away_id,
                    league_id=league_id,
                    season=season
                )
            except Exception:
                away_standing = None

            if home_standing and away_standing:
                standings_stats = {
                    "home_rank":      home_standing["rank"],
                    "away_rank":      away_standing["rank"],
                    "rank_diff":      home_standing["rank"] - away_standing["rank"],
                    "home_points":    home_standing["points"],
                    "away_points":    away_standing["points"],
                    "points_diff":    home_standing["points"] - away_standing["points"],
                    "home_goal_diff": home_standing["goal_diff"],
                    "away_goal_diff": away_standing["goal_diff"],
                    "goal_diff_diff": home_standing["goal_diff"] - away_standing["goal_diff"],
                    "home_form":      home_standing["form"],
                    "away_form":      away_standing["form"],
                }
            else:
                standings_stats = {}
                print(f"[TIPSTER] Sem standings para {fixture_id} — IA usará apenas stats e histórico")

            # =====================
            # MÉDIAS (contexto)
            # =====================
            home_stats = self.team_stats.get_stats(
                team_id=home_id,
                league_id=league_id,
                season=season,
                context_type="HOME"
            )

            away_stats = self.team_stats.get_stats(
                team_id=away_id,
                league_id=league_id,
                season=season,
                context_type="AWAY"
            )

            if not home_stats or not away_stats:
                print(f"[TIPSTER] Sem stats -> pulando {fixture_id}")
                return None

            # =============================
            # HISTÓRICO FILTRADO (Casa/Fora)
            # =============================
            home_matches = self.match_stats.get_all_matches(
                team_id=home_id,
                season=season,
                league_id=league_id,
                is_home=True
            )

            away_matches = self.match_stats.get_all_matches(
                team_id=away_id,
                season=season,
                league_id=league_id,
                is_home=False
            )

            # =============================
            # HISTÓRICO TOTAL
            # =============================
            total_home_matches = self.match_stats.get_total_matches(
                team_id=home_id,
                season=season,
                league_id=league_id
            )

            total_away_matches = self.match_stats.get_total_matches(
                team_id=away_id,
                season=season,
                league_id=league_id
            )

            # =============================
            # FALLBACK: sem histórico no banco
            # → busca últimos 8 jogos na API (amistosos, outras comps.)
            # =============================
            if not home_matches and not total_home_matches:
                print(f"[TIPSTER] Sem historico no banco para home {home_id} — buscando na API...")
                total_home_matches = self.historical_api.get_recent_with_stats(home_id, n=8)
                if total_home_matches:
                    print(f"[TIPSTER] {len(total_home_matches)} jogo(s) externos carregados para home {home_id}")

            if not away_matches and not total_away_matches:
                print(f"[TIPSTER] Sem historico no banco para away {away_id} — buscando na API...")
                total_away_matches = self.historical_api.get_recent_with_stats(away_id, n=8)
                if total_away_matches:
                    print(f"[TIPSTER] {len(total_away_matches)} jogo(s) externos carregados para away {away_id}")

            # ======================================
            # ÁRBITRO
            # ======================================
            referee = fx.get("referee")
            referee_stats = None
            if referee:
                try:
                    referee_stats = self.referee_stats.get_stats(referee, season)
                except Exception:
                    referee_stats = None

            if referee:
                print(f"[TIPSTER] Arbitro: {referee} | stats: {referee_stats}")
            else:
                print(f"[TIPSTER] Arbitro nao identificado para {fixture_id}")

            # ======================================
            # IA recebe os blocos + prompt da liga
            # ======================================
            result = self.ai.generate_and_save(
                fx,
                home_stats,
                away_stats,
                home_matches,
                away_matches,
                total_home_matches,
                total_away_matches,
                standings_stats,
                referee_stats=referee_stats,
                league_id=league_id,
                performance_str=performance_str,
            )

            if result:
                print(f"[TIPSTER] OK -> sugestao salva para {fixture_id}")
            else:
                print(f"[TIPSTER] Nenhuma sugestão válida para {fixture_id}")

            return result

        except Exception as e:
            print(f"[TIPSTER] ERRO fixture {fixture_id}: {e}")
            return None

    ##########################################################################
    # Processa fixture da Copa do Mundo com sistema de seleções
    ##########################################################################
    def _process_world_cup_fixture(self, fx, performance_str: str | None = None):
        """Processa fixture da Copa do Mundo usando perfis personalizados de seleções"""
        
        fixture_id = fx["fixture_id"]
        season = fx["season"]
        league_id = fx["league_id"]
        home_id = fx["home_team_id"]
        away_id = fx["away_team_id"]
        
        try:
            # Buscar perfis das seleções (fixture_id para injuries precisas)
            print(f"[TIPSTER] Buscando perfil da seleção home (ID: {home_id})...")
            home_profile = self.national_team_profile.get_team_profile(home_id, season, fixture_id=fixture_id)

            print(f"[TIPSTER] Buscando perfil da seleção away (ID: {away_id})...")
            away_profile = self.national_team_profile.get_team_profile(away_id, season, fixture_id=fixture_id)
            
            print(f"[TIPSTER] ✓ Perfil {home_profile['team_name']}: {home_profile['matches_analyzed']} jogos analisados")
            print(f"[TIPSTER] ✓ Perfil {away_profile['team_name']}: {away_profile['matches_analyzed']} jogos analisados")
            
            # Construir prompt personalizado
            print(f"[TIPSTER] Construindo prompt personalizado...")
            base_prompt = get_prompt(league_id)  # Prompt base da Copa
            custom_prompt = self.prompt_builder.build_world_cup_prompt(
                home_profile,
                away_profile,
                base_prompt
            )
            
            print(f"[TIPSTER] ✓ Prompt personalizado gerado ({len(custom_prompt)} caracteres)")
            
            # Buscar dados adicionais (standings, referee, etc.)
            # Standings (opcional para Copa)
            try:
                home_standing = self.standings.get_team_standing(
                    team_id=home_id,
                    league_id=league_id,
                    season=season
                )
            except Exception:
                home_standing = None

            try:
                away_standing = self.standings.get_team_standing(
                    team_id=away_id,
                    league_id=league_id,
                    season=season
                )
            except Exception:
                away_standing = None

            if home_standing and away_standing:
                standings_stats = {
                    "home_rank":      home_standing["rank"],
                    "away_rank":      away_standing["rank"],
                    "rank_diff":      home_standing["rank"] - away_standing["rank"],
                    "home_points":    home_standing["points"],
                    "away_points":    away_standing["points"],
                    "points_diff":    home_standing["points"] - away_standing["points"],
                    "home_goal_diff": home_standing["goal_diff"],
                    "away_goal_diff": away_standing["goal_diff"],
                    "goal_diff_diff": home_standing["goal_diff"] - away_standing["goal_diff"],
                    "home_form":      home_standing["form"],
                    "away_form":      away_standing["form"],
                }
            else:
                standings_stats = {}
            
            # Stats agregadas (usar do perfil se disponível)
            home_stats = {
                "avg_goals_for": home_profile["offensive_stats"].get("goals_per_game", 0),
                "avg_goals_against": home_profile["defensive_stats"].get("goals_against_per_game", 0),
                "avg_corners": home_profile["set_pieces"].get("corners_per_game", 0),
                "avg_cards_yellow": home_profile["discipline"].get("yellow_cards_per_game", 0),
            }
            
            away_stats = {
                "avg_goals_for": away_profile["offensive_stats"].get("goals_per_game", 0),
                "avg_goals_against": away_profile["defensive_stats"].get("goals_against_per_game", 0),
                "avg_corners": away_profile["set_pieces"].get("corners_per_game", 0),
                "avg_cards_yellow": away_profile["discipline"].get("yellow_cards_per_game", 0),
            }
            
            # Histórico (vazio para Copa - já está no perfil)
            home_matches = []
            away_matches = []
            total_home_matches = []
            total_away_matches = []
            
            # Árbitro
            referee = fx.get("referee")
            referee_stats = None
            if referee:
                try:
                    referee_stats = self.referee_stats.get_stats(referee, season)
                except Exception:
                    referee_stats = None
            
            # Chamar IA com prompt customizado
            result = self.ai.generate_and_save(
                fx,
                home_stats,
                away_stats,
                home_matches,
                away_matches,
                total_home_matches,
                total_away_matches,
                standings_stats,
                referee_stats=referee_stats,
                league_id=league_id,
                performance_str=performance_str,
                custom_prompt=custom_prompt  # NOVO parâmetro
            )
            
            if result:
                print(f"[TIPSTER] ✅ Sugestão salva para fixture {fixture_id}")
            else:
                print(f"[TIPSTER] ⚠️ Nenhuma sugestão válida para fixture {fixture_id}")
            
            return result
            
        except Exception as e:
            print(f"[TIPSTER] ❌ ERRO ao processar Copa do Mundo fixture {fixture_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    ##########################################################################
    # Processar lista completa
    ##########################################################################
    def run_for_fixtures(self, fixtures):
        # Busca desempenho histórico uma vez para todos os fixtures do dia
        performance_str = self.performance.format_for_prompt()
        print(f"[TIPSTER] Desempenho historico carregado: {performance_str[:80]}...")

        results = []
        for fx in fixtures:
            sug = self.run_single_fixture(fx, performance_str=performance_str)
            if sug:
                results.append(sug)

        return results