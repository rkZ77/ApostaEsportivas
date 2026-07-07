"""
Construtor de Prompts Personalizados por Seleção

Recebe perfis de duas seleções e gera contexto rico para injetar no prompt base.
Inclui análise tática, métricas, pontos fortes/fracos e confrontos diretos.
"""

from datetime import date
from utils.db_utils import get_connection


# Fases da Copa do Mundo 2026 (datas BRT aproximadas)
_WC2026_PHASES = [
    (date(2026, 6, 11), date(2026, 7, 2),  "FASE DE GRUPOS"),
    (date(2026, 7, 4),  date(2026, 7, 10), "ROUND OF 32 (Oitavas-de-final)"),
    (date(2026, 7, 13), date(2026, 7, 17), "ROUND OF 16 (Quartas-de-final)"),
    (date(2026, 7, 19), date(2026, 7, 22), "QUARTAS DE FINAL"),
    (date(2026, 7, 25), date(2026, 7, 26), "SEMIFINAIS"),
    (date(2026, 7, 29), date(2026, 8, 1),  "FINAL / TERCEIRO LUGAR"),
]

def _wc_phase(match_date=None) -> str:
    d = match_date if isinstance(match_date, date) else date.today()
    for start, end, label in _WC2026_PHASES:
        if start <= d <= end:
            return label
    return "Copa do Mundo 2026"


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

        # Tendências gerais da Copa (últimos 15 jogos)
        tendencias_section = self._format_league_tendencias(league_id=1, limit=15)

        # Injeta no prompt base antes de "DADOS DO JOGO"
        context = f"{teams_section}\n\n{h2h_section}\n\n{tendencias_section}"
        if "DADOS DO JOGO" in base_prompt:
            return base_prompt.replace(
                "DADOS DO JOGO",
                f"{context}\n\n{'='*68}\nDADOS DO JOGO"
            )
        else:
            # Fallback: adiciona no final antes das regras
            return base_prompt.replace(
                "─────────────────────────────────────────────────",
                f"{context}\n\n{'─'*68}\n"
            )
    
    # ========================================================================
    # FORMATAÇÃO DE SEÇÕES
    # ========================================================================
    def get_world_cup_context(self, home_profile: dict, away_profile: dict, match_date=None) -> str:
        """
        Retorna o bloco completo de contexto Copa (perfis + H2H + tendências) pronto para injeção
        em qualquer pipeline que receba jogos da Copa do Mundo.
        """
        phase = _wc_phase(match_date)
        phase_header = f"{'='*68}\nCOPA DO MUNDO 2026 · {phase}\n{'='*68}\n"
        teams_section = self._format_teams_section(home_profile, away_profile)
        h2h_section = self._format_head_to_head(
            home_profile["team_id"],
            away_profile["team_id"],
            home_profile["team_name"],
            away_profile["team_name"],
        )
        tendencias = self._format_league_tendencias(league_id=1, limit=15)
        base = f"{phase_header}{teams_section}\n\n{h2h_section}"
        return f"{base}\n\n{tendencias}" if tendencias else base

    def get_compact_wc_context(self, home_profile: dict, away_profile: dict, match_date=None) -> str:
        """
        Versão compacta (~50% menos tokens) para pipelines que não precisam
        de detalhes táticos (alavancagem, dica_do_dia, multiplas).
        Mantém forma, gols, disciplina, cantos, Copa stats, grupo e tendências.
        """
        phase = _wc_phase(match_date)
        home_text = self._format_compact_team(home_profile)
        away_text = self._format_compact_team(away_profile)

        # Tabela do grupo (usa o grupo do time da casa, geralmente o mesmo)
        home_st = self._fetch_group_standing(home_profile["team_id"])
        group_section = ""
        if home_st:
            group_section = (
                f"\nCLASSIFICAÇÃO · {home_st['group']}:\n"
                + self._format_group_table(home_st["group"], home_profile["team_name"])
            )

        tendencias = self._format_league_tendencias(league_id=1, limit=15)
        base = (
            f"COPA DO MUNDO 2026 · {phase}\n"
            f"{'─'*60}\n"
            f"{home_text}\n"
            f"{'─'*60}\n"
            f"{away_text}\n"
            f"{'─'*60}\n"
            f"{group_section}"
        )
        return f"{base}\n\n{tendencias}" if tendencias else base

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
        weighted_gf = quality.get("weighted_goals_for", "N/A")
        weighted_ga = quality.get("weighted_goals_against", "N/A")
        weighted_cf = quality.get("weighted_corners_for", "N/A")
        weighted_cc = quality.get("weighted_corners_against", "N/A")
        amostra_ok = quality.get("amostra_suficiente_para_alta_confianca")
        amostra_line = "" if amostra_ok is None else (
            "" if amostra_ok else "  AMOSTRA PEQUENA · nao eleve confianca acima de MODERADO.\n"
        )

        return (
            f"{name} ({matches}j analisados)\n"
            f"  Forma: {sequence} V{win_rate}%/E{draw_rate}%/D{loss_rate}%\n"
            f"  Ataque:{goals_pg}gols/j | Defesa:{goals_ag}sofridos/j CS{cs_pct}%\n"
            f"  Ponderado(Copa/Elim/Amist) ataque: {weighted_gf}gols feitos/j | {weighted_cf}cantos feitos/j\n"
            f"  Ponderado(Copa/Elim/Amist) defesa: {weighted_ga}gols sofridos/j | {weighted_cc}cantos cedidos/j\n"
            f"{amostra_line}"
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

{away_text}
"""
    
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

        # Classificação no grupo
        standing = self._fetch_group_standing(profile["team_id"])
        if standing:
            group_table = self._format_group_table(standing["group"], profile["team_name"])
            standing_text = (
                f"{standing['group']} · {standing['rank']}º lugar | "
                f"{standing['points']}pts | "
                f"{standing['played']}J {standing['win']}V {standing['draw']}E {standing['lose']}D | "
                f"GF{standing['goals_for']} GA{standing['goals_against']} GD{standing['goals_diff']:+d} | "
                f"Forma: {(standing['form'] or '')[-5:]}\n"
                f"  Status: {standing['description'] or 'Em disputa'}\n"
                + group_table
            )
        else:
            standing_text = "Classificação não disponível (execute Stage 3)"

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
                        f"Cantos feitos:{q.get('cantos_feitos','N/A')}/j "
                        f"cedidos:{q.get('cantos_cedidos','N/A')}/j "
                        f"CS:{q['clean_sheet_pct']}% "
                        f"Amarelos:{q['amarelos']}/j"
                    )
            weighted_gf = quality.get("weighted_goals_for")
            weighted_ga = quality.get("weighted_goals_against")
            weighted_cf = quality.get("weighted_corners_for")
            weighted_cc = quality.get("weighted_corners_against")
            if weighted_ga is not None:
                q_lines.append(
                    f"  → Média PONDERADA (Copa>Elim>Amistoso) ataque: "
                    f"{weighted_gf} gols feitos/j | {weighted_cf} cantos feitos/j"
                )
                q_lines.append(
                    f"  → Média PONDERADA (Copa>Elim>Amistoso) defesa: "
                    f"{weighted_ga} gols sofridos/j | {weighted_cc} cantos cedidos/j"
                )
            amostra_ok = quality.get("amostra_suficiente_para_alta_confianca")
            if amostra_ok is False:
                grupo = quality.get("amostra_grupo_maior_peso", {})
                q_lines.append(
                    f"  AMOSTRA PEQUENA (total={quality.get('amostra_total','?')}j, "
                    f"grupo de maior peso={grupo.get('tipo','?')} com {grupo.get('jogos','?')}j) · "
                    f"nao sustenta confianca alta, declare limitacao."
                )
            quality_text = "\n".join(q_lines)
        else:
            quality_text = "  Dados insuficientes para breakdown por competição"

        return f"""{flag} {name}
{'─'*68}
TÉCNICO: {coach} | FORMAÇÃO: {formation}
LESIONADOS/SUSPENSOS: {injuries_text}

CLASSIFICAÇÃO NO GRUPO:
  {standing_text}

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
    
    def _fetch_league_tendencias(self, league_id: int, limit: int = 15) -> list:
        """Busca últimos N jogos da liga no banco com estatísticas."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT ms.match_date,
                       ms.home_goals, ms.away_goals, ms.total_goals,
                       ms.total_corners, ms.total_yellow_cards, ms.total_red_cards,
                       COALESCE(f.home_team, '') AS home_team,
                       COALESCE(f.away_team, '') AS away_team
                FROM match_statistics ms
                LEFT JOIN fixtures f ON f.fixture_id = ms.fixture_id
                WHERE ms.league_id = %s
                  AND ms.status IN ('FT', 'AET', 'PEN')
                ORDER BY ms.match_date DESC
                LIMIT %s
            """, (league_id, limit))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [
                {
                    "match_date":        r[0],
                    "home_goals":        r[1] or 0,
                    "away_goals":        r[2] or 0,
                    "total_goals":       r[3] or 0,
                    "total_corners":     r[4] or 0,
                    "total_yellows":     r[5] or 0,
                    "total_reds":        r[6] or 0,
                    "home_team":         r[7],
                    "away_team":         r[8],
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[PROMPT_BUILDER] Erro ao buscar tendências da liga {league_id}: {e}")
            return []

    def _format_league_tendencias(self, league_id: int, limit: int = 15) -> str:
        """Formata bloco de tendências gerais da liga para o prompt."""
        games = self._fetch_league_tendencias(league_id, limit)
        if not games:
            return ""

        n = len(games)
        avg_goals   = round(sum(g["total_goals"]   for g in games) / n, 2)
        avg_corners = round(sum(g["total_corners"] for g in games) / n, 2)
        avg_yellows = round(sum(g["total_yellows"] for g in games) / n, 2)
        avg_reds    = round(sum(g["total_reds"]    for g in games) / n, 2)
        btts        = sum(1 for g in games if g["home_goals"] > 0 and g["away_goals"] > 0)
        btts_pct    = int(btts / n * 100)
        over25      = sum(1 for g in games if g["total_goals"] >= 3)
        over25_pct  = int(over25 / n * 100)

        goals_label   = "ALTO"   if avg_goals   >= 2.5 else "MÉDIO" if avg_goals   >= 1.5 else "BAIXO"
        corners_label = "ALTO"   if avg_corners >= 10  else "MÉDIO" if avg_corners >= 7   else "BAIXO"
        yellows_label = "ALTO"   if avg_yellows >= 3.5 else "MÉDIO" if avg_yellows >= 2   else "BAIXO"

        games_lines = []
        for g in games[:10]:
            dt = g["match_date"].strftime("%d/%m") if g["match_date"] else "N/A"
            home = g["home_team"] or "?"
            away = g["away_team"] or "?"
            games_lines.append(
                f"  {dt}: {home} {g['home_goals']}-{g['away_goals']} {away}"
                f" | Escan:{g['total_corners']} Amar:{g['total_yellows']}"
                + (f" Verm:{g['total_reds']}" if g["total_reds"] > 0 else "")
            )

        return (
            f"{'='*68}\n"
            f"TENDÊNCIAS GERAIS DA COPA DO MUNDO (Últimos {n} jogos)\n"
            f"{'='*68}\n"
            f"  Gols/jogo:           {avg_goals}  → {goals_label}  | BTTS: {btts_pct}%  | Over 2.5: {over25_pct}%\n"
            f"  Escanteios/jogo:     {avg_corners} → {corners_label}\n"
            f"  Amarelos/jogo:       {avg_yellows} → {yellows_label}\n"
            f"  Vermelhos/jogo:      {avg_reds}\n"
            f"\nÚLTIMOS JOGOS:\n"
            + "\n".join(games_lines)
        )

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
    # CLASSIFICAÇÃO DO GRUPO (Copa do Mundo)
    # ========================================================================
    def _fetch_group_standing(self, team_id: int, league_id: int = 1) -> dict | None:
        """Retorna a linha de standing do time no grupo Copa."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT group_name, rank, points, played, win, draw, lose,
                       goals_for, goals_against, goals_diff, form, description
                FROM league_standings
                WHERE team_id = %s AND league_id = %s
                LIMIT 1
            """, (team_id, league_id))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                return None
            return {
                "group":       row[0],
                "rank":        row[1],
                "points":      row[2],
                "played":      row[3],
                "win":         row[4],
                "draw":        row[5],
                "lose":        row[6],
                "goals_for":   row[7],
                "goals_against": row[8],
                "goals_diff":  row[9],
                "form":        row[10],
                "description": row[11],
            }
        except Exception as e:
            print(f"[PROMPT_BUILDER] Erro ao buscar standing team {team_id}: {e}")
            return None

    def _fetch_full_group(self, group_name: str, league_id: int = 1) -> list:
        """Retorna a tabela completa do grupo para exibir ao lado do time."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT rank, team_name, played, win, draw, lose,
                       goals_for, goals_against, goals_diff, points, form
                FROM league_standings
                WHERE group_name = %s AND league_id = %s
                ORDER BY rank ASC
            """, (group_name, league_id))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [
                {"rank": r[0], "team": r[1], "p": r[2], "w": r[3], "d": r[4],
                 "l": r[5], "gf": r[6], "ga": r[7], "gd": r[8], "pts": r[9], "form": r[10]}
                for r in rows
            ]
        except Exception:
            return []

    def _format_group_table(self, group_name: str, highlight_team: str) -> str:
        """Formata tabela do grupo no estilo placar."""
        rows = self._fetch_full_group(group_name)
        if not rows:
            return ""
        lines = [f"  {group_name} │ PJ  V  E  D  GP GA GD Pts  Forma"]
        for r in rows:
            marker = "►" if r["team"].lower() == highlight_team.lower() else " "
            form = (r["form"] or "")[-5:]
            lines.append(
                f"  {marker}{r['rank']}. {r['team']:<22} "
                f"{r['p']:>2} {r['w']:>2} {r['d']:>2} {r['l']:>2} "
                f"{r['gf']:>3}{r['ga']:>3}{r['gd']:>+4} {r['pts']:>3}  {form}"
            )
        return "\n".join(lines)

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
