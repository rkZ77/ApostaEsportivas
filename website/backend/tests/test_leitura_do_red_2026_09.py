"""Leitura do RED pelo que aconteceu no jogo (leitura_do_red.ler).

Usa a mesma função de liquidação do site (_stat_for_market), então o número
que a leitura mostra é o mesmo que decidiu o RED. Nada toca banco.
"""
import leitura_do_red
from routers.live import _stat_for_market


def folha(**extra):
    base = {"home_team_id": 10, "away_team_id": 20,
            "home_goals": 2, "away_goals": 2, "home_goals_ht": 2, "away_goals_ht": 1,
            "home_corners": 6, "away_corners": 5, "home_corners_1h": 3, "away_corners_1h": 2,
            "home_yellow_cards": 2, "away_yellow_cards": 1,
            "home_red_cards": 0, "away_red_cards": 0}
    base.update(extra)
    return base


def ler(market, line, ms=None, trocas=None, market_type=None):
    return leitura_do_red.ler(market, line, market_type, ms if ms is not None else folha(),
                              _stat_for_market, trocas)


def test_under_que_ja_tinha_estourado_no_intervalo():
    r = ler("Gols Mais/Menos", "Under 2.5")
    assert r["categoria"] == "estourou_cedo"
    assert any("intervalo" in f for f in r["fatos"])


def test_perdeu_por_um():
    r = ler("Escanteios Mais/Menos", "Under 10.5")
    assert r["categoria"] == "por_pouco"
    assert r["fatos"][0] == "Terminou em 11 contra a linha 10,5, diferença de 0,5."


def test_perdeu_longe_e_leitura_errada():
    r = ler("Escanteios Mais/Menos", "Over 14.5")
    assert r["categoria"] == "leitura_errada"


def test_expulsao_tem_prioridade():
    r = ler("Escanteios Mais/Menos", "Over 14.5", folha(home_red_cards=1))
    assert r["categoria"] == "evento_atipico"


def test_time_poupado():
    r = ler("Escanteios Mais/Menos", "Over 14.5", trocas={"Flamengo": 7})
    assert r["categoria"] == "time_poupado"
    assert any("Flamengo trocou 7" in f for f in r["fatos"])


def test_mercado_do_1o_tempo_le_o_1o_tempo():
    r = ler("Total de Escanteios (1º Tempo)", "Over 6.5", market_type="corners_1h")
    assert "Terminou em 5" in r["fatos"][0]


def test_sem_folha_nao_afirma_nada():
    r = leitura_do_red.ler("Gols Mais/Menos", "Under 2.5", None, None, _stat_for_market)
    assert r == {"categoria": "sem_folha", "rotulo": "Sem estatística do jogo", "fatos": []}


def test_bilhete_aponta_a_perna_que_derrubou():
    boa = {"rotulo": "A x B, Gols Over 0.5", "result": "GREEN",
           "leitura": ler("Gols Mais/Menos", "Over 0.5")}
    ruim = {"rotulo": "C x D, Gols Under 2.5", "result": "RED",
            "leitura": ler("Gols Mais/Menos", "Under 2.5")}
    r = leitura_do_red.ler_bilhete([boa, ruim])
    assert r["categoria"] == "estourou_cedo"
    assert r["fatos"][0] == "1 de 2 pernas perderam."
    assert r["fatos"][1].startswith("C x D, Gols Under 2.5: Estourou já no 1º tempo.")


def test_alavancagem_sem_result_por_perna_usa_a_folha():
    """4 gols no jogo: o Over 1.5 venceu e o Under 2.5 perdeu."""
    over = {"rotulo": "Over", "result": None, "leitura": ler("Gols Mais/Menos", "Over 1.5")}
    under = {"rotulo": "Under", "result": None, "leitura": ler("Gols Mais/Menos", "Under 2.5")}
    r = leitura_do_red.ler_bilhete([over, under])
    assert r["fatos"][0] == "1 de 2 pernas perderam."
    assert "Under:" in r["fatos"][1]


def test_jogador_que_saiu_cedo():
    r = leitura_do_red.ler_jogador("Over 1.5", 1, 52, False, "Pedro")
    assert r["categoria"] == "saiu_cedo"
    assert "Pedro saiu aos 52 minutos." in r["fatos"]


def test_jogador_que_veio_do_banco():
    r = leitura_do_red.ler_jogador("Over 0.5", 0, 20, True, "Pedro")
    assert r["categoria"] == "veio_do_banco"


def test_jogador_que_jogou_tudo_e_perdeu_por_um():
    r = leitura_do_red.ler_jogador("Over 2.5", 2, 90, False, "Pedro")
    assert r["categoria"] == "por_pouco"
