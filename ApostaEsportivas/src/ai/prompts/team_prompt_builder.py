"""
Construtor de Prompts Personalizados por Seleção

Recebe perfis de duas seleções e gera contexto rico para injetar no prompt base.
Inclui análise tática, métricas, pontos fortes/fracos e confrontos diretos.
"""

from utils.db_utils import get_connection


class TeamPromptBuilder:
    
    def __init__(self):
        pass
    
    # ========================================================================
    # MÉTODO PRINCIPAL - Constrói prompt completo
    # ========================================================================
    def build_world_cup_prompt(
        self,
        home_profile: dict,
        away_profile: dict,
        base_prompt: str
    ) -> str:
        """
        Constrói prompt personalizado para Copa do Mundo.
        
        Injeta contexto das seleções no prompt base antes da seção "DADOS DO JOGO".
        """
        # Formata seção das seleções
        teams_section = self._format_teams_section(home_profile, away_profile)
        
        # Formata confrontos diretos
        h2h_section = self._format_head_to_head(
            home_profile["team_id"],
            away_profile["team_id"],
            home_profile["team_name"],
            away_profile["team_name"]
        )
        
        # Injeta no prompt base antes de "DADOS DO JOGO"
        if "DADOS DO JOGO" in base_prompt:
            return base_prompt.replace(
                "DADOS DO JOGO",
                f"{teams_section}\n\n{h2h_section}\n\n{'='*68}\nDADOS DO JOGO"
            )
        else:
            # Fallback: adiciona no final antes das regras
            return base_prompt.replace(
                "─────────────────────────────────────────────────",
                f"{teams_section}\n\n{h2h_section}\n\n{'─'*68}\n"
            )
    
    # ========================================================================
    # FORMATAÇÃO DE SEÇÕES
    # ========================================================================
    def get_world_cup_context(self, home_profile: dict, away_profile: dict) -> str:
        """
        Retorna o bloco completo de contexto Copa (perfis + H2H) pronto para injeção
        em qualquer pipeline que receba jogos da Copa do Mundo.
        """
        teams_section = self._format_teams_section(home_profile, away_profile)
        h2h_section = self._format_head_to_head(
            home_profile["team_id"],
            away_profile["team_id"],
            home_profile["team_name"],
            away_profile["team_name"],
        )
        return f"{teams_section}\n\n{h2h_section}"

    def get_compact_wc_context(self, home_profile: dict, away_profile: dict) -> str:
        """
        Versão compacta (~50% menos tokens) para pipelines que não precisam
        de detalhes táticos (alavancagem, dica_do_dia).
        Mantém forma, gols, disciplina, cantos e Copa stats.
        """
        home_text = self._format_compact_team(home_profile)
        away_text = self._format_compact_team(away_profile)
        h2h_section = self._format_compact_h2h(
            home_profile["team_id"],
            away_profile["team_id"],
            home_profile["team_name"],
            away_profile["team_name"],
        )
        return (
            f"PERFIS Copa do Mundo\n"
            f"{'─'*60}\n"
            f"{home_text}\n"
            f"{'─'*60}\n"
            f"{away_text}\n"
            f"{'─'*60}\n"
            f"{h2h_section}"
        )

    def _format_compact_team(self, profile: dict) -> str:
        name = profile["team_name"].upper()
        matches = profile["matches_analyzed"]

        form = profile.get("form", {})
        sequence = form.get("sequence", "N/A")
        win_rate = int(form.get("win_rate", 0) * 100)
        draw_rate = int(form.get("draw_rate", 0) * 100)
        loss_rate = int(form.get("loss_rate", 0) * 100)

        off = profile.get("offensive_stats", {})
        goals_pg = off.get("goals_per_game", 0)

        defs = profile.get("defensive_stats", {})
        goals_ag = defs.get("goals_against_per_game", 0)
        cs_pct = int(defs.get("clean_sheets_pct", 0) * 100)

        disc = profile.get("discipline", {})
        yellows_pg = disc.get("yellow_cards_per_game", 0)

        sp = profile.get("set_pieces", {})
        corners_pg = sp.get("corners_per_game", 0)

        copa_stats = profile.get("copa_stats") or {}
        if copa_stats:
            copa_line = (
                f"Copa: {copa_stats['jogos']}j "
                f"{copa_stats['gols_marcados']}-{copa_stats['gols_sofridos']} gols "
                f"| Cantos:{copa_stats['media_cantos']}/j "
                f"| Amarelos:{copa_stats['media_amarelos']}/j"
            )
        else:
            copa_line = "Copa: sem jogos nesta edição ainda"

        quality = profile.get("quality_breakdown") or {}
        weighted_ga = quality.get("weighted_goals_against", "N/A")

        return (
            f"{name} ({matches}j analisados)\n"
            f"  Forma: {sequence} V{win_rate}%/E{draw_rate}%/D{loss_rate}%\n"
            f"  Ataque:{goals_pg}gols/j | Defesa:{goals_ag}sofridos/j CS{cs_pct}%\n"
            f"  Def.ponderada(Copa/Elim/Amist):{weighted_ga}gols sofridos/j\n"
            f"  Disciplina:{yellows_pg}amarelos/j | Cantos:{corners_pg}/j\n"
            f"  {copa_line}"
        )

    def _format_compact_h2h(
        self,
        team1_id: int,
        team2_id: int,
        team1_name: str,
        team2_name: str,
    ) -> str:
        matches = self._fetch_head_to_head(team1_id, team2_id)
        if not matches:
            return f"H2H: sem histórico recente entre {team1_name} e {team2_name}"

        total = len(matches)
        total_goals = sum(m["home_goals"] + m["away_goals"] for m in matches)
        btts = sum(1 for m in matches if m["home_goals"] > 0 and m["away_goals"] > 0)
        avg_goals = round(total_goals / total, 1)
        btts_pct = int(btts / total * 100)

        games = []
        for m in matches:
            dt = m["match_date"].strftime("%Y-%m-%d") if m["match_date"] else "N/A"
            if m["home_team_id"] == team1_id:
                games.append(f"{dt}: {team1_name} {m['home_goals']}-{m['away_goals']} {team2_name}")
            else:
                games.append(f"{dt}: {team2_name} {m['home_goals']}-{m['away_goals']} {team1_name}")

        return (
            f"H2H últimos {total}j: média {avg_goals}gols/j BTTS{btts_pct}%\n"
            + "\n".join(f"  {g}" for g in games)
        )

    # ========================================================================
    def _format_teams_section(self, home: dict, away: dict) -> str:
        """Formata seção completa com análise das duas seleções"""
        
        home_flag = self._get_country_flag(home["country"])
        away_flag = self._get_country_flag(away["country"])
        
        home_text = self._format_single_team(home, home_flag)
        away_text = self._format_single_team(away, away_flag)
        
        return f"""{'='*68}
ANÁLISE DETALHADA DAS SELEÇÕES
{'='*68}

{home_text}

{'─'*68}

{away_text}"""
    
    def _format_single_team(self, profile: dict, flag: str) -> str:
        """Formata análise de uma seleção"""

        name = profile["team_name"].upper()
        matches = profile["matches_analyzed"]

        # Convocados / escalação
        squad_info = profile.get("squad_info") or {}
        coach = squad_info.get("coach") or "N/D"
        formation = squad_info.get("formation") or "N/D"

        # Forma
        form = profile.get("form", {})
        sequence = form.get("sequence", "N/A")
        last_5 = form.get("last_5", "N/A")
        win_rate = int(form.get("win_rate", 0) * 100)
        draw_rate = int(form.get("draw_rate", 0) * 100)
        loss_rate = int(form.get("loss_rate", 0) * 100)
        
        # Ofensivo
        offensive = profile.get("offensive_stats", {})
        goals_pg = offensive.get("goals_per_game", 0)
        shots_pg = offensive.get("shots_per_game", 0)
        shots_on_pg = offensive.get("shots_on_target_per_game", 0)
        conversion = offensive.get("shot_conversion_pct", 0)
        
        # Defensivo
        defensive = profile.get("defensive_stats", {})
        goals_against = defensive.get("goals_against_per_game", 0)
        clean_sheets = int(defensive.get("clean_sheets_pct", 0) * 100)
        
        # Disciplina
        discipline = profile.get("discipline", {})
        fouls_pg = discipline.get("fouls_per_game", 0)
        yellows_pg = discipline.get("yellow_cards_per_game", 0)
        reds_pg = discipline.get("red_cards_per_game", 0)
        
        # Bolas paradas
        set_pieces = profile.get("set_pieces", {})
        corners_pg = set_pieces.get("corners_per_game", 0)
        
        # Tático
        tactical = profile.get("tactical_profile", {})
        style = tactical.get("style", "N/A")
        possession = tactical.get("avg_possession", 0)
        passes = tactical.get("avg_passes", 0)
        pass_accuracy = tactical.get("avg_pass_accuracy", 0)
        pressing = tactical.get("pressing_intensity", "N/A")
        
        # Lesionados / suspensos
        injuries = profile.get("injuries") or []
        injured_list  = [i["name"] for i in injuries if "injur" in i.get("type", "").lower()]
        suspended_list = [i["name"] for i in injuries if "suspen" in i.get("type", "").lower()]
        injuries_text = ""
        if injured_list or suspended_list:
            parts = []
            if injured_list:
                parts.append(f"Lesionados: {', '.join(injured_list)}")
            if suspended_list:
                parts.append(f"Suspensos: {', '.join(suspended_list)}")
            injuries_text = "\n".join(parts)
        else:
            injuries_text = "Nenhum reportado"

        # Copa desta edição
        copa_stats = profile.get("copa_stats") or {}
        if copa_stats:
            copa_text = (
                f"Jogos: {copa_stats['jogos']} | Resultado: {copa_stats['resultado']}\n"
                f"  Gols: {copa_stats['gols_marcados']} marcados / {copa_stats['gols_sofridos']} sofridos"
                f" ({copa_stats['media_gols_marcados']}/jogo)"
                f" | Escanteios: {copa_stats['media_cantos']}/jogo"
                f" | Amarelos: {copa_stats['media_amarelos']}/jogo"
            )
        else:
            copa_text = "Sem jogos desta Copa no banco ainda"

        # Pontos fortes e fracos
        strengths = profile.get("strengths", [])
        weaknesses = profile.get("weaknesses", [])

        # Qualidade dos adversários
        quality = profile.get("quality_breakdown") or {}
        if quality:
            q_lines = []
            for comp_type in ["Copa do Mundo", "Eliminatórias", "Amistoso/Outra"]:
                if comp_type in quality:
                    q = quality[comp_type]
                    q_lines.append(
                        f"  {comp_type}: {q['jogos']}j | "
                        f"Marcados:{q['gols_marcados']}/j "
                        f"Sofridos:{q['gols_sofridos']}/j "
                        f"CS:{q['clean_sheet_pct']}% "
                        f"Amarelos:{q['amarelos']}/j"
                    )
            weighted_ga = quality.get("weighted_goals_against")
            if weighted_ga is not None:
                q_lines.append(
                    f"  → Média defensiva PONDERADA (Copa>Elim>Amistoso): "
                    f"{weighted_ga} gols sofridos/j"
                )
            quality_text = "\n".join(q_lines)
        else:
            quality_text = "  Dados insuficientes para breakdown por competição"

        return f"""{flag} {name}
{'─'*68}
TÉCNICO: {coach} | FORMAÇÃO: {formation}
LESIONADOS/SUSPENSOS: {injuries_text}

DESEMPENHO NESTA COPA:
  {copa_text}

FORMA RECENTE ({matches} jogos): {sequence} | V{win_rate}% E{draw_rate}% D{loss_rate}% | Últimos 5: {last_5}

ATAQUE: Gols/j={goals_pg} Chutes/j={shots_pg}({shots_on_pg} alvo) Conv={conversion}%
DEFESA: Sofridos/j={goals_against} CS={clean_sheets}%
QUALIDADE DOS ADVERSÁRIOS:
{quality_text}
DISCIPLINA: Faltas/j={fouls_pg} Amarelos/j={yellows_pg} Vermelhos/j={reds_pg}
BOLAS PARADAS: Escanteios/j={corners_pg}
TÁTICO: {style} | Posse={possession}% Passes/j={int(passes)}({pass_accuracy}%) Pressing={pressing}

FORÇAS: {" | ".join([f"+ {s}" for s in strengths])}
FRAQUEZAS: {" | ".join([f"- {w}" for w in weaknesses])}"""
    
    def _format_head_to_head(
        self,
        team1_id: int,
        team2_id: int,
        team1_name: str,
        team2_name: str
    ) -> str:
        """Formata análise de confrontos diretos"""
        
        matches = self._fetch_head_to_head(team1_id, team2_id)
        
        if not matches or len(matches) == 0:
            return f"""{'─'*68}
CONFRONTOS DIRETOS RECENTES:
  Sem histórico recente de confrontos entre {team1_name} e {team2_name}"""
        
        # Formata lista de jogos
        games_text = []
        team1_wins = 0
        team2_wins = 0
        draws = 0
        total_goals = 0
        btts_count = 0
        total_yellows = 0
        
        for match in matches:
            date = match["match_date"].strftime("%Y-%m-%d") if match["match_date"] else "N/A"
            home_id = match["home_team_id"]
            home_goals = match["home_goals"]
            away_goals = match["away_goals"]
            
            # Determina quem é quem
            if home_id == team1_id:
                score = f"{team1_name} {home_goals}-{away_goals} {team2_name}"
                if home_goals > away_goals:
                    team1_wins += 1
                elif away_goals > home_goals:
                    team2_wins += 1
                else:
                    draws += 1
            else:
                score = f"{team2_name} {home_goals}-{away_goals} {team1_name}"
                if home_goals > away_goals:
                    team2_wins += 1
                elif away_goals > home_goals:
                    team1_wins += 1
                else:
                    draws += 1
            
            games_text.append(f"  {date}: {score}")
            
            total_goals += home_goals + away_goals
            if home_goals > 0 and away_goals > 0:
                btts_count += 1
            total_yellows += match.get("home_yellow_cards", 0) + match.get("away_yellow_cards", 0)
        
        games_list = "\n".join(games_text)
        
        # Estatísticas do confronto
        total = len(matches)
        avg_goals = round(total_goals / total, 1) if total > 0 else 0
        btts_pct = int(btts_count / total * 100) if total > 0 else 0
        avg_yellows = round(total_yellows / total, 1) if total > 0 else 0
        
        return f"""{'─'*68}
CONFRONTOS DIRETOS RECENTES (últimos {total} jogos):
{games_list}

ESTATÍSTICAS DO CONFRONTO:
  {team1_name}: {team1_wins} vitória(s) | Empates: {draws} | {team2_name}: {team2_wins} vitória(s)
  Média de gols: {avg_goals}/jogo
  BTTS (ambas marcam): {btts_pct}% dos jogos
  Cartões amarelos: {avg_yellows}/jogo (média)
  Padrão: {"Jogos equilibrados e táticos" if avg_goals < 2.5 else "Jogos abertos com gols"}"""
    
    def _fetch_head_to_head(self, team1_id: int, team2_id: int, limit: int = 5) -> list:
        """Busca confrontos diretos no banco"""
        try:
            conn = get_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT
                    match_date,
                    home_team_id,
                    away_team_id,
                    home_goals,
                    away_goals,
                    home_yellow_cards,
                    away_yellow_cards
                FROM match_statistics
                WHERE ((home_team_id = %s AND away_team_id = %s)
                   OR (home_team_id = %s AND away_team_id = %s))
                  AND status = 'FT'
                ORDER BY match_date DESC
                LIMIT %s
            """, (team1_id, team2_id, team2_id, team1_id, limit))
            
            rows = cur.fetchall()
            cur.close()
            conn.close()
            
            matches = []
            for r in rows:
                matches.append({
                    "match_date": r[0],
                    "home_team_id": r[1],
                    "away_team_id": r[2],
                    "home_goals": r[3] or 0,
                    "away_goals": r[4] or 0,
                    "home_yellow_cards": r[5] or 0,
                    "away_yellow_cards": r[6] or 0
                })
            
            return matches
        except Exception as e:
            print(f"[PROMPT_BUILDER] Erro ao buscar confrontos diretos: {e}")
            return []
    
    # ========================================================================
    # UTILITÁRIOS
    # ========================================================================
    def _get_country_flag(self, country: str) -> str:
        """Retorna emoji da bandeira do país"""
        flags = {
            "Brazil": "🇧🇷",
            "Argentina": "🇦🇷",
            "France": "🇫🇷",
            "Germany": "🇩🇪",
            "Spain": "🇪🇸",
            "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
            "Portugal": "🇵🇹",
            "Netherlands": "🇳🇱",
            "Belgium": "🇧🇪",
            "Italy": "🇮🇹",
            "Uruguay": "🇺🇾",
            "Croatia": "🇭🇷",
            "Denmark": "🇩🇰",
            "Switzerland": "🇨🇭",
            "Mexico": "🇲🇽",
            "USA": "🇺🇸",
            "Canada": "🇨🇦",
            "Colombia": "🇨🇴",
            "Chile": "🇨🇱",
            "Ecuador": "🇪🇨",
            "Peru": "🇵🇪",
            "Paraguay": "🇵🇾",
            "Venezuela": "🇻🇪",
            "Bolivia": "🇧🇴",
            "Japan": "🇯🇵",
            "South Korea": "🇰🇷",
            "Australia": "🇦🇺",
            "Saudi Arabia": "🇸🇦",
            "Iran": "🇮🇷",
            "Morocco": "🇲🇦",
            "Senegal": "🇸🇳",
            "Tunisia": "🇹🇳",
            "Ghana": "🇬🇭",
            "Cameroon": "🇨🇲",
            "Nigeria": "🇳🇬",
            "Poland": "🇵🇱",
            "Serbia": "🇷🇸",
            "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
            "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
            "Costa Rica": "🇨🇷",
            "Qatar": "🇶🇦"
        }
        return flags.get(country, "🌍")

# Made with Bob
