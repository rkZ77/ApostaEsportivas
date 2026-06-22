"""
Serviço de Perfil de Seleções Nacionais para Copa do Mundo

Busca e analisa dados de seleções usando:
1. Dados do banco (match_statistics) - prioridade
2. API Football (últimos jogos) - complemento quando necessário

Gera perfil completo com análise tática, métricas e pontos fortes/fracos.
"""

import os
from datetime import datetime
from utils.db_utils import get_connection
from services.historical_api_fetcher import HistoricalApiFetcher
from services.world_cup_squad_service import WorldCupSquadService


class NationalTeamProfileService:

    def __init__(self):
        self.cache = {}  # Cache em memória: {team_id: {season: profile}}
        self.historical_api = HistoricalApiFetcher()
        self.squad_service = WorldCupSquadService()
        
    # ========================================================================
    # MÉTODO PRINCIPAL - Retorna perfil completo da seleção
    # ========================================================================
    def get_team_profile(self, team_id: int, season: int, fixture_id: int = None) -> dict:
        """
        Busca perfil completo da seleção.

        fixture_id é usado para buscar lesionados/suspensos específicos do jogo.
        """
        # Injuries são fixture-específicos; o resto pode ser cacheado por team+season
        cache_key = f"{team_id}_{season}"
        if cache_key in self.cache and fixture_id is None:
            print(f"[PROFILE] Cache hit para team {team_id}")
            return self.cache[cache_key]

        print(f"[PROFILE] Gerando perfil para team {team_id}, season {season}")

        # Busca informações básicas do time
        team_info = self._get_team_info(team_id)

        # Busca convocados, técnico e formação
        squad_info = self.squad_service.get_squad_info(team_id)

        # Busca lesionados/suspensos (específico por fixture se disponível)
        injuries = self.squad_service.get_injuries(
            team_id=team_id,
            fixture_id=fixture_id,
            season=season,
            league_id=1,
        )

        # Busca últimos jogos (forma geral: eliminatórias + amistosos + Copa)
        matches = self._fetch_recent_matches(team_id, limit=10)

        # Busca jogos específicos desta Copa
        copa_matches = self._fetch_copa_matches(team_id, season)
        
        print(f"[PROFILE] {len(matches)} jogos encontrados para análise | {len(copa_matches)} da Copa")

        if len(matches) < 5:
            print(f"[PROFILE] AVISO: Apenas {len(matches)} jogos disponíveis - análise limitada")
        
        # Analisa padrões táticos
        tactical_profile = self._analyze_tactical_patterns(matches, team_id)
        
        # Calcula métricas de forma
        form_metrics = self._calculate_form_metrics(matches, team_id)
        
        # Calcula estatísticas ofensivas
        offensive_stats = self._calculate_offensive_stats(matches, team_id)
        
        # Calcula estatísticas defensivas
        defensive_stats = self._calculate_defensive_stats(matches, team_id)
        
        # Calcula disciplina
        discipline_stats = self._calculate_discipline_stats(matches, team_id)
        
        # Calcula bolas paradas
        set_pieces_stats = self._calculate_set_pieces_stats(matches, team_id)
        
        # Identifica pontos fortes e fracos
        strengths, weaknesses = self._identify_strengths_weaknesses({
            "offensive": offensive_stats,
            "defensive": defensive_stats,
            "tactical": tactical_profile,
            "form": form_metrics
        })

        # Calcula stats específicas desta Copa
        copa_stats = self._calculate_copa_stats(copa_matches, team_id)

        # Calcula breakdown de qualidade por tipo de competição
        quality_breakdown = self._calculate_quality_breakdown(matches, team_id)

        # Monta perfil completo
        profile = {
            "team_id": team_id,
            "team_name": team_info["name"],
            "country": team_info["country"],
            "season": season,
            "matches_analyzed": len(matches),
            "data_source": "database" if len(matches) >= 10 else "database + api",

            "matches_raw": matches,           # últimos 10 jogos com competition_type
            "squad_info": squad_info,
            "injuries": injuries,
            "copa_stats": copa_stats,
            "quality_breakdown": quality_breakdown,
            "form": form_metrics,
            "offensive_stats": offensive_stats,
            "defensive_stats": defensive_stats,
            "discipline": discipline_stats,
            "set_pieces": set_pieces_stats,
            "tactical_profile": tactical_profile,
            "strengths": strengths,
            "weaknesses": weaknesses
        }

        # Só cacheia se não teve fixture_id (injuries mudam por jogo)
        if fixture_id is None:
            self.cache[cache_key] = profile
        
        return profile
    
    # ========================================================================
    # BUSCA DE DADOS
    # ========================================================================
    def _fetch_copa_matches(self, team_id: int, season: int) -> list:
        """Busca jogos finalizados desta Copa no banco.
        Usa ms.league_id diretamente — sem JOIN com fixtures, que só contém jogos NS/futuros.
        """
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    ms.home_team_id,
                    ms.away_team_id,
                    COALESCE(ms.home_goals, 0),
                    COALESCE(ms.away_goals, 0),
                    COALESCE(ms.home_corners, 0),
                    COALESCE(ms.away_corners, 0),
                    COALESCE(ms.home_yellow_cards, 0),
                    COALESCE(ms.away_yellow_cards, 0)
                FROM match_statistics ms
                WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
                  AND ms.league_id = 1
                  AND ms.season = %s
                  AND ms.status = 'FT'
                ORDER BY ms.match_date DESC
            """, (team_id, team_id, season))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [
                {
                    "home_team_id": r[0],
                    "away_team_id": r[1],
                    "home_goals": r[2],
                    "away_goals": r[3],
                    "home_corners": r[4],
                    "away_corners": r[5],
                    "home_yellow_cards": r[6],
                    "away_yellow_cards": r[7],
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[PROFILE] Erro ao buscar jogos Copa team {team_id}: {e}")
            return []

    def _calculate_copa_stats(self, copa_matches: list, team_id: int) -> dict:
        """Calcula estatísticas desta edição da Copa especificamente."""
        if not copa_matches:
            return {}

        gols_marcados = gols_sofridos = cantos = amarelos = 0
        wins = draws = losses = 0

        for m in copa_matches:
            is_home = m["home_team_id"] == team_id
            gf = m["home_goals"] if is_home else m["away_goals"]
            ga = m["away_goals"] if is_home else m["home_goals"]
            c  = m["home_corners"] if is_home else m["away_corners"]
            y  = m["home_yellow_cards"] if is_home else m["away_yellow_cards"]

            gols_marcados += gf
            gols_sofridos += ga
            cantos += c
            amarelos += y

            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1

        total = len(copa_matches)
        return {
            "jogos": total,
            "resultado": f"{wins}V-{draws}E-{losses}D",
            "gols_marcados": gols_marcados,
            "gols_sofridos": gols_sofridos,
            "media_gols_marcados": round(gols_marcados / total, 1),
            "media_gols_sofridos": round(gols_sofridos / total, 1),
            "media_cantos": round(cantos / total, 1),
            "media_amarelos": round(amarelos / total, 1),
        }

    def _get_team_info(self, team_id: int) -> dict:
        """Busca informações básicas do time"""
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT name, country
            FROM teams
            WHERE team_id = %s
            LIMIT 1
        """, (team_id,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row:
            return {"name": row[0], "country": row[1]}
        else:
            return {"name": f"Team {team_id}", "country": "Unknown"}
    
    def _fetch_recent_matches(self, team_id: int, limit: int = 10) -> list:
        """
        Busca últimos jogos da seleção.
        Prioridade: banco (match_statistics)
        Complemento: API se necessário
        """
        # Busca no banco
        db_matches = self._fetch_from_database(team_id, limit)

        print(f"[PROFILE] {len(db_matches)} jogos encontrados no banco")

        # Se tem jogos suficientes no banco, usa só eles
        if len(db_matches) >= limit:
            return db_matches[:limit]
        
        # Se tem menos, complementa com API
        needed = limit - len(db_matches)
        print(f"[PROFILE] Buscando {needed} jogos adicionais via API...")
        
        api_matches = self._fetch_from_api(team_id, needed)
        
        print(f"[PROFILE] {len(api_matches)} jogos obtidos da API")
        
        # Combina e remove duplicatas
        all_matches = db_matches + api_matches
        seen_ids = set()
        unique_matches = []
        
        for match in all_matches:
            fid = match.get("fixture_id")
            if fid and fid not in seen_ids:
                seen_ids.add(fid)
                unique_matches.append(match)
        
        return unique_matches[:limit]
    
    def _fetch_from_database(self, team_id: int, limit: int) -> list:
        """Busca jogos finalizados do banco, incluindo nome do adversário e league_id."""
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                ms.fixture_id,
                ms.match_date,
                ms.home_team_id,
                ms.away_team_id,
                ms.home_goals,
                ms.away_goals,
                ms.total_goals,
                ms.home_corners,
                ms.away_corners,
                ms.total_corners,
                ms.home_yellow_cards,
                ms.away_yellow_cards,
                ms.home_red_cards,
                ms.away_red_cards,
                ms.home_shots_on,
                ms.away_shots_on,
                ms.home_total_shots,
                ms.away_total_shots,
                ms.home_possession,
                ms.away_possession,
                ms.home_passes,
                ms.away_passes,
                ms.home_passes_accuracy,
                ms.away_passes_accuracy,
                ms.home_fouls,
                ms.away_fouls,
                ms.league_id,
                t_opp.name AS opponent_name
            FROM match_statistics ms
            LEFT JOIN (
                SELECT DISTINCT ON (team_id) team_id, name
                FROM teams
                ORDER BY team_id, created_at DESC
            ) t_opp
                ON t_opp.team_id = CASE
                    WHEN ms.home_team_id = %s THEN ms.away_team_id
                    ELSE ms.home_team_id
                END
            WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
              AND ms.status = 'FT'
            ORDER BY ms.match_date DESC
            LIMIT %s
        """, (team_id, team_id, team_id, limit))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        matches = []
        for r in rows:
            matches.append({
                "fixture_id": r[0],
                "match_date": r[1],
                "home_team_id": r[2],
                "away_team_id": r[3],
                "home_goals": r[4] or 0,
                "away_goals": r[5] or 0,
                "total_goals": r[6] or 0,
                "home_corners": r[7] or 0,
                "away_corners": r[8] or 0,
                "total_corners": r[9] or 0,
                "home_yellow_cards": r[10] or 0,
                "away_yellow_cards": r[11] or 0,
                "home_red_cards": r[12] or 0,
                "away_red_cards": r[13] or 0,
                "home_shots_on": r[14] or 0,
                "away_shots_on": r[15] or 0,
                "home_total_shots": r[16] or 0,
                "away_total_shots": r[17] or 0,
                "home_possession": r[18] or 0,
                "away_possession": r[19] or 0,
                "home_passes": r[20] or 0,
                "away_passes": r[21] or 0,
                "home_passes_accuracy": r[22] or 0,
                "away_passes_accuracy": r[23] or 0,
                "home_fouls": r[24] or 0,
                "away_fouls": r[25] or 0,
                "league_id": r[26],
                "opponent_name": r[27],
                "competition_type": self._classify_competition(r[26] or 0),
            })

        return matches
    
    def _classify_competition(self, league_id: int) -> str:
        """Classifica o tipo de competição pelo league_id."""
        if league_id == 1:
            return "Copa do Mundo"
        if league_id in (31, 32, 33, 34, 35, 36, 37, 38, 39, 882, 780):
            return "Eliminatórias"
        return "Amistoso/Outra"

    def _calculate_quality_breakdown(self, matches: list, team_id: int) -> dict:
        """
        Agrupa partidas por tipo de competição e calcula stats por grupo.
        Pesos: Copa do Mundo=3x | Eliminatórias=2x | Amistoso/Outra=0.5x
        """
        WEIGHTS = {
            "Copa do Mundo": 3.0,
            "Eliminatórias": 2.0,
            "Amistoso/Outra": 0.5,
        }

        groups = {comp: [] for comp in WEIGHTS}

        for m in matches:
            league_id = m.get("league_id")
            comp_type = self._classify_competition(league_id) if league_id is not None else "Amistoso/Outra"

            is_home = m.get("home_team_id") == team_id
            gf = m.get("home_goals", 0) if is_home else m.get("away_goals", 0)
            ga = m.get("away_goals", 0) if is_home else m.get("home_goals", 0)
            yellows = m.get("home_yellow_cards", 0) if is_home else m.get("away_yellow_cards", 0)
            clean_sheet = 1 if (ga or 0) == 0 else 0

            groups[comp_type].append({
                "gf": gf or 0,
                "ga": ga or 0,
                "yellows": yellows or 0,
                "clean_sheet": clean_sheet,
            })

        result = {}
        total_weight = 0.0
        weighted_ga  = 0.0

        for comp_type, entries in groups.items():
            n = len(entries)
            if n == 0:
                continue
            result[comp_type] = {
                "jogos":            n,
                "gols_marcados":    round(sum(e["gf"] for e in entries) / n, 2),
                "gols_sofridos":    round(sum(e["ga"] for e in entries) / n, 2),
                "clean_sheet_pct":  round(sum(e["clean_sheet"] for e in entries) / n * 100, 1),
                "amarelos":         round(sum(e["yellows"] for e in entries) / n, 2),
            }
            w = WEIGHTS[comp_type]
            avg_ga = sum(e["ga"] for e in entries) / n
            weighted_ga  += avg_ga * w * n
            total_weight += w * n

        if total_weight > 0:
            result["weighted_goals_against"] = round(weighted_ga / total_weight, 2)
        else:
            result["weighted_goals_against"] = None

        return result

    def _fetch_from_api(self, team_id: int, needed: int) -> list:
        """Busca jogos recentes via API"""
        try:
            return self.historical_api.get_recent_with_stats(team_id, n=needed)
        except Exception as e:
            print(f"[PROFILE] Erro ao buscar da API: {e}")
            return []
    
    # ========================================================================
    # ANÁLISE DE PADRÕES TÁTICOS
    # ========================================================================
    def _analyze_tactical_patterns(self, matches: list, team_id: int) -> dict:
        """Analisa padrões táticos baseado nos jogos"""
        if not matches:
            return self._default_tactical_profile()
        
        total_possession = 0
        total_shots = 0
        total_shots_on = 0
        total_passes = 0
        total_pass_accuracy = 0
        total_corners = 0
        total_fouls = 0
        count = 0
        
        for match in matches:
            is_home = match["home_team_id"] == team_id
            
            if is_home:
                total_possession += match.get("home_possession", 0)
                total_shots += match.get("home_total_shots", 0)
                total_shots_on += match.get("home_shots_on", 0)
                total_passes += match.get("home_passes", 0)
                total_pass_accuracy += match.get("home_passes_accuracy", 0)
                total_corners += match.get("home_corners", 0)
                total_fouls += match.get("home_fouls", 0)
            else:
                total_possession += match.get("away_possession", 0)
                total_shots += match.get("away_total_shots", 0)
                total_shots_on += match.get("away_shots_on", 0)
                total_passes += match.get("away_passes", 0)
                total_pass_accuracy += match.get("away_passes_accuracy", 0)
                total_corners += match.get("away_corners", 0)
                total_fouls += match.get("away_fouls", 0)
            
            count += 1
        
        if count == 0:
            return self._default_tactical_profile()
        
        avg_possession = total_possession / count
        avg_shots = total_shots / count
        avg_shots_on = total_shots_on / count
        avg_passes = total_passes / count
        avg_pass_accuracy = total_pass_accuracy / count
        avg_corners = total_corners / count
        avg_fouls = total_fouls / count
        
        # Determina estilo de jogo
        style = self._determine_playing_style(avg_possession, avg_shots, avg_passes)
        
        # Determina intensidade de pressão
        pressing = self._determine_pressing_intensity(avg_fouls, avg_possession)
        
        return {
            "style": style,
            "avg_possession": round(avg_possession, 1),
            "avg_shots": round(avg_shots, 1),
            "avg_shots_on_target": round(avg_shots_on, 1),
            "shot_accuracy_pct": round((avg_shots_on / avg_shots * 100) if avg_shots > 0 else 0, 1),
            "avg_passes": round(avg_passes, 0),
            "avg_pass_accuracy": round(avg_pass_accuracy, 1),
            "avg_corners": round(avg_corners, 1),
            "avg_fouls": round(avg_fouls, 1),
            "pressing_intensity": pressing
        }
    
    def _default_tactical_profile(self) -> dict:
        """Perfil tático padrão quando não há dados"""
        return {
            "style": "Dados insuficientes",
            "avg_possession": 0,
            "avg_shots": 0,
            "avg_shots_on_target": 0,
            "shot_accuracy_pct": 0,
            "avg_passes": 0,
            "avg_pass_accuracy": 0,
            "avg_corners": 0,
            "avg_fouls": 0,
            "pressing_intensity": "Desconhecida"
        }
    
    def _determine_playing_style(self, possession: float, shots: float, passes: float) -> str:
        """Determina estilo de jogo baseado em métricas"""
        if possession >= 55 and passes >= 450:
            return "Posse de bola dominante"
        elif possession >= 55:
            return "Posse de bola + Contra-ataque"
        elif shots >= 14:
            return "Ataque direto e intenso"
        elif possession <= 45:
            return "Contra-ataque rápido"
        else:
            return "Jogo equilibrado"
    
    def _determine_pressing_intensity(self, fouls: float, possession: float) -> str:
        """Determina intensidade de pressão"""
        if fouls >= 13 and possession >= 52:
            return "Alta"
        elif fouls >= 11:
            return "Média-Alta"
        elif fouls >= 9:
            return "Média"
        else:
            return "Baixa"
    
    # ========================================================================
    # CÁLCULO DE MÉTRICAS
    # ========================================================================
    def _calculate_form_metrics(self, matches: list, team_id: int) -> dict:
        """Calcula métricas de forma recente"""
        if not matches:
            return self._default_form_metrics()
        
        results = []
        wins = 0
        draws = 0
        losses = 0
        
        for match in matches:
            is_home = match["home_team_id"] == team_id
            home_goals = match.get("home_goals", 0)
            away_goals = match.get("away_goals", 0)
            
            if is_home:
                if home_goals > away_goals:
                    results.append("W")
                    wins += 1
                elif home_goals == away_goals:
                    results.append("D")
                    draws += 1
                else:
                    results.append("L")
                    losses += 1
            else:
                if away_goals > home_goals:
                    results.append("W")
                    wins += 1
                elif away_goals == home_goals:
                    results.append("D")
                    draws += 1
                else:
                    results.append("L")
                    losses += 1
        
        total = len(results)
        sequence = "-".join(results)
        last_5 = "-".join(results[:5]) if len(results) >= 5 else "-".join(results)
        
        return {
            "sequence": sequence,
            "last_5": last_5,
            "games_played": total,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "win_rate": round(wins / total, 2) if total > 0 else 0,
            "draw_rate": round(draws / total, 2) if total > 0 else 0,
            "loss_rate": round(losses / total, 2) if total > 0 else 0
        }
    
    def _default_form_metrics(self) -> dict:
        """Métricas de forma padrão"""
        return {
            "sequence": "",
            "last_5": "",
            "games_played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "win_rate": 0,
            "draw_rate": 0,
            "loss_rate": 0
        }
    
    def _calculate_offensive_stats(self, matches: list, team_id: int) -> dict:
        """Calcula estatísticas ofensivas"""
        if not matches:
            return {}
        
        total_goals = 0
        total_shots = 0
        total_shots_on = 0
        count = len(matches)
        
        for match in matches:
            is_home = match["home_team_id"] == team_id
            
            if is_home:
                total_goals += match.get("home_goals", 0)
                total_shots += match.get("home_total_shots", 0)
                total_shots_on += match.get("home_shots_on", 0)
            else:
                total_goals += match.get("away_goals", 0)
                total_shots += match.get("away_total_shots", 0)
                total_shots_on += match.get("away_shots_on", 0)
        
        return {
            "goals_per_game": round(total_goals / count, 2) if count > 0 else 0,
            "shots_per_game": round(total_shots / count, 1) if count > 0 else 0,
            "shots_on_target_per_game": round(total_shots_on / count, 1) if count > 0 else 0,
            "shot_conversion_pct": round((total_goals / total_shots * 100) if total_shots > 0 else 0, 1)
        }
    
    def _calculate_defensive_stats(self, matches: list, team_id: int) -> dict:
        """Calcula estatísticas defensivas"""
        if not matches:
            return {}
        
        total_goals_against = 0
        clean_sheets = 0
        count = len(matches)
        
        for match in matches:
            is_home = match["home_team_id"] == team_id
            
            if is_home:
                goals_against = match.get("away_goals", 0)
            else:
                goals_against = match.get("home_goals", 0)
            
            total_goals_against += goals_against
            if goals_against == 0:
                clean_sheets += 1
        
        return {
            "goals_against_per_game": round(total_goals_against / count, 2) if count > 0 else 0,
            "clean_sheets": clean_sheets,
            "clean_sheets_pct": round(clean_sheets / count, 2) if count > 0 else 0
        }
    
    def _calculate_discipline_stats(self, matches: list, team_id: int) -> dict:
        """Calcula estatísticas de disciplina"""
        if not matches:
            return {}
        
        total_fouls = 0
        total_yellow = 0
        total_red = 0
        count = len(matches)
        
        for match in matches:
            is_home = match["home_team_id"] == team_id
            
            if is_home:
                total_fouls += match.get("home_fouls", 0)
                total_yellow += match.get("home_yellow_cards", 0)
                total_red += match.get("home_red_cards", 0)
            else:
                total_fouls += match.get("away_fouls", 0)
                total_yellow += match.get("away_yellow_cards", 0)
                total_red += match.get("away_red_cards", 0)
        
        return {
            "fouls_per_game": round(total_fouls / count, 1) if count > 0 else 0,
            "yellow_cards_per_game": round(total_yellow / count, 1) if count > 0 else 0,
            "red_cards_per_game": round(total_red / count, 2) if count > 0 else 0
        }
    
    def _calculate_set_pieces_stats(self, matches: list, team_id: int) -> dict:
        """Calcula estatísticas de bolas paradas"""
        if not matches:
            return {}
        
        total_corners = 0
        count = len(matches)
        
        for match in matches:
            is_home = match["home_team_id"] == team_id
            
            if is_home:
                total_corners += match.get("home_corners", 0)
            else:
                total_corners += match.get("away_corners", 0)
        
        return {
            "corners_per_game": round(total_corners / count, 1) if count > 0 else 0
        }
    
    # ========================================================================
    # IDENTIFICAÇÃO DE PONTOS FORTES E FRACOS
    # ========================================================================
    def _identify_strengths_weaknesses(self, stats: dict) -> tuple:
        """Identifica pontos fortes e fracos baseado nas estatísticas"""
        strengths = []
        weaknesses = []
        
        offensive = stats.get("offensive", {})
        defensive = stats.get("defensive", {})
        tactical = stats.get("tactical", {})
        form = stats.get("form", {})
        
        # Análise ofensiva
        goals_pg = offensive.get("goals_per_game", 0)
        if goals_pg >= 2.0:
            strengths.append(f"Ataque eficiente ({goals_pg} gols/jogo)")
        elif goals_pg < 1.0:
            weaknesses.append(f"Dificuldade para marcar gols ({goals_pg} gols/jogo)")
        
        # Análise defensiva
        goals_against = defensive.get("goals_against_per_game", 0)
        clean_sheets_pct = defensive.get("clean_sheets_pct", 0)
        
        if clean_sheets_pct >= 0.40:
            strengths.append(f"Defesa sólida ({int(clean_sheets_pct * 100)}% clean sheets)")
        elif goals_against >= 1.5:
            weaknesses.append(f"Defesa vulnerável ({goals_against} gols sofridos/jogo)")
        
        # Análise tática
        possession = tactical.get("avg_possession", 0)
        if possession >= 55:
            strengths.append(f"Domínio de posse de bola ({possession}%)")
        elif possession <= 45:
            weaknesses.append(f"Baixa posse de bola ({possession}%)")
        
        shot_accuracy = tactical.get("shot_accuracy_pct", 0)
        if shot_accuracy >= 40:
            strengths.append(f"Alta precisão nos chutes ({shot_accuracy}%)")
        
        # Análise de forma
        win_rate = form.get("win_rate", 0)
        if win_rate >= 0.65:
            strengths.append(f"Excelente forma recente ({int(win_rate * 100)}% vitórias)")
        elif win_rate <= 0.35:
            weaknesses.append(f"Forma irregular ({int(win_rate * 100)}% vitórias)")
        
        # Garante pelo menos 2 de cada
        if len(strengths) < 2:
            strengths.append("Análise baseada em dados limitados")
        if len(weaknesses) < 2:
            weaknesses.append("Análise baseada em dados limitados")
        
        return strengths[:4], weaknesses[:3]

# Made with Bob
