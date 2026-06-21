"""
Modelo de Poisson para cálculo determinístico de prob_real por mercado/linha.
Pré-calcula probabilidades antes de enviar dados para a IA — elimina erros de
contagem/matemática do modelo e torna o score reproduzível para o mesmo jogo.
"""

import math
import re

# ──────────────────────────────────────────────────────────
# MATEMÁTICA POISSON (sem dependência externa)
# ──────────────────────────────────────────────────────────

def _pmf(k: int, lam: float) -> float:
    """P(X = k) com X ~ Poisson(lam)."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    try:
        return (lam ** k) * math.exp(-lam) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def _cdf(k: int, lam: float) -> float:
    """P(X <= k) com X ~ Poisson(lam)."""
    return sum(_pmf(i, lam) for i in range(k + 1))


def _p_over(lam: float, line: float) -> float:
    """P(X > line) — Over line. Ex: Over 2.5 → P(X >= 3)."""
    return max(0.0, min(1.0, 1.0 - _cdf(int(line), lam)))


def _p_under(lam: float, line: float) -> float:
    """P(X <= line) — Under line. Ex: Under 2.5 → P(X <= 2)."""
    return max(0.0, min(1.0, _cdf(int(line), lam)))


# ──────────────────────────────────────────────────────────
# CÁLCULO DE LAMBDA
# ──────────────────────────────────────────────────────────

def _lam(avg_for: float | None, avg_against_opp: float | None) -> float:
    """
    Estima o lambda esperado para um time neste jogo.
    Combina produção do time (feitos) com fragilidade do adversário (cedidos).
    Média simples dos dois vetores — Dixon-Coles simplificado.
    """
    vals = [v for v in [avg_for, avg_against_opp] if v is not None and v > 0]
    if not vals:
        return 1.5
    return sum(vals) / len(vals)


# ──────────────────────────────────────────────────────────
# PARSER DE LINHA
# ──────────────────────────────────────────────────────────

_RE_NUM = re.compile(r'\d+\.?\d*')


def _parse_line(line_str: str) -> tuple[str, float] | None:
    """
    'Over 2.5'  → ('over', 2.5)
    'Under 1.5' → ('under', 1.5)
    'Sim'       → ('sim', 0.0)
    '1X'        → ('1x', 0.0)
    Retorna None se não reconhecido.
    """
    s = str(line_str).strip().lower()
    if s.startswith('over'):
        m = _RE_NUM.search(s)
        return ('over', float(m.group())) if m else None
    if s.startswith('under'):
        m = _RE_NUM.search(s)
        return ('under', float(m.group())) if m else None
    if s in ('sim', 'yes'):
        return ('sim', 0.0)
    if s in ('não', 'nao', 'no'):
        return ('nao', 0.0)
    if s in ('1x', 'x2', '12'):
        return (s, 0.0)
    try:
        return ('value', float(s))
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────
# SCORE MATRIX (para mercados de resultado)
# ──────────────────────────────────────────────────────────

_MAX_G = 9


def _score_matrix(lh: float, la: float) -> list[list[float]]:
    return [[_pmf(h, lh) * _pmf(a, la) for a in range(_MAX_G)] for h in range(_MAX_G)]


# ──────────────────────────────────────────────────────────
# PROBABILIDADE POR MERCADO
# ──────────────────────────────────────────────────────────

def _prob_for_market(
    mn: str,
    direction: str,
    value: float,
    h: dict,
    a: dict,
) -> float | None:
    """
    Retorna prob_real [0,1] para o mercado dado.
    h = home_stats (contexto HOME): avg_goals_for, avg_goals_against,
        avg_corners_for, avg_corners_against, avg_yellow_for, avg_yellow_against.
    a = away_stats (contexto AWAY): mesmos campos.
    """

    # ── GOLS TOTAIS ───────────────────────────────────────
    if any(k in mn for k in ('gols mais/menos', 'goals over/under', 'total goals')):
        lh = _lam(h.get('avg_goals_for'), a.get('avg_goals_against'))
        la = _lam(a.get('avg_goals_for'), h.get('avg_goals_against'))
        lam = lh + la
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── GOLS CASA (time específico) ───────────────────────
    elif any(k in mn for k in ('total de gols casa', 'total - home', 'gols casa')):
        lam = _lam(h.get('avg_goals_for'), a.get('avg_goals_against'))
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── GOLS VISITANTE (time específico) ──────────────────
    elif any(k in mn for k in ('total de gols visitante', 'total - away', 'gols visitante')):
        lam = _lam(a.get('avg_goals_for'), h.get('avg_goals_against'))
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── BTTS ──────────────────────────────────────────────
    elif any(k in mn for k in ('ambas as equipes', 'both teams score', 'btts')):
        lh = _lam(h.get('avg_goals_for'), a.get('avg_goals_against'))
        la = _lam(a.get('avg_goals_for'), h.get('avg_goals_against'))
        p_h = 1.0 - _pmf(0, lh)
        p_a = 1.0 - _pmf(0, la)
        if direction == 'sim': return p_h * p_a
        if direction == 'nao': return 1.0 - (p_h * p_a)

    # ── ESCANTEIOS TOTAIS ─────────────────────────────────
    elif any(k in mn for k in ('escanteios mais/menos', 'escanteios total', 'corners over/under', 'corners over under')):
        lh = _lam(h.get('avg_corners_for'), a.get('avg_corners_against'))
        la = _lam(a.get('avg_corners_for'), h.get('avg_corners_against'))
        lam = lh + la
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── ESCANTEIOS CASA ───────────────────────────────────
    elif any(k in mn for k in ('escanteios casa', 'home corners')):
        lam = _lam(h.get('avg_corners_for'), a.get('avg_corners_against'))
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── ESCANTEIOS VISITANTE ──────────────────────────────
    elif any(k in mn for k in ('escanteios visitante', 'away corners')):
        lam = _lam(a.get('avg_corners_for'), h.get('avg_corners_against'))
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── CARTÕES TOTAIS ────────────────────────────────────
    elif any(k in mn for k in ('cartões mais/menos', 'cartoes mais/menos', 'cards over/under')):
        lh = _lam(h.get('avg_yellow_for'), a.get('avg_yellow_against'))
        la = _lam(a.get('avg_yellow_for'), h.get('avg_yellow_against'))
        lam = lh + la
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── CARTÕES CASA ──────────────────────────────────────
    elif any(k in mn for k in ('total de cartões casa', 'home team total cards')):
        lam = _lam(h.get('avg_yellow_for'), a.get('avg_yellow_against'))
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── CARTÕES VISITANTE ─────────────────────────────────
    elif any(k in mn for k in ('total de cartões visitante', 'away team total cards')):
        lam = _lam(a.get('avg_yellow_for'), h.get('avg_yellow_against'))
        if direction == 'over':  return _p_over(lam, value)
        if direction == 'under': return _p_under(lam, value)

    # ── DUPLA CHANCE ──────────────────────────────────────
    elif any(k in mn for k in ('dupla chance', 'double chance')):
        lh = _lam(h.get('avg_goals_for'), a.get('avg_goals_against'))
        la = _lam(a.get('avg_goals_for'), h.get('avg_goals_against'))
        mat = _score_matrix(lh, la)
        p_home = sum(mat[hg][ag] for hg in range(_MAX_G) for ag in range(_MAX_G) if hg > ag)
        p_draw  = sum(mat[g][g] for g in range(_MAX_G))
        p_away  = max(0.0, 1.0 - p_home - p_draw)
        if direction == '1x': return p_home + p_draw
        if direction == 'x2': return p_away + p_draw
        if direction == '12': return p_home + p_away

    return None


# ──────────────────────────────────────────────────────────
# FUNÇÃO PRINCIPAL
# ──────────────────────────────────────────────────────────

def enrich_odds_with_poisson(
    odds: list[dict],
    home_stats: dict | None,
    away_stats: dict | None,
) -> list[dict]:
    """
    Adiciona prob_real, implied, edge, ev (calculados por Poisson) a cada odd.
    Odds de mercados não suportados ou sem stats recebem prob_real=None.

    home_stats: stats do mandante no contexto HOME (avg_goals_for, avg_goals_against,
                avg_corners_for, avg_corners_against, avg_yellow_for, avg_yellow_against)
    away_stats: stats do visitante no contexto AWAY — mesmos campos.
    """
    if not home_stats or not away_stats:
        return odds

    h = home_stats
    a = away_stats
    result = []

    for o in odds:
        o = dict(o)
        mn = (o.get('market_name') or o.get('market', '')).lower()
        line_str = str(o.get('line', ''))
        odd_val = float(o.get('odd', 0) or 0)

        parsed = _parse_line(line_str)
        prob = None
        if parsed:
            direction, value = parsed
            try:
                prob = _prob_for_market(mn, direction, value, h, a)
            except Exception:
                prob = None

        if prob is not None and odd_val > 0:
            # cap em 0.93 / 0.07: prob_real extrema (>0.93) indica histórico
            # descontextualizado (ex: Copa com médias de cantos muito baixas).
            # Sem o cap, edge artificial domina e suprime outros mercados.
            capped = max(0.07, min(0.93, prob))
            if capped != prob:
                print(f"[POISSON] prob_real={round(prob,4)} capeada em {capped} ({mn[:40]})")
            prob = capped
            o['prob_real'] = round(prob, 4)
            o['implied']   = round(1.0 / odd_val, 4)
            o['edge']      = round(prob - (1.0 / odd_val), 4)
            o['ev']        = round(prob * odd_val - 1.0, 4)
        else:
            o['prob_real'] = None
            o['implied']   = round(1.0 / odd_val, 4) if odd_val > 0 else None
            o['edge']      = None
            o['ev']        = None

        result.append(o)

    n_enriched = sum(1 for o in result if o.get('prob_real') is not None)
    print(f"[POISSON] {n_enriched}/{len(result)} odds enriquecidas com prob_real")
    return result
