"""Tres correcoes de 2026-08-08, todas nascidas do mesmo pick publicado em
producao: VIP #1573, "Escanteios Visitante Over 4.5" a 78% de probabilidade.

O Fluminense bate essa linha em 40% dos jogos FORA. Os 78% sairam de somar
tres coisas erradas, e cada teste aqui trava uma delas:

1. o pool do mercado de visitante incluia os jogos EM CASA do time;
2. o prior bayesiano era o hit-rate dos proprios picks (0.857 medido em prod),
   entao 40% da probabilidade final vinha de "escanteio vem ganhando";
3. o Poisson dizia 53.5% e o desacordo de 24.5pp nao mexia em nada.
"""
import pytest

from services.pick_engine import bayesian_model, confidence, orchestrator, stats_model
from services.pick_engine.config import DEFAULT_CONFIG


def _jogo(match_date, home_team_id, away_team_id, home_corners, away_corners):
    return {
        "match_date": match_date,
        "home_team_id": home_team_id, "away_team_id": away_team_id,
        "home_corners": home_corners, "away_corners": away_corners,
        "opponent_rank": None,
    }


# Time 10 e' o visitante do jogo analisado. Em casa faz muito escanteio (8, 9),
# fora faz pouco (2, 3) -- exatamente o formato do caso real.
_HISTORICO_VISITANTE = [
    _jogo("2026-08-01", 10, 99, 8, 4),   # jogou em CASA
    _jogo("2026-07-25", 98, 10, 5, 2),   # jogou FORA
    _jogo("2026-07-18", 10, 97, 9, 3),   # jogou em CASA
    _jogo("2026-07-11", 96, 10, 6, 3),   # jogou FORA
]


# ───────────────────────── 1. mando ─────────────────────────


def test_pool_de_mercado_visitante_so_pega_jogo_fora():
    pool, _ = stats_model.pool_and_field("corners", "away", [], _HISTORICO_VISITANTE, team_id=10)
    assert len(pool) == 2
    assert all(j["away_team_id"] == 10 for j in pool), "jogo em casa nao responde a esse mercado"


def test_pool_de_mercado_da_casa_so_pega_jogo_em_casa():
    pool, _ = stats_model.pool_and_field("corners", "home", _HISTORICO_VISITANTE, [], team_id=10)
    assert len(pool) == 2
    assert all(j["home_team_id"] == 10 for j in pool)


def test_pool_de_total_pega_o_mandante_em_casa_e_o_visitante_fora():
    """Mercado de total e' sobre o JOGO, mas o jogo tem mando: o que descreve
    "Goias x Londrina" e' o Goias em casa mais o Londrina fora. Estendido em
    2026-08-10, ver o caso de producao na docstring de pool_and_field."""
    pool, _ = stats_model.pool_and_field(
        "corners", "total", _HISTORICO_VISITANTE, _HISTORICO_VISITANTE,
        team_id=None, home_team_id=10, away_team_id=10)
    assert len(pool) == 4          # 2 em casa do mandante + 2 fora do visitante
    em_casa = [j for j in pool if j["home_team_id"] == 10]
    fora = [j for j in pool if j["away_team_id"] == 10]
    assert len(em_casa) == 2 and len(fora) == 2


def test_pool_de_total_sem_os_ids_nao_filtra():
    """Mesma regra de _somente_no_mando: sem id nao da' pra saber o mando, e
    chutar seria pior que nao filtrar."""
    pool, _ = stats_model.pool_and_field(
        "corners", "total", _HISTORICO_VISITANTE, _HISTORICO_VISITANTE)
    assert len(pool) == len(_HISTORICO_VISITANTE) * 2


def test_sem_team_id_o_pool_nao_e_filtrado():
    """Nao da' pra saber qual lado e' o time sem o id -- chutar seria pior que
    nao filtrar, entao o comportamento antigo fica preservado."""
    pool, _ = stats_model.pool_and_field("corners", "away", [], _HISTORICO_VISITANTE)
    assert len(pool) == len(_HISTORICO_VISITANTE)


def test_taxa_do_visitante_deixa_de_herdar_o_desempenho_em_casa():
    """O bug em uma linha. resolve_side ja lia a coluna do time certo em cada
    jogo (8, 2, 9, 3), entao Over 4.5 batia nos DOIS jogos em casa e a taxa
    saia 50% -- num mercado que so' fala dos jogos fora, onde bate 0 de 2."""
    hit_fn = stats_model._build_market_hit_fn("corners", "away", "Over", "4.5", team_id=10)
    sem_filtro = stats_model.weighted_rate(_HISTORICO_VISITANTE, hit_fn)
    assert sem_filtro["amostra"] == 4
    assert sem_filtro["taxa_bruta"] == 0.5

    com_filtro = stats_model.market_taxa(
        "corners", "away", "Over", "4.5", [], _HISTORICO_VISITANTE, team_id=10)
    assert com_filtro["amostra"] == 2
    assert com_filtro["taxa_ponderada"] == 0.0


# ───────────────────────── 2. prior ─────────────────────────


def test_prior_de_mercado_puxa_amostra_curta_pro_consenso_das_casas():
    """n pequeno perto do prior_strength -> o mercado domina; n grande -> a
    evidencia propria domina. E' o que impede amostra curta de virar edge."""
    curta = bayesian_model.shrink_taxa(0.90, amostra=2, prior=0.50)
    longa = bayesian_model.shrink_taxa(0.90, amostra=100, prior=0.50)
    assert curta == pytest.approx((2 * 0.90 + 10 * 0.50) / 12, abs=1e-4)
    assert abs(longa - 0.90) < 0.04


def _odds_over_under(odd_over=2.00, odd_under=2.00, linha="4.5"):
    """Par Over/Under de escanteios com 3 casas dos dois lados -- assim
    resolve_prob_baseline resolve por no-vig, que e' o caminho de producao."""
    base = {"market_id": 1, "market_name": "Corners Over/Under",
            "line": linha, "bookmakers_count": 3}
    return [
        {**base, "value": "Over", "best_odd": odd_over},
        {**base, "value": "Under", "best_odd": odd_under},
    ]


def _historico_total(corners_por_jogo):
    """Jogos do confronto (escopo total): cada um com o total pedido.

    `total_corners` precisa existir: _extract_stat le a coluna "total_X" pronta
    quando a familia tem uma, e sem ela o jogo entra como ZERO escanteios (nao
    como "sem dado") -- foi assim que a primeira versao deste teste mediu o
    lado oposto do mercado sem perceber."""
    return [
        {**_jogo(f"2026-07-{(i % 28) + 1:02d}", 1, 2, c, 0), "total_corners": c}
        for i, c in enumerate(corners_por_jogo)
    ]


def test_prior_do_motor_e_o_mercado_mesmo_com_calibracao_otimista():
    """Trava a FONTE do prior pelo comportamento, nao pelo texto do arquivo.

    calibration_data aqui diz que escanteios acerta 95% (n=40) -- o formato
    exato do que virava prior antes. Se aquele caminho voltar, a probabilidade
    final sobe na direcao de 0.95; com o prior de mercado, ela desce na direcao
    de 0.50 (no-vig do par 2.00/2.00)."""
    hist = _historico_total([9] * 10)          # 10 jogos, todos com 9 escanteios
    calibracao_otimista = {
        "by_market": {"corners": {"n": 40, "hit": 0.95, "conf": 0.80, "gap": -0.15}},
        "by_market_league": {},
    }
    candidatos = orchestrator.analyze_fixture_markets(
        _odds_over_under(linha="4.5"), hist, hist,
        calibration_data=calibracao_otimista,
        home_team_id=1, away_team_id=2,
    )
    over = next(c for c in candidatos if c["value"] == "Over")
    # taxa empirica e' 1.0 (9 > 4.5 em todos), amostra 20, prior de mercado 0.5
    esperado = bayesian_model.shrink_taxa(1.0, amostra=20, prior=0.5)
    assert over["prob_baseline_value"] == 0.5
    assert over["taxa_real"] == pytest.approx(esperado, abs=1e-4)
    assert over["taxa_real"] < 0.90, "prior de 0.95 nao pode estar puxando pra cima"


def test_prior_de_mercado_derruba_o_caso_real():
    """#1573 com os numeros de producao: taxa 72.83% em 15 jogos.
    Prior antigo (0.857, hit-rate dos picks) -> 77.98%, virou pick.
    Prior novo (0.50, mercado no-vig na odd 2.00) -> mais baixo que o antigo.

    NOTA: a assertion original era `novo < DEFAULT_CONFIG.min_taxa`, escrita
    quando min_taxa=0.65. Com min_taxa=0.60 (ajuste de 2026-08-11, pool de
    mando correto reduz taxas honestas para 0.60-0.64) o valor encolhido
    0.637 fica acima do piso -- o que e' o comportamento CORRETO: esse
    candidato real deveria ser aprovado com o prior honesto, e o problema
    era o prior inflado (0.857) que o aprovava com taxa super-estimada.
    O teste agora verifica a direcao certa: prior honesto derruba em relacao
    ao prior inflado (o caso que importa proteger)."""
    antigo = bayesian_model.shrink_taxa(0.7283, amostra=15, prior=0.857)
    novo = bayesian_model.shrink_taxa(0.7283, amostra=15, prior=0.50)
    assert antigo == pytest.approx(0.7798, abs=1e-3)
    # prior honesto produz taxa menor que o prior inflado -- isso e' o que importa
    assert novo < antigo


# ─────────────────────── 3. desacordo ───────────────────────


def test_desacordo_grande_cobra_confidence():
    """Era 0.30 e por isso nunca disparava -- o caso real tinha 0.245."""
    assert confidence.model_fit_adjustment(0.05) == 0.05
    assert confidence.model_fit_adjustment(0.245) == -0.05
    assert confidence.model_fit_adjustment(None) == 0.0


def test_limiar_de_desacordo_bate_com_o_do_ajuste_de_confidence():
    """O mesmo fato nao pode ser grave num lugar e irrelevante no outro."""
    limiar = DEFAULT_CONFIG.model_disagreement_threshold
    assert confidence.model_fit_adjustment(limiar) == -0.05


def test_orchestrator_fica_com_a_estimativa_menor_quando_os_modelos_discordam():
    """10 jogos com EXATAMENTE 5 escanteios (3 do mandante, 2 do visitante).

    A contagem direta diz que Over 4.5 bateu em 100% deles. O Poisson, com o
    mesmo lambda 5, diz ~56% -- a contagem so' parece perfeita porque nenhum
    jogo caiu do outro lado de uma linha colada na media. O motor tem que ficar
    com os 56%, e recalcular edge/EV a partir dele (os tres numeros nunca podem
    sair de sincronia -- foi assim que a multipla passou meses mostrando uma
    probabilidade que nao correspondia ao proprio EV)."""
    hist = [
        {**_jogo(f"2026-07-{i + 1:02d}", 1, 2, 3, 2), "total_corners": 5}
        for i in range(10)
    ]
    candidatos = orchestrator.analyze_fixture_markets(
        _odds_over_under(linha="4.5"), hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
    )
    c = next(x for x in candidatos if x["market_type"] == "corners")
    assert c["value"] == "Over"
    assert c["taxa_real_pre_desacordo"] == pytest.approx(0.8333, abs=1e-3)
    assert c["model_fit_diff"] > DEFAULT_CONFIG.model_disagreement_threshold
    assert c["taxa_real"] == c["poisson_probability"] < 0.60
    # edge e EV derivados da probabilidade REBAIXADA, nao da anterior
    assert c["edge"] == pytest.approx(c["taxa_real"] - c["prob_baseline_value"], abs=1e-4)
    assert c["ev"] == pytest.approx(c["taxa_real"] * c["odd"] - 1, abs=1e-4)


def test_confidence_acompanha_a_probabilidade_rebaixada():
    """Um candidato anunciando 56% de chance com a confianca dos 83% de antes
    seria a mesma dessincronia que a regra existe pra fechar."""
    hist = [
        {**_jogo(f"2026-07-{i + 1:02d}", 1, 2, 3, 2), "total_corners": 5}
        for i in range(10)
    ]
    candidatos = orchestrator.analyze_fixture_markets(
        _odds_over_under(linha="4.5"), hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
    )
    c = next(x for x in candidatos if x["market_type"] == "corners")
    conf_da_taxa_rebaixada = confidence.confidence_score(
        C=c["taxa_real"], Q=c["Q"], K=1.0, config=DEFAULT_CONFIG)
    conf_da_taxa_antiga = confidence.confidence_score(
        C=c["taxa_real_pre_desacordo"], Q=c["Q"], K=1.0, config=DEFAULT_CONFIG)
    # o confidence publicado parte da menor (os deltas de calibracao/variancia/
    # model-fit ainda somam por cima, entao compara com folga)
    assert abs(c["confidence"] - conf_da_taxa_rebaixada) < abs(c["confidence"] - conf_da_taxa_antiga)


def test_desacordo_nunca_sobe_a_probabilidade():
    """A regra e' conservadora nos dois sentidos: se o Poisson for MAIOR que a
    taxa empirica, o motor nao aproveita pra inflar o pick.

    6 jogos de 10 escanteios e 4 de 3, contra Over 4.5: a contagem direta da'
    60% (56.7% depois do encolhimento) e o modelo, com lambda 7.2, da' 75.8%.
    Discordam 19.1pp, acima do limiar -- mas pro lado de cima, e ai nada pode
    acontecer.

    Os numeros do historico mudaram em 2026-08-20 (era 8 e 4). Sob Poisson
    aquele par ja' discordava 19.8pp; sob a Binomial Negativa a distancia cai
    pra 11.3pp e o cenario deixaria de exercitar a regra -- que e' justamente
    o efeito da correcao, o modelo parou de exagerar. Pra continuar testando
    "desacordo pra cima nao faz nada" o desacordo tem que existir."""
    hist = _historico_total([10] * 6 + [3] * 4)
    candidatos = orchestrator.analyze_fixture_markets(
        _odds_over_under(linha="4.5"), hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
    )
    over = next(c for c in candidatos if c["value"] == "Over")
    assert over["poisson_probability"] > over["taxa_real"]
    assert over["model_fit_diff"] > DEFAULT_CONFIG.model_disagreement_threshold
    assert "taxa_real_pre_desacordo" not in over, "rebaixou pra cima"
    assert over["taxa_real"] == pytest.approx(
        bayesian_model.shrink_taxa(0.6, over["amostra"], over["prob_baseline_value"]), abs=1e-4)


# ─────────── 4. o caso Goias x Londrina (2026-08-10) ───────────


def test_taxa_de_total_nao_herda_mais_o_mando_errado():
    """Pick real: "Escanteios Menos de 11.5" @1.73, publicado com 65.2%.

    No card (que desde 2026-08-10 mostra so' o mando do jogo) o Goias EM CASA
    tinha media 12.0 e o Londrina FORA media 14.4 -- a amostra que responde a
    pergunta batia Under 11.5 em 4 de 10. Os outros ~20 jogos do pool eram
    partidas hospedadas por outros times, e foram eles que sustentaram a taxa.

    Aqui o formato do caso, reduzido: o mandante joga jogos de 13 escanteios em
    casa e de 8 fora; o visitante, 8 em casa e 14 fora. Under 11.5 bate em 100%
    do pool misto pela metade errada, e em 0% da metade que descreve o jogo.
    """
    mandante = [
        {**_jogo("2026-08-01", 1, 90, 13, 0), "total_corners": 13},   # em casa
        {**_jogo("2026-07-25", 91, 1, 8, 0),  "total_corners": 8},    # fora
    ]
    visitante = [
        {**_jogo("2026-08-02", 2, 92, 8, 0),  "total_corners": 8},    # em casa
        {**_jogo("2026-07-26", 93, 2, 14, 0), "total_corners": 14},   # fora
    ]

    misto = stats_model.market_taxa(
        "corners", "total", "Under", "11.5", mandante, visitante)
    assert misto["amostra"] == 4
    assert misto["taxa_bruta"] == 0.5, "os jogos do mando errado seguravam a taxa"

    no_mando = stats_model.market_taxa(
        "corners", "total", "Under", "11.5", mandante, visitante,
        home_team_id=1, away_team_id=2)
    assert no_mando["amostra"] == 2       # mandante em casa + visitante fora
    assert no_mando["taxa_ponderada"] == 0.0


def test_variancia_e_taxa_medem_o_MESMO_pool():
    """Penalidade de dispersao calculada sobre um conjunto de jogos e taxa sobre
    outro descreveria uma amostra que nao e' a que sustenta o pick."""
    mandante = [{**_jogo("2026-08-01", 1, 90, 13, 0), "total_corners": 13},
                {**_jogo("2026-07-25", 91, 1, 8, 0), "total_corners": 8}]
    visitante = [{**_jogo("2026-08-02", 2, 92, 8, 0), "total_corners": 8},
                 {**_jogo("2026-07-26", 93, 2, 14, 0), "total_corners": 14}]

    from services.pick_engine import variance_model
    var = variance_model.variance_stats(
        "corners", "total", mandante, visitante, home_team_id=1, away_team_id=2)
    taxa = stats_model.market_taxa(
        "corners", "total", "Under", "11.5", mandante, visitante,
        home_team_id=1, away_team_id=2)
    assert var["amostra"] == taxa["amostra"] == 2
