"""O arbitro decide parte do cartao, entao ele decide parte da probabilidade.

Ate' 2026-08-10 o arbitro so' existia como porteira (cards_market_eligible) e
como -0.15..+0.15 num score de intensidade que nao chegava na conta. O caso que
mostrou o custo: pick VIP #1579 (RB Bragantino x Corinthians, "Cartoes Over 4.5"
a 71.8%, RED com 4 cartoes). Raphael Claus estava em 3.60 pontos de cartao por
jogo, ABAIXO da linha, e esse numero movia o pick em -0.025 de intensidade.

Medido nos 31 picks de cartao resolvidos com media de arbitro (2026-08-10):
quando a media dele CONTRADIZ a linha, 54.5% de acerto (n=11, -0.64u); quando
concorda, 75.0% (n=20, +5.40u).
"""
import pytest

from services.pick_engine import orchestrator, probability_model, referee_model
from services.pick_engine.config import DEFAULT_CONFIG


def _arbitro(avg_yellow, avg_red=0.0, games=5, fallback=False):
    return {"reliable": True, "games": games, "avg_yellow": avg_yellow,
            "avg_red": avg_red, "avg_fouls": 24.0, "is_league_fallback": fallback}


# ─────────────────────── o lambda do arbitro ───────────────────────


def test_vermelho_pesa_dois_no_lambda():
    """Mesma convencao de _cards_points: amarelo 1, vermelho 2."""
    so_amarelo = referee_model.cards_lambda(_arbitro(4.0, 0.0, games=100))
    com_vermelho = referee_model.cards_lambda(_arbitro(4.0, 0.5, games=100))
    assert com_vermelho == pytest.approx(so_amarelo + 1.0, abs=0.05)


def test_amostra_curta_e_puxada_pro_baseline():
    """3 jogos apitados nao sustentam a media crua, mas tambem nao valem zero."""
    cru = 2.0
    curto = referee_model.cards_lambda(_arbitro(cru, games=3))
    longo = referee_model.cards_lambda(_arbitro(cru, games=100))
    assert cru < curto < referee_model._REFEREE_CARD_POINTS_BASELINE
    assert abs(longo - cru) < abs(curto - cru), "amostra grande encolhe menos"


def test_fallback_de_liga_nao_vira_estimativa_do_arbitro():
    """Ali o numero e' a media da COMPETICAO, que ja esta embutida em todo o
    resto da conta -- usar como terceira leitura seria contar duas vezes."""
    assert referee_model.cards_lambda(_arbitro(5.0, fallback=True)) is None
    assert referee_model.cards_probability(_arbitro(5.0, fallback=True), 4.5, "over") is None


def test_sem_arbitro_confiavel_nao_ha_estimativa():
    assert referee_model.cards_lambda({"reliable": False, "games": 1}) is None


# ─────────────────────── a probabilidade ───────────────────────


def test_o_caso_1579_em_numeros():
    """Claus em 3.60 pontos com 5 jogos, contra Over 4.5."""
    lam = referee_model.cards_lambda(_arbitro(3.60, 0.0, games=5))
    assert lam == pytest.approx(3.82, abs=0.01)
    p = referee_model.cards_probability(_arbitro(3.60, 0.0, games=5), 4.5, "over")
    # family/scope obrigatorios desde 2026-08-20: cartao de partida e'
    # superdisperso (phi 2.28) e a chamada sem eles devolveria Poisson puro,
    # que e' outra distribuicao.
    assert p == pytest.approx(
        probability_model.poisson_prob_for_line(lam, 4.5, "over",
                                                family="cards", scope="total"),
        abs=1e-6)
    assert p < 0.40, "o motor publicou 71.8% neste mercado"


def test_arbitro_rigoroso_sustenta_over():
    """A regra nao e' 'sempre desconfiar': arbitro acima da linha concorda.

    O patamar caiu de 0.70 pra 0.60 em 2026-08-20, e a queda E' o ponto: com a
    dispersao medida de cartao (phi 2.28), um arbitro de ~7 pontos por jogo
    sustenta 64% em Over 4.5, nao 74%. Os 10pp de diferenca eram o Poisson
    afirmando variancia = media num mercado em que ela e' o dobro.
    """
    p = referee_model.cards_probability(_arbitro(6.5, 0.3, games=12), 4.5, "over")
    assert p > 0.60
    assert p < probability_model.poisson_prob_for_line(
        referee_model.cards_lambda(_arbitro(6.5, 0.3, games=12)), 4.5, "over"), (
        "a Binomial Negativa tem que ficar ABAIXO do Poisson nesta faixa")


# ─────────────────── dentro do motor ───────────────────


def _jogo(i, amarelos_casa, amarelos_fora):
    return {
        "match_date": f"2026-07-{i + 1:02d}",
        "home_team_id": 1, "away_team_id": 2,
        "home_yellow_cards": amarelos_casa, "away_yellow_cards": amarelos_fora,
        "home_red_cards": 0, "away_red_cards": 0,
        "opponent_rank": None,
    }


def _odds(linha="4.5"):
    base = {"market_id": 9, "market_name": "Cards Over/Under",
            "line": linha, "bookmakers_count": 3}
    return [{**base, "value": "Over", "best_odd": 2.00},
            {**base, "value": "Under", "best_odd": 2.00}]


def _rodar(referee_stats, linha="4.5"):
    """Times que dao MUITO cartao (9 por jogo) -- a taxa empirica e o modelo
    dos times concordam em Over 4.5. So' o arbitro discorda.

    Eram 7 por jogo ate' 2026-08-20. Com a dispersao medida de cartao e o
    limiar em 0.12, um jogo de 7 cartoes da' 83% na contagem e 71% no modelo:
    os TIMES ja' discordavam entre si, e o cenario deixava de isolar o
    arbitro, que e' a variavel que estes testes existem pra medir."""
    hist = [_jogo(i, 5, 4) for i in range(10)]
    return orchestrator.analyze_fixture_markets(
        _odds(linha), hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
        referee_stats=referee_stats,
        league_stats={"games": 200, "avg_yellow": 4.0, "avg_red": 0.1},
    )


def test_arbitro_muito_permissivo_ja_era_barrado_pela_porteira():
    """Antes da terceira estimativa existir, o unico efeito do arbitro era este:
    media MUITO baixa derruba o score de intensidade abaixo do corte e o mercado
    de cartoes nem e' analisado. Continua valendo -- o que faltava era o meio do
    caminho, o arbitro que passa na porteira e mesmo assim contradiz a linha."""
    assert not [x for x in _rodar({"games": 8, "avg_yellow": 2.0, "avg_red": 0.0})
                if x["market_type"] == "cards"]


def test_arbitro_permissivo_rebaixa_o_over_dos_times():
    """Times de 9 cartoes por jogo (taxa 83%, modelo 85%) com um arbitro de 3.4
    pontos: as duas leituras dos times concordam entre si e o arbitro discorda
    das duas. E' a forma exata do #1579."""
    permissivo = {"games": 8, "avg_yellow": 3.0, "avg_red": 0.0}
    c = next(x for x in _rodar(permissivo) if x["market_type"] == "cards")
    assert c["value"] == "Over"
    assert c["referee_probability"] is not None
    assert c["referee_fit_diff"] > DEFAULT_CONFIG.model_disagreement_threshold
    # a probabilidade publicada vira a do arbitro, a menor das tres
    assert c["taxa_real"] == c["referee_probability"]
    assert c["taxa_real"] < c["taxa_real_pre_desacordo"]
    # e edge/EV/confidence saem da nova, nunca da anterior
    assert c["ev"] == pytest.approx(c["taxa_real"] * c["odd"] - 1, abs=1e-4)
    assert c["edge"] == pytest.approx(c["taxa_real"] - c["prob_baseline_value"], abs=1e-4)


def test_arbitro_de_acordo_nao_mexe_em_nada():
    """Arbitro rigoroso num jogo de times rigorosos: as tres leituras se
    sustentam e a probabilidade fica onde estava.

    O arbitro deste teste subiu de 8.0 pra 10.0 amarelos em 2026-08-20, e o
    motivo importa: com a dispersao medida, um arbitro de 6.7 pontos NAO
    sustenta 83% em Over 4.5 -- ele sustenta 68%, e essa distancia passa do
    limiar de desacordo. Sob o Poisson ele parecia sustentar 79% e concordar.
    Ou seja: o cenario nunca foi de concordancia, a distribuicao errada e' que
    escondia a discordancia. Pra continuar testando "quando concorda, nao
    mexe", o arbitro precisa concordar de verdade.
    """
    rigoroso = {"games": 8, "avg_yellow": 10.0, "avg_red": 0.0}
    c = next(x for x in _rodar(rigoroso) if x["market_type"] == "cards")
    assert c["referee_probability"] is not None
    assert "taxa_real_pre_desacordo" not in c
    assert c["taxa_real"] == pytest.approx(0.8333, abs=1e-3)


def test_o_rastro_guarda_a_leitura_do_arbitro_mesmo_sem_rebaixar():
    """Sem o numero gravado nao da' pra medir depois se o sinal esta ajudando --
    foi essa falta que atrasou a descoberta do #1579."""
    rigoroso = {"games": 8, "avg_yellow": 10.0, "avg_red": 0.0}
    c = next(x for x in _rodar(rigoroso) if x["market_type"] == "cards")
    assert c["referee_lambda"] is not None
    assert c["referee_probability"] is not None


def test_fora_de_cartoes_o_arbitro_nao_entra():
    """Em escanteio ou gol o arbitro nao e' causa; uma terceira estimativa ali
    seria inventar relacao."""
    hist = [{**_jogo(i, 4, 3), "total_corners": 9, "home_corners": 5,
             "away_corners": 4} for i in range(10)]
    odds = [{"market_id": 3, "market_name": "Corners Over/Under", "line": "8.5",
             "bookmakers_count": 3, "value": v, "best_odd": 2.00}
            for v in ("Over", "Under")]
    candidatos = orchestrator.analyze_fixture_markets(
        odds, hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
        referee_stats={"games": 8, "avg_yellow": 2.0, "avg_red": 0.0},
    )
    c = next(x for x in candidatos if x["market_type"] == "corners")
    assert c["referee_probability"] is None
    assert c["referee_lambda"] is None


# ────── a escolha da LINHA passa a ver as tres leituras (2026-08-10) ──────


def _odds_duas_linhas():
    return [
        {"market_id": 9, "market_name": "Cards Over/Under", "line": linha,
         "bookmakers_count": 3, "value": v, "best_odd": 2.00}
        for linha in ("2.5", "7.5") for v in ("Over", "Under")
    ]


def _rodar_duas_linhas(referee_stats):
    """Times de 5 cartoes por jogo: Over 2.5 e Under 7.5 batem os dois em 100%
    do historico, entao a taxa empirica sozinha nao sabe escolher entre eles.

    As linhas abriram de 3.5/5.5 pra 2.5/7.5 em 2026-08-20. Com a dispersao
    medida, 3.5 e 5.5 ficam os DOIS com o modelo perto de 62% num lambda de
    5.0 -- empatados, e o desempate passa a ser ruido em vez do arbitro. O par
    aberto devolve a folga que o cenario precisa pra mostrar a troca de lado.
    """
    hist = [_jogo(i, 3, 2) for i in range(10)]
    return orchestrator.analyze_fixture_markets(
        _odds_duas_linhas(), hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
        referee_stats=referee_stats,
        league_stats={"games": 200, "avg_yellow": 4.0, "avg_red": 0.1},
    )


def test_arbitro_permissivo_faz_o_motor_escolher_o_outro_lado():
    """A pergunta do usuario (2026-08-10): "ele corta, mas pode pegar um under?"

    Podia nao. A linha era escolhida pela taxa empirica sozinha e SO' DEPOIS
    levava o corte -- o motor fechava em Over 3.5, tomava o corte do arbitro em
    cima dela e ficava sem pick, sem nunca ter olhado o outro lado do mesmo
    mercado. Agora as tres leituras sao resolvidas linha por linha, ANTES da
    escolha, e a comparacao acontece entre numeros ja corrigidos."""
    sem_arbitro = next(x for x in _rodar_duas_linhas(None) if x["market_type"] == "cards")
    assert (sem_arbitro["value"], sem_arbitro["line"]) == ("Over", "2.5")

    permissivo = next(x for x in _rodar_duas_linhas({"games": 8, "avg_yellow": 3.0, "avg_red": 0.0})
                      if x["market_type"] == "cards")
    assert permissivo["value"] == "Under", "ficou no lado que o arbitro contradiz"
    assert permissivo["line"] == "7.5"
    # e o que o arbitro diz do lado escolhido nao derruba nada: ele CONCORDA
    assert permissivo["referee_probability"] > permissivo["taxa_real"]


def test_a_correcao_acontece_antes_da_escolha_nao_depois():
    """Trava a ordem, que e' o coracao da mudanca: toda linha candidata carrega
    a probabilidade ja corrigida, nao so' a vencedora."""
    cs = _rodar_duas_linhas({"games": 8, "avg_yellow": 3.0, "avg_red": 0.0})
    c = next(x for x in cs if x["market_type"] == "cards")
    linhas = c.get("_all_lines")
    assert linhas is None, "_all_lines so' existe em debug"
    # a vencedora traz o rastro das tres leituras
    for chave in ("poisson_probability", "model_fit_diff",
                  "referee_probability", "referee_fit_diff", "referee_lambda"):
        assert chave in c, chave
