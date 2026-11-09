"""A medicao da regua unica do pre-jogo (09/11/2026) · so' as contas, sem banco."""
from scripts import medir_regua_unica as m
from services.ai_result_checker_service import AIResultCheckerService


def _cand(p=0.72, q=0.60, odd=1.60, nivel="mercado", edge=0.12, best=False,
          market="Gols Mais/Menos", line="Over 2.5", mt="goals"):
    return {"nivel": nivel, "taxa_real": p, "odd": odd, "edge": edge, "is_best_pick": best,
            "market_name": market, "line": line, "market_type": mt,
            "avaliacao": {"probabilidade": {"mercado_no_vig": q}}}


def test_so_entra_o_nivel_mercado_com_preco():
    assert m.candidato(_cand()) is not None
    assert m.candidato(_cand(nivel="linha")) is None
    assert m.candidato(_cand(q=None)) is None
    assert m.candidato(_cand(odd=1.0)) is None


def test_ancora_fica_entre_motor_e_mercado():
    c = m.candidato(_cand(p=0.75, q=0.55))
    pf = m.ancorada(c, 0.35)
    assert 0.55 < pf < 0.75
    assert pf < (0.75 + 0.55) / 2  # mais perto do mercado com w < 0.5


def test_reguas_de_piso_e_de_ancora():
    regras = dict(m.REGUAS)
    alto = m.candidato(_cand(p=0.72, q=0.62, odd=1.70))
    baixo = m.candidato(_cand(p=0.66, q=0.60, odd=1.60))
    caro = m.candidato(_cand(p=0.80, q=0.78, odd=1.25))
    assert regras["piso 70%"](alto) and not regras["piso 70%"](baixo)
    assert regras["piso 70%"](alto) and regras["piso 70% + edge 8pp"](alto)
    assert not regras["piso 70%"](caro)  # odd abaixo de 1.35
    # Mercado em 62% e a melhor casa pagando 1.70: a ancorada ~0.655, EV ~11%.
    assert regras["ancora w=0.35 + EV>=4%"](alto)
    # Mercado concordando com a odd (q ~ 1/odd): sem valor, nao passa.
    justo = m.candidato(_cand(p=0.72, q=0.62, odd=1.55))
    assert not regras["ancora w=0.35 + EV>=4%"](justo)


def test_liquida_pelo_verificador_do_site():
    checker = AIResultCheckerService("picks_vip")
    c = m.candidato(_cand(line="Over 2.5"))
    stats = {"status": "FT", "home_goals": 2, "away_goals": 1, "total_goals": 3}
    r = m.liquidar(checker, stats, c, "Flamengo", "Palmeiras")
    assert r["g"] == 1 and abs(r["lucro"] - 0.60) < 1e-9
    stats_red = {"status": "FT", "home_goals": 1, "away_goals": 1, "total_goals": 2}
    assert m.liquidar(checker, stats_red, c, "Flamengo", "Palmeiras")["lucro"] == -1.0


def test_push_e_pendente_ficam_fora():
    checker = AIResultCheckerService("picks_vip")
    c = m.candidato(_cand(line="Over 2.0"))
    stats = {"status": "FT", "home_goals": 1, "away_goals": 1, "total_goals": 2}
    assert m.liquidar(checker, stats, c, "Flamengo", "Palmeiras") is None


def test_veredito_exige_amostra_ruido_e_as_duas_metades():
    def r(n, roi, ep):
        return {"n": n, "roi": roi, "ep": ep}
    assert "curta" in m.veredito(r(10, 0.5, 0.01), r(5, 0.5, 0), r(5, 0.5, 0))
    assert "FORA DO RUIDO" in m.veredito(r(100, 0.10, 0.03), r(50, 0.1, 0), r(50, 0.1, 0))
    assert "sem lucro" in m.veredito(r(100, 0.10, 0.03), r(50, -0.1, 0), r(50, 0.3, 0))
    assert "PERDE" in m.veredito(r(100, -0.10, 0.03), r(50, -0.1, 0), r(50, -0.1, 0))
