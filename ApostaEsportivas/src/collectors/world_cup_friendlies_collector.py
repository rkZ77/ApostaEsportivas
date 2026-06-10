"""
Collector de Amistosos e Jogos Recentes de Seleções da Copa do Mundo

Busca últimos 15 jogos de cada seleção participante da Copa do Mundo via API Football.
Salva no banco (match_statistics) para análise posterior.
"""

import os
import requests
from datetime import datetime
from utils.db_utils import get_connection


API_KEY = os.getenv("API_FOOTBALL_KEY")
HEADERS = {"x-apisports-key": API_KEY}
FIXTURES_URL = "https://v3.football.api-sports.io/fixtures"
STATS_URL = "https://v3.football.api-sports.io/fixtures/statistics"

# Status de jogos finalizados
FINISHED_STATUS = ["FT", "AET", "PEN"]


class WorldCupFriendliesCollector:
    """
    Coleta jogos recentes (amistosos, qualificatórias, etc.) de seleções da Copa do Mundo.
    """
    
    def __init__(self):
        self.conn = None
        self.cur = None
    
    def _connect(self):
        """Conecta ao banco"""
        if not self.conn:
            self.conn = get_connection()
            self.cur = self.conn.cursor()
    
    def _close(self):
        """Fecha conexão"""
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
    
    # ========================================================================
    # BUSCA SELEÇÕES DA COPA DO MUNDO
    # ========================================================================
    def get_world_cup_teams(self, season: int = 2026) -> list:
        """Retorna team_ids dos times cadastrados na tabela teams com league_id = 1 (Copa do Mundo)."""
        self._connect()

        self.cur.execute("""
            SELECT team_id FROM teams WHERE league_id = 1 AND season = %s
        """, (season,))

        teams = [row[0] for row in self.cur.fetchall()]

        print(f"[WC_FRIENDLIES] {len(teams)} seleções encontradas na tabela teams para Copa {season}")
        return teams
    
    # ========================================================================
    # BUSCA JOGOS RECENTES VIA API
    # ========================================================================
    def fetch_recent_matches(self, team_id: int, limit: int = 15) -> list:
        """
        Busca últimos N jogos finalizados de uma seleção via API.
        Inclui: amistosos, qualificatórias, competições internacionais.
        """
        try:
            response = requests.get(
                FIXTURES_URL,
                headers=HEADERS,
                params={"team": team_id, "last": limit},
                timeout=15
            )
            response.raise_for_status()
            data = response.json().get("response", [])
            
            matches = []
            for item in data:
                fixture = item["fixture"]
                status = fixture["status"]["short"]
                
                # Só jogos finalizados
                if status not in FINISHED_STATUS:
                    continue
                
                league = item["league"]
                teams = item["teams"]
                goals = item["goals"]
                
                matches.append({
                    "fixture_id": fixture["id"],
                    "league_id": league["id"],
                    "league_name": league["name"],
                    "season": league["season"],
                    "match_date": fixture["date"],
                    "home_team_id": teams["home"]["id"],
                    "away_team_id": teams["away"]["id"],
                    "home_goals": goals["home"] or 0,
                    "away_goals": goals["away"] or 0,
                    "status": status,
                    "referee": fixture.get("referee")
                })
            
            return matches
            
        except Exception as e:
            print(f"[WC_FRIENDLIES] Erro ao buscar jogos do time {team_id}: {e}")
            return []
    
    # ========================================================================
    # BUSCA ESTATÍSTICAS DE UM JOGO
    # ========================================================================
    def fetch_match_statistics(self, fixture_id: int) -> dict:
        """Busca estatísticas detalhadas de um jogo"""
        try:
            response = requests.get(
                STATS_URL,
                headers=HEADERS,
                params={"fixture": fixture_id},
                timeout=15
            )
            response.raise_for_status()
            stats_list = response.json().get("response", [])
            
            if len(stats_list) < 2:
                return None
            
            # Extrai stats de ambos os times
            home_stats = stats_list[0]["statistics"]
            away_stats = stats_list[1]["statistics"]
            
            def get_stat(stats, name):
                for s in stats:
                    if s["type"] == name:
                        v = s["value"]
                        if v is None:
                            return 0
                        if isinstance(v, str):
                            try:
                                return float(v.replace("%", ""))
                            except Exception:
                                return 0
                        return v
                return 0
            
            return {
                "home_corners": get_stat(home_stats, "Corner Kicks"),
                "away_corners": get_stat(away_stats, "Corner Kicks"),
                "home_yellow": get_stat(home_stats, "Yellow Cards"),
                "away_yellow": get_stat(away_stats, "Yellow Cards"),
                "home_red": get_stat(home_stats, "Red Cards"),
                "away_red": get_stat(away_stats, "Red Cards"),
                "home_shots_on": get_stat(home_stats, "Shots on Goal"),
                "away_shots_on": get_stat(away_stats, "Shots on Goal"),
                "home_shots_off": get_stat(home_stats, "Shots off Goal"),
                "away_shots_off": get_stat(away_stats, "Shots off Goal"),
                "home_total_shots": get_stat(home_stats, "Total Shots"),
                "away_total_shots": get_stat(away_stats, "Total Shots"),
                "home_blocked_shots": get_stat(home_stats, "Blocked Shots"),
                "away_blocked_shots": get_stat(away_stats, "Blocked Shots"),
                "home_goalkeeper_saves": get_stat(home_stats, "Goalkeeper Saves"),
                "away_goalkeeper_saves": get_stat(away_stats, "Goalkeeper Saves"),
                "home_fouls": get_stat(home_stats, "Fouls"),
                "away_fouls": get_stat(away_stats, "Fouls"),
                "home_offsides": get_stat(home_stats, "Offsides"),
                "away_offsides": get_stat(away_stats, "Offsides"),
                "home_possession": get_stat(home_stats, "Ball Possession"),
                "away_possession": get_stat(away_stats, "Ball Possession"),
                "home_passes": get_stat(home_stats, "Total passes"),
                "away_passes": get_stat(away_stats, "Total passes"),
                "home_passes_accuracy": get_stat(home_stats, "Passes accurate"),
                "away_passes_accuracy": get_stat(away_stats, "Passes accurate"),
            }
            
        except Exception as e:
            print(f"[WC_FRIENDLIES] Erro ao buscar stats do fixture {fixture_id}: {e}")
            return None
    
    # ========================================================================
    # SALVA NO BANCO
    # ========================================================================
    def save_match_to_db(self, match: dict, stats: dict = None):
        """Salva jogo no banco (match_statistics)"""
        self._connect()
        
        # Verifica se já existe
        self.cur.execute(
            "SELECT fixture_id FROM match_statistics WHERE fixture_id = %s",
            (match["fixture_id"],)
        )
        
        if self.cur.fetchone():
            # Já existe, pula
            return False
        
        # Prepara dados
        total_goals = match["home_goals"] + match["away_goals"]
        
        if stats:
            total_corners = stats["home_corners"] + stats["away_corners"]
            total_yellow = stats["home_yellow"] + stats["away_yellow"]
            total_red = stats["home_red"] + stats["away_red"]
        else:
            total_corners = 0
            total_yellow = 0
            total_red = 0
            stats = {}
        
        # Insere
        self.cur.execute("""
            INSERT INTO match_statistics (
                fixture_id, league_id, season,
                home_team_id, away_team_id,
                home_goals, away_goals, total_goals,
                home_corners, away_corners, total_corners,
                home_yellow_cards, away_yellow_cards, total_yellow_cards,
                home_red_cards, away_red_cards, total_red_cards,
                status, match_date,
                home_shots_on, away_shots_on,
                home_shots_off, away_shots_off,
                home_total_shots, away_total_shots,
                home_blocked_shots, away_blocked_shots,
                home_goalkeeper_saves, away_goalkeeper_saves,
                home_fouls, away_fouls,
                home_offsides, away_offsides,
                home_possession, away_possession,
                home_passes, away_passes,
                home_passes_accuracy, away_passes_accuracy,
                referee,
                last_updated
            )
            VALUES (
                %s,%s,%s,
                %s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,
                NOW()
            )
        """, (
            match["fixture_id"], match["league_id"], match["season"],
            match["home_team_id"], match["away_team_id"],
            match["home_goals"], match["away_goals"], total_goals,
            stats.get("home_corners", 0), stats.get("away_corners", 0), total_corners,
            stats.get("home_yellow", 0), stats.get("away_yellow", 0), total_yellow,
            stats.get("home_red", 0), stats.get("away_red", 0), total_red,
            match["status"], match["match_date"],
            stats.get("home_shots_on", 0), stats.get("away_shots_on", 0),
            stats.get("home_shots_off", 0), stats.get("away_shots_off", 0),
            stats.get("home_total_shots", 0), stats.get("away_total_shots", 0),
            stats.get("home_blocked_shots", 0), stats.get("away_blocked_shots", 0),
            stats.get("home_goalkeeper_saves", 0), stats.get("away_goalkeeper_saves", 0),
            stats.get("home_fouls", 0), stats.get("away_fouls", 0),
            stats.get("home_offsides", 0), stats.get("away_offsides", 0),
            stats.get("home_possession", 0), stats.get("away_possession", 0),
            stats.get("home_passes", 0), stats.get("away_passes", 0),
            stats.get("home_passes_accuracy", 0), stats.get("away_passes_accuracy", 0),
            match.get("referee")
        ))
        
        self.conn.commit()
        return True
    
    # ========================================================================
    # PROCESSO PRINCIPAL
    # ========================================================================
    def collect_world_cup_friendlies(self, season: int = 2026, limit: int = 15):
        """
        Processo principal:
        1. Busca seleções da Copa do Mundo
        2. Para cada seleção, busca últimos N jogos
        3. Busca estatísticas de cada jogo
        4. Salva no banco
        5. Atualiza team_statistics
        """
        print(f"\n{'='*70}")
        print(f"🏆 COLETANDO AMISTOSOS E JOGOS RECENTES - COPA DO MUNDO {season}")
        print(f"{'='*70}\n")
        
        # Busca seleções
        teams = self.get_world_cup_teams(season)
        
        if not teams:
            print("[WC_FRIENDLIES] Nenhuma seleção encontrada. Execute atualizar_jogos primeiro.")
            return
        
        total_saved = 0
        total_teams = len(teams)
        
        for idx, team_id in enumerate(teams, 1):
            print(f"\n[{idx}/{total_teams}] Processando seleção ID {team_id}...")
            
            # Busca jogos recentes
            matches = self.fetch_recent_matches(team_id, limit)
            
            if not matches:
                print(f"  ⚠️ Nenhum jogo encontrado")
                continue
            
            print(f"  ✓ {len(matches)} jogos encontrados")
            
            saved_count = 0
            
            for match in matches:
                fixture_id = match["fixture_id"]
                
                # Busca estatísticas
                stats = self.fetch_match_statistics(fixture_id)
                
                # Salva no banco
                if self.save_match_to_db(match, stats):
                    saved_count += 1
            
            if saved_count > 0:
                print(f"  ✅ {saved_count} novos jogos salvos")
                total_saved += saved_count
            else:
                print(f"  ℹ️ Todos os jogos já estavam no banco")
        
        print(f"\n{'='*70}")
        print(f"✅ COLETA FINALIZADA")
        print(f"   Total de jogos novos salvos: {total_saved}")
        print(f"   Seleções processadas: {total_teams}")
        print(f"{'='*70}\n")
        
        self._close()
        
        # Retorna lista de seleções para Stage 5 atualizar
        return teams


# ============================================================================
# EXECUÇÃO STANDALONE
# ============================================================================
if __name__ == "__main__":
    collector = WorldCupFriendliesCollector()
    collector.collect_world_cup_friendlies(season=2026, limit=15)

# Made with Bob
