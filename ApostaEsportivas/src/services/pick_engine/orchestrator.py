"""Ponto de entrada unico do motor de picks. `consensus.py` fica fora deste
fluxo por decisao explicita (modo sombra, roda separado em
shadow_consensus.py, sem influenciar o calculo de picks aqui)."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG
from services.pick_engine import (
    stats_model, market_model, confidence, calibration, ranking, explanation,
    context_model, team_profile_model, news_model, probability_model, variance_model,
    data_validation, bayesian_model, referee_model,
    market_anchor, selection_bias, context_gate, tie_effect,
)

_CARDS_FAMILIES = ("cards", "handicap_cards")

# Familias de mercado de RESULTADO -- excluidas do pool de candidatos por
# decisao explicita do usuario (2026-07-24): 1X2 puro, dupla chance e empate
# anula (mesmo grupo de correlacao "result" em ranking.py).
_RESULT_FAMILIES = ("outcome", "double_chance", "draw_no_bet")

# Handicap Asiatico (gols/escanteios/cartoes) -- excluido do pool de
# candidatos por decisao explicita do usuario (2026-08-05): o motor nao gera
# mais pick de handicap em nenhum pipeline. Substitui a regra anterior
# (2026-07-24 + 2026-07-26), que mantinha handicap_goals disponivel a partir
# de |linha| >= 1.0 -- o corte de +-0.5 dentro de stats_model.handicap_taxa()
# continua no lugar, mas hoje nao chega a ser exercido pela producao.
# classify_market() segue reconhecendo o mercado (o rotulo em PT e a
# resolucao de picks JA publicados dependem disso, ver
# services/ai_result_checker_service.evaluate_handicap e
# website/backend/routers/live.py) -- o descarte e' aqui, na entrada do
# pool, igual _RESULT_FAMILIES acima.
_HANDICAP_FAMILIES = ("handicap_goals", "handicap_corners", "handicap_cards")

# Par/Impar (gols e escanteios) -- excluido do pool por propriedade
# matematica do mercado, nao por decisao de gosto: pra uma contagem
# Poisson(lambda) (gols/escanteios de uma partida), P(par) = (1+e^-2*lambda)/2.
# Pra lambda tipico de gols (~2.5-3.5) isso da P(par) entre ~50.0% e ~50.7%;
# pra escanteios (~9-12) a diferenca e' praticamente zero (e^-2*lambda ~ 0).
# Ou seja: NENHUM time, por melhor ou pior que seja ofensiva/defensivamente,
# desloca esse mercado de forma relevante pra longe de 50/50 -- e' o oposto
# de over/under, que reflete a media diretamente. O problema real (achado
# 2026-07-26, pick de Odd/Even gerado pro jogo do Mirassol parecendo
# aleatorio): _extract_stat/weighted_rate calculam taxa empirica numa
# amostra de ~10 jogos como fariam pra qualquer outro mercado, mas:
# (1) odd_even_goals/odd_even_corners NAO batem em probability_model.
# _POISSON_FAMILIES (que so' reconhece "goals"/"corners"/"cards" literal),
# entao NUNCA recebem o termo M (model_fit_adjustment) que pegaria esse
# tipo de contradicao estatistica pra outras familias;
# (2) por ser mercado raro/novo, calibration.get_prior() nao tinha amostra
# historica suficiente pra esse market_type, retornava None e
# bayesian_model.shrink_taxa() devolvia a taxa empirica SEM encolher.
# ATUALIZACAO 2026-08-08: esse (2) especifico deixou de valer -- o prior agora
# e' o mercado no-vig, que existe pra qualquer linha cotada, entao a taxa passa
# a ser encolhida tambem aqui. A exclusao continua de pe' pelo (1) e pela
# matematica do paragrafo acima: o teto real de desvio de 50/50 e' baixo demais
# pra sustentar edge, encolhido ou nao.
# Resultado: um desvio de amostra pequena (n~10, p~0.5, erro padrao ~15.8pp
# -- bater 70-80% "por sorte" e' estatisticamente comum) passa direto pelos
# 2 unicos filtros que existem hoje pra pegar isso, e ainda compete pelo
# slot da categoria "goals"/"corners" no ranking final (correlation_group)
# contra um over/under de verdade, que tem sinal real. Nao ha fix de
# calibracao que resolva isso de forma robusta (o teto real de desvio de
# 50/50 e' baixo demais pra sustentar um edge), entao o mercado sai do pool
# igual _RESULT_FAMILIES acima.
_NEAR_COINFLIP_FAMILIES = ("odd_even_goals", "odd_even_corners")

_OPPOSITE_VALUE = {
    "over": "under", "under": "over",
    "yes": "no", "no": "yes", "sim": "não", "não": "sim", "nao": "sim",
}


def _find_sibling(entry: dict, entries: list) -> dict | None:
    """Acha a entrada complementar (Over/Under ou Yes/No do MESMO
    market_id+line) pra calculo de probabilidade no-vig -- None se nao
    houver par (mercado sem contraparte, ex.: handicap/outcome de 3 vias)."""
    opposite = _OPPOSITE_VALUE.get((entry.get("value") or "").strip().lower())
    if not opposite:
        return None
    for other in entries:
        if other is entry:
            continue
        if (
            other.get("market_id") == entry.get("market_id")
            and other.get("line") == entry.get("line")
            and (other.get("value") or "").strip().lower() == opposite
        ):
            return other
    return None


def _rastrear(rastro, **campos) -> None:
    """Anota uma linha/familia no rastro, quando o chamador pediu um.

    O RASTRO NAO E' O MODO DEBUG (2026-08-27).

    `debug=True` muda o tipo de retorno e existe pra homologacao. O rastro e'
    o contrario: caro de nao ter e barato de ter -- e' uma lista que o caller
    passa vazia e o motor preenche com TODA linha e TODA familia que ele viu,
    inclusive as que morreram antes de virar candidato.

    A razao dele existir: `analyze_fixture_markets` devolve UM candidato por
    familia (a linha vencedora). O log de decisao gravava exatamente isso, e
    entao a tela do admin mostrava "goals Under 2.5" e nada mais -- o Over da
    mesma linha, as outras linhas do mesmo mercado e as familias inteiras que
    foram eliminadas antes (handicap, resultado, cartoes sem arbitro) nao
    deixavam rastro nenhum. Quem olhava perguntava "cade o mercado de gols?"
    sem ter como saber que ele existiu e perdeu.
    """
    if rastro is None:
        return
    rastro.append(campos)


def analyze_fixture_markets(
    structured_odds: list,
    last10_home: list,
    last10_away: list,
    reference_date=None,
    config: PickEngineConfig = DEFAULT_CONFIG,
    calibration_data: dict | None = None,
    context_data: dict | None = None,
    matchup_data: dict | None = None,
    news_data: dict | None = None,
    team_strength_data: dict | None = None,
    referee_stats: dict | None = None,
    league_stats: dict | None = None,
    league_id: int | None = None,
    data_quality_score: float | None = None,
    # IDs dos times: sem eles scored_conceded_avg nao consegue resolver o mando
    # POR PARTIDA e volta ao comportamento antigo (um mando so' pra lista
    # inteira, que le metade dos jogos na coluna errada -- ver docstring de
    # stats_model.scored_conceded_avg). Opcionais so' por compatibilidade com
    # chamadores antigos; todos os pipelines de producao passam.
    home_team_id: int | None = None,
    away_team_id: int | None = None,
    # Linhas de `team_statistics` (services/team_stats_service.TeamStatsService)
    # do mandante em HOME e do visitante em AWAY -- fonte preferida do sinal
    # feitos-vs-cedidos. Ausentes -> cai no historico cru.
    team_stats_home: dict | None = None,
    team_stats_away: dict | None = None,
    # Camada probabilistica (2026-08-06). Ambos opcionais e ignorados quando
    # as flags de config estao desligadas, que e' o padrao.
    # `calibrators`: {market_type: IsotonicCalibrator}, de
    # calibration_model.fit_por_grupo() sobre o picks_ledger.
    # `clv_by_market`: {market_type: {clv_medio, clv_n, clv_significativo}},
    # de attribution.group_by(pernas, "market_type").
    calibrators: dict | None = None,
    clv_by_market: dict | None = None,
    # Contexto de partida (2026-08-06): saida de context_gate.build_context().
    # Mata-mata, ida/volta, placar da ida, agregado, quem precisa do resultado
    # e rivalidade medida no H2H. Ausente -> gate inerte, motor identico ao de
    # antes. Presente -> barra Under que contradiz o que a partida vai ser,
    # em TODAS as familias de volume (nao so' cartoes).
    match_context: dict | None = None,
    # Media da liga por mando (TeamStatsService.get_league_baseline) -- alvo
    # do encolhimento das medias de team_statistics. Sem ela as medias entram
    # cruas, que e' medidamente PIOR que o historico de 15 jogos.
    league_baseline: dict | None = None,
    # Lista que o caller passa VAZIA pra receber tudo que o motor viu -- linha
    # por linha, familia por familia, com o motivo de cada morte. Nao muda o
    # retorno nem nenhuma decisao; ver _rastrear() logo acima.
    rastro: list | None = None,
    debug: bool = False,
) -> list | dict:
    """Calcula taxa/confidence/edge/EV para cada mercado suportado
    (classify_market()) disponivel nas odds ja estruturadas
    (services.odds_service.OddsService.load_odds_structured), a partir do
    historico ja carregado. Cobre gols/escanteios/cartoes/faltas/ambas marcam/
    chutes/impedimentos (over-under), clean sheet e vitoria sem sofrer gol --
    ver stats_model.classify_market() pra lista completa e o que fica de fora
    (jogador individual, placar exato, 1o/2o tempo). 1X2, dupla chance e
    empate anula aposta (_RESULT_FAMILIES acima) sao classificados mas
    descartados de proposito antes de virar candidato -- mercado de resultado
    excluido por decisao de produto (2026-07-24). Handicap de gols/escanteios/
    cartoes (_HANDICAP_FAMILIES acima) idem, excluido por decisao de produto
    (2026-08-05) -- o motor nao gera mais nenhum pick de handicap.
    Par/impar (_NEAR_COINFLIP_FAMILIES acima) tambem e' classificado mas
    descartado -- mercado matematicamente proximo de 50/50 independente dos
    times, ver comentario da constante (2026-07-26).

    `context_data` (saida de context_model.build_context), `matchup_data`
    (saida de team_profile_model.compare_matchup), `news_data` (saida de
    news_model.injury_signal) e `team_strength_data` (saida de
    team_strength.compare_team_strength) sao opcionais -- Fase 1 continua
    funcionando identica sem eles (ranking.final_score() so aplica os pesos
    de Contexto/Perfil/Noticias quando os campos existem no candidato;
    team_strength_data e so informativo por enquanto, anexado a cada
    candidato mas ainda nao pesado no confidence -- ver Fase 2b).

    `data_quality_score` (0-100, saida de
    data_validation.data_quality_score) e opcional -- quando presente,
    ranking.select_smart_safe_line() exige mais edge pra aprovar uma
    linha em fixtures com dado ruim (Prioridade 2 do plano de refatoracao).

    Fase 2b (Statistical Engine): pra familias com decomposicao feitos/
    cedidos (goals/corners/cards, ver stats_model._SCORED_CONCEDED_FIELDS),
    alem da taxa empirica bruta agora tambem calcula P(linha) via Poisson
    (probability_model, lambda = expected_value_convergence) e usa a
    concordancia entre as duas estimativas como termo M no confidence
    (confidence.model_fit_adjustment); e a variancia/coeficiente de
    variacao do historico bruto como termo V (variance_model.variance_penalty)
    -- mercados com dispersao alta (mesma media, resultados muito
    irregulares) perdem confidence mesmo com taxa boa.

    Retorna candidatos prontos para ranking.rank_market_candidates().

    `referee_stats` (saida de services.referee_stats_service.RefereeStatsService.
    get_stats) e opcional -- quando ausente, mercados de cartoes (cards/
    handicap_cards) ficam bloqueados por falta de dado confiavel de arbitro
    (ver referee_model.cards_market_eligible, gate duro pra TODOS os
    pipelines: sem arbitro com amostra minima OU jogo classificado "frio"
    pelo contexto, cartoes nem vira candidato).

    `league_id` e opcional -- quando presente, calibration_adjustment tenta a
    calibracao segmentada por (market_type, league_id) antes de cair pro
    agregado so por market_type (ver services/pick_engine/calibration.py,
    fallback gracioso quando a liga especifica nao tem amostra suficiente).
    Isso corrige CONFIDENCE, nao a probabilidade -- desde 2026-08-08 o prior
    da probabilidade e' o mercado no-vig, nao o hit-rate dos proprios picks.

    `debug=True` (fase de homologacao, ver services/pick_engine/homologation.py
    e o plano de validacao antes de promover o motor pra producao): retorno
    muda de list pra dict {"candidates": [...], "eliminated_markets": [...],
    "entries_dropped": [...]} -- captura tambem os `continue` silenciosos
    (odd invalida, poucos bookmakers, taxa sem dado) que hoje descartam uma
    entrada ANTES dela virar line_candidate, e familias inteiras eliminadas
    (sem best_line). `debug=False` (default, usado por toda a producao/
    pipelines atuais) mantem o retorno IDENTICO ao de sempre -- nao muda
    nenhuma decisao, so nao expoe o rastro extra.
    """
    entries_dropped = []
    eliminated_markets = []
    if calibration_data is None:
        calibration_data = calibration.get_market_calibration()
    ctx_score = (context_model.context_score(context_data, match_context)
                 if context_data else None)
    news_score = news_model.news_score(news_data) if news_data else None
    referee_sig = referee_model.referee_signal(referee_stats, config, league_stats=league_stats)
    game_intensity = referee_model.game_intensity(context_data, matchup_data, referee_sig)

    groups: dict[tuple, list] = {}
    for m in structured_odds:
        classified = stats_model.classify_market(m.get("market_name", ""))
        if not classified:
            continue
        groups.setdefault(classified, []).append(m)

    candidates = []
    for (family, scope), entries in groups.items():
        if family in _RESULT_FAMILIES:
            motivo = "mercado de resultado excluido por decisao de produto"
            _rastrear(rastro, nivel="familia", market_type=family, scope=scope,
                      status="eliminada", motivo=motivo)
            if debug:
                eliminated_markets.append({
                    "family": family, "scope": scope, "market_type": family,
                    "reason": motivo,
                })
            continue
        if family in _HANDICAP_FAMILIES:
            motivo = "handicap excluido por decisao de produto"
            _rastrear(rastro, nivel="familia", market_type=family, scope=scope,
                      status="eliminada", motivo=motivo)
            if debug:
                eliminated_markets.append({
                    "family": family, "scope": scope, "market_type": family,
                    "reason": motivo,
                })
            continue
        if family in _NEAR_COINFLIP_FAMILIES:
            _rastrear(rastro, nivel="familia", market_type=family, scope=scope,
                      status="eliminada",
                      motivo="par/impar e' proximo de 50/50 por construcao "
                             "(paridade Poisson) -- excluido do pool")
            if debug:
                eliminated_markets.append({
                    "family": family, "scope": scope, "market_type": family,
                    "reason": "par/impar e matematicamente proximo de 50/50 (paridade Poisson); "
                              "sem sinal Poisson nem prior calibrado, taxa empirica de amostra "
                              "pequena passa como se fosse edge real",
                })
            continue
        if family in _CARDS_FAMILIES:
            eligible, reason = referee_model.cards_market_eligible(referee_sig, game_intensity, config)
            if not eligible:
                _rastrear(rastro, nivel="familia", market_type=family, scope=scope,
                          status="eliminada", motivo=reason)
                if debug:
                    eliminated_markets.append({
                        "family": family, "scope": scope, "market_type": family,
                        "reason": reason,
                    })
                continue

        convergence = stats_model.expected_value_convergence(
            last10_home, last10_away, family, scope,
            home_team_id=home_team_id, away_team_id=away_team_id,
            team_stats_home=team_stats_home, team_stats_away=team_stats_away,
            league_baseline=league_baseline,
        )
        # BTTS TEM market_type PROPRIO (2026-08-20). Ate' aqui ele era gravado
        # como "goals", e isso escondia o melhor mercado do motor dentro do
        # balde do segundo melhor. Medido em PROD no mesmo dia, separando os
        # dois pelo NOME do mercado porque o market_type nao separava:
        #
        #     Ambas Marcam    n= 31   80,6% de acerto   +12,12 u   ROI ~+39%
        #     Gols over/under n=119   69,7% de acerto    +7,71 u   ROI  ~+6%
        #
        # Sao dinamicas diferentes -- um e' binario sobre os dois times
        # marcarem, o outro e' contagem total -- e estavam sendo calibrados
        # juntos (calibration.calibration_adjustment e
        # calibration_model.fit_por_grupo agrupam por market_type). Com o balde
        # unico, a curva de um contaminava o outro e nenhum dos dois podia ser
        # medido em separado.
        #
        # A protecao de correlacao NAO se perde: ranking._CORRELATION_GROUP_
        # OVERRIDES ja mapeia "btts" -> "goals" desde 2026-08-10, entao a
        # multipla/alavancagem continuam impedidas de juntar "Over 1.5 gols" com
        # "Ambas Marcam" no mesmo bilhete. E a liquidacao ja' esperava por isto:
        # ai_result_checker_service._MARKET_TYPE_HINTS tem "btts": "btts", e o
        # hint so' entra quando o texto do mercado nao decide -- antes um pick
        # de BTTS carregava o hint errado ("goals") pra esse caso de borda.
        market_type = family
        # Time que o escopo do mercado aponta -- resolve o mando POR PARTIDA
        # na taxa/variancia/estabilidade/outlier. Sem isso, um mercado
        # "Home Corners"/"Away Team Total Goals" lia a coluna fixa do escopo
        # em TODO o historico do time, e nos jogos em que ele estava do outro
        # lado a estatistica contada era a do ADVERSARIO (ver
        # stats_model.resolve_side -- metade da amostra vinha do time errado).
        side_team_id = stats_model.scope_team_id(scope, home_team_id, away_team_id)

        # Lambdas da familia -- nao dependem da LINHA, so' do jogo, entao saem
        # uma vez so' aqui fora e cada linha candidata pergunta a sua
        # probabilidade a eles logo abaixo.
        is_poisson_fam = probability_model.is_poisson_family(family)
        lambda_familia = (convergence["expected_value"]
                          if is_poisson_fam and convergence else None)
        # BTTS tem Poisson proprio: P(ambas marcam) = P(casa marca)xP(fora
        # marca), com um lambda por LADO (nao um lambda combinado do jogo
        # inteiro como goals/corners/cards usam) -- por isso fica fora de
        # is_poisson_family, tratado a parte, mas conta igual pra decidir se K
        # cede lugar a M.
        btts_sim = None
        if family == "btts":
            home_conv = stats_model.expected_value_convergence(
                last10_home, last10_away, "goals", "home",
                home_team_id=home_team_id, away_team_id=away_team_id,
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
                league_baseline=league_baseline,
            )
            away_conv = stats_model.expected_value_convergence(
                last10_home, last10_away, "goals", "away",
                home_team_id=home_team_id, away_team_id=away_team_id,
                team_stats_home=team_stats_home, team_stats_away=team_stats_away,
                league_baseline=league_baseline,
            )
            if home_conv and away_conv:
                btts_sim = probability_model.btts_probability(
                    home_conv["expected_value"], away_conv["expected_value"])
        has_poisson_signal = is_poisson_fam or family == "btts"
        # Lambda do arbitro: so' cartoes, e so' quando ha sinal proprio dele
        # (ver referee_model.cards_lambda).
        referee_lambda = (referee_model.cards_lambda(referee_sig)
                          if family in _CARDS_FAMILIES else None)

        line_candidates = []
        for m in entries:
            # DUAS odds, papeis diferentes (2026-08-14):
            #   best_odd -- melhor casa. E' o que o site publica e o que o
            #     usuario aposta de fato.
            #   eval_odd -- mediana das casas. E' o que decide se ha valor:
            #     edge, EV, faixa de odd e line_score rodam todos em cima
            #     dela, pra o motor nao confundir "casa desalinhada" com
            #     "valor estatistico". Ver market_model.evaluation_odd.
            # Quando so ha uma casa (ou o chamador nao trouxe consenso) as
            # duas coincidem e nada muda em relacao ao comportamento antigo.
            best_odd = float(m.get("best_odd") or 0)
            eval_odd = market_model.evaluation_odd(m, config)
            rotulo_linha = m.get("value_label") or m.get("line")
            if best_odd <= 1.0 or eval_odd <= 1.0:
                _rastrear(rastro, nivel="linha", market_type=market_type, scope=scope,
                          market_name=m.get("market_pt") or m.get("market_name"),
                          line=rotulo_linha, direcao=m.get("value"),
                          status="descartada_sem_calcular", motivo="odd invalida ou ausente")
                if debug:
                    entries_dropped.append({
                        "market_name": m.get("market_pt") or m.get("market_name"),
                        "family": family, "scope": scope, "reason": "odd invalida ou ausente",
                    })
                continue
            if m.get("bookmakers_count", 1) < config.min_bookmakers_count:
                motivo = (f"poucos bookmakers ({m.get('bookmakers_count', 1)} < "
                          f"{config.min_bookmakers_count})")
                _rastrear(rastro, nivel="linha", market_type=market_type, scope=scope,
                          market_name=m.get("market_pt") or m.get("market_name"),
                          line=rotulo_linha, direcao=m.get("value"), odd=eval_odd,
                          status="descartada_sem_calcular", motivo=motivo)
                if debug:
                    entries_dropped.append({
                        "market_name": m.get("market_pt") or m.get("market_name"),
                        "family": family, "scope": scope,
                        "reason": motivo,
                    })
                continue

            # ODD FORA DA FAIXA MORRE AQUI, ANTES DA CONTA (2026-08-27).
            #
            # A faixa ja' era filtro duro desde 14/08, mas so' na hora de
            # aprovar: a linha passava por compute_taxa, encolhimento
            # bayesiano, Poisson, arbitro e estabilidade -- e entao era
            # reprovada por um numero que ja' se sabia antes de qualquer uma
            # dessas contas. Pedido do usuario, e ele esta' certo: "se a odd
            # esta' fora do padrao ja' descarta, nem calcula, porque nao vai
            # adiantar calcular".
            #
            # NAO MUDA NENHUM PICK. motivo_de_odd_fora() aplica exatamente os
            # tres gates que ranking.rank_all_candidates() reaplica no fim
            # (min_odd, max_odd, faixa do pipeline), entao a linha que cai
            # aqui e' a mesma que morreria la'. O unico caminho que enxergava
            # essas linhas era o fallback conservador de select_smart_safe_line
            # -- e o candidato que ele devolvia por esse caminho ja' era
            # barrado depois, sem nunca poder virar pick.
            #
            # O que MUDA e' o rastro: antes a linha sumia dentro de um
            # candidato reprovado; agora ela aparece nomeada, com a faixa que
            # a matou.
            fora = ranking.motivo_de_odd_fora(eval_odd, config)
            if fora:
                _rastrear(rastro, nivel="linha", market_type=market_type, scope=scope,
                          market_name=m.get("market_pt") or m.get("market_name"),
                          line=rotulo_linha, direcao=m.get("value"), odd=eval_odd,
                          status="descartada_sem_calcular", motivo=fora)
                if debug:
                    entries_dropped.append({
                        "market_name": m.get("market_pt") or m.get("market_name"),
                        "family": family, "scope": scope, "reason": fora,
                    })
                continue
            taxa = stats_model.compute_taxa(
                family, scope, m.get("value", ""), m.get("line", ""),
                last10_home, last10_away, reference_date, config,
                team_id=side_team_id,
                home_team_id=home_team_id, away_team_id=away_team_id,
            )
            if not taxa or taxa["taxa_ponderada"] is None:
                _rastrear(rastro, nivel="linha", market_type=market_type, scope=scope,
                          market_name=m.get("market_pt") or m.get("market_name"),
                          line=rotulo_linha, direcao=m.get("value"), odd=eval_odd,
                          status="descartada_sem_calcular",
                          motivo="sem taxa calculavel (amostra insuficiente)")
                if debug:
                    entries_dropped.append({
                        "market_name": m.get("market_pt") or m.get("market_name"),
                        "family": family, "scope": scope, "reason": "sem taxa calculavel (amostra insuficiente)",
                    })
                continue
            # No-vig quando o par complementar (Over/Under, Yes/No) tiver
            # 2+ bookmakers dos dois lados -- probabilidade real de mercado
            # sem a margem da casa embutida, mais precisa que 1/odd puro
            # (que ja tinha essa peca pronta em market_model desde a Fase 1
            # e nunca era chamada). Cai pra implied_prob automaticamente
            # via resolve_prob_baseline quando nao ha par ou nao ha consenso.
            sibling = _find_sibling(m, entries)
            prob_baseline = market_model.resolve_prob_baseline(m, sibling, config)
            # Encolhimento Bayesiano: puxa a taxa em direcao ao prior
            # proporcional a quao pequena e' a amostra (n<<10 -> quase todo
            # peso vai pro prior; n>>10 -> quase nao muda). taxa_bruta_raw
            # preserva o valor original pra transparencia/debug -- taxa_real
            # (usado daqui pra frente em edge/EV/confidence) e' o ajustado.
            #
            # O PRIOR E' O MERCADO (2026-08-08), nao mais calibration.get_prior().
            #
            # Ate' aqui o prior era o hit-rate dos PROPRIOS picks daquele
            # market_type. Medido em producao em 2026-08-08: get_prior("corners")
            # devolvia 0.857, vindo de 14 picks resolvidos (12 GREEN, 2 RED).
            # Duas coisas erradas nisso, e a segunda e' pior que a primeira:
            #
            #  1. E' amostra SELECIONADA. "Quanto os picks de escanteio que o
            #     motor escolheu acertaram" nao responde "com que frequencia
            #     este time passa desta linha" -- os picks so' existem porque
            #     ja' tinham taxa alta, entao o prior nasce enviesado pra cima.
            #  2. E' um LACO. Sequencia boa sobe o prior, o prior sobe a
            #     probabilidade de todo pick novo, que sobe o edge, que aprova
            #     mais pick. O motor ficava mais confiante por ter ganhado, nao
            #     por ter aprendido. No pick VIP #1573 (Escanteios Visitante
            #     Over 4.5), com n=15, esse prior respondeu por 40% da
            #     probabilidade final: (15*0.7283 + 10*0.857)/25 = 0.7798.
            #
            # A probabilidade de mercado no-vig nao tem nenhum dos dois
            # problemas: e' externa ao motor, ja' esta' calculada aqui do lado,
            # e diz exatamente o que um prior deve dizer -- "na falta de
            # evidencia propria, acredite no consenso das casas". Com ela,
            # amostra curta deixa de virar edge: a taxa so' se afasta do
            # mercado quando ha jogo suficiente pra sustentar o afastamento.
            #
            # Medido contra os 43 picks resolvidos com rastro (2026-08-08):
            # os que sobrevivem a esta regra acertaram 80.0% (n=25) contra
            # 55.6% (n=18) dos que ela corta.
            taxa_bruta_raw = taxa["taxa_ponderada"]
            taxa_ajustada = bayesian_model.shrink_taxa(
                taxa_bruta_raw, taxa["amostra"], prob_baseline["prob"]
            )
            try:
                line_val = float(m.get("line")) if family != "btts" else None
            except (TypeError, ValueError):
                line_val = None

            # As outras leituras da MESMA linha, e o desacordo entre elas,
            # resolvidos AQUI -- linha por linha, antes de escolher qual delas
            # vira o pick (2026-08-10).
            #
            # Antes isso rodava so' sobre a linha JA escolhida, e a escolha saia
            # da taxa empirica sozinha. Consequencia: num jogo em que o arbitro
            # e' permissivo, o motor escolhia o "Over 4.5" (que os times
            # sustentam), levava o corte do arbitro em cima dele e ficava sem
            # pick -- sem nunca olhar o "Under 4.5" do mesmo mercado, que e'
            # exatamente o lado que o arbitro estava apontando. Pergunta do
            # usuario em 2026-08-10, e ele estava certo: o outro lado existia.
            direcao = (m.get("value") or "").strip().lower()
            poisson_linha = None
            if lambda_familia is not None and line_val is not None:
                poisson_linha = probability_model.poisson_prob_for_line(
                    lambda_familia, line_val, direcao,
                    # A dispersao MEDIDA da familia/escopo. Sem ela a conta
                    # assume variancia = media, o que so' e' verdade em gols
                    # (ver probability_model._DISPERSAO).
                    family=family, scope=scope)
            elif btts_sim is not None:
                poisson_linha = (btts_sim if direcao in ("yes", "sim")
                                 else round(1 - btts_sim, 4))
            referee_linha = None
            if referee_lambda is not None and line_val is not None:
                referee_linha = probability_model.poisson_prob_for_line(
                    referee_lambda, line_val, direcao,
                    # scope="total" fixo, nao o do mercado: cards_lambda e' a
                    # media de pontos de cartao do arbitro na PARTIDA INTEIRA
                    # (ver referee_model.cards_lambda), e a dispersao do total
                    # e' quase o dobro da de um lado so'.
                    family="cards", scope="total")

            fit_poisson = probability_model.model_fit(taxa_ajustada, poisson_linha)
            fit_referee = probability_model.model_fit(taxa_ajustada, referee_linha)
            # O MESMO desacordo medido contra a taxa BRUTA, sempre calculado e
            # sempre gravado -- inclusive quando nao decide nada (config.
            # disagreement_on_raw_rate=False). Sem o par de numeros no rastro nao
            # da' pra medir depois quanto o encolhimento estava escondendo, que e'
            # exatamente a pergunta que a flag existe pra responder.
            fit_poisson_bruta = probability_model.model_fit(taxa_bruta_raw, poisson_linha)
            fit_referee_bruta = probability_model.model_fit(taxa_bruta_raw, referee_linha)

            # QUAL dos dois pares dispara a regra. Ver config.disagreement_on_raw_rate
            # pro porque: o encolhimento puxa a taxa pro mercado, o Poisson esta' do
            # mesmo lado, e ai o encolhimento apaga a distancia que a regra procura.
            fits_de_decisao = (
                ((poisson_linha, fit_poisson_bruta), (referee_linha, fit_referee_bruta))
                if config.disagreement_on_raw_rate
                else ((poisson_linha, fit_poisson), (referee_linha, fit_referee))
            )
            taxa_pre_desacordo = None
            # A DETECCAO usa o fit escolhido acima; a ACAO continua comparando
            # contra taxa_ajustada. Os dois papeis sao diferentes de proposito:
            # detectar e' "a evidencia discorda do modelo?", agir e' "a outra
            # estimativa e' mais pessimista do que eu publicaria?". Trocar o
            # segundo por taxa_bruta_raw deixaria a regra SUBIR a probabilidade
            # num caso em que o encolhimento ja tinha corrigido pra baixo, e a
            # regra nunca pode subir (ver test_desacordo_nunca_sobe_a_probabilidade).
            menores = [
                p for p, d in fits_de_decisao
                if p is not None and d is not None
                and config.model_disagreement_threshold is not None
                and d > config.model_disagreement_threshold
                and p < taxa_ajustada
            ]
            if menores:
                taxa_pre_desacordo = taxa_ajustada
                taxa_ajustada = min(menores)

            ev_edge = market_model.edge_and_ev(
                taxa_ajustada, eval_odd, prob_baseline["prob"]
            )
            # Estabilidade da linha especifica ao longo do tempo (nao so a
            # media agregada) -- entra no line_score via ranking._stability_bonus.
            # So cobre mercados classicos (over/under/btts); None pros
            # demais (handicap/outcome/etc), tratado como neutro no score.
            stability = stats_model.line_stability(
                family, scope, m.get("value", ""), m.get("line", ""), last10_home, last10_away,
                team_id=side_team_id,
                home_team_id=home_team_id, away_team_id=away_team_id,
            )
            line_candidates.append({
                "market_id":        m.get("market_id"),
                "market_name":      m.get("market_pt") or m.get("market_name"),
                "value":            m.get("value"),
                "line":             m.get("line"),
                "value_label":      m.get("value_label"),
                # A odd de AVALIACAO e' a que vira `odd` do pick -- e' ela que
                # passa nos gates, no line_score e na faixa, e e' ela que o
                # site publica. Publicar a melhor casa aqui criaria uma pick
                # anunciada a 2.00 cuja faixa foi conferida a 1.79: o usuario
                # veria a odd fora da faixa que ele mesmo pediu.
                #
                # O usuario nunca perde com isso: best_bookmaker e' a casa de
                # maior odd, e o maximo e' sempre >= a mediana. Ele vai a casa
                # indicada e encontra um preco igual ou melhor que o anunciado
                # -- nunca pior. O ROI publicado fica conservador pelo mesmo
                # motivo, o que e' o lado certo pra errar.
                "odd":              eval_odd,
                "melhor_odd":       best_odd,
                "best_bookmaker":   m.get("best_bookmaker"),
                "bookmakers_count": m.get("bookmakers_count", 1),
                "taxa_real":        taxa_ajustada,
                "taxa_bruta_pre_bayes": taxa_bruta_raw,
                "amostra":          taxa["amostra"],
                "amostra_label":    taxa["amostra_label"],
                "Q":                taxa["Q"],
                "wilson":           taxa.get("wilson"),
                # De onde vieram os jogos desta taxa. Alimenta a "Entenda esta
                # analise": ate 2026-08-13 o texto dizia "em N jogos" sem dizer
                # a origem, e desde a abertura do historico de copa esses N
                # podem misturar competicoes.
                "composicao":       taxa.get("composicao"),
                "prob_baseline_source": prob_baseline["source"],
                # O VALOR da probabilidade de mercado, nao so' a origem. Antes
                # so' `source` era guardado, entao o edge era calculado e o
                # numero que o produziu se perdia -- o que impedia tanto
                # recalcular edge depois quanto ancorar contra o mercado.
                "prob_baseline_value": prob_baseline["prob"],
                "stability":        stability,
                # As tres leituras da linha, sempre gravadas -- inclusive quando
                # nenhuma rebaixou nada. Sem o numero no rastro nao da' pra
                # medir depois se o sinal esta ajudando.
                "poisson_probability": poisson_linha,
                "model_fit_diff":      fit_poisson,
                "referee_probability": referee_linha,
                "referee_fit_diff":    fit_referee,
                "referee_lambda":      referee_lambda,
                # O desacordo contra a taxa BRUTA. E' o numero que mede quanto o
                # encolhimento estava escondendo -- ver config.disagreement_on_raw_rate.
                "model_fit_diff_bruta":   fit_poisson_bruta,
                "referee_fit_diff_bruta": fit_referee_bruta,
                **({"taxa_real_pre_desacordo": taxa_pre_desacordo}
                   if taxa_pre_desacordo is not None else {}),
                "_direction":       direcao,
                "_line_val":        line_val,
                **ev_edge,
            })

        best_line = ranking.select_smart_safe_line(line_candidates, config, data_quality_score=data_quality_score)

        # TODAS as linhas que chegaram a ser calculadas, com o motivo de cada
        # uma -- e nao so' a vencedora. E' a metade do rastro que o descarte
        # antecipado la' em cima nao cobre: aqui estao as linhas que passaram
        # na faixa de odd e perderam por edge, EV ou line_score.
        if rastro is not None and line_candidates:
            avaliadas = ranking.evaluate_all_lines(line_candidates, config, data_quality_score)
            escolhida = None
            if best_line:
                escolhida = (best_line.get("market_id"), best_line.get("value"),
                             best_line.get("line"))
            for a in avaliadas:
                _rastrear(
                    rastro, nivel="linha", market_type=market_type, scope=scope,
                    market_name=a.get("market_name"),
                    line=a.get("value_label") or a.get("line"), direcao=a.get("value"),
                    odd=a.get("odd"), taxa_real=a.get("taxa_real"),
                    amostra=a.get("amostra"), ev=a.get("ev"), edge=a.get("edge"),
                    line_score=a.get("line_score"),
                    status="avaliada",
                    motivo=a.get("reject_reason"),
                    # A linha que representou o mercado no ranking. Sem isso a
                    # lista nao diz qual das dez o motor levou adiante.
                    escolhida_do_mercado=(
                        escolhida is not None
                        and (a.get("market_id"), a.get("value"), a.get("line")) == escolhida
                    ),
                )

        if not best_line:
            _rastrear(rastro, nivel="familia", market_type=market_type, scope=scope,
                      status="eliminada",
                      motivo=("nenhuma linha aprovada (nem via fallback conservador)"
                              if line_candidates
                              else "nenhuma linha chegou a ser calculada"))
            if debug and line_candidates:
                eliminated_markets.append({
                    "family": family, "scope": scope, "market_type": market_type,
                    "reason": "nenhuma linha aprovada (nem via fallback conservador)",
                    "all_lines": ranking.evaluate_all_lines(line_candidates, config, data_quality_score),
                })
            continue

        # K: para familias SEM Poisson (shots/outcome/handicap/etc),
        # convergence_adjustment continua sendo o unico sinal de "o
        # feitos/cedidos concorda com a direcao do pick". Para familias COM
        # Poisson (goals/corners/cards/btts), esse bonus/penalidade sai
        # daqui -- M abaixo usa a MESMA base estatistica pra fazer a mesma
        # pergunta de forma mais precisa (probabilidade completa, nao so
        # direcao); manter os dois seria confirmar a mesma evidencia duas
        # vezes (Prioridade 1.3 do plano de refatoracao).
        K = confidence.confirmation_k(best_line["amostra"], best_line["bookmakers_count"])
        if not has_poisson_signal:
            K += confidence.convergence_adjustment(best_line["_direction"], best_line["_line_val"], convergence)
        K = round(min(max(K, 0.10), 1.00), 4)
        conf = confidence.confidence_score(C=best_line["taxa_real"], Q=best_line["Q"], K=K, config=config)

        cal_delta = calibration.calibration_adjustment(market_type, calibration_data, league_id=league_id)

        # V (variancia): mesma media, dispersao real -> menos previsivel,
        # perde confidence mesmo com taxa boa (nao aplica a familias sem
        # leitura de valor bruto, ex. btts/outcome -- variance_stats retorna
        # None e a penalidade fica 0).
        var_stats = variance_model.variance_stats(
            family, scope, last10_home, last10_away, team_id=side_team_id,
            home_team_id=home_team_id, away_team_id=away_team_id)
        v_penalty = variance_model.variance_penalty(
            var_stats["coefficient_of_variation"] if var_stats else None
        )

        # Amostra especifica desta familia (Prioridade 3) -- so exposto/
        # logado por enquanto, NAO usado como filtro/penalidade ainda: a
        # correcao completa exigiria mudar _extract_stat() pra excluir
        # jogos sem o campo em vez de tratar como 0, o que mudaria
        # taxa_real/confidence pra qualquer familia com gap de cobertura --
        # decisao separada, fora do escopo desta revisao.
        market_sample = data_validation.validate_market_sample(
            family, scope, last10_home, last10_away, team_id=side_team_id)

        # M (model-fit): concordancia entre a taxa empirica (contagem direta) e
        # as outras leituras da MESMA linha -- substitui convergence_adjustment
        # (K) pra familias com sinal Poisson, ver comentario acima.
        #
        # Os numeros ja vieram resolvidos do loop de linhas, linha por linha
        # (2026-08-10). Antes eram calculados aqui, so' pra linha ja escolhida,
        # e a escolha saia da taxa empirica sozinha -- ver o comentario grande
        # la em cima pro que isso custava. `conf` acima ja parte da taxa
        # corrigida pelo mesmo motivo.
        poisson_prob = best_line.get("poisson_probability")
        model_fit_diff = best_line.get("model_fit_diff")
        referee_prob = best_line.get("referee_probability")
        referee_fit_diff = best_line.get("referee_fit_diff")

        # A penalidade de confidence olha o PIOR desacordo entre as estimativas
        # disponiveis: duas leituras discordando ja e' motivo de desconfiar, e
        # esconder a maior das duas divergencias atras da media anularia
        # justamente o sinal que a regra existe pra capturar.
        pior_fit = max((d for d in (model_fit_diff, referee_fit_diff) if d is not None), default=None)
        m_adjustment = (confidence.model_fit_adjustment(pior_fit, config)
                        if (has_poisson_signal or referee_prob is not None) else 0.0)

        total_delta = (cal_delta or 0) - v_penalty + m_adjustment
        if total_delta:
            conf = round(
                min(max(conf + total_delta, config.confidence_min_clamp), config.confidence_max_clamp), 4
            )

        candidate = {
            **best_line,
            "market_type": market_type,
            # ESCOPO NO CANDIDATO (2026-08-19). Ele existia so' como chave do
            # agrupamento aqui em cima e morria neste ponto -- as camadas
            # seguintes recebiam "corners" sem saber se era o total da partida
            # ou o escanteio de UM time. E' a informacao que faltava pro
            # contexto de agregado agir do lado certo (ver tie_effect.py), e a
            # ausencia dela era o motivo de o gate de contexto tratar
            # "Escanteios Casa" e "Escanteios Totais" como o mesmo mercado.
            "scope": scope,
            "confidence": conf,
            "risco": confidence.risco_from_confidence(conf, config),
            "convergence": convergence,
            "calibration_delta": cal_delta,
            "variance": var_stats,
            "variance_penalty": v_penalty,
            "market_sample": market_sample,
            # poisson_probability / model_fit_diff / referee_* ja vem em
            # best_line (calculados por linha) -- so' o ajuste de confidence
            # nasce aqui.
            "model_fit_adjustment": m_adjustment,
            "context_score": ctx_score,
            "context_raw": context_data,
            # Contexto de CONFRONTO (agregado, fase, formato, regulamento).
            # Separado de context_raw porque responde outra pergunta: aquele
            # descreve a condicao dos times (descanso, tabela, mando), este
            # descreve o que a partida e' dentro da competicao.
            "match_context_raw": match_context,
            "profile_score": team_profile_model.profile_score_for_market(matchup_data, market_type),
            "matchup_raw": matchup_data.get(market_type) if matchup_data else None,
            "news_score": news_score,
            "news_raw": news_data,
            "team_strength": team_strength_data,
            "referee_signal": referee_sig if family in _CARDS_FAMILIES else None,
            "game_intensity": game_intensity if family in _CARDS_FAMILIES else None,
        }
        if debug:
            candidate["_all_lines"] = ranking.evaluate_all_lines(line_candidates, config, data_quality_score)
        candidates.append(candidate)

    # Gate de contexto ANTES da camada probabilistica: nao adianta calibrar e
    # ancorar uma estimativa que veio da distribuicao errada. Um "Under
    # cartoes" em volta de mata-mata decisivo nao esta' mal calibrado -- esta'
    # descrevendo outro tipo de jogo.
    if match_context and config.use_context_gate:
        sobreviventes = []
        for c in candidates:
            veredito = context_gate.evaluate(
                c, match_context, delegar_lados=config.use_tie_effect)
            c["context_gate"] = veredito
            if veredito["bloqueado"]:
                _rastrear(rastro, nivel="familia", market_type=c.get("market_type"),
                          scope=c.get("scope"), status="eliminada",
                          motivo=context_gate.explicar_rejeicao(c, veredito))
                if debug:
                    eliminated_markets.append({
                        "family": c.get("market_type"), "scope": None,
                        "market_type": c.get("market_type"),
                        "reason": context_gate.explicar_rejeicao(c, veredito),
                    })
                continue
            if veredito["penalidade"]:
                p = max(0.0, round(c["taxa_real"] - veredito["penalidade"], 4))
                c["taxa_real"] = p
                baseline = c.get("prob_baseline_value")
                if baseline is not None:
                    c["edge"] = round(p - baseline, 4)
                c["ev"] = round(p * c["odd"] - 1, 4)
            sobreviventes.append(c)
        candidates = sobreviventes

    # Efeito medido do agregado sobre o mercado DE CADA LADO. Vem DEPOIS do
    # gate (que ja' tirou de circulacao o que nao deveria existir) e ANTES da
    # camada probabilistica, pelo mesmo motivo que o gate: calibrar e ancorar
    # uma probabilidade que ainda vai ser corrigida por contexto seria calibrar
    # um numero intermediario.
    #
    # Diferente do gate, este passo NAO elimina candidato -- ele corrige a
    # estimativa nos dois sentidos, e as duas correcoes tem teto (ver
    # tie_effect.TETO_DE_DELTA).
    if match_context and config.use_tie_effect:
        for c in candidates:
            ef = tie_effect.efeito(c, match_context)
            c["tie_effect"] = ef
            if not ef.get("aplicavel"):
                continue
            if ef["delta_prob"]:
                # A estimativa SEM contexto fica guardada, e nao e' so' rastro:
                # e' o numero que decide a aprovacao quando o ajuste e'
                # positivo (ver ranking._valores_de_aprovacao). O contexto pode
                # melhorar o EV publicado e a ordem do ranking; nao pode ser o
                # que faz um mercado passar no corte.
                c["taxa_real_sem_contexto"] = c["taxa_real"]
                c["ev_sem_contexto"] = c["ev"]
                c["edge_sem_contexto"] = c.get("edge")
                p = max(0.0, min(1.0, round(c["taxa_real"] + ef["delta_prob"], 4)))
                c["taxa_real"] = p
                baseline = c.get("prob_baseline_value")
                if baseline is not None:
                    c["edge"] = round(p - baseline, 4)
                c["ev"] = round(p * c["odd"] - 1, 4)
            if ef["delta_confianca"]:
                c["confidence"] = round(min(max(
                    c["confidence"] + ef["delta_confianca"],
                    config.confidence_min_clamp), config.confidence_max_clamp), 4)
                # Risco DERIVA do confidence -- recalcular aqui e' o que impede
                # um pick sair anunciando "BAIXO" com a confianca ja' descontada
                # pelo regime da partida.
                c["risco"] = confidence.risco_from_confidence(c["confidence"], config)

    candidates = apply_probability_layer(
        candidates, config, calibrators=calibrators, clv_by_market=clv_by_market,
    )

    if debug:
        return {"candidates": candidates, "eliminated_markets": eliminated_markets, "entries_dropped": entries_dropped}
    return candidates


def apply_probability_layer(
    candidates: list, config: PickEngineConfig = DEFAULT_CONFIG,
    calibrators: dict | None = None, clv_by_market: dict | None = None,
) -> list:
    """Calibracao isotonica -> ancoragem de mercado -> desconto de vies de
    selecao, nesta ordem, sobre os candidatos ja montados.

    A ORDEM NAO E' ARBITRARIA. Calibrar primeiro porque a curva foi ajustada
    sobre a probabilidade CRUA do motor -- aplicar depois da ancoragem seria
    calibrar um numero que a curva nunca viu. Ancorar em seguida porque a
    combinacao com o mercado deve usar a melhor estimativa propria disponivel,
    que e' a ja calibrada. Descontar o vies por ultimo porque ele corrige o
    ato de SELECIONAR, que acontece depois de toda a estimativa estar pronta.

    Cada etapa reescreve taxa_real e recalcula edge/EV a partir dela, pra os
    tres numeros nunca sairem de sincronia -- foi assim que a multipla passou
    meses mostrando uma probabilidade que nao correspondia ao proprio EV.

    Com as tres flags em False (padrao) devolve `candidates` sem tocar em
    nada: mesmo objeto, mesmos valores.
    """
    if not candidates:
        return candidates
    if not (config.use_isotonic_calibration or config.use_market_anchor
            or config.use_selection_bias):
        return candidates

    # O desconto de vies depende da dispersao do POOL INTEIRO, entao e'
    # calculado uma vez antes de mexer em qualquer candidato -- calcular
    # depois de alterar os edges mediria a dispersao ja' corrigida.
    bias_info = selection_bias.corrigir(candidates, campo="edge") if config.use_selection_bias else None

    ajustados = []
    for c in candidates:
        novo = dict(c)
        p = novo["taxa_real"]
        rastro: dict = {}

        if config.use_isotonic_calibration and calibrators:
            cal = calibrators.get(novo.get("market_type"))
            if cal is not None:
                p_cal = cal.predict(p)
                if p_cal is not None:
                    rastro["p_pre_calibracao"] = p
                    p = p_cal

        if config.use_market_anchor:
            clv = (clv_by_market or {}).get(novo.get("market_type")) or {}
            ancora = market_anchor.anchor(
                p_modelo=p, p_mercado=novo.get("prob_baseline_value"),
                clv_medio=clv.get("clv_medio"), amostra_clv=clv.get("clv_n", 0),
                clv_significativo=clv.get("clv_significativo", False),
            )
            if ancora["p_final"] is not None:
                rastro["p_pre_ancoragem"] = p
                rastro["ancoragem"] = ancora
                p = ancora["p_final"]

        if bias_info and bias_info["desconto"]:
            rastro["p_pre_vies_selecao"] = p
            rastro["vies_selecao"] = bias_info
            p = max(0.0, round(p - bias_info["desconto"], 4))

        if rastro:
            novo["taxa_real"] = p
            novo["probability_trace"] = rastro
            # edge e EV SEMPRE derivados da probabilidade final -- nunca
            # carregados do calculo anterior.
            baseline = novo.get("prob_baseline_value")
            if baseline is not None:
                novo["edge"] = round(p - baseline, 4)
            novo["ev"] = round(p * novo["odd"] - 1, 4)
        ajustados.append(novo)

    return ajustados


def explain(candidate: dict) -> str:
    """Atalho: gera a explicacao estruturada e ja serializa pro campo
    reasoning (texto) do banco."""
    return explanation.explanation_to_text(explanation.build_explanation(candidate))
