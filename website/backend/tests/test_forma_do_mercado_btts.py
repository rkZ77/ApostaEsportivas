"""Ambas Marcam ganha serie por jogo no "Entenda esta analise".

Antes de 2026-08-08 o mercado nao tinha barra nenhuma: `_stat_for_market`
devolvia 1.0/0.0, que decide o pick mas nao e' contador, entao `serie_do_mercado`
nao resolvia jogo nenhum e a rota respondia available=False. O usuario percebeu
comparando com os cards de escanteios, que tem a serie.

O contador certo e' o placar do time que MENOS marcou: ele passa de 0 pra 1
exatamente quando "ambas marcam" acontece. Estes testes prendem as duas pontas
-- que o contador decide igual ao booleano de antes (pra o ticker ao vivo nao
mudar de veredito) e que a serie sai com regua, cor e taxa.
"""
import market_form
from routers.live import _stat_for_market, _pick_status


def _jogo(fixture_id, home_goals, away_goals):
    return {"fixture_id": fixture_id, "match_date": "2026-08-01",
            "home_goals": home_goals, "away_goals": away_goals}


def _serie(jogos, line="Yes"):
    return market_form.serie_do_mercado(
        jogos, "Ambas as Equipes Marcam", "btts", line, _stat_for_market)


# ── o contador ───────────────────────────────────────────────────────────────
def test_valor_e_o_placar_do_time_que_menos_marcou():
    valor, rotulo, _ = _stat_for_market("Ambas as Equipes Marcam", "Yes", {}, {}, 3, 1, "btts")
    assert valor == 1.0
    assert rotulo == "Ambas Marcam"
    assert _stat_for_market("Ambas as Equipes Marcam", "Yes", {}, {}, 2, 2, "btts")[0] == 2.0
    assert _stat_for_market("Ambas as Equipes Marcam", "Yes", {}, {}, 4, 0, "btts")[0] == 0.0


def test_placar_ausente_nao_vira_zero():
    """0 afirma 'alguem levou a zero'. Folha sem placar nao sustenta isso."""
    assert _stat_for_market("Ambas as Equipes Marcam", "Yes", {}, {}, None, 1, "btts")[0] is None


def test_ticker_ao_vivo_mantem_o_mesmo_veredito():
    """Todo consumidor de cur_val compara com 1.0 -- trocar o booleano pelo
    minimo do placar nao pode mudar nenhum desses vereditos."""
    for hg, ag in ((1, 1), (3, 2), (2, 0), (0, 0), (5, 0)):
        valor, _, _ = _stat_for_market("Ambas as Equipes Marcam", "Yes", {}, {}, hg, ag, "btts")
        ambas = hg > 0 and ag > 0
        assert _pick_status(valor, "Yes") == ("winning" if ambas else "losing")
        assert _pick_status(valor, "No") == ("losing" if ambas else "winning")


# ── a serie ──────────────────────────────────────────────────────────────────
def test_serie_resolve_cada_jogo_em_vez_de_sumir():
    serie = _serie([_jogo(1, 2, 1), _jogo(2, 3, 0), _jogo(3, 1, 1)])
    assert serie["resolved"] == 3
    assert [m["result"] for m in serie["matches"]] == ["GREEN", "RED", "GREEN"]
    assert serie["greens"] == 2
    assert serie["hit_rate"] == round(2 / 3, 4)


def test_serie_tem_regua_em_meio_gol():
    """Sem linha o grafico desenha barras sem nada contra o que le-las."""
    assert _serie([_jogo(1, 2, 1)])["line"] == 0.5


def test_rotulo_descreve_o_contador_nao_o_mercado():
    assert _serie([_jogo(1, 2, 1)])["label"] == "Gols do time que menos marcou"


def test_nao_inverte_o_lado_no_pick_de_nao():
    serie = _serie([_jogo(1, 2, 1), _jogo(2, 3, 0)], line="No")
    assert [m["result"] for m in serie["matches"]] == ["RED", "GREEN"]


def test_jogo_sem_placar_fica_fora_da_taxa():
    serie = _serie([_jogo(1, 2, 1), _jogo(2, None, None)])
    assert serie["resolved"] == 1
    assert serie["matches"][1]["value"] is None
    assert serie["matches"][1]["result"] is None


def test_media_sai_do_contador_nao_do_booleano():
    """Media do minimo do placar (1, 0, 1) = 0.67. Com o 1.0/0.0 de antes essa
    media seria a propria taxa de acerto, dois numeros iguais no mesmo card."""
    serie = _serie([_jogo(1, 2, 1), _jogo(2, 3, 0), _jogo(3, 1, 4)])
    assert serie["average"] == 0.67
    assert serie["hit_rate"] != serie["average"]


def test_over_under_continua_igual():
    """A mudanca do BTTS nao pode ter mexido no caminho de escanteios."""
    jogos = [{"fixture_id": 9, "match_date": "2026-08-01", "home_corners": 6,
              "away_corners": 5, "home_goals": 1, "away_goals": 0}]
    serie = market_form.serie_do_mercado(
        jogos, "Escanteios Mais/Menos", "corners", "Over 9.5", _stat_for_market)
    assert serie["line"] == 9.5
    assert serie["matches"][0]["value"] == 11.0
    assert serie["matches"][0]["result"] == "GREEN"
