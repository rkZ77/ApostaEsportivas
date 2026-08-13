"""Modelo 1 (Dados Estatisticos): taxa de ocorrencia ponderada por
recencia e forca do adversario, feitos x cedidos, classificacao de
mercado, eficiencia ofensiva. Migrado de pick_math_service.py
(feature/pick-math-deterministico), reorganizado em pacote modular."""
import math
from datetime import datetime, date

from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG
from services.pick_engine.competition_profile import cross_competition_weight

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

    # Terceiro fator (2026-08-13): a competicao de ORIGEM do jogo. Um 4x0 na
    # Copa do Brasil contra time de divisao inferior nao descreve o mesmo time
    # que um 4x0 no Brasileirao, e o historico de copa MISTURA os dois -- sem
    # este peso, abrir o historico pra todas as competicoes trocava "amostra
    # pequena" por "amostra enviesada". O peso ja estava definido em
    # competition_profile._CROSS_COMPETITION_WEIGHT desde 2026-08-01, com o
    # comentario dizendo que faltava conectar; era isto.
    #
    # Historico de UMA liga so (fixture de pontos corridos) fica intacto de
    # proposito: todos os jogos vem da mesma competicao, entao o fator e
    # constante e some na divisao de taxa_ponderada (media ponderada normaliza
    # pelo total). Nao e' um caso especial escrito a mao -- e' consequencia
    # aritmetica, e ha teste travando isso.
    weights = [
        opponent_weight(m.get("opponent_rank"), config)
        * temporal_decay_weight(m["match_date"], reference_date, config)
        * cross_competition_weight(m.get("league_id"))
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
    # Defesas de goleiro (2026-08-01). ATENCAO AO LADO: home_goalkeeper_saves
    # sao as defesas do goleiro DA CASA, feitas contra os chutes do VISITANTE.
    # A relacao e' quase mecanica -- defesas = 0.678 x chutes no alvo sofridos,
    # correlacao 0.88 medida em 1892 atuacoes -- entao quem prediz defesa do
    # mandante e' o volume ofensivo do adversario, nao o do proprio time.
    # Ver services/pick_engine/goalkeeper_model.py.
    "saves":            {"total": None, "home": "home_goalkeeper_saves", "away": "away_goalkeeper_saves"},
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

    # Defesas de goleiro: FORA DE ESCOPO do motor de mercado de time.
    #
    # Eu tinha classificado como familia de time ("saves", total/home/away)
    # em 2026-08-01, assumindo over/under de equipe. A primeira coleta real
    # com jogo da Copa do Brasil desmentiu: a Betano manda bet_id 267
    # "Goalkeeper Saves" como PROP DE JOGADOR, com value_name no formato
    # "<nome do goleiro> - <N>" ("Everson - 1", "Leo Jardim - 3"), ou seja
    # "N ou mais defesas DESSE goleiro" -- nao existe linha de time ali.
    #
    # Na pratica o motor ja descartava, porque "Everson - 1" nao parseia como
    # over/under; mas descartava por acidente de parse, nao por decisao. Aqui
    # vira explicito, mesmo tratamento que "Player Fouls Committed" ja tinha.
    #
    # O caminho certo pra esse mercado NAO e' este: e' dado por jogador
    # (player_match_stats.saves, tabela criada em 2026-08-01) somado ao
    # goalkeeper_model, que ja estima P(defesas > linha) por Binomial
    # Negativa. Enquanto isso nao existir como pipeline, melhor nao gerar
    # candidato nenhum do que gerar em cima de campo de time que nao
    # corresponde ao que a casa esta oferecendo.
    #
    # 268/274 (Home/Away Goalkeeper Saves) e 315/318/319 (Saves Total, O/U)
    # nao apareceram em nenhuma das 3 fixtures coletadas -- pode ser que
    # sejam de time, mas nao da pra afirmar sem ver. Ficam de fora junto.
    if "save" in name or "goalkeeper" in name:
        return None

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


def resolve_side(m: dict, scope: str, team_id: int | None) -> str:
    """Coluna ('home'/'away') que guarda a estatistica DO TIME analisado
    naquela partida especifica.

    `scope` diz QUAL time interessa (o mandante ou o visitante DESTE jogo,
    que define de qual historico o pool veio); `team_id` diz onde ele estava
    NAQUELA partida do historico. Sem team_id devolve o proprio scope --
    comportamento antigo, correto so' quando todos os jogos do pool tem o
    mesmo mando.

    Bug real corrigido 2026-08-05: MatchStatsService.get_all_matches_full()
    filtra por `(home_team_id = X OR away_team_id = X)`, ou seja devolve os
    15 jogos do time MISTURANDO casa e fora. _extract_stat() lia o campo
    fixo do scope (`home_corners` pra scope='home') em TODOS eles, entao nos
    jogos em que o time foi visitante a taxa contava os escanteios/cartoes/
    gols DO ADVERSARIO como se fossem dele. Metade da amostra vinha do time
    errado em todo mercado de escopo home/away ("Home Corners Over/Under",
    "Home Team Total Goals", "Away Team Total Cards", ...).

    E' exatamente o mesmo bug que scored_conceded_avg() e
    offensive_efficiency() ja tinham corrigido cada uma por conta propria
    (ver docstrings de la') e que nunca tinha sido propagado ate' a taxa em
    si -- que e' o numero que vira edge, EV e pick."""
    if scope not in ("home", "away") or team_id is None:
        return scope
    return "home" if m.get("home_team_id") == team_id else "away"


def scope_team_id(scope: str, home_team_id: int | None, away_team_id: int | None):
    """team_id do lado que o escopo do mercado aponta -- scope='home' e o
    MANDANTE do jogo analisado, scope='away' o visitante. None pra
    scope='total' (a leitura e' do jogo inteiro, nao de um time)."""
    if scope == "home":
        return home_team_id
    if scope == "away":
        return away_team_id
    return None


def _cards_points(m: dict, scope: str, team_id: int | None = None) -> float:
    """Pontuacao de cartoes de uma partida: amarelo vale 1, vermelho vale 2
    -- mesma convencao que ai_result_checker_service.py ja usa pra gradear
    o resultado real (e convencao padrao de mercado "Total de Cartoes" nas
    casas de aposta). Bug real corrigido 2026-07-25: _FAMILY_STAT_FIELDS
    ["cards"] apontava so pra total_yellow_cards, entao a taxa historica
    NUNCA via cartao vermelho -- picks de "Cartoes Under" saiam com taxa
    inflada (rodando o motor contra dados reais: taxa "real" de 69% pra
    Under 5.5 que, contando vermelho como o jogo de verdade conta, era na
    prática ~40-50%).

    `team_id` resolve o mando POR PARTIDA -- ver resolve_side()."""
    side = resolve_side(m, scope, team_id)
    if side == "home":
        return (m.get("home_yellow_cards") or 0) + 2 * (m.get("home_red_cards") or 0)
    if side == "away":
        return (m.get("away_yellow_cards") or 0) + 2 * (m.get("away_red_cards") or 0)
    return (
        (m.get("home_yellow_cards") or 0) + (m.get("away_yellow_cards") or 0)
        + 2 * ((m.get("home_red_cards") or 0) + (m.get("away_red_cards") or 0))
    )


#: Status de jogo decidido fora dos 90 minutos.
PRORROGACAO = ("AET", "PEN")


def gols_90(m: dict, lado: str) -> int:
    """Gols do lado no tempo REGULAMENTAR.

    `home_goals`/`away_goals` da API-Football sao o placar do JOGO INTEIRO: num
    jogo decidido na prorrogacao eles ja incluem o tempo extra (caso real no
    repositorio: Belgium x Senegal, goals 3x2 com score.fulltime 2x2). Casa de
    aposta liquida Over/Under e BTTS pelos 90 minutos, entao ler a coluna cheia
    contaria gol que nao existe pro mercado.

    Jogo normal nao tem `_90` preenchido (a coluna nasceu depois), e ai o
    placar cheio E' o de 90 minutos -- por isso o fallback, e nao um erro.
    """
    valor = m.get(f"{lado}_goals_90")
    if valor is None:
        valor = m.get(f"{lado}_goals")
    return int(valor or 0)


def comparavel_em_90(pool: list, family: str) -> list:
    """Tira do pool o jogo cujo contador desta familia nao cabe em 90 minutos.

    A folha de estatistica de um AET cobre os 120 minutos jogados: escanteios,
    cartoes, faltas e chutes vem inflados em cerca de um terco de tempo extra, e
    NAO ha coluna de 90 minutos pra eles. Manter esses jogos empurraria a taxa
    de Over pra cima usando jogo que a casa liquidou noutro placar.

    Gols e BTTS ficam, porque tem `home_goals_90`/`away_goals_90` (ver
    gols_90) -- e sao justamente as familias que mais precisam do jogo de
    mata-mata, que e' onde a prorrogacao acontece.

    Jogo sem `status` (chamador antigo, fixture de teste) e' tratado como FT e
    permanece: a ausencia do campo nunca pode ENCOLHER o pool.
    """
    if family in ("goals", "btts"):
        return pool
    return [m for m in pool if (m.get("status") or "FT") not in PRORROGACAO]


def _extract_stat(m: dict, family: str, scope: str, team_id: int | None = None):
    """Le o valor real de uma familia/escopo num jogo historico, somando
    home+away quando a familia nao tem coluna 'total_X' pronta
    (shots/offsides).

    `team_id` resolve o mando POR PARTIDA quando o escopo e' de um time so'
    (home/away) -- sem ele, metade do historico e' lida na coluna do
    adversario. Ver resolve_side()."""
    if family == "cards":
        return _cards_points(m, scope, team_id)
    if family == "goals":
        # Sempre pelos 90 minutos -- ver gols_90. `total_goals` do banco e' a
        # soma do placar CHEIO e nao serve num jogo de prorrogacao.
        lado_gols = resolve_side(m, scope, team_id)
        if lado_gols in ("home", "away"):
            return gols_90(m, lado_gols)
        return gols_90(m, "home") + gols_90(m, "away")
    fields = _FAMILY_STAT_FIELDS[family]
    side = resolve_side(m, scope, team_id)
    if side in ("home", "away"):
        return m.get(fields[side]) or 0
    total_field = fields.get("total")
    if total_field:
        return m.get(total_field) or 0
    return (m.get(fields["home"]) or 0) + (m.get(fields["away"]) or 0)


def _somente_no_mando(pool: list, team_id: int | None, mando: str) -> list:
    """Jogos em que o time atuou NO MANDO que o mercado descreve.

    Sem team_id devolve o pool inteiro (comportamento antigo) -- nao da' pra
    saber qual lado e' o time sem o id, e chutar seria pior que nao filtrar."""
    if team_id is None:
        return pool
    chave = "home_team_id" if mando == "home" else "away_team_id"
    return [m for m in pool if m.get(chave) == team_id]


def pool_and_field(family: str, scope: str, last10_home: list, last10_away: list,
                    team_id: int | None = None,
                    home_team_id: int | None = None, away_team_id: int | None = None):
    """Pool de jogos que sustenta a taxa de um mercado, e o campo bruto (hoje
    sempre None -- _extract_stat resolve o campo por familia).

    MANDO (2026-08-08). Mercado de escopo home/away e' sobre o time NAQUELE
    mando ("Escanteios Visitante Mais/Menos" = escanteios de quem joga fora),
    mas o pool vinha de MatchStatsService.get_all_matches_full(), que filtra
    por `(home_team_id = X OR away_team_id = X)` e devolve os 15 jogos do time
    MISTURANDO casa e fora. resolve_side() ja corrigia a COLUNA lida em cada
    jogo (achado de 2026-08-05); o que ninguem tinha corrigido e' que metade
    daqueles jogos e' do mando ERRADO pro mercado em questao.

    Nao e' um vies pequeno. Medido nos dados de producao em 2026-08-08:

        Serie A 2026:  5.62 escanteios do mandante x 4.41 do visitante (+27%)
        Serie B 2026:  5.78 x 4.25 (+36%)

    O caso que motivou o fix (pick VIP #1573, Botafogo x Fluminense): "Escanteios
    Visitante Over 4.5" saiu com 78% de probabilidade. O Fluminense fora de casa
    na temporada bate essa linha em 4 de 10 jogos (40%); a media dele em casa
    (6.18) e' que puxava a conta pra cima. O modelo Poisson do mesmo pick, que
    le media ja' separada por mando em `team_statistics`, dizia 53.5% -- os dois
    numeros nunca fecharam porque estavam medindo mandos diferentes.

    Efeito colateral aceito: o pool cai de ~15 pra ~7-8 jogos, entao a amostra
    encolhe e Q cai junto (sample_rich_n=8). Isso e' o numero honesto -- a
    amostra grande de antes era grande por incluir jogo que nao respondia a
    pergunta do mercado.

    Sede neutra (Copa/selecao, via get_last_n_all_competitions) segue o mesmo
    caminho: filtra por quem a fixture designou como mandante, que e' a mesma
    convencao que a casa de aposta usa pra nomear o mercado.

    TOTAL E BTTS ENTRARAM NA MESMA REGRA (2026-08-10), com caso de producao.
    Em 08/08 o filtro ficou so' nos mercados de UM time, com o argumento de que
    num contador de PARTIDA os dois mandos se compensam. Nao se compensam, e o
    pick que mostrou isso foi Goias x Londrina, "Escanteios Menos de 11.5" @1.73,
    publicado com 65.2% de probabilidade e EV +12.7%:

        Goias EM CASA:     media 12.0, bateu Under 11.5 em 4 de 5
        Londrina FORA:     media 14.4, bateu em 0 de 5
        -> a amostra que responde a pergunta da' 4 de 10 (40%)

    Os outros ~20 jogos do pool (Goias fora + Londrina em casa) sao partidas
    hospedadas por OUTROS times, com outro ritmo, e foram eles que levaram a
    taxa ponderada pra perto de 70%. O usuario viu a discrepancia no card, que
    desde 2026-08-10 mostra so' o mando do jogo.

    O pool cai de ~30 pra ~14 jogos. Continua RICO (sample_rich_n=8), e o
    encolhimento bayesiano fica mais forte -- que e' o efeito desejado: com
    amostra menor a taxa so' se afasta do mercado quando ha evidencia real.

    BTTS entra pelo mesmo argumento: "as duas marcam" e' propriedade da partida,
    e a partida que interessa e' esta, com estes mandos."""
    if scope == "home":
        return comparavel_em_90(_somente_no_mando(last10_home, team_id, "home"), family), None
    if scope == "away":
        return comparavel_em_90(_somente_no_mando(last10_away, team_id, "away"), family), None
    # total e btts: o mandante nos jogos EM CASA dele, o visitante nos de FORA.
    # Sem os ids o filtro nao acontece (mesma regra de _somente_no_mando) e o
    # pool volta ao comportamento antigo, em vez de sair vazio.
    return comparavel_em_90(
        _somente_no_mando(last10_home, home_team_id, "home")
        + _somente_no_mando(last10_away, away_team_id, "away"), family), None


def _build_market_hit_fn(family: str, scope: str, value: str, line_str: str,
                          team_id: int | None = None):
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
            # 90 minutos, igual a familia goals: gol de prorrogacao nao faz
            # BTTS pra casa de aposta.
            occurred = gols_90(m, "home") > 0 and gols_90(m, "away") > 0
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
        stat = _extract_stat(m, family, scope, team_id)
        # linha redonda (sem .5) e stat bate exato -- PUSH na graduacao
        # real (evaluate_asian), nao conta nem a favor nem contra aqui.
        if is_round_line and stat == line_val:
            return None
        over = 1 if stat > line_val else 0
        return over if is_over else 1 - over

    return hit_fn


def market_taxa(family: str, scope: str, value: str, line_str: str,
                last10_home: list, last10_away: list, reference_date=None,
                config: PickEngineConfig = DEFAULT_CONFIG,
                team_id: int | None = None,
                home_team_id: int | None = None, away_team_id: int | None = None):
    """Over/under (gols/escanteios/cartoes/chutes/impedimentos) e ambas
    marcam (btts) -- os mercados 'classicos' ja existiam desde a Fase 1.
    Mercados novos (1X2/handicap/dupla-chance/etc) tem funcoes proprias
    abaixo (outcome_taxa, handicap_taxa, ...), despachadas pelo
    orchestrator via classify_market()."""
    pool, _ = pool_and_field(family, scope, last10_home, last10_away, team_id,
                             home_team_id, away_team_id)
    if not pool:
        return None

    hit_fn = _build_market_hit_fn(family, scope, value, line_str, team_id)
    if hit_fn is None:
        return None

    return weighted_rate(pool, hit_fn, reference_date=reference_date, config=config)


_MIN_MATCHES_PER_HALF_STABILITY = 2


def line_stability(family: str, scope: str, value: str, line_str: str,
                    last10_home: list, last10_away: list,
                    team_id: int | None = None,
                    home_team_id: int | None = None,
                    away_team_id: int | None = None) -> dict | None:
    """Compara a taxa BRUTA (nao ponderada) da linha na metade mais
    recente do historico vs a metade mais antiga -- diferente da media
    agregada (que pode esconder uma linha que so comecou a bater
    recentemente, ou que parou de bater e a media agregada ainda nao
    refletiu isso). Divergencia grande = padrao instavel/recente demais
    pra confiar tanto quanto a taxa agregada sugere.

    So cobre mercados 'classicos' (over/under/btts, mesmo escopo de
    market_taxa) -- amostra minima de 2 jogos por metade (4 no total),
    senao a comparacao vira ruido puro. None quando nao aplicavel."""
    pool, _ = pool_and_field(family, scope, last10_home, last10_away, team_id,
                             home_team_id, away_team_id)
    if not pool or len(pool) < _MIN_MATCHES_PER_HALF_STABILITY * 2:
        return None

    hit_fn = _build_market_hit_fn(family, scope, value, line_str, team_id)
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
                  config: PickEngineConfig = DEFAULT_CONFIG,
                  team_id: int | None = None,
                  home_team_id: int | None = None, away_team_id: int | None = None):
    """Ponto de entrada unico do Modelo 1 -- despacha pra funcao de taxa
    certa conforme a familia (classify_market() ja devolveu family/scope).
    Mercados 'classicos' (goals/corners/cards/btts/shots/shots_on_target/
    offsides) usam market_taxa() (over/under ou yes/no); os demais tem
    parsing de value proprio (3-way, side+handicap, odd/even).

    `team_id` e' o time que o ESCOPO aponta (mandante pra scope='home',
    visitante pra scope='away') -- resolve o mando por partida no historico
    misto. Sem ele o calculo volta ao comportamento antigo, que le metade da
    amostra na coluna do adversario (ver resolve_side()).

    `home_team_id`/`away_team_id` sao os dois lados da partida analisada, e
    valem pro escopo TOTAL (e btts), onde nao existe "o time do escopo": e' com
    eles que pool_and_field pega o mandante em casa e o visitante fora."""
    direction = (value or "").strip().lower()

    if family in ("goals", "corners", "cards", "btts", "shots", "shots_on_target", "offsides", "fouls", "saves"):
        return market_taxa(family, scope, value, line_str, last10_home, last10_away,
                            reference_date, config, team_id=team_id,
                            home_team_id=home_team_id, away_team_id=away_team_id)

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
    # Defesas: "feitos" e o que o goleiro defende, "cedidos" o que o
    # goleiro adversario defende -- a validacao cruzada feitos-vs-cedidos
    # vale igual, so o significado muda.
    "saves":   ("home_goalkeeper_saves", "away_goalkeeper_saves"),
}


def scored_conceded_avg(matches: list, is_home_ctx: bool, family: str,
                         team_id: int | None = None):
    """Media do que o time FAZ (feitos) e do que CEDE (cedidos) no
    historico, no contexto correto (casa/fora). Base da validacao
    feitos-vs-cedidos: toda estimativa de total precisa ser validada
    cruzando feitos de um lado com cedidos do outro, nao so olhar se
    jogos passados bateram a linha.

    `team_id` resolve o lado POR PARTIDA (home_team_id == team_id). Sem ele
    cai no `is_home_ctx` unico pra lista inteira, que so' e' correto quando
    todos os jogos da lista tem o mesmo mando.

    Por que isso importa: MatchStatsService.get_all_matches_full() filtra por
    `(home_team_id = X OR away_team_id = X)` -- devolve os 15 jogos do time
    MISTURANDO casa e fora. Com um is_home_ctx unico, metade das partidas era
    lida na coluna errada: pro mandante lia-se `home_corners` tambem nos jogos
    em que ele era visitante, ou seja, os escanteios DO ADVERSARIO entravam
    como "feitos" dele. Mesmo bug que ja' tinha sido encontrado e corrigido em
    offensive_efficiency() (ver docstring de la'), que nunca foi propagado
    ate' aqui."""
    if not matches or family not in _SCORED_CONCEDED_FIELDS:
        return None, None
    # Mesma regra do pool de taxa (ver comparavel_em_90): a folha de um AET
    # cobre 120 minutos, entao escanteios/cartoes/faltas/defesas daquele jogo
    # nao descrevem a mesma partida de 90 que o mercado precifica. Gols ficam,
    # porque abaixo sao lidos por gols_90. Sem isto o caminho de historico cru
    # -- que e' o caminho da COPA -- ficaria com a media inflada exatamente nos
    # jogos de mata-mata.
    matches = comparavel_em_90(matches, family)
    if not matches:
        return None, None
    n = len(matches)

    def _lado(m):
        """('home','away') quando o time e' o mandante NAQUELA partida."""
        if team_id is None:
            return ("home", "away") if is_home_ctx else ("away", "home")
        return ("home", "away") if m.get("home_team_id") == team_id else ("away", "home")

    if family == "cards":
        # amarelo=1, vermelho=2 (ver _cards_points) -- mesma correcao do
        # bug de vermelho ignorado, aqui pro sinal de convergencia feitos
        # x cedidos em vez da taxa em si.
        scored = conceded = 0.0
        for m in matches:
            s_side, c_side = _lado(m)
            scored += _cards_points(m, s_side)
            conceded += _cards_points(m, c_side)
        return round(scored / n, 3), round(conceded / n, 3)

    if family == "goals":
        # Pelos 90 minutos, igual a taxa (ver gols_90): num jogo de
        # prorrogacao, `home_goals` ja inclui o tempo extra.
        scored = conceded = 0.0
        for m in matches:
            s_side, c_side = _lado(m)
            scored += gols_90(m, s_side)
            conceded += gols_90(m, c_side)
        return round(scored / n, 3), round(conceded / n, 3)

    home_f, away_f = _SCORED_CONCEDED_FIELDS[family]
    scored = conceded = 0.0
    for m in matches:
        s_side, c_side = _lado(m)
        scored += (m.get(home_f if s_side == "home" else away_f) or 0)
        conceded += (m.get(home_f if c_side == "home" else away_f) or 0)
    return round(scored / n, 3), round(conceded / n, 3)


# Familia -> (campo_feitos, campo_cedidos) em `team_statistics`. Essa tabela e'
# mantida pelo collector (services/team_stats_aggregator_service.py) com media
# ja' separada por context_type HOME/AWAY e `games_count` proprio -- ou seja, o
# recorte de mando ja' vem correto e cobre mais jogos que os 15 de
# get_all_matches_full(). Cartoes nao tem coluna "pontos" pronta: soma amarelo
# + 2*vermelho pra bater com _cards_points.
_TEAM_STATS_FIELDS = {
    "goals":   ("avg_goals_for", "avg_goals_against"),
    "corners": ("avg_corners_for", "avg_corners_against"),
    "fouls":   ("avg_fouls_for", "avg_fouls_against"),
    "saves":   ("avg_saves_for", "avg_saves_against"),
}


# Forca do encolhimento das medias de `team_statistics` em direcao a media da
# liga. Escolhido varrendo k em {0,2,4,6,8,12} contra 506 jogos reais, sempre
# usando so' partidas ANTERIORES a cada jogo (sem vazamento), medindo erro
# absoluto medio contra o total que de fato aconteceu:
#
#   k       corners        goals         fouls
#   0       -1.1%          +3.1%         -2.9%     <- sem encolher, PIORA em 2 de 3
#   2       +1.6%          +4.0%         +1.3%
#   4       +2.0%          +3.5%         +2.3%     <- adotado
#   8       +1.7%          +2.8%         +2.8%
#
# (ganho vs. o comportamento de producao: media dos 15 jogos crus.) Entre k=2
# e k=8 e' um plato dentro do ruido de 506 jogos -- k=4 fica no meio e vence
# nas tres familias. O que NAO e' ruido e' k=0: cruzar feitos-x-cedidos sem
# encolher perde da linha de base, porque a media de um time com 5 jogos no
# mando nao sustenta o peso literal que recebia.
#
# Decaimento por recencia foi testado junto (meia-vida 30/45/60/90 dias) e nao
# ajudou: o recorte de 15 jogos ja' cobre recencia, e nas listas por mando
# (metade do tamanho) o decaimento so' joga amostra fora.
_TEAM_STATS_SHRINK_K = 4


def shrink_to_baseline(valor: float | None, amostra: int | None, baseline: float | None,
                        k: int = _TEAM_STATS_SHRINK_K) -> float | None:
    """Puxa `valor` na direcao de `baseline` proporcional a quao curta e' a
    amostra: (n*valor + k*baseline) / (n+k). Mesma formula de encolhimento
    bayesiano ja' usada em bayesian_model.shrink_taxa e em
    calibration._evidence_weight -- aqui aplicada a uma MEDIA (escanteios por
    jogo), nao a uma taxa. Sem baseline confiavel devolve o valor cru."""
    if valor is None:
        return None
    if baseline is None or not amostra or k <= 0:
        return valor
    return round((amostra * valor + k * baseline) / (amostra + k), 3)


# Familia -> (chave_casa, chave_fora) em get_league_baseline(). O baseline e'
# sempre "o que o time FAZ naquele mando" -- serve tanto pra encolher os feitos
# de um lado quanto os cedidos do outro, porque as duas estimativas miram a
# MESMA quantidade (ex.: escanteios do mandante).
_BASELINE_KEYS = {
    "goals":   ("home_goals", "away_goals"),
    "corners": ("home_corners", "away_corners"),
    "cards":   ("home_cards", "away_cards"),
    "fouls":   ("home_fouls", "away_fouls"),
    "saves":   ("home_saves", "away_saves"),
}


def scored_conceded_from_team_stats(team_stats: dict | None, family: str):
    """(feitos, cedidos, amostra) de uma linha de `team_statistics`, ou
    (None, None, 0) se a familia nao estiver mapeada / a linha nao servir.

    A agregacao ja' e' por mando (context_type) e sobre a temporada inteira,
    entao nao sofre nem do recorte de 15 jogos nem da mistura casa/fora que
    scored_conceded_avg() enfrenta. Em compensacao precisa ser encolhida --
    ver _TEAM_STATS_SHRINK_K."""
    if not team_stats or not team_stats.get("games_count"):
        return None, None, 0
    n = int(team_stats["games_count"])

    if family == "cards":
        try:
            feitos = float(team_stats["avg_yellow_for"] or 0) + 2 * float(team_stats["avg_red_for"] or 0)
            cedidos = float(team_stats["avg_yellow_against"] or 0) + 2 * float(team_stats["avg_red_against"] or 0)
        except (KeyError, TypeError, ValueError):
            return None, None, 0
        return round(feitos, 3), round(cedidos, 3), n

    campos = _TEAM_STATS_FIELDS.get(family)
    if not campos:
        return None, None, 0
    f_key, a_key = campos
    feitos, cedidos = team_stats.get(f_key), team_stats.get(a_key)
    if feitos is None or cedidos is None:
        return None, None, 0
    try:
        return round(float(feitos), 3), round(float(cedidos), 3), n
    except (TypeError, ValueError):
        return None, None, 0


def expected_value_convergence(last10_home: list, last10_away: list, family: str, scope: str,
                                home_team_id: int | None = None, away_team_id: int | None = None,
                                team_stats_home: dict | None = None,
                                team_stats_away: dict | None = None,
                                league_baseline: dict | None = None):
    """Duas estimativas independentes do valor esperado para a partida,
    uma pelo que cada time costuma FAZER, outra pelo que costuma CEDER --
    se convergem (<=15% de diferenca), e sinal forte; se divergem, e
    motivo pra desconfiar do mercado, nao so olhar taxa historica isolada.

    scope='total' (ex. Gols Mais/Menos): feitos_casa+feitos_fora vs
      cedidos_casa+cedidos_fora.
    scope='home' (ex. Total de Gols Casa): feitos do mandante vs cedidos
      do visitante fora (o adversario especifico deste jogo).
    scope='away': feitos do visitante fora vs cedidos do mandante em casa.

    FONTE (2026-08-03): usa `team_statistics` quando as duas linhas chegam
    (media por mando ja' agregada pelo collector, temporada inteira); cai pro
    historico cru de get_all_matches_full() quando falta. A tabela existe e e'
    atualizada todo dia desde sempre, mas so' era lida pelos pipelines de IA
    -- quando a IA saiu de producao em 2026-07-17 ela ficou orfa, e o motor
    passou a recalcular tudo dos 15 jogos crus. `source` no retorno diz qual
    caminho respondeu."""
    if family not in _SCORED_CONCEDED_FIELDS:
        return None

    h_scored, h_conceded, n_home = scored_conceded_from_team_stats(team_stats_home, family)
    a_scored, a_conceded, n_away = scored_conceded_from_team_stats(team_stats_away, family)
    source = "team_statistics"
    if None in (h_scored, h_conceded, a_scored, a_conceded):
        h_scored, h_conceded = scored_conceded_avg(last10_home, True, family, team_id=home_team_id)
        a_scored, a_conceded = scored_conceded_avg(last10_away, False, family, team_id=away_team_id)
        # A AMOSTRA VEM DO POOL, e nao mais zero (2026-08-13).
        #
        # Ate' aqui o caminho de historico cru pulava o encolhimento inteiro,
        # porque n_home/n_away chegavam 0 de scored_conceded_from_team_stats e
        # shrink_to_baseline devolve o valor cru com amostra 0. Isso deixava
        # justamente a fixture de COPA sem o ajuste medido como ganho
        # (+2.0%/+3.5%/+2.3% contra 506 jogos), ja' que copa e' o caso em que
        # team_statistics vem vazio ou fino -- ela caia aqui sempre.
        #
        # A contagem espelha pool_and_field (mando + comparavel em 90 minutos)
        # pra o peso do encolhimento refletir os jogos que de fato sustentam a
        # media, nao o tamanho da lista bruta.
        n_home = len(comparavel_em_90(
            _somente_no_mando(last10_home, home_team_id, "home"), family))
        n_away = len(comparavel_em_90(
            _somente_no_mando(last10_away, away_team_id, "away"), family))
        source = "historico_cru"

    # Encolhimento pra media da competicao, nos DOIS caminhos: SEM ele o
    # cruzamento feitos-x-cedidos mede PIOR que a media dos 15 jogos crus (ver
    # _TEAM_STATS_SHRINK_K). Os feitos do mandante e os cedidos do visitante
    # miram a mesma quantidade (o que acontece do lado de CASA), entao ambos
    # sao puxados pro mesmo baseline -- e vice-versa pro lado de fora.
    base_casa = base_fora = None
    if league_baseline:
        k_casa, k_fora = _BASELINE_KEYS.get(family, (None, None))
        base_casa = league_baseline.get(k_casa) if k_casa else None
        base_fora = league_baseline.get(k_fora) if k_fora else None
        base_casa = float(base_casa) if base_casa is not None else None
        base_fora = float(base_fora) if base_fora is not None else None
    h_scored = shrink_to_baseline(h_scored, n_home, base_casa)
    a_conceded = shrink_to_baseline(a_conceded, n_away, base_casa)
    a_scored = shrink_to_baseline(a_scored, n_away, base_fora)
    h_conceded = shrink_to_baseline(h_conceded, n_home, base_fora)
    amostra = min(n_home, n_away) if (n_home and n_away) else None
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
        "source":            source,
        "amostra":           amostra,
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
