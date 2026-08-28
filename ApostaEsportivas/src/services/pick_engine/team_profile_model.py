"""Modelo 3 (Perfil das equipes): funcoes puras de perfil tatico/forma/
ofensivo/defensivo/disciplina/bolas-paradas, portadas dos metodos genericos
de national_team_profile_service.py (que ja eram estruturalmente
independentes de qualquer logica especifica de Copa do Mundo). Aqui viram
funcoes puras (matches, team_id) -> dict, reutilizaveis tanto para selecoes
quanto para clubes -- national_team_profile_service.py nao e alterado."""
from services.pick_engine.stats_model import offensive_efficiency


#: Rótulo do perfil -> coluna de `match_statistics`, sem o prefixo home_/away_.
_CAMPOS_TATICOS = {
    "possession": "possession",
    "shots": "total_shots",
    "shots_on": "shots_on",
    "passes": "passes",
    "pass_accuracy": "passes_accuracy",
    "corners": "corners",
    "fouls": "fouls",
}


def tactical_patterns(matches: list, team_id: int) -> dict:
    """Perfil tático do time a partir das partidas cruas.

    CADA MÉDIA DIVIDE PELOS JOGOS EM QUE O CONTADOR EXISTE (2026-08-28).

    Antes isto somava `m.get(campo) or 0` e dividia tudo por `count`, e o
    estrago aqui é maior que uma média torta: `_determine_playing_style` lê a
    posse de bola pra classificar o time, e posse é justamente o campo que
    NUNCA pode virar zero (utils/stat_sheet._NUNCA_ZERO -- posse 0% num jogo
    que aconteceu é impossível). Um único jogo sem folha derrubava a média de
    posse abaixo dos 45%, e o time era rotulado "Contra-ataque rápido" por
    causa de uma partida em que o provedor não publicou estatística.
    """
    if not matches:
        return _default_tactical_profile()

    somas = {chave: 0.0 for chave in _CAMPOS_TATICOS}
    amostras = {chave: 0 for chave in _CAMPOS_TATICOS}
    count = 0

    for m in matches:
        prefixo = "home" if m["home_team_id"] == team_id else "away"
        for chave, coluna in _CAMPOS_TATICOS.items():
            valor = m.get(f"{prefixo}_{coluna}")
            if valor is None:
                continue
            somas[chave] += float(valor)
            amostras[chave] += 1
        count += 1

    if count == 0:
        return _default_tactical_profile()

    def media(chave):
        n = amostras[chave]
        return (somas[chave] / n) if n else 0

    avg_possession = media("possession")
    avg_shots = media("shots")
    avg_shots_on = media("shots_on")
    avg_passes = media("passes")
    avg_pass_accuracy = media("pass_accuracy")
    avg_corners = media("corners")
    avg_fouls = media("fouls")

    # Sem UM jogo com posse publicada não dá pra falar de estilo: o
    # classificador leria zero e devolveria "Contra-ataque rápido" pra
    # qualquer time.
    style = (_determine_playing_style(avg_possession, avg_shots, avg_passes)
             if amostras["possession"] else "Dados insuficientes")
    pressing = (_determine_pressing_intensity(avg_fouls, avg_possession)
                if amostras["fouls"] and amostras["possession"] else "Desconhecida")

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
        "pressing_intensity": pressing,
        # Quantos jogos sustentam cada média · o perfil de um time com 10 jogos
        # e posse publicada em 3 não é o mesmo objeto que o de 10 em 10.
        "amostra_por_campo": amostras,
    }


def _default_tactical_profile() -> dict:
    return {
        "style": "Dados insuficientes", "avg_possession": 0, "avg_shots": 0,
        "avg_shots_on_target": 0, "shot_accuracy_pct": 0, "avg_passes": 0,
        "avg_pass_accuracy": 0, "avg_corners": 0, "avg_fouls": 0,
        "pressing_intensity": "Desconhecida",
    }


def _determine_playing_style(possession: float, shots: float, passes: float) -> str:
    if possession >= 55 and passes >= 450:
        return "Posse de bola dominante"
    if possession >= 55:
        return "Posse de bola + Contra-ataque"
    if shots >= 14:
        return "Ataque direto e intenso"
    if possession <= 45:
        return "Contra-ataque rápido"
    return "Jogo equilibrado"


def _determine_pressing_intensity(fouls: float, possession: float) -> str:
    if fouls >= 13 and possession >= 52:
        return "Alta"
    if fouls >= 11:
        return "Média-Alta"
    if fouls >= 9:
        return "Média"
    return "Baixa"


def form_metrics(matches: list, team_id: int) -> dict:
    if not matches:
        return _default_form_metrics()

    results, wins, draws, losses = [], 0, 0, 0
    for m in matches:
        is_home = m["home_team_id"] == team_id
        home_goals = m.get("home_goals") or 0
        away_goals = m.get("away_goals") or 0
        scored, conceded = (home_goals, away_goals) if is_home else (away_goals, home_goals)
        if scored > conceded:
            results.append("W"); wins += 1
        elif scored == conceded:
            results.append("D"); draws += 1
        else:
            results.append("L"); losses += 1

    total = len(results)
    return {
        "sequence": "-".join(results),
        "last_5": "-".join(results[:5]),
        "games_played": total,
        "wins": wins, "draws": draws, "losses": losses,
        "win_rate": round(wins / total, 2) if total > 0 else 0,
        "draw_rate": round(draws / total, 2) if total > 0 else 0,
        "loss_rate": round(losses / total, 2) if total > 0 else 0,
    }


def _default_form_metrics() -> dict:
    return {
        "sequence": "", "last_5": "", "games_played": 0, "wins": 0, "draws": 0,
        "losses": 0, "win_rate": 0, "draw_rate": 0, "loss_rate": 0,
    }


def offensive_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_goals = total_shots = total_shots_on = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        if is_home:
            total_goals += m.get("home_goals") or 0
            total_shots += m.get("home_total_shots") or 0
            total_shots_on += m.get("home_shots_on") or 0
        else:
            total_goals += m.get("away_goals") or 0
            total_shots += m.get("away_total_shots") or 0
            total_shots_on += m.get("away_shots_on") or 0

    return {
        "goals_per_game": round(total_goals / count, 2),
        "shots_per_game": round(total_shots / count, 1),
        "shots_on_target_per_game": round(total_shots_on / count, 1),
        "shot_conversion_pct": round((total_goals / total_shots * 100) if total_shots > 0 else 0, 1),
    }


def defensive_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_goals_against = clean_sheets = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        goals_against = (m.get("away_goals") or 0) if is_home else (m.get("home_goals") or 0)
        total_goals_against += goals_against
        if goals_against == 0:
            clean_sheets += 1

    return {
        "goals_against_per_game": round(total_goals_against / count, 2),
        "clean_sheets": clean_sheets,
        "clean_sheets_pct": round(clean_sheets / count, 2),
    }


def discipline_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_fouls = total_yellow = total_red = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        if is_home:
            total_fouls += m.get("home_fouls") or 0
            total_yellow += m.get("home_yellow_cards") or 0
            total_red += m.get("home_red_cards") or 0
        else:
            total_fouls += m.get("away_fouls") or 0
            total_yellow += m.get("away_yellow_cards") or 0
            total_red += m.get("away_red_cards") or 0

    return {
        "fouls_per_game": round(total_fouls / count, 1),
        "yellow_cards_per_game": round(total_yellow / count, 1),
        "red_cards_per_game": round(total_red / count, 2),
    }


def set_pieces_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_corners = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        total_corners += (m.get("home_corners") or 0) if is_home else (m.get("away_corners") or 0)

    return {"corners_per_game": round(total_corners / count, 1)}


def strengths_weaknesses(stats: dict) -> tuple:
    strengths, weaknesses = [], []
    offensive = stats.get("offensive", {})
    defensive = stats.get("defensive", {})
    tactical = stats.get("tactical", {})
    form = stats.get("form", {})

    goals_pg = offensive.get("goals_per_game", 0)
    if goals_pg >= 2.0:
        strengths.append(f"Ataque eficiente ({goals_pg} gols/jogo)")
    elif goals_pg < 1.0:
        weaknesses.append(f"Dificuldade para marcar gols ({goals_pg} gols/jogo)")

    goals_against = defensive.get("goals_against_per_game", 0)
    clean_sheets_pct = defensive.get("clean_sheets_pct", 0)
    if clean_sheets_pct >= 0.40:
        strengths.append(f"Defesa sólida ({int(clean_sheets_pct * 100)}% clean sheets)")
    elif goals_against >= 1.5:
        weaknesses.append(f"Defesa vulnerável ({goals_against} gols sofridos/jogo)")

    possession = tactical.get("avg_possession", 0)
    if possession >= 55:
        strengths.append(f"Domínio de posse de bola ({possession}%)")
    elif possession <= 45:
        weaknesses.append(f"Baixa posse de bola ({possession}%)")

    shot_accuracy = tactical.get("shot_accuracy_pct", 0)
    if shot_accuracy >= 40:
        strengths.append(f"Alta precisão nos chutes ({shot_accuracy}%)")

    win_rate = form.get("win_rate", 0)
    if win_rate >= 0.65:
        strengths.append(f"Excelente forma recente ({int(win_rate * 100)}% vitórias)")
    elif win_rate <= 0.35:
        weaknesses.append(f"Forma irregular ({int(win_rate * 100)}% vitórias)")

    if len(strengths) < 2:
        strengths.append("Análise baseada em dados limitados")
    if len(weaknesses) < 2:
        weaknesses.append("Análise baseada em dados limitados")

    return strengths[:4], weaknesses[:3]


def build_profile(matches: list, team_id: int) -> dict:
    """Monta o perfil completo (tatico/forma/ofensivo/defensivo/disciplina/
    bolas-paradas/pontos-fortes-fracos) a partir de jogos ja buscados --
    funciona tanto com match_stats_service.py (clubes) quanto com o
    _fetch_recent_matches de national_team_profile_service.py (selecoes),
    pois ambos devolvem o mesmo formato de linha."""
    tactical = tactical_patterns(matches, team_id)
    form = form_metrics(matches, team_id)
    offensive = offensive_stats(matches, team_id)
    defensive = defensive_stats(matches, team_id)
    discipline = discipline_stats(matches, team_id)
    set_pieces = set_pieces_stats(matches, team_id)
    efficiency = offensive_efficiency(matches, team_id)
    strengths, weaknesses = strengths_weaknesses({
        "offensive": offensive, "defensive": defensive,
        "tactical": tactical, "form": form,
    })

    return {
        "team_id": team_id,
        "matches_analyzed": len(matches),
        "tactical_profile": tactical,
        "form": form,
        "offensive_stats": offensive,
        "defensive_stats": defensive,
        "discipline_stats": discipline,
        "set_pieces_stats": set_pieces,
        "offensive_efficiency": efficiency,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }


_PRESSING_SCORE = {"Alta": 2, "Média-Alta": 1, "Média": 0, "Baixa": -1, "Desconhecida": 0}

# Baseline de conversao (gols por chute no alvo) tipica do futebol
# profissional -- mesmo espirito de referencia que _CORNERS_BASELINE/
# _CARDS_BASELINE ja usavam (ponto zero do delta, nao "ajuste" arbitrario).
# Nao calibrado contra resultado real ainda -- revisar com o log de sombra
# (Prioridade 4 do plano: Calibration Engine) quando houver volume.
_CONVERSION_BASELINE = 0.30
_MIN_EFFICIENCY_AMOSTRA = 3

# Baselines neutros de posse (%) e chutes totais/jogo (por time) -- ponto
# zero do indice continuo de pressao ofensiva usado em corners_delta abaixo.
# Substituem o antigo bucket categorico de "estilo de jogo" (_POSSESSION_PRESSURE)
# por um sinal proporcional aos numeros reais de avg_possession/avg_shots
# (pedido explicito do usuario: "escanteios tem que analisar estatisticamente
# pressao/posse de bola/ataque/chutes", nao so uma faixa de estilo).
_POSSESSION_BASELINE = 50.0
_SHOTS_BASELINE = 12.5


def _attacking_pressure_score(tactical: dict) -> float:
    """Indice continuo de pressao ofensiva (posse + volume de chutes) de UM
    time, centrado em 0 nos baselines acima -- usa avg_possession/avg_shots
    (ja calculados em tactical_patterns(), stats_model.py), NUNCA
    home_corners/away_corners diretamente, preservando o principio anti-
    double-counting ja documentado em compare_matchup() (Prioridade 1.3)."""
    # float() defensivo -- mesmo bug real ja visto em referee_model.py: campo
    # numerico vindo do banco (psycopg2) pode chegar como Decimal, e Decimal-
    # float estoura TypeError. avg_possession/avg_shots passam por soma+round()
    # em tactical_patterns() antes de chegar aqui, o que preserva o tipo
    # original do campo bruto se ele vier Decimal.
    possession = float(tactical.get("avg_possession") or 0)
    shots = float(tactical.get("avg_shots") or 0)
    return (possession - _POSSESSION_BASELINE) / 100 + (shots - _SHOTS_BASELINE) / _SHOTS_BASELINE


def compare_matchup(profile_home: dict, profile_away: dict) -> dict:
    """Compara os perfis de casa e fora e devolve deltas numericos por
    familia de mercado (goals/corners/cards). Cada delta e soma de
    componentes explicitos (sempre expostos em 'components'), nunca um
    numero ajustado sem conta rastreavel.

    Prioridade 1.3 do plano de refatoracao (double-counting): as versoes
    anteriores de goals_delta/corners_delta/cards_delta usavam medias
    brutas (gols/jogo, escanteios/jogo, faltas/jogo) que sao os MESMOS
    campos brutos que ja alimentam taxa_real/confidence em outro lugar do
    motor (stats_model.compute_taxa/expected_value_convergence) -- somado
    de novo aqui no Score Final, isso confirmava a mesma evidencia duas
    vezes. Agora cada delta usa APENAS sinais que nao vem de contar o
    proprio evento historico: eficiencia de finalizacao (chutes no alvo ->
    gol, nao contagem de gols), pressao ofensiva continua de posse+chutes
    (nao contagem de escanteios) e intensidade de pressao (categorico, nao
    contagem de faltas). Efeito colateral: corners_delta agora pode ser
    NEGATIVO (time de baixa posse/poucos chutes -> menos escanteios
    esperados) -- antes so' discriminava pra Over (bucket categorico de
    estilo nunca ia abaixo de 0), essa era uma limitacao conhecida que o
    indice continuo de posse/chutes corrige; goals ainda so' discrimina pra
    Over (falta sinal tatico igualmente forte pra Under) e cards ja e'
    simetrico (pressing_score vai de -2 a +4)."""
    tac_h, tac_a = profile_home.get("tactical_profile", {}), profile_away.get("tactical_profile", {})
    eff_h, eff_a = profile_home.get("offensive_efficiency") or {}, profile_away.get("offensive_efficiency") or {}

    conv_h, conv_a = eff_h.get("conversion_rate"), eff_a.get("conversion_rate")
    n_h, n_a = eff_h.get("amostra", 0), eff_a.get("amostra", 0)
    if conv_h is not None and conv_a is not None and n_h >= _MIN_EFFICIENCY_AMOSTRA and n_a >= _MIN_EFFICIENCY_AMOSTRA:
        combined_conversion = round((conv_h + conv_a) / 2, 3)
        goals_delta = round((combined_conversion - _CONVERSION_BASELINE) * 3, 2)
    else:
        combined_conversion = None
        goals_delta = 0.0  # amostra insuficiente pra eficiencia -- neutro, nao inventa

    pressure_h, pressure_a = _attacking_pressure_score(tac_h), _attacking_pressure_score(tac_a)
    attacking_pressure = round(max(min(pressure_h + pressure_a, 2.0), -2.0), 3)
    corners_delta = round(attacking_pressure * 0.5, 2)

    pressing_score = (
        _PRESSING_SCORE.get(tac_h.get("pressing_intensity"), 0)
        + _PRESSING_SCORE.get(tac_a.get("pressing_intensity"), 0)
    )
    cards_delta = round(pressing_score * 0.15, 2)

    def label(delta):
        if delta > 0.15:
            return "Over"
        if delta < -0.15:
            return "Under"
        return "neutro"

    return {
        "goals": {
            "delta": goals_delta, "label": label(goals_delta),
            "components": {
                "conversion_rate_home": conv_h,
                "conversion_rate_away": conv_a,
                "combined_conversion_rate": combined_conversion,
                "baseline": _CONVERSION_BASELINE,
            },
        },
        "corners": {
            "delta": corners_delta, "label": label(corners_delta),
            "components": {
                "attacking_pressure_score": attacking_pressure,
                "avg_possession_home": tac_h.get("avg_possession"),
                "avg_possession_away": tac_a.get("avg_possession"),
                "avg_shots_home": tac_h.get("avg_shots"),
                "avg_shots_away": tac_a.get("avg_shots"),
                "possession_baseline": _POSSESSION_BASELINE,
                "shots_baseline": _SHOTS_BASELINE,
            },
        },
        "cards": {
            "delta": cards_delta, "label": label(cards_delta),
            "components": {
                "pressing_score": pressing_score,
                "pressing_intensity_home": tac_h.get("pressing_intensity"),
                "pressing_intensity_away": tac_a.get("pressing_intensity"),
            },
        },
    }


def profile_score_for_market(matchup: dict | None, market_type: str) -> float | None:
    """Reduz o delta de compare_matchup (para a familia de mercado do
    candidato) a um score 0-1 (0.5=neutro) para uso no Score Final
    (ranking.py::final_score). Delta tipico fica entre -2 e +2; escala
    suave para nao dominar o score.

    O delta e clampado em [-2, 2] ANTES de escalar -- sem isso, um
    baseline de familia mal calibrado pra um tipo de time (ex: selecoes
    nacionais fazem bem menos escanteios que o baseline de futebol de
    clube, _CORNERS_BASELINE=9.5) produz delta muito mais extremo que
    gols/cartoes pro mesmo jogo, satura o score no piso/teto (0.0/1.0) e
    passa a dominar sistematicamente o Score Final -- nao por ter sinal
    mais forte, so por causa do descompasso de baseline. Bug real
    encontrado via decision_log.py: escanteios com EV +73% e confidence
    86% perdendo pra cartoes com EV +57%/80% so por causa disso."""
    if not matchup:
        return None
    # BTTS le' o matchup de GOLS. compare_matchup produz tres chaves (goals,
    # corners, cards) e "ambas marcam" nao tem uma propria -- o sinal tatico
    # que serve pra ele e' o mesmo da familia de gols (eficiencia de
    # finalizacao dos dois lados). Ate' 2026-08-20 isso funcionava por
    # acidente, porque o orchestrator gravava market_type="goals" no candidato
    # de BTTS; quando ele ganhou tipo proprio, a busca passaria a devolver None
    # e o BTTS perderia o termo de Perfil no Score Final em silencio.
    entry = matchup.get("goals" if market_type == "btts" else market_type)
    if not entry:
        return 0.5
    delta = max(min(entry.get("delta", 0.0), 2.0), -2.0)
    return round(max(min(0.5 + delta * 0.15, 1.0), 0.0), 4)
