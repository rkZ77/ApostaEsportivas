"""O Pick Boost nao tinha a serie "Como esse mercado vem se comportando".

Ele e' a unica familia gravada com DUAS condicoes numa linha so':
`market` = "Over 1.5 FT + Under 2.5 HT", `market_type` = "boost_over15_under25ht",
`line` = "Over 1.5 FT · Under 2.5 HT". Nenhuma dessas strings casa com familia
nenhuma de `_stat_for_market` -- "Over 1.5 FT + Under 2.5 HT" nao tem "gol" nem
"goal" --, entao a serie saia sem valor em todo jogo, era descartada, e o modal
abria sem a secao que todo outro produto tem.

A saida e' a mesma da multipla: uma serie POR PERNA. A do primeiro tempo mede o
placar do INTERVALO, que `match_statistics` guarda desde sempre.
"""
import market_form
from routers.live import _stat_for_market
from tests.test_home_2026_08 import _codigo, _fonte


def _jogo(fid, gols_casa, gols_fora, ht_casa, ht_fora):
    return {"fixture_id": fid, "match_date": "2026-09-01",
            "home_goals": gols_casa, "away_goals": gols_fora,
            "home_goals_ht": ht_casa, "away_goals_ht": ht_fora}


# 3x1 no fim, 0x0 no intervalo: o Over 1.5 FT paga e o Under 2.5 HT tambem.
# E' o jogo que denuncia a serie do HT lida contra o placar final.
JOGOS = [_jogo(1, 3, 1, 0, 0), _jogo(2, 0, 0, 0, 0), _jogo(3, 2, 2, 2, 1)]


def _serie(market, mtype, line):
    return market_form.serie_do_mercado(JOGOS, market, mtype, line, _stat_for_market)


def test_perna_do_jogo_completo_le_o_placar_final():
    serie = _serie("Gols Mais/Menos", "goals", "Over 1.5")
    assert [i["value"] for i in serie["matches"]] == [4.0, 0.0, 4.0]
    assert serie["greens"] == 2
    assert serie["line"] == 1.5


def test_perna_do_primeiro_tempo_le_o_placar_do_intervalo():
    serie = _serie("Gols HT Mais/Menos", "goals_ht", "Under 2.5")
    assert [i["value"] for i in serie["matches"]] == [0.0, 0.0, 3.0]
    # Under 2.5 HT: paga nos dois primeiros, perde no 2x1 do intervalo.
    assert serie["greens"] == 2
    assert "1º tempo" in serie["label"], "a serie do HT tem que se identificar"


def test_serie_do_ht_nao_e_a_do_jogo_inteiro():
    """O 3x1 que ficou 0x0 no intervalo: com o placar final, o Under 2.5 HT
    apareceria como derrota num jogo em que ele pagou."""
    ht = _serie("Gols HT Mais/Menos", "goals_ht", "Under 2.5")
    ft = _serie("Gols Mais/Menos", "goals", "Under 2.5")
    assert ht["matches"][0]["result"] != ft["matches"][0]["result"]


def test_o_boost_entra_pelas_pernas_como_a_multipla():
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert '_pernas_de_boost' in corpo, "boost voltou a cair no caminho de pick simples"
    pernas = _codigo("routers/suggestions.py", "_pernas_de_boost")
    assert '"goals_ht"' in pernas and '"goals"' in pernas


def test_serie_traz_o_placar_do_intervalo_do_banco():
    """Sem as colunas na consulta, `home_goals_ht` chega None e a serie do HT
    fica vazia -- o mesmo sumico silencioso de antes, um passo adiante."""
    assert "ms.home_goals_ht" in _fonte("routers/suggestions.py")
