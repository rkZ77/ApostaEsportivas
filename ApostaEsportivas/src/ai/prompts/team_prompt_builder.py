"""
Construtor de Prompts Personalizados por Seleção

Recebe perfis de duas seleções e gera contexto compacto para injetar no prompt dos
pipelines de Copa do Mundo (alavancagem, dica_do_dia, multiplas).
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
    # CONTEXTO COMPACTO · usado por alavancagem, dica_do_dia e multiplas
    # ========================================================================
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
