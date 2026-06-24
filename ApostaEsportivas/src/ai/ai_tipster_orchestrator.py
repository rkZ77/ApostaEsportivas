import time
from services.team_stats_service import TeamStatsService
from services.match_stats_service import MatchStatsService, NATIONAL_TEAM_LEAGUE_IDS
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
            # Stats de seleções são salvas com league_id=1 pelo process_national_team
            # =====================
            is_national = league_id in NATIONAL_TEAM_LEAGUE_IDS
            stats_league_id = 1 if is_national else league_id

            home_stats = self.team_stats.get_stats(
                team_id=home_id,
                league_id=stats_league_id,
                season=season,
                context_type="HOME"
            )

            away_stats = self.team_stats.get_stats(
                team_id=away_id,
                league_id=stats_league_id,
                season=season,
                context_type="AWAY"
            )

            if not home_stats or not away_stats:
                print(f"[TIPSTER] Sem stats -> pulando {fixture_id}")
                return None

            # =============================
            # HISTÓRICO — seleções usam cross-competition (último 15 de qualquer liga)
            # =============================

            if is_national:
                home_matches       = self.match_stats.get_last_n_all_competitions(home_id, limit=15)
                away_matches       = self.match_stats.get_last_n_all_competitions(away_id, limit=15)
                total_home_matches = home_matches
                total_away_matches = away_matches
            else:
                home_matches = self.match_stats.get_all_matches(
                    team_id=home_id, season=season, league_id=league_id, is_home=True
                )
                away_matches = self.match_stats.get_all_matches(
                    team_id=away_id, season=season, league_id=league_id, is_home=False
                )
                total_home_matches = self.match_stats.get_total_matches(
                    team_id=home_id, season=season, league_id=league_id
                )
                total_away_matches = self.match_stats.get_total_matches(
                    team_id=away_id, season=season, league_id=league_id
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
    # Processa fixture da Copa do Mundo — mesmo formato do VIP regular
    ##########################################################################
    @staticmethod
    def _compute_copa_team_avgs(matches: list, team_id: int) -> dict:
        """Médias feitas/cedidas para seleção em jogos de mando misto."""
        if not matches:
            return {}
        n = len(matches)
        gf = ga = cf = ca = yf = tg_s = tc_s = 0
        for m in matches:
            is_home = m.get("home_team_id") == team_id
            gf  += (m.get("home_goals") or 0)        if is_home else (m.get("away_goals") or 0)
            ga  += (m.get("away_goals") or 0)        if is_home else (m.get("home_goals") or 0)
            cf  += (m.get("home_corners") or 0)      if is_home else (m.get("away_corners") or 0)
            ca  += (m.get("away_corners") or 0)      if is_home else (m.get("home_corners") or 0)
            yf  += (m.get("home_yellow_cards") or 0) if is_home else (m.get("away_yellow_cards") or 0)
            tg_s += (m.get("total_goals") or 0)
            tc_s += (m.get("total_corners") or 0)
        btts = sum(1 for m in matches if (m.get("home_goals") or 0) > 0 and (m.get("away_goals") or 0) > 0)
        return {
            "jogos":                    n,
            "gols_feitos_media":        round(gf  / n, 2),
            "gols_cedidos_media":       round(ga  / n, 2),
            "total_gols_media":         round(tg_s / n, 2),
            "escanteios_feitos_media":  round(cf  / n, 2),
            "escanteios_cedidos_media": round(ca  / n, 2),
            "total_escanteios_media":   round(tc_s / n, 2),
            "amarelos_media":           round(yf  / n, 2),
            "btts_pct":                 round(btts / n * 100, 1),
        }

    def _process_world_cup_fixture(self, fx, performance_str: str | None = None):
        """Copa do Mundo — mesmo pipeline de dados que ligas regulares.
        Envia últimos 10 jogos da seleção (com competition_type) como histórico total,
        e médias feitas/cedidas pré-calculadas nos blocos de estatísticas.
        """
        fixture_id = fx["fixture_id"]
        season     = fx["season"]
        league_id  = fx["league_id"]
        home_id    = fx["home_team_id"]
        away_id    = fx["away_team_id"]

        try:
            print(f"[TIPSTER] Buscando perfil da seleção home (ID: {home_id})...")
            home_profile = self.national_team_profile.get_team_profile(home_id, season, fixture_id=fixture_id)

            print(f"[TIPSTER] Buscando perfil da seleção away (ID: {away_id})...")
            away_profile = self.national_team_profile.get_team_profile(away_id, season, fixture_id=fixture_id)

            print(f"[TIPSTER] Perfil {home_profile['team_name']}: {home_profile['matches_analyzed']} jogos")
            print(f"[TIPSTER] Perfil {away_profile['team_name']}: {away_profile['matches_analyzed']} jogos")

            # Últimos 10 jogos já buscados durante get_team_profile (sem 2ª chamada ao DB)
            home_matches_raw = home_profile.get("matches_raw", [])
            away_matches_raw = away_profile.get("matches_raw", [])

            # Médias feitas/cedidas (mando misto corrigido por time_id)
            home_avgs = self._compute_copa_team_avgs(home_matches_raw, home_id)
            away_avgs = self._compute_copa_team_avgs(away_matches_raw, away_id)

            # Bloco de estatísticas completo (feitas/cedidas + perfil)
            home_stats = {
                **home_avgs,
                "quality_breakdown": home_profile.get("quality_breakdown", {}),
                "squad_info":        home_profile.get("squad_info", {}),
                "injuries":          home_profile.get("injuries", []),
                "tactical_profile":  home_profile.get("tactical_profile", {}),
                "strengths":         home_profile.get("strengths", []),
                "weaknesses":        home_profile.get("weaknesses", []),
            }
            away_stats = {
                **away_avgs,
                "quality_breakdown": away_profile.get("quality_breakdown", {}),
                "squad_info":        away_profile.get("squad_info", {}),
                "injuries":          away_profile.get("injuries", []),
                "tactical_profile":  away_profile.get("tactical_profile", {}),
                "strengths":         away_profile.get("strengths", []),
                "weaknesses":        away_profile.get("weaknesses", []),
            }

            # Classificação — grupo + situação + Copa stats
            try:
                home_standing = self.standings.get_team_standing(home_id, league_id, season)
            except Exception:
                home_standing = None
            try:
                away_standing = self.standings.get_team_standing(away_id, league_id, season)
            except Exception:
                away_standing = None

            # Grupo detalhado (inclui description/situação da Copa)
            home_group_data = self.prompt_builder._fetch_group_standing(home_id)
            away_group_data = self.prompt_builder._fetch_group_standing(away_id)

            if home_standing and away_standing:
                standings_stats = {
                    "home_rank":        home_standing["rank"],
                    "away_rank":        away_standing["rank"],
                    "rank_diff":        home_standing["rank"] - away_standing["rank"],
                    "home_points":      home_standing["points"],
                    "away_points":      away_standing["points"],
                    "points_diff":      home_standing["points"] - away_standing["points"],
                    "home_goal_diff":   home_standing["goal_diff"],
                    "away_goal_diff":   away_standing["goal_diff"],
                    "goal_diff_diff":   home_standing["goal_diff"] - away_standing["goal_diff"],
                    "home_form":        home_standing["form"],
                    "away_form":        away_standing["form"],
                }
            else:
                standings_stats = {}

            standings_stats.update({
                "home_group":       home_group_data.get("group")       if home_group_data else None,
                "away_group":       away_group_data.get("group")       if away_group_data else None,
                "home_situacao":    (home_group_data.get("description") or "em disputa") if home_group_data else "em disputa",
                "away_situacao":    (away_group_data.get("description") or "em disputa") if away_group_data else "em disputa",
                "home_copa_stats":  home_profile.get("copa_stats", {}),
                "away_copa_stats":  away_profile.get("copa_stats", {}),
            })

            # Árbitro
            referee = fx.get("referee")
            referee_stats = None
            if referee:
                try:
                    referee_stats = self.referee_stats.get_stats(referee, season)
                except Exception:
                    referee_stats = None

            # Passa histórico como total_matches (home/away vazios → IA recebe o total)
            result = self.ai.generate_and_save(
                fx,
                home_stats,
                away_stats,
                [],                  # home_matches (Copa = sem contexto de mando)
                [],                  # away_matches
                home_matches_raw,    # total_home_matches (últimos 10 com competition_type)
                away_matches_raw,    # total_away_matches
                standings_stats,
                referee_stats=referee_stats,
                league_id=league_id,
                performance_str=performance_str,
            )

            if result:
                print(f"[TIPSTER] Sugestao salva para fixture {fixture_id}")
            else:
                print(f"[TIPSTER] Nenhuma sugestao valida para fixture {fixture_id}")

            return result

        except Exception as e:
            print(f"[TIPSTER] ERRO Copa fixture {fixture_id}: {e}")
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