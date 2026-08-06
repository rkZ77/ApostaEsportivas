"""Atribuicao de desempenho: CLV, EV realizado, faixas e agregacao.

Toda a matematica do painel e' testada aqui sem banco -- e' o que separa
"o dashboard mostra um numero" de "o numero esta certo".
"""
import pytest

from services.pick_engine import attribution as at


# ----------------------------------------------------------------------
# CLV
# ----------------------------------------------------------------------
def test_clv_positivo_quando_a_odd_pega_e_melhor_que_o_fechamento():
    assert at.clv(2.10, 1.90) == pytest.approx(0.1053, abs=1e-3)


def test_clv_negativo_quando_o_mercado_fecha_acima():
    assert at.clv(1.80, 2.00) == pytest.approx(-0.10, abs=1e-3)


def test_clv_zero_quando_nao_houve_movimento():
    assert at.clv(1.95, 1.95) == 0.0


def test_clv_none_sem_fechamento():
    """Nao pode virar zero: isso puxaria a media pra perto de zero justo nos
    mercados com pior cobertura de fechamento."""
    assert at.clv(1.95, None) is None
    assert at.clv(None, 1.95) is None


def test_clv_rejeita_odd_invalida():
    assert at.clv(1.0, 1.90) is None
    assert at.clv(1.90, 0.5) is None


# ----------------------------------------------------------------------
# EV realizado
# ----------------------------------------------------------------------
def test_ev_realizado_green_e_o_lucro_liquido():
    assert at.realized_ev("GREEN", 2.40) == pytest.approx(1.40)


def test_ev_realizado_red_perde_a_unidade():
    assert at.realized_ev("RED", 2.40) == -1.0


def test_ev_realizado_push_e_neutro():
    assert at.realized_ev("PUSH", 2.40) == 0.0
    assert at.realized_ev("PUSH", None) == 0.0


def test_ev_realizado_none_sem_resultado():
    assert at.realized_ev(None, 2.40) is None


# ----------------------------------------------------------------------
# Faixas e papeis
# ----------------------------------------------------------------------
@pytest.mark.parametrize("odd,esperado", [
    (1.39, "1.01-1.50"), (1.50, "1.01-1.50"), (1.75, "1.51-2.00"),
    (2.00, "1.51-2.00"), (2.50, "2.01-3.00"), (7.00, "3.01+"),
])
def test_faixa_de_odd(odd, esperado):
    assert at.odd_band(odd) == esperado


def test_faixa_de_odd_rejeita_invalida():
    assert at.odd_band(None) is None
    assert at.odd_band(1.0) is None


def test_papel_da_selecao_pela_probabilidade_implicita():
    assert at.selection_role(1.60) == "favorito"   # implicita 62,5%
    assert at.selection_role(2.00) == "favorito"   # implicita 50%, no limite
    assert at.selection_role(2.50) == "azarao"     # implicita 40%
    assert at.selection_role(None) is None


@pytest.mark.parametrize("market,line,esperado", [
    ("Escanteios Casa Mais/Menos", "Over 4.5", "home"),
    ("Total de Gols Visitante", "Over 1.5", "away"),
    ("Gols Mais/Menos", "Over 2.5", "neutral"),
    ("Ambas Marcam", "Sim", "neutral"),
    ("Home Corners Over/Under", "Over 5.5", "home"),
])
def test_lado_da_aposta(market, line, esperado):
    assert at.pick_side(market, line) == esperado


@pytest.mark.parametrize("hora,esperado", [
    (0, "madrugada"), (5, "madrugada"), (6, "manha"), (11, "manha"),
    (12, "tarde"), (17, "tarde"), (18, "noite"), (21, "noite"), (23, "noite"),
])
def test_faixa_horaria(hora, esperado):
    assert at.hour_bucket(hora) == esperado


def test_faixa_horaria_rejeita_invalida():
    assert at.hour_bucket(None) is None
    assert at.hour_bucket(24) is None
    assert at.hour_bucket(-1) is None


# ----------------------------------------------------------------------
# Agregacao
# ----------------------------------------------------------------------
def _perna(result="GREEN", odd=2.0, prob=0.60, ev=0.20, profit=None, clv=None, **extra):
    if profit is None:
        profit = at.realized_ev(result, odd)
    linha = {"result": result, "odd": odd, "probability": prob, "ev": ev,
             "profit": profit, "clv": clv}
    linha.update(extra)
    return linha


def test_resumo_calcula_acerto_e_roi():
    legs = [_perna("GREEN"), _perna("GREEN"), _perna("RED"), _perna("RED")]
    r = at.summarize(legs)
    assert r["n_binarias"] == 4
    assert r["hit_rate"] == pytest.approx(0.5)
    # 2 x (+1.0) e 2 x (-1.0) -> ROI zero
    assert r["roi"] == pytest.approx(0.0)


def test_push_conta_no_roi_mas_nao_no_acerto():
    legs = [_perna("GREEN"), _perna("RED"), _perna("PUSH")]
    r = at.summarize(legs)
    assert r["n_binarias"] == 2       # PUSH fora do hit rate
    assert r["n_resolvidas"] == 3     # mas dentro do ROI
    assert r["hit_rate"] == pytest.approx(0.5)


def test_intervalo_de_confianca_exige_amostra():
    assert at.confidence_interval([0.5]) is None
    assert at.confidence_interval([]) is None
    assert at.confidence_interval([1.0, -1.0, 1.0, -1.0]) is not None


def test_roi_pequeno_nao_e_significativo():
    """4 picks com ROI positivo nao distinguem vantagem de sorte -- o painel
    tem que dizer isso em vez de mostrar so' o ponto."""
    legs = [_perna("GREEN"), _perna("GREEN"), _perna("GREEN"), _perna("RED")]
    r = at.summarize(legs)
    assert r["roi"] > 0
    assert r["roi_significativo"] is False


def test_clv_consistente_vira_significativo_com_menos_amostra_que_roi():
    """O ponto central do modulo: CLV mede processo, nao resultado, entao
    converge muito mais rapido."""
    legs = [_perna("GREEN" if i % 2 else "RED", clv=0.04 + (i % 3) * 0.004) for i in range(14)]
    r = at.summarize(legs)
    assert r["clv_significativo"] is True
    assert r["roi_significativo"] is False


def test_brier_usa_probabilidade_nao_confidence():
    """Se o Brier lesse `confidence`, este caso daria outro numero -- o
    campo esta' presente de proposito com valor bem diferente."""
    legs = [_perna("GREEN", prob=1.0, confidence=0.5), _perna("RED", prob=0.0, confidence=0.5)]
    r = at.summarize(legs)
    assert r["brier"] == pytest.approx(0.0)


def test_gap_ev_expoe_a_diferenca_entre_prometido_e_entregue():
    # EV prometido +20% por perna, resultado real 0% (metade GREEN a 2.0).
    legs = [_perna("GREEN", ev=0.20), _perna("RED", ev=0.20)]
    r = at.summarize(legs)
    assert r["ev_esperado_medio"] == pytest.approx(0.20)
    assert r["roi"] == pytest.approx(0.0)
    assert r["gap_ev"] == pytest.approx(0.20)


def test_agrupamento_por_dimensao():
    legs = [
        _perna("GREEN", market_type="goals"), _perna("RED", market_type="goals"),
        _perna("GREEN", market_type="corners"),
    ]
    grupos = at.group_by(legs, "market_type")
    assert set(grupos) == {"goals", "corners"}
    assert grupos["goals"]["n_binarias"] == 2
    assert grupos["corners"]["hit_rate"] == pytest.approx(1.0)


def test_valor_ausente_vira_grupo_visivel():
    """Cobertura ruim de dado e' informacao, nao motivo pra sumir com a linha."""
    legs = [_perna("GREEN", referee="Fulano"), _perna("RED")]
    grupos = at.group_by(legs, "referee")
    assert "(nao atribuido)" in grupos


def test_relatorio_completo_cobre_as_dimensoes_pedidas():
    legs = [_perna("GREEN", market_type="goals", league_id=71, bet_house="Bet365")]
    rel = at.full_report(legs)
    for d in ("market_type", "league_id", "bet_house", "referee", "round_phase",
              "season", "competition_type", "pick_side", "selection_role", "odd_band"):
        assert d in rel["por_dimensao"]
    assert rel["geral"]["n_total"] == 1
