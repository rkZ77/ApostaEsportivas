from futebol_agent.config import ODDS_MIN, ODDS_MAX


def fmt_live_matches(matches: list[dict]) -> str:
    if not matches:
        return "LISTA COMPLETA: 0 partidas ao vivo nas ligas monitoradas agora."
    lines = [f"LISTA COMPLETA: {len(matches)} partida(s) ao vivo nas ligas monitoradas:"]
    for m in matches:
        lines.append(f"ID:{m['fixture_id']} | {m['home']} {m['score']} {m['away']} | {m['minute']}' | {m['league']}")
    return "\n".join(lines)


def fmt_today_matches(matches: list[dict]) -> str:
    if not matches:
        return "LISTA COMPLETA: 0 jogos encontrados nas ligas monitoradas hoje."
    lines = [f"LISTA COMPLETA: {len(matches)} jogo(s) nas ligas monitoradas hoje:"]
    for m in matches:
        status = m["status_short"]
        score  = m["score"] if status not in ("NS", "TBD") else "x"
        lines.append(f"ID:{m['fixture_id']} | {m['home']} {score} {m['away']} | {status} {m['minute']}' | {m['league']}")
    return "\n".join(lines)


def fmt_match_stats(data: dict) -> str:
    if "error" in data:
        return data["error"]
    parts = []
    info  = data.get("match_info", {})
    if info:
        parts.append(f"{info['home']} {info['score']} {info['away']} | {info['minute']}' | {info['status']}")
    stats = data.get("statistics", {})
    is_halftime = info.get("status", "").lower() in ("halftime", "half time", "ht")
    if stats:
        teams = list(stats.keys())
        if len(teams) == 2:
            t1, t2 = teams
            keys   = ["Ball Possession","Total Shots","Shots on Goal","Corner Kicks","Fouls","Yellow Cards","Red Cards","expected_goals"]
            labels = ["Posse","Chutes","A gol","Escanteios","Faltas","Amarelos","Vermelhos","xG"]
            rows   = [f"{'':16} {t1[:12]:>12} {t2[:12]:>12}"]
            for label, key in zip(labels, keys):
                v1 = stats[t1].get(key) or "0"
                v2 = stats[t2].get(key) or "0"
                rows.append(f"{label:<16} {str(v1):>12} {str(v2):>12}")
            parts.append("STATS:\n" + "\n".join(rows))
    elif is_halftime:
        parts.append("STATS: indisponíveis no intervalo.")
    events = data.get("events", [])
    if events:
        ev_lines = [f"{e['minute']}' {e['type'].upper()} {e['team']} ({e['player']}) · {e['detail']}" for e in events]
        parts.append("EVENTOS:\n" + "\n".join(ev_lines))
    return "\n\n".join(parts) if parts else "Sem dados disponíveis."


def _fmt_markets(markets: dict) -> list[str]:
    lines = []
    for market, outcomes in markets.items():
        parts = []
        for outcome, val in outcomes.items():
            if isinstance(val, dict):
                parts.append(f"{outcome}: {val['odd']} ({val['bookmaker']})")
            else:
                parts.append(f"{outcome}: {val}")
        lines.append(f"{market}: {' | '.join(parts)}")
    return lines


def _eligible_entries(markets: dict, min_odd: float = ODDS_MIN, max_odd: float = ODDS_MAX) -> list[str]:
    entries = []
    for market, outcomes in markets.items():
        for outcome, val in outcomes.items():
            odd_str = val["odd"] if isinstance(val, dict) else val
            try:
                odd = float(odd_str)
            except (ValueError, TypeError):
                continue
            if min_odd <= odd <= max_odd:
                bookmaker = val.get("bookmaker", "") if isinstance(val, dict) else ""
                bm_str = f" ({bookmaker})" if bookmaker else ""
                entries.append(f"{market} · {outcome}: {odd}{bm_str}")
    return entries


def _append_eligible_sections(result: str, markets: dict) -> str:
    eligible = _eligible_entries(markets)
    if eligible:
        result += f"\n\nELEGÍVEIS ANÁLISE ({ODDS_MIN}–{ODDS_MAX}):\n" + "\n".join(eligible)
    else:
        result += f"\n\nELEGÍVEIS ANÁLISE ({ODDS_MIN}–{ODDS_MAX}): nenhuma odd neste range. Nao sugira entradas."
    return result


def fmt_odds(data: dict) -> str:
    if data.get("error") == "sem_cobertura":
        return "Sem cobertura de odds para esta partida."
    if data.get("status") == "ok" and data.get("markets"):
        markets = data["markets"]
        result  = "\n".join(_fmt_markets(markets))
        return _append_eligible_sections(result, markets)
    return "Odds pré-jogo não disponíveis."


def fmt_live_odds(data: dict) -> str:
    status  = data.get("status", "")
    markets = data.get("markets", {})
    lines   = _fmt_markets(markets)
    headers = {
        "live":               "",
        "intervalo":          "[INTERVALO] Odds do 2º tempo disponíveis:\n",
        "prematch_fallback":  "[ODDS PRÉ-JOGO] Live indisponível. Exibindo odds pré-jogo:\n",
        "sem_cobertura":      "Sem cobertura de odds para esta partida.",
    }
    header = headers.get(status, "")
    if not lines:
        return header or "Sem odds disponíveis."
    result = header + "\n".join(lines)
    return _append_eligible_sections(result, markets)


def _fmt_group_table(teams: list[dict]) -> str:
    header = f"{'Pos':>3} {'Time':<22} {'Pts':>3} {'J':>2} {'V':>2} {'E':>2} {'D':>2} {'SG':>4} {'Forma':<6} {'Status'}"
    rows   = [header]
    for t in teams:
        status = f"[{t['description']}]" if t.get("description") else ""
        rows.append(f"{t['pos']:>3} {t['team']:<22} {t['pts']:>3} {t['played']:>2} {t['won']:>2} {t['draw']:>2} {t['lost']:>2} {t['gd']:>+4} {t.get('form',''):>6} {status}")
    return "\n".join(rows)


def fmt_standings(data: list | dict) -> str:
    if isinstance(data, dict) and "error" in data:
        return data["error"]
    if not data:
        return "Classificação não disponível."
    if isinstance(data, list) and data and isinstance(data[0], dict) and "teams" in data[0]:
        parts = []
        for g in data:
            group_name = g["group"].split(",")[-1].strip() if "," in g["group"] else g["group"]
            parts.append(f"{group_name}:\n{_fmt_group_table(g['teams'])}")
        return "\n\n".join(parts)
    lines = [f"{'Pos':>3} {'Time':<22} {'Pts':>3} {'J':>2} {'V':>2} {'E':>2} {'D':>2} {'SG':>4} {'Forma':<6}"]
    teams = data[0]["teams"] if (data and isinstance(data[0], dict) and "teams" in data[0]) else data
    for t in teams[:20]:
        lines.append(f"{t['pos']:>3} {t['team']:<22} {t['pts']:>3} {t['played']:>2} {t['won']:>2} {t['draw']:>2} {t['lost']:>2} {t['gd']:>+4} {t.get('form',''):>6}")
    return "\n".join(lines)


def fmt_h2h(data: dict) -> str:
    if "error" in data:
        return data["error"]
    summary = data.get("summary", {})
    matches = data.get("matches", [])
    s = " | ".join(f"{k}: {v}" for k, v in summary.items())
    lines = [f"H2H: {s}"]
    for m in matches:
        lines.append(f"{m['date']} {m['home']} {m['score']} {m['away']} → {m['winner']}")
    return "\n".join(lines)


def fmt_injuries(data: list | dict) -> str:
    if isinstance(data, dict) and "error" in data:
        return data["error"]
    if not data:
        return "Sem lesionados/suspensos registrados para esta partida."
    by_team: dict[str, list[str]] = {}
    for p in data:
        by_team.setdefault(p.get("team", "?"), []).append(f"{p['player']} ({p.get('reason', p.get('type', ''))})")
    return "\n".join(f"{team}: {', '.join(players)}" for team, players in by_team.items())


def fmt_prediction(data: dict | None) -> str:
    if not data:
        return "Previsão não disponível para esta partida."
    lines = []
    if data.get("advice"):   lines.append(f"Conselho: {data['advice']}")
    if data.get("winner"):   lines.append(f"Vencedor previsto: {data['winner']}")
    pct = data.get("percent", {})
    if pct:
        lines.append(f"Probabilidades: Casa {pct.get('home','?')} | Empate {pct.get('draw','?')} | Fora {pct.get('away','?')}")
    goals = data.get("goals", {})
    if goals:
        lines.append(f"Gols esperados: Casa {goals.get('home','?')} | Fora {goals.get('away','?')}")
    if data.get("under_over") is not None:
        lines.append(f"Under/Over 2.5: {data['under_over']}")
    return "\n".join(lines)


def fmt_team_form(data: dict) -> str:
    if "error" in data:
        return data["error"]
    lines = [f"Forma {data['team']}: {data['form']}"]
    for m in data.get("last_matches", []):
        lines.append(f"{m['date']} {m['home']} {m['score']} {m['away']} [{m.get('result_for_team','')}]")
    return "\n".join(lines)


def fmt_lineups(data: list[dict]) -> str:
    if not data:
        return "Escalações não disponíveis para esta partida."
    parts = []
    for t in data:
        lines = [
            f"{t['team']} [{t['formation']}] · Técnico: {t['coach']}",
            f"  GK:  {', '.join(t['gk'])}",
            f"  DEF: {', '.join(t['defenders'])}",
            f"  MED: {', '.join(t['midfielders'])}",
            f"  ATA: {', '.join(t['forwards'])}",
            f"  BNC: {', '.join(t['substitutes'][:6])}{'...' if len(t['substitutes']) > 6 else ''}",
        ]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def fmt_player_stats(data: list[dict]) -> str:
    if not data:
        return "Stats de jogadores não disponíveis para esta partida."
    parts = []
    for team_data in data:
        lines = [f"{team_data['team']}:"]
        lines.append(f"  {'Nome':<22} {'Pos':>3} {'Min':>3} {'Rat':>4} {'G':>2} {'A':>2} {'Chut':>4} {'PsCh':>4} {'Des':>3} {'Cart'}")
        for p in team_data["players"]:
            rating = p["rating"] or "-"
            cap    = "© " if p["captain"] else "  "
            cards  = ("🟨" if p["yellow"] else "") + ("🟥" if p["red"] else "")
            lines.append(f"  {cap}{p['name']:<20} {p['pos']:>3} {p['minutes']:>3} {str(rating):>4} {p['goals']:>2} {p['assists']:>2} {p['shots']:>4} {p['key_passes']:>4} {p['tackles']:>3} {cards}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def fmt_team_historical_stats(data: dict) -> str:
    if "error" in data:
        return data["error"]
    venue_label = {"home": "em casa", "away": "fora", "all": "geral"}.get(data.get("venue", "all"), "geral")
    t  = data.get("total", {})
    h1 = data.get("first_half", {})
    h2 = data.get("second_half", {})
    def r(d: dict, k: str) -> str: return str(d.get(k, "?"))
    lines = [
        f"Stats reais {data['team']} | {data['league']} {data['season']} | {venue_label} | {data['games_analyzed']} jogos",
        f"{'':20} Total   1ºT   2ºT",
        f"{'Escanteios':<20} {r(t,'corners'):>5} {r(h1,'corners'):>5} {r(h2,'corners'):>5}",
        f"{'Chutes total':<20} {r(t,'shots'):>5} {r(h1,'shots'):>5} {r(h2,'shots'):>5}",
        f"{'Chutes a gol':<20} {r(t,'shots_on'):>5} {r(h1,'shots_on'):>5} {r(h2,'shots_on'):>5}",
        f"{'Posse (%)':<20} {r(t,'possession'):>5} {r(h1,'possession'):>5} {r(h2,'possession'):>5}",
        f"{'Amarelos':<20} {r(t,'yellow_cards'):>5} {r(h1,'yellow_cards'):>5} {r(h2,'yellow_cards'):>5}",
        f"{'Vermelhos':<20} {r(t,'red_cards'):>5} {r(h1,'red_cards'):>5} {r(h2,'red_cards'):>5}",
        f"{'Faltas':<20} {r(t,'fouls'):>5} {r(h1,'fouls'):>5} {r(h2,'fouls'):>5}",
        f"{'xG':<20} {r(t,'xg'):>5} {r(h1,'xg'):>5} {r(h2,'xg'):>5}",
        f"Gols marcados: {data['avg_goals_scored']}/jogo  Sofridos: {data['avg_goals_conceded']}/jogo",
    ]
    return "\n".join(lines)


def fmt_team_historical_stats_any(data: dict) -> str:
    if "error" in data:
        return data["error"]
    venue_label = {"home": "em casa", "away": "fora", "all": "geral"}.get(data.get("venue", "all"), "geral")
    t  = data.get("total", {})
    h1 = data.get("first_half", {})
    h2 = data.get("second_half", {})
    leagues = ", ".join(data.get("leagues_seen", [])) or "?"
    def r(d: dict, k: str) -> str: return str(d.get(k, "?"))
    lines = [
        f"Stats reais {data['team']} | qualquer competição ({leagues}) | {venue_label} | {data['games_analyzed']} jogos",
        f"⚠️ Dados de múltiplas competições. Use como referência.",
        f"{'':20} Total   1ºT   2ºT",
        f"{'Escanteios':<20} {r(t,'corners'):>5} {r(h1,'corners'):>5} {r(h2,'corners'):>5}",
        f"{'Chutes total':<20} {r(t,'shots'):>5} {r(h1,'shots'):>5} {r(h2,'shots'):>5}",
        f"{'Chutes a gol':<20} {r(t,'shots_on'):>5} {r(h1,'shots_on'):>5} {r(h2,'shots_on'):>5}",
        f"{'Posse (%)':<20} {r(t,'possession'):>5} {r(h1,'possession'):>5} {r(h2,'possession'):>5}",
        f"{'Amarelos':<20} {r(t,'yellow_cards'):>5} {r(h1,'yellow_cards'):>5} {r(h2,'yellow_cards'):>5}",
        f"{'Faltas':<20} {r(t,'fouls'):>5} {r(h1,'fouls'):>5} {r(h2,'fouls'):>5}",
        f"Gols marcados: {data['avg_goals_scored']}/jogo  Sofridos: {data['avg_goals_conceded']}/jogo",
    ]
    return "\n".join(lines)


def fmt_team_halftime_record(data: dict) -> str:
    if "error" in data:
        return data["error"]
    lines = [
        f"Placar no intervalo (1ºT) de {data['team']} | últimos {data['games_analyzed']} jogos:",
        f"Vencendo no intervalo: {data['ht_wins']} | Empatando: {data['ht_draws']} | Perdendo: {data['ht_losses']}",
    ]
    for m in data["matches"]:
        lines.append(f"  {m['date']} vs {m['opponent']}: {m['ht_score']} [{m['result']}]")
    return "\n".join(lines)


def fmt_team_season_stats(data: dict) -> str:
    if "error" in data:
        return data["error"]
    agf = data.get("avg_goals_for", {})
    aga = data.get("avg_goals_against", {})
    lines = [
        f"Stats temporada {data['team']} | {data['league']} {data['season']}",
        f"Jogos: {data['played']} | V:{data['wins']} E:{data['draws']} D:{data['losses']}",
        f"Media gols marcados: casa {agf.get('home','?')} | fora {agf.get('away','?')} | total {agf.get('total','?')}",
        f"Media gols sofridos: casa {aga.get('home','?')} | fora {aga.get('away','?')} | total {aga.get('total','?')}",
        f"Clean sheets: {data.get('clean_sheets',0)} | Sem marcar: {data.get('failed_to_score',0)}",
        f"Forma recente: {data.get('form','?')}",
    ]
    return "\n".join(lines)
