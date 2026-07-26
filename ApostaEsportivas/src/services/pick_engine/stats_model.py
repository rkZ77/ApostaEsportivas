"""Modelo 1 (Dados Estatisticos): taxa de ocorrencia ponderada por
recencia e forca do adversario, feitos x cedidos, classificacao de
mercado, eficiencia ofensiva. Migrado de pick_math_service.py
(feature/pick-math-deterministico), reorganizado em pacote modular."""
import math
from datetime import datetime, date

from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG

_WILSON_Z = 1.96  # 95% de confianca


def wilson_interval(hits: int, n: int, z: float = _WILSON_Z) -> dict | None:
    """Intervalo de confianca de Wilson pra uma proporcao binomial (hits/n)
    -- mais confiavel que Wald em amostra pequena (nao estoura os limites
    0/1, nao fica simetrico artificialmente quando p esta perto de 0 ou 1).
    Usa a contagem BRUTA (nao ponderada) porque a derivacao assume ensaios
    iid -- taxa_ponderada ja incorpora peso de adversario/recencia, misturar
    os dois na mesma formula nao teria interpretacao estatistica limpa.
    None se n=0 (sem amostra, sem intervalo a calcular)."""
    if not n or n <= 0:
        return None
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    lower = round(max(0.0, center - margin), 4)
    upper = round(min(1.0, center + margin), 4)
    return {"lower": lower, "upper": upper, "width": round(upper - lower, 4)}


def temporal_decay_weight(match_date, reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    if isinstance(match_date, str):
        match_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
    if isinstance(match_date, datetime):
        match_date = match_date.date()
    reference_date = reference_date or date.today()
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    days_old = (reference_date - match_date).days
    for max_days, weight in config.temporal_tiers:
        if days_old <= max_days:
            return weight
    return config.temporal_default


def opponent_weight(rank, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    if rank is None:
        return config.opponent_unknown_weight
    if rank <= config.opponent_top_rank:
        return config.opponent_top_weight
    if rank <= config.opponent_mid_rank:
        return config.opponent_mid_weight
    return config.opponent_weak_weight


def sample_quality(n: int, config: PickEngineConfig = DEFAULT_CONFIG) -> dict:
    if n >= config.sample_rich_n:
        return {"label": "RICO", "Q": config.sample_rich_q}
    if n >= config.sample_moderate_n:
        return {"label": "MODERADO", "Q": config.sample_moderate_q}
    if n >= config.sample_scarce_n:
        return {"label": "ESCASSO", "Q": config.sample_scarce_q}
    return {"label": "VAZIO", "Q": config.sample_empty_q}


def weighted_rate(matches: list, hit_fn, reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG) -> dict:
    """Taxa de ocorrencia (0-1) de um evento no historico, ponderada por
    forca do adversario (opponent_weight) e recencia (temporal_decay_weight).

    hit_fn(match) -> valor numerico (0/1 para taxa de ocorrencia, ou um
    float para medias) ja lido no contexto correto (casa/fora) pelo
    chamador, ou None quando o jogo NAO conta pra taxa (push/empate exato
    numa linha redonda -- nem acerto nem erro). Bug real corrigido
    2026-07-25: antes hit_fn nao tinha como sinalizar push, entao um jogo
    empatado na linha (ex.: 10 escanteios numa linha "Under 10") virava
    VITORIA automatica pro lado Under -- a graduacao real (evaluate_asian()
    em ai_result_checker_service.py) sempre tratou esse caso como PUSH,
    entao a taxa historica saia inflada (Under) ou deflacionada (Over)
    exatamente nos jogos que empatavam a linha. amostra abaixo reflete a
    contagem POS-filtro (jogos push nao contam nem a favor da confianca)."""
    scored = [(m, hit_fn(m)) for m in matches]
    counted = [(m, v) for m, v in scored if v is not None]
    n = len(counted)
    quality = sample_quality(n, config)
    if n == 0:
        return {
            "taxa_bruta": None, "taxa_ponderada": None,
            "amostra": 0, "amostra_label": quality["label"], "Q": quality["Q"],
            "wilson": None,
        }

    values = [v for _, v in counted]
    taxa_bruta = sum(values) / n

    weights = [
        opponent_weight(m.get("opponent_rank"), config)
        * temporal_decay_weight(m["match_date"], reference_date, config)
        for m, _ in counted
    ]
    total_weight = sum(weights)
    taxa_ponderada = (
        sum(v * w for v, w in zip(values, weights)) / total_weight
        if total_weight > 0 else taxa_bruta
    )

    return {
        "taxa_bruta": round(taxa_bruta, 4),
        "taxa_ponderada": round(taxa_ponderada, 4),
        "amostra": n,
        "amostra_label": quality["label"],
        "Q": quality["Q"],
        "wilson": wilson_interval(round(sum(values)), n),
    }


_FAMILY_STAT_FIELDS = {
    "goals":    {"total": "total_goals",        "home": "home_goals",        "away": "away_goals"},
    "corners":  {"total": "total_corners",      "home": "home_corners",      "away": "away_corners"},
    "cards":    {"total": "total_yellow_cards", "home": "home_yellow_cards", "away": "away_yellow_cards"},
    # shots/shots_on_target/offsides nao tem coluna "total_X" pronta (so
    # home/away) -- _extract_stat soma os dois quando scope="total".
    # IMPORTANTE: "shots" (chutes totais/tentativas) e "shots_on_target"
    # (chutes NO ALVO) sao familias DIFERENTES com linhas bem diferentes
    # (chutes totais ~20-25/jogo, chutes no alvo ~8-10/jogo) -- misturar
    # os dois faz a taxa parecer quase perfeita (bug real encontrado
    # rodando contra fixture real: "Total ShotOnGoal" caindo na familia
    # errada, taxa saindo 98.7% por comparar chutes-no-alvo com o campo
    # de chutes totais).
    "shots":            {"total": None, "home": "home_total_shots", "away": "away_total_shots"},
    "shots_on_target":  {"total": None, "home": "home_shots_on",    "away": "away_shots_on"},
    "offsides":         {"total": None, "home": "home_offsides",    "away": "away_offsides"},
    # Faltas -- dado ja existia em match_statistics (home_fouls/away_fouls)
    # desde antes, nunca tinha sido ligado ao motor (pedido do usuario
    # 2026-07-26 pra cobrir mercado que a API ja oferece e o dado ja
    # sustenta). Sem coluna "total_X" pronta, mesmo padrao de shots/offsides.
    "fouls":            {"total": None, "home": "home_fouls",      "away": "away_fouls"},
}


def classify_market(market_name: str):
    """Deriva (familia, escopo) do nome (ingles, de odds_service).
    Familias cobertas hoje: goals|corners|cards|btts|shots|shots_on_target|
    offsides (over/under), outcome (1X2), double_chance, draw_no_bet,
    handicap_goals|handicap_corners|handicap_cards, odd_even_goals|
    odd_even_corners, clean_sheet, win_to_nil.

    Fora de escopo (retorna None), por decisao explicita:
    - Mercados de jogador individual (artilheiro, chutes/cartao/assistencia
      do jogador) -- nao existe historico por jogador no sistema hoje
      (existe via API /players, mas exige coletor+tabela novos -- Fase 6).
    - Placar exato/numero de gols exato -- amostra de ~15 jogos nao
      sustenta uma distribuicao de placar confiavel.
    - Mercados de 1o/2o tempo -- o dado (home_goals_ht) existe em
      match_statistics mas a query de historico agregado nao traz isso.
    - Mercados exoticos ainda nao modelados (Corners/Shots 1x2 -- e um
      3-way sobre a contagem, nao sobre o resultado da partida --,
      Winning Margin, Method of Victory, Race To, Highest Scoring Half,
      Game Decided After Penalties/Extra Time, etc.) -- ordem dos checks
      abaixo e do mais especifico pro mais generico; qualquer coisa que
      nao bater cai em None por padrao (nunca advinha).
    - "Handicap Result" (bet_id 9) -- 3-way (Home/Draw/Away com handicap
      aplicado), estrutura diferente do Handicap Asiatico 2-way; achado
      real 2026-07-26, ver comentario na checagem "handicap" abaixo.
    - "Multicorners" (bet_id 249) -- linhas (18.5-29.5+) fora de escala do
      total_corners real de uma partida; produto exato nao documentado
      pela API, exclui por seguranca em vez de advinhar."""
    name = market_name.lower()

    if "handicap" in name:
        if "half" in name:
            return None
        # "Handicap Result" (API bet_id 9) -- achado real 2026-07-26: e' um
        # mercado 3-VIAS (Home/Draw/Away apos aplicar o handicap, ex. "Draw
        # -1", "Home -1"), estrutura DIFERENTE do Handicap Asiatico normal
        # (2-vias, sem opcao de empate). _parse_side_handicap so aceita
        # side em ("home","away","draw") mas compute_taxa descarta "draw"
        # (side not in ("home","away")) silenciosamente, entao so' as
        # selecoes Home/Away sobreviviam, sendo calculadas com a MESMA
        # formula do Handicap Asiatico (handicap_taxa) como se fossem o
        # mesmo produto -- nao sao (odds de um 3-vias refletem a massa de
        # probabilidade que vai pro empate, Handicap Asiatico nao tem essa
        # terceira opcao). Tambem nao tinha traducao PT nenhuma (ia cru pro
        # site). Excluido por ser, na pratica, o exemplo mais direto de
        # "handicap que e' resultado disfarcado" que o usuario ja tinha
        # pedido pra tirar.
        if "result" in name:
            return None
        # "European Handicap" -- achado real 2026-07-26 (varredura completa
        # de mercados): "Corners. European Handicap" TAMBEM tem valores
        # "Draw -1"/"Draw -2" etc (3-way, mesma estrutura de "Handicap
        # Result" acima), diferente de "Corners Asian Handicap" (2-way,
        # sem Draw -- confirmado nos dados reais). O fix de 2026-07-24 so
        # corrigiu o ROTULO em PT (mostrava "Handicap Asiatico" errado pra
        # cartoes/escanteios), nao tinha percebido que European e' uma
        # estrutura de mercado diferente da Asian, nao so' um nome
        # alternativo pra mesma coisa. Exclui pelo mesmo motivo de
        # "Handicap Result".
        if "european" in name:
            return None
        if "corner" in name:
            return ("handicap_corners", "total")
        if "card" in name:
            return ("handicap_cards", "total")
        return ("handicap_goals", "total")

    if "odd/even" in name or "odd or even" in name:
        if "half" in name:
            return None
        if "corner" in name:
            return ("odd_even_corners", "total")
        return ("odd_even_goals", "total")

    if "double chance" in name:
        if "half" in name:
            return None
        return ("double_chance", "total")

    if "draw no bet" in name:
        if "half" in name:
            return None
        return ("draw_no_bet", "total")

    if "clean sheet" in name:
        if "home" in name:
            return ("clean_sheet", "home")
        if "away" in name:
            return ("clean_sheet", "away")
        return None

    if "win to nil" in name:
        return ("win_to_nil", "total")

    if name.strip() in ("match winner", "winner"):
        return ("outcome", "total")

    if "both teams" in name and "score" in name and "half" not in name:
        return ("btts", "total")

    # Guards contra mercados compostos que contem palavra de familia mas
    # nao sao over/under simples (ex: "Corners 1x2", "Corners. Total
    # (Range)", "Corners Race To", "Shots.1x2") -- checa antes dos
    # fallbacks genericos de corner/card/goal/shot abaixo.
    #
    # "between" pega mercados de JANELA DE TEMPO (ex.: "Cards over/under
    # between 0 and 10 m", "Corners. total between 0 and 10m") -- achado
    # real 2026-07-26 na varredura completa: caia no fallback generico de
    # cards/corners (contagem de PARTIDA INTEIRA, media ~4-5 cartoes/~10
    # escanteios) comparado contra um recorte de so' 10 minutos de jogo,
    # escala completamente incompativel (mesma familia de bug do
    # Multicorners). Hoje e' inofensivo na pratica (o value vem "Over"/
    # "Under" sem numero, o parse de linha falha e descarta sozinho) mas
    # fica exposto se a API um dia mandar a linha numerica de verdade --
    # exclui na classificacao pra nao depender desse acidente de formato.
    if any(kw in name for kw in ("1x2", "race to", "range", "3 way", "highest scoring", "between")):
        return None

    # "Multicorners" (API bet_id 249) -- achado real 2026-07-26: linhas de
    # 18.5 ate 29.5+, muito acima do total_corners real de UMA partida
    # (historico gira em ~8-12). Contem "corner" como substring e cairia no
    # fallback generico abaixo, comparando essas linhas absurdas contra o
    # historico normal de escanteios -- qualquer "Under" nessa faixa bateria
    # ~100% das vezes por pura incompatibilidade de escala (nao e' sinal
    # real), mesma classe do bug "chute no alvo vs chute total" ja corrigido
    # antes. Produto exato que "Multicorners" representa nao esta claro nem
    # documentado pela API -- na duvida, exclui em vez de advinhar.
    if "multicorners" in name:
        return None

    if "corner" in name:
        if "half" in name:
            return None
        if "home" in name:
            return ("corners", "home")
        if "away" in name:
            return ("corners", "away")
        return ("corners", "total")

    if "card" in name:
        if "half" in name:
            return None
        if "home" in name:
            return ("cards", "home")
        if "away" in name:
            return ("cards", "away")
        return ("cards", "total")

    if "offside" in name:
        if "home" in name:
            return ("offsides", "home")
        if "away" in name:
            return ("offsides", "away")
        return ("offsides", "total")

    if "foul" in name:
        # "Player Fouls Committed" (Bet365, achado real 2026-07-26 rodando
        # validacao contra fixture real) e' prop por JOGADOR (value_name
        # vira nome de jogador, ex. "Ademir - 1+"), nao total do time --
        # mesmo motivo de exclusao de jogador individual ja documentado no
        # topo desta funcao (shots ja tem o mesmo guard "player not in name").
        if "player" in name or "half" in name:
            return None
        if "home" in name:
            return ("fouls", "home")
        if "away" in name:
            return ("fouls", "away")
        return ("fouls", "total")

    if "shot" in name and "player" not in name and "half" not in name:
        # "Total ShotOnGoal"/"Shot On Target"/"ShotsOnTarget" etc -- variantes
        # com e sem espaco, e com "goal" ou "target" -- sao chutes NO ALVO
        # (linha ~8-10/jogo), MUITO diferente de chutes totais (linha ~20-25).
        # Checa sem espaco nenhum pra pegar "ShotOnGoal" (uma palavra so, o
        # "on goal" com espaco nao bate nessa string e caia no fallback
        # errado -- bug real encontrado com dado de producao).
        name_nospace = name.replace(" ", "")
        if "shotontarget" in name_nospace or "shotongoal" in name_nospace or "shotsontarget" in name_nospace:
            if "home" in name:
                return ("shots_on_target", "home")
            if "away" in name:
                return ("shots_on_target", "away")
            return ("shots_on_target", "total")

        if "target" in name or "on goal" in name:
            return None  # variante nao reconhecida de chute no alvo -- nao adivinha

        if "home" in name:
            return ("shots", "home")
        if "away" in name:
            return ("shots", "away")
        return ("shots", "total")

    if "goal" in name:
        # "Goalkeeper Saves" contem a substring "goal" (de "Goalkeeper"),
        # nao tem nada a ver com o mercado de gols -- mesma classe do bug
        # real ja corrigido pra "Total ShotOnGoal" caindo em "goals" (ver
        # comentario de shots acima). Jogador individual (goleiro, artilheiro
        # etc.) fica fora de escopo por decisao explicita ja documentada no
        # topo desta funcao -- nao ha historico por jogador no sistema hoje.
        if "keeper" in name:
            return None
        if "half" in name or "method" in name or "scorer" in name or "exact" in name or "number of" in name:
            return None
        if "home" in name:
            return ("goals", "home")
        if "away" in name:
            return ("goals", "away")
        return ("goals", "total")

    return None


def _cards_points(m: dict, scope: str) -> float:
    """Pontuacao de cartoes de uma partida: amarelo vale 1, vermelho vale 2
    -- mesma convencao que ai_result_checker_service.py ja usa pra gradear
    o resultado real (e convencao padrao de mercado "Total de Cartoes" nas
    casas de aposta). Bug real corrigido 2026-07-25: _FAMILY_STAT_FIELDS
    ["cards"] apontava so pra total_yellow_cards, entao a taxa historica
    NUNCA via cartao vermelho -- picks de "Cartoes Under" saiam com taxa
    inflada (rodando o motor contra dados reais: taxa "real" de 69% pra
    Under 5.5 que, contando vermelho como o jogo de verdade conta, era na
    prática ~40-50%)."""
    if scope == "home":
        return (m.get("home_yellow_cards") or 0) + 2 * (m.get("home_red_cards") or 0)
    if scope == "away":
        return (m.get("away_yellow_cards") or 0) + 2 * (m.get("away_red_cards") or 0)
    return (
        (m.get("home_yellow_cards") or 0) + (m.get("away_yellow_cards") or 0)
        + 2 * ((m.get("home_red_cards") or 0) + (m.get("away_red_cards") or 0))
    )


def _extract_stat(m: dict, family: str, scope: str):
    """Le o valor real de uma familia/escopo num jogo historico, somando
    home+away quando a familia nao tem coluna 'total_X' pronta
    (shots/offsides)."""
    if family == "cards":
        return _cards_points(m, scope)
    fields = _FAMILY_STAT_FIELDS[family]
    if scope in ("home", "away"):
        return m.get(fields[scope]) or 0
    total_field = fields.get("total")
    if total_field:
        return m.get(total_field) or 0
    return (m.get(fields["home"]) or 0) + (m.get(fields["away"]) or 0)


def pool_and_field(family: str, scope: str, last10_home: list, last10_away: list):
    if family == "btts":
        return last10_home + last10_away, None
    if scope == "home":
        return last10_home, None
    if scope == "away":
        return last10_away, None
    return last10_home + last10_away, None


def _build_market_hit_fn(family: str, scope: str, value: str, line_str: str):
    """Constroi o hit_fn (jogo -> 0/1) pra um mercado 'classico' (over/under
    ou btts) -- extraido de market_taxa() pra ser reaproveitado por
    line_stability() sem duplicar a logica de parsing/validacao de
    value/line. Retorna None se o value/line nao forem reconhecidos
    (mesmos casos que market_taxa ja rejeitava)."""
    direction = (value or "").strip().lower()

    if family == "btts":
        if direction not in ("yes", "sim", "no", "não", "nao"):
            return None
        want_btts = direction in ("yes", "sim")

        def hit_fn(m):
            occurred = (m.get("home_goals") or 0) > 0 and (m.get("away_goals") or 0) > 0
            return 1 if occurred == want_btts else 0

        return hit_fn

    if direction not in ("over", "under"):
        return None
    try:
        line_val = float(line_str)
    except (TypeError, ValueError):
        return None
    # Linha de quarto (.25/.75, ex: "Goal Line" Over 1.25/1.75 -- variante
    # asiatica de over/under total) -- mesmo problema ja corrigido em
    # handicap_taxa: e' uma aposta dividida em 2 metades com resultado
    # possivel de win/push/loss por metade que esta comparacao binaria (`>`)
    # nao modela direito. Aqui o sinal costuma sair certo (nao vira "vitoria
    # disfarcada de resultado" como no caso do handicap +0.25), mas a
    # MAGNITUDE fica imprecisa (conta meia-vitoria/meia-derrota como
    # inteira) -- consistente excluir aqui tambem em vez de sustentar taxa
    # aproximada com confidence que assume precisao exata.
    if round(abs(line_val) % 1, 2) in (0.25, 0.75):
        return None
    is_over = direction == "over"
    is_round_line = line_val % 1 == 0

    def hit_fn(m):
        stat = _extract_stat(m, family, scope)
        # linha redonda (sem .5) e stat bate exato -- PUSH na graduacao
        # real (evaluate_asian), nao conta nem a favor nem contra aqui.
        if is_round_line and stat == line_val:
            return None
        over = 1 if stat > line_val else 0
        return over if is_over else 1 - over

    return hit_fn


def market_taxa(family: str, scope: str, value: str, line_str: str,
                last10_home: list, last10_away: list, reference_date=None,
                config: PickEngineConfig = DEFAULT_CONFIG):
    """Over/under (gols/escanteios/cartoes/chutes/impedimentos) e ambas
    marcam (btts) -- os mercados 'classicos' ja existiam desde a Fase 1.
    Mercados novos (1X2/handicap/dupla-chance/etc) tem funcoes proprias
    abaixo (outcome_taxa, handicap_taxa, ...), despachadas pelo
    orchestrator via classify_market()."""
    pool, _ = pool_and_field(family, scope, last10_home, last10_away)
    if not pool:
        return None

    hit_fn = _build_market_hit_fn(family, scope, value, line_str)
    if hit_fn is None:
        return None

    return weighted_rate(pool, hit_fn, reference_date=reference_date, config=config)


_MIN_MATCHES_PER_HALF_STABILITY = 2


def line_stability(family: str, scope: str, value: str, line_str: str,
                    last10_home: list, last10_away: list) -> dict | None:
    """Compara a taxa BRUTA (nao ponderada) da linha na metade mais
    recente do historico vs a metade mais antiga -- diferente da media
    agregada (que pode esconder uma linha que so comecou a bater
    recentemente, ou que parou de bater e a media agregada ainda nao
    refletiu isso). Divergencia grande = padrao instavel/recente demais
    pra confiar tanto quanto a taxa agregada sugere.

    So cobre mercados 'classicos' (over/under/btts, mesmo escopo de
    market_taxa) -- amostra minima de 2 jogos por metade (4 no total),
    senao a comparacao vira ruido puro. None quando nao aplicavel."""
    pool, _ = pool_and_field(family, scope, last10_home, last10_away)
    if not pool or len(pool) < _MIN_MATCHES_PER_HALF_STABILITY * 2:
        return None

    hit_fn = _build_market_hit_fn(family, scope, value, line_str)
    if hit_fn is None:
        return None

    def _match_date(m):
        d = m.get("match_date")
        if isinstance(d, str):
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        return d or datetime.min

    sorted_pool = sorted(pool, key=_match_date, reverse=True)
    mid = len(sorted_pool) // 2
    recent_half, older_half = sorted_pool[:mid], sorted_pool[mid:]

    def _half_rate(half):
        # hit_fn pode devolver None (push/empate exato em linha redonda) --
        # mesmo tratamento de weighted_rate, exclui da amostra em vez de
        # contar como acerto ou erro.
        vals = [v for v in (hit_fn(m) for m in half) if v is not None]
        return sum(vals) / len(vals) if vals else None

    recent_rate = _half_rate(recent_half)
    older_rate = _half_rate(older_half)
    if recent_rate is None or older_rate is None:
        return None
    instability = round(abs(recent_rate - older_rate), 4)

    return {
        "recent_rate": round(recent_rate, 4),
        "older_rate": round(older_rate, 4),
        "instability": instability,
        "recent_n": len(recent_half),
        "older_n": len(older_half),
    }


def _combine_two_estimates(rate_a: dict, rate_b: dict, config: PickEngineConfig = DEFAULT_CONFIG):
    """Combina duas estimativas independentes de weighted_rate() (mesmo
    espirito de expected_value_convergence: duas leituras do historico,
    uma por lado, combinadas por media -- soma a amostra de ambas pra Q)."""
    a = rate_a.get("taxa_ponderada") if rate_a else None
    b = rate_b.get("taxa_ponderada") if rate_b else None
    if a is None and b is None:
        return None
    combined = b if a is None else (a if b is None else (a + b) / 2)
    amostra = (rate_a.get("amostra", 0) if rate_a else 0) + (rate_b.get("amostra", 0) if rate_b else 0)
    quality = sample_quality(amostra, config)
    return {
        "taxa_bruta": round(combined, 4),
        "taxa_ponderada": round(combined, 4),
        "amostra": amostra,
        "amostra_label": quality["label"],
        "Q": quality["Q"],
    }


def outcome_taxa(last10_home: list, last10_away: list, outcome: str,
                  reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG):
    """Taxa ponderada do resultado 1X2 (outcome='home'/'draw'/'away').
    Mesmo hit_fn aplicado a last10_home (jogos do mandante atual em casa)
    e last10_away (jogos do visitante atual fora) -- em AMBOS os pools,
    'home_goals'/'away_goals' se referem ao lado casa/fora DAQUELE jogo
    historico especifico, entao o mesmo hit_fn mede coisas diferentes mas
    complementares: no pool casa, a propria tendencia do mandante atual;
    no pool fora, a tendencia do adversario historico do visitante atual
    (evidencia indireta, mesmo estilo de expected_value_convergence)."""
    if outcome not in ("home", "draw", "away"):
        return None

    def hit_fn(m):
        h, a = m.get("home_goals") or 0, m.get("away_goals") or 0
        if outcome == "home":
            return 1 if h > a else 0
        if outcome == "draw":
            return 1 if h == a else 0
        return 1 if h < a else 0

    rate_home = weighted_rate(last10_home, hit_fn, reference_date, config)
    rate_away = weighted_rate(last10_away, hit_fn, reference_date, config)
    return _combine_two_estimates(rate_home, rate_away, config)


_DOUBLE_CHANCE_COMBOS = {
    "home_draw": ("home", "draw"),
    "draw_away": ("draw", "away"),
    "home_away": ("home", "away"),
}


def double_chance_taxa(last10_home: list, last10_away: list, combo: str,
                        reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG):
    """P(A ou B) = P(A)+P(B) -- resultados mutuamente exclusivos, soma
    direta e exata (nao e aproximacao), reaproveitando outcome_taxa."""
    pair = _DOUBLE_CHANCE_COMBOS.get(combo)
    if not pair:
        return None
    r1 = outcome_taxa(last10_home, last10_away, pair[0], reference_date, config)
    r2 = outcome_taxa(last10_home, last10_away, pair[1], reference_date, config)
    if not r1 or not r2:
        return None
    combined = min(r1["taxa_ponderada"] + r2["taxa_ponderada"], 1.0)
    amostra = max(r1["amostra"], r2["amostra"])
    quality = sample_quality(amostra, config)
    return {"taxa_bruta": round(combined, 4), "taxa_ponderada": round(combined, 4),
            "amostra": amostra, "amostra_label": quality["label"], "Q": quality["Q"]}


def draw_no_bet_taxa(last10_home: list, last10_away: list, side: str,
                      reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG):
    """side='home'/'away' -- taxa condicionada a nao-empate (remove
    empate do universo, renormaliza win/loss entre as duas opcoes)."""
    if side not in ("home", "away"):
        return None
    r_home = outcome_taxa(last10_home, last10_away, "home", reference_date, config)
    r_away = outcome_taxa(last10_home, last10_away, "away", reference_date, config)
    if not r_home or not r_away:
        return None
    total = r_home["taxa_ponderada"] + r_away["taxa_ponderada"]
    if total <= 0:
        return None
    taxa = r_home["taxa_ponderada"] / total if side == "home" else r_away["taxa_ponderada"] / total
    amostra = max(r_home["amostra"], r_away["amostra"])
    quality = sample_quality(amostra, config)
    return {"taxa_bruta": round(taxa, 4), "taxa_ponderada": round(taxa, 4),
            "amostra": amostra, "amostra_label": quality["label"], "Q": quality["Q"]}


def handicap_taxa(family: str, side: str, handicap: float, last10_home: list, last10_away: list,
                   reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG):
    """side='home'/'away' com handicap aplicado (ex: 'Home -1' cobre se
    home_stat-1 > away_stat, i.e. mandante vence por 2+). Aplica ao valor
    real de cada jogo historico (gols/escanteios/cartoes -- so troca o
    field) e combina os dois pools do mesmo jeito de outcome_taxa: o
    mesmo hit_fn mede, no pool casa, a tendencia do mandante atual, e no
    pool fora, a tendencia do adversario historico do visitante atual.

    Linha de QUARTO de gol (.25/.75, ex: 'Home +0.25') fica de fora --
    bug real encontrado em producao (2026-07-26): handicap de quarto e' na
    verdade uma aposta dividida em 2 metades (ex: +0.25 = metade da banca
    em +0 e metade em +0.5), com resultados possiveis de win/push/loss por
    metade que este hit_fn binario (`>`) nao modela. Pra +0.25 especifico,
    um EMPATE conta como HIT TOTAL (0+0.25 > 0), o que faz a taxa medir
    literalmente "mandante nao perde" -- mesmo criterio de draw_no_bet/
    double_chance 1X, que ja foi excluido do pool por ser mercado de
    resultado (_RESULT_FAMILIES em orchestrator.py). Era por isso que a
    mesma linha 'Home +0.25' vencia em quase toda fixture (Remo, Londrina,
    Gremio, Sao Bernardo, Bahia no mesmo dia): nao estava testando margem
    de gols, estava testando resultado disfarcado de handicap. Linha
    inteira/.5 nao tem esse problema (.5 nunca empata na linha; linha
    inteira tem push real no empate exato, mas o hit_fn conta como MISS,
    nao como hit -- vies pra baixo, conhecido e nao corrigido aqui por ser
    bem mais raro que o caso .25/.75 e nao inflar taxa).

    MAS pra family='goals' especificamente, handicap=+-0.5 tem um problema
    DIFERENTE, achado real 2026-07-26 (usuario percebeu direto no pick de
    Gremio x Fluminense): 'Home +0.5' e' matematicamente IDENTICO a Dupla
    Chance 1X (home_gols+0.5>away_gols equivale a home nao perder -- testado
    contra toda combinacao de placar 0-5 x 0-5, zero divergencia), e 'Home
    -0.5' e' identico a Resultado Final Casa (1X2). Nao e' aproximacao, e'
    a MESMA aposta com nome de handicap -- exatamente o mercado de
    resultado que _RESULT_FAMILIES ja exclui, so' que disfarçado. So' a
    partir de +-1.0 o handicap de gols vira aposta genuina de margem (ex.:
    +1.5 tambem cobre "perde por so 1", que nao existe em nenhum mercado de
    resultado simples). Escanteios/cartoes NAO tem esse problema (nao existe
    "1X2 de escanteios" banido pra duplicar), entao so' exclui pra 'goals'."""
    if side not in ("home", "away"):
        return None
    if round(abs(handicap) % 1, 2) in (0.25, 0.75):
        return None
    if family == "goals" and round(abs(handicap), 2) == 0.5:
        return None

    if family == "cards":
        # Cartoes usa _cards_points (amarelo=1, vermelho=2) em vez do campo
        # bruto do dict -- mesmo motivo de _extract_stat acima, esta funcao
        # NAO passava por ali (lia home_f/away_f direto), entao o bug de
        # ignorar vermelho continuava valendo pra handicap_cards mesmo
        # depois do fix em _extract_stat.
        def hit_fn(m):
            h = _cards_points(m, "home")
            a = _cards_points(m, "away")
            if side == "home":
                return 1 if (h + handicap) > a else 0
            return 1 if (a + handicap) > h else 0
    else:
        if family not in _FAMILY_STAT_FIELDS:
            return None
        fields = _FAMILY_STAT_FIELDS[family]
        home_f, away_f = fields["home"], fields["away"]
        if not home_f or not away_f:
            return None

        def hit_fn(m):
            h = m.get(home_f) or 0
            a = m.get(away_f) or 0
            if side == "home":
                return 1 if (h + handicap) > a else 0
            return 1 if (a + handicap) > h else 0

    rate_home = weighted_rate(last10_home, hit_fn, reference_date, config)
    rate_away = weighted_rate(last10_away, hit_fn, reference_date, config)
    return _combine_two_estimates(rate_home, rate_away, config)


def odd_even_taxa(family: str, want: str, last10_home: list, last10_away: list,
                   reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG):
    """want='odd'/'even' -- paridade do total da familia (gols/escanteios)."""
    if family not in _FAMILY_STAT_FIELDS or want not in ("odd", "even"):
        return None
    pool = last10_home + last10_away
    if not pool:
        return None
    want_odd = want == "odd"

    def hit_fn(m):
        stat = _extract_stat(m, family, "total")
        is_odd = int(stat) % 2 == 1
        return 1 if is_odd == want_odd else 0

    return weighted_rate(pool, hit_fn, reference_date=reference_date, config=config)


def clean_sheet_taxa(side: str, last10_home: list, last10_away: list,
                      reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG):
    """side='home'/'away' -- taxa ponderada de terminar sem sofrer gol,
    no proprio contexto (casa/fora) do time. Mesmo conceito de
    team_profile_model.py::defensive_stats, exposto como taxa ponderada
    (nao media simples) pra alimentar o motor de picks."""
    if side not in ("home", "away"):
        return None
    pool = last10_home if side == "home" else last10_away
    against_f = "away_goals" if side == "home" else "home_goals"

    def hit_fn(m):
        return 1 if (m.get(against_f) or 0) == 0 else 0

    return weighted_rate(pool, hit_fn, reference_date=reference_date, config=config)


def win_to_nil_taxa(side: str, last10_home: list, last10_away: list,
                     reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG):
    """side='home'/'away' -- vence E nao sofre gol."""
    if side not in ("home", "away"):
        return None
    pool = last10_home if side == "home" else last10_away
    for_f = "home_goals" if side == "home" else "away_goals"
    against_f = "away_goals" if side == "home" else "home_goals"

    def hit_fn(m):
        scored = m.get(for_f) or 0
        conceded = m.get(against_f) or 0
        return 1 if (scored > conceded and conceded == 0) else 0

    return weighted_rate(pool, hit_fn, reference_date=reference_date, config=config)


def _parse_side_handicap(value: str):
    """Parseia 'Home -1', 'Away +0.25', 'Draw -3' -> (side, handicap).
    side em minusculo. Retorna (None, None) se nao reconhecer o formato."""
    if not value:
        return None, None
    parts = value.strip().split()
    if len(parts) < 2:
        return None, None
    side = parts[0].strip().lower()
    if side not in ("home", "away", "draw"):
        return None, None
    try:
        handicap = float(parts[1].replace("+", ""))
    except ValueError:
        return None, None
    return side, handicap


_DOUBLE_CHANCE_VALUE_MAP = {
    "home/draw": "home_draw", "draw/home": "home_draw",
    "draw/away": "draw_away", "away/draw": "draw_away",
    "home/away": "home_away", "away/home": "home_away",
}


def compute_taxa(family: str, scope: str, value: str, line_str: str,
                  last10_home: list, last10_away: list, reference_date=None,
                  config: PickEngineConfig = DEFAULT_CONFIG):
    """Ponto de entrada unico do Modelo 1 -- despacha pra funcao de taxa
    certa conforme a familia (classify_market() ja devolveu family/scope).
    Mercados 'classicos' (goals/corners/cards/btts/shots/shots_on_target/
    offsides) usam market_taxa() (over/under ou yes/no); os demais tem
    parsing de value proprio (3-way, side+handicap, odd/even)."""
    direction = (value or "").strip().lower()

    if family in ("goals", "corners", "cards", "btts", "shots", "shots_on_target", "offsides", "fouls"):
        return market_taxa(family, scope, value, line_str, last10_home, last10_away, reference_date, config)

    if family == "outcome":
        if direction not in ("home", "draw", "away"):
            return None
        return outcome_taxa(last10_home, last10_away, direction, reference_date, config)

    if family == "double_chance":
        combo = _DOUBLE_CHANCE_VALUE_MAP.get(direction)
        if not combo:
            return None
        return double_chance_taxa(last10_home, last10_away, combo, reference_date, config)

    if family == "draw_no_bet":
        if direction not in ("home", "away"):
            return None
        return draw_no_bet_taxa(last10_home, last10_away, direction, reference_date, config)

    if family in ("handicap_goals", "handicap_corners", "handicap_cards"):
        side, handicap = _parse_side_handicap(value)
        if side not in ("home", "away") or handicap is None:
            return None
        base_family = family.replace("handicap_", "")
        return handicap_taxa(base_family, side, handicap, last10_home, last10_away, reference_date, config)

    if family in ("odd_even_goals", "odd_even_corners"):
        if direction not in ("odd", "even"):
            return None
        base_family = family.replace("odd_even_", "")
        return odd_even_taxa(base_family, direction, last10_home, last10_away, reference_date, config)

    if family == "clean_sheet":
        if direction not in ("yes", "sim", "no", "não", "nao"):
            return None
        taxa = clean_sheet_taxa(scope, last10_home, last10_away, reference_date, config)
        if not taxa or taxa["taxa_ponderada"] is None:
            return None
        want_yes = direction in ("yes", "sim")
        if want_yes:
            return taxa
        # "No" (nao faz clean sheet) -- inverte a taxa ponderada
        inverted = dict(taxa)
        inverted["taxa_bruta"] = round(1 - taxa["taxa_bruta"], 4)
        inverted["taxa_ponderada"] = round(1 - taxa["taxa_ponderada"], 4)
        return inverted

    if family == "win_to_nil":
        if direction not in ("home", "away"):
            return None
        return win_to_nil_taxa(direction, last10_home, last10_away, reference_date, config)

    return None


_SCORED_CONCEDED_FIELDS = {
    "goals":   ("home_goals", "away_goals"),
    "corners": ("home_corners", "away_corners"),
    "cards":   ("home_yellow_cards", "away_yellow_cards"),
    "fouls":   ("home_fouls", "away_fouls"),
}


def scored_conceded_avg(matches: list, is_home_ctx: bool, family: str):
    """Media do que o time FAZ (feitos) e do que CEDE (cedidos) no
    historico, no contexto correto (casa/fora). Base da validacao
    feitos-vs-cedidos: toda estimativa de total precisa ser validada
    cruzando feitos de um lado com cedidos do outro, nao so olhar se
    jogos passados bateram a linha."""
    if not matches or family not in _SCORED_CONCEDED_FIELDS:
        return None, None
    n = len(matches)
    if family == "cards":
        # amarelo=1, vermelho=2 (ver _cards_points) -- mesma correcao do
        # bug de vermelho ignorado, aqui pro sinal de convergencia feitos
        # x cedidos em vez da taxa em si.
        scored_side, conceded_side = ("home", "away") if is_home_ctx else ("away", "home")
        scored = sum(_cards_points(m, scored_side) for m in matches) / n
        conceded = sum(_cards_points(m, conceded_side) for m in matches) / n
        return round(scored, 3), round(conceded, 3)
    home_f, away_f = _SCORED_CONCEDED_FIELDS[family]
    scored_k, conceded_k = (home_f, away_f) if is_home_ctx else (away_f, home_f)
    scored = sum((m.get(scored_k) or 0) for m in matches) / n
    conceded = sum((m.get(conceded_k) or 0) for m in matches) / n
    return round(scored, 3), round(conceded, 3)


def expected_value_convergence(last10_home: list, last10_away: list, family: str, scope: str):
    """Duas estimativas independentes do valor esperado para a partida,
    uma pelo que cada time costuma FAZER, outra pelo que costuma CEDER --
    se convergem (<=15% de diferenca), e sinal forte; se divergem, e
    motivo pra desconfiar do mercado, nao so olhar taxa historica isolada.

    scope='total' (ex. Gols Mais/Menos): feitos_casa+feitos_fora vs
      cedidos_casa+cedidos_fora.
    scope='home' (ex. Total de Gols Casa): feitos do mandante vs cedidos
      do visitante fora (o adversario especifico deste jogo).
    scope='away': feitos do visitante fora vs cedidos do mandante em casa.
    """
    if family not in _SCORED_CONCEDED_FIELDS:
        return None

    h_scored, h_conceded = scored_conceded_avg(last10_home, True, family)
    a_scored, a_conceded = scored_conceded_avg(last10_away, False, family)
    if None in (h_scored, h_conceded, a_scored, a_conceded):
        return None

    if scope == "home":
        estimate_feitos, estimate_cedidos = h_scored, a_conceded
    elif scope == "away":
        estimate_feitos, estimate_cedidos = a_scored, h_conceded
    else:
        estimate_feitos, estimate_cedidos = h_scored + a_scored, h_conceded + a_conceded

    base = max(abs(estimate_feitos), abs(estimate_cedidos), 0.01)
    diff_pct = abs(estimate_feitos - estimate_cedidos) / base

    return {
        "estimate_feitos":   round(estimate_feitos, 2),
        "estimate_cedidos":  round(estimate_cedidos, 2),
        "expected_value":    round((estimate_feitos + estimate_cedidos) / 2, 2),
        "converged":         diff_pct <= 0.15,
        "diff_pct":          round(diff_pct, 3),
    }


def offensive_efficiency(matches: list, team_id: int) -> dict | None:
    """Eficiencia ofensiva usando chutes no alvo e posse (dados que ja
    existem no banco -- match_statistics.home_shots_on/home_possession).
    Mede QUALIDADE de finalizacao (gols por chute-no-alvo), nao QUANTIDADE
    de gols -- sinal mais independente da taxa historica de gols do que
    uma segunda media de gols/jogo seria (usado por
    team_profile_model.compare_matchup() no lugar de combined_goals_avg,
    ver Prioridade 1.3 do plano de refatoracao).

    Contexto (casa/fora) resolvido POR PARTIDA via home_team_id==team_id --
    correto tanto para pool de um so lado (clubes) quanto pool de mando
    misto (selecoes, sede neutra). Antes recebia um unico is_home_ctx pra
    lista inteira -- bug real: em mando misto isso lia o campo errado
    (home_shots_on de um jogo onde o time era visitante, por exemplo) pra
    parte dos jogos. Nunca foi chamada em producao com esse bug (funcao
    nao estava conectada a nada), corrigido antes de conectar."""
    if not matches:
        return None

    with_shots = [
        m for m in matches
        if m.get("home_shots_on" if m.get("home_team_id") == team_id else "away_shots_on") is not None
    ]
    if not with_shots:
        return None

    n = total_shots_on = total_goals = 0
    total_possession = possession_n = 0
    for m in with_shots:
        is_home = m.get("home_team_id") == team_id
        # float() defensivo -- coluna do banco pode chegar como Decimal
        # (psycopg2, NUMERIC) em vez de int/float puro; misturar Decimal com
        # float mais adiante (ex.: goals_delta em team_profile_model.compare_matchup)
        # estoura TypeError (bug real de producao ja visto em referee_model.py).
        shots_on = float(m.get("home_shots_on" if is_home else "away_shots_on") or 0)
        goals = float(m.get("home_goals" if is_home else "away_goals") or 0)
        possession = m.get("home_possession" if is_home else "away_possession")
        total_shots_on += shots_on
        total_goals += goals
        n += 1
        if possession is not None:
            total_possession += float(possession)
            possession_n += 1

    avg_shots_on = round(total_shots_on / n, 2)
    conversion = round(total_goals / total_shots_on, 3) if total_shots_on > 0 else None
    avg_possession = round(total_possession / possession_n, 1) if possession_n else None

    return {
        "amostra": n,
        "avg_shots_on_target": avg_shots_on,
        "conversion_rate": conversion,
        "avg_possession": avg_possession,
    }
