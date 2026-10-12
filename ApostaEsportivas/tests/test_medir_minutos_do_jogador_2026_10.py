"""A medicao de minutos do jogador (11/10/2026) · so' as contas, sem banco."""
from scripts import medir_minutos_do_jogador as m
from services.player_stats_engine import methods as cat

METODO = cat.de("shots_on")


def _a(minutos, valor, reserva=False, dia=1):
    return {"player_id": 1, "league_id": 71, "season": 2026, "match_date": dia,
            "minutes": minutos, "is_substitute": reserva, "valor": valor}


def test_entrada_curta_pesa_pelos_minutos():
    """2 chutes em 90' e 0 em 5': a taxa mal se mexe com a entrada curta."""
    historico = [_a(5, 0, reserva=True), _a(90, 2), _a(90, 2), _a(90, 2), _a(90, 2)]
    prev = m.previsao_por_minutos(historico, 1)
    assert 1.9 < prev <= 2.0


def test_titular_que_saiu_cedo_entra_na_conta_por_minutos():
    """Saiu aos 30' sem chutar: o 60+ ignora o jogo, o por-minutos nao."""
    historico = [_a(30, 0), _a(90, 2), _a(90, 2), _a(90, 2)]
    assert m.previsao_atual(historico, 1) == 2.0
    assert m.previsao_por_minutos(historico, 1) < 2.0


def test_piso_de_amostra_e_regime():
    assert m.previsao_atual([_a(90, 1)], 3) is None
    # So' entradas do banco: nao ha' como saber quantos minutos ele joga
    # quando comeca, entao nao projeta.
    assert m.previsao_por_minutos([_a(20, 1, True), _a(15, 0, True)], 1) is None


def test_caminhada_so_usa_o_passado_e_so_mira_titular():
    folhas = [_a(90, 1, dia=1), _a(90, 3, dia=2), _a(10, 0, reserva=True, dia=3), _a(90, 2, dia=4)]
    regs = m.caminhar(folhas, METODO)
    assert [r["real"] for r in regs] == [1.0, 3.0, 2.0]       # o jogo do banco nao e' alvo
    assert regs[0]["atual"] is None                            # sem passado nenhum


def test_resumo_compara_na_mesma_amostra():
    regs = [{"real": 1.0, "minutos": 90, "atual": 1.5, "minutos_est": 1.0},
            {"real": 0.0, "minutos": 40, "atual": 1.5, "minutos_est": 0.8},
            {"real": 2.0, "minutos": 90, "atual": None, "minutos_est": 1.2}]
    s = m.resumo(regs, phi=1.2)
    assert s["n"] == 2 and s["so_minutos"] == 1
    assert s["atual"]["vies"] > s["minutos_est"]["vies"]
    assert set(s["atual"]["brier"]) == set(m.LINHAS)
