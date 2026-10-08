"""Bilhete pessoal (06/10/2026): montado no Raio-X, lancado e liquidado na banca."""
import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import bilhete_pessoal as bp  # noqa: E402

BASE = {"fixture_id": 10, "home_team_id": 1, "away_team_id": 2, "home": "Casa", "away": "Fora"}


def perna_time(**k):
    return {**BASE, "tipo": "time", "mercado": "escanteios", "direcao": "mais", "linha": 9.5, **k}


def perna_jogador(**k):
    return {**BASE, "tipo": "jogador", "estat": "chutes_alvo", "minimo": 1,
            "player_id": 77, "player_name": "Hulk", **k}


JOGO = {"status": "FT", "home_goals": 2, "away_goals": 1, "home_corners": 6, "away_corners": 5,
        "home_yellow_cards": 2, "away_yellow_cards": 3, "home_shots_on": 5, "away_shots_on": 3,
        "home_fouls": 11, "away_fouls": 13}


# ── validacao ───────────────────────────────────────────────────────────────
def test_valida_e_limpa_campos_desconhecidos():
    [p] = bp.validar_pernas([perna_time(lixo="x", descricao="Escanteios · Mais de 9.5")])
    assert "lixo" not in p and p["linha"] == 9.5 and p["descricao"]


@pytest.mark.parametrize("ruim", [
    perna_time(mercado="laterais"),   # impedimentos virou mercado em 07/10
    perna_time(direcao="talvez"),
    perna_time(linha="abc"),
    perna_time(fixture_id=None),
    perna_jogador(estat="dribles_magicos"),
    perna_jogador(minimo=0),
    perna_time(mercado="escanteios_time"),          # mercado do time sem dizer qual time
    {**BASE, "tipo": "outro"},
])
def test_recusa_o_que_a_liquidacao_nao_sabe_conferir(ruim):
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([ruim])


def test_selecao_repetida_entra_uma_vez_e_limite_de_pernas():
    assert len(bp.validar_pernas([perna_time(), perna_time(descricao="outra frase")])) == 1
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([])
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([perna_time(linha=0.5 + i) for i in range(bp.MAX_PERNAS + 1)])


# ── liquidacao de uma perna ────────────────────────────────────────────────
def test_mercado_do_jogo_e_do_time():
    assert bp.liquidar_perna(perna_time(), JOGO, None, False, False)[:2] == ("GREEN", 11)
    assert bp.liquidar_perna(perna_time(direcao="menos"), JOGO, None, False, False)[0] == "RED"
    fora = perna_time(mercado="cartoes_time", lado_time="away", linha=2.5)
    assert bp.liquidar_perna(fora, JOGO, None, False, False)[:2] == ("GREEN", 3)


def test_linha_cheia_empatada_e_devolvida():
    assert bp.liquidar_perna(perna_time(linha=11), JOGO, None, False, False)[0] == "VOID"


def test_ambas_marcam():
    btts = {**BASE, "tipo": "time", "mercado": "btts"}
    assert bp.liquidar_perna(btts, JOGO, None, False, False)[0] == "GREEN"
    assert bp.liquidar_perna(btts, {**JOGO, "away_goals": 0}, None, False, False)[0] == "RED"


def test_jogo_nao_terminado_espera_e_depois_anula():
    assert bp.liquidar_perna(perna_time(), {**JOGO, "status": "NS"}, None, False, False)[0] is None
    assert bp.liquidar_perna(perna_time(), None, None, False, True) == ("VOID", None, "jogo sem resultado")


def test_jogador_null_em_campo_e_zero_e_quem_nao_jogou_e_anulado():
    em_campo = {"minutes": 90, "shots_on": None}
    assert bp.liquidar_perna(perna_jogador(), JOGO, em_campo, True, False)[:2] == ("RED", 0)
    assert bp.liquidar_perna(perna_jogador(), JOGO, {"minutes": 70, "shots_on": 2}, True, False)[0] == "GREEN"
    assert bp.liquidar_perna(perna_jogador(), JOGO, None, True, False)[2] == "jogador nao entrou em campo"
    # Sem ficha nenhuma do jogo, "nao achei" nao quer dizer "nao jogou": espera.
    assert bp.liquidar_perna(perna_jogador(), JOGO, None, False, False)[0] is None
    assert bp.liquidar_perna(perna_jogador(), JOGO, None, False, True)[2] == "sem estatistica de jogador"


# ── o bilhete ──────────────────────────────────────────────────────────────
def test_regra_do_bilhete():
    assert bp.resultado_do_bilhete(["GREEN", None, "RED"]) == "RED"   # RED fecha na hora
    assert bp.resultado_do_bilhete(["GREEN", None]) is None
    assert bp.resultado_do_bilhete(["VOID", "VOID"]) == "PUSH"
    assert bp.resultado_do_bilhete(["GREEN", "VOID"]) == "GREEN"


class Cur:
    def __init__(self, bilhetes, jogos, fichas):
        self.bilhetes, self.jogos, self.fichas = bilhetes, jogos, fichas
        self.updates = []
        self._r = []

    def execute(self, sql, params=None):
        if "FROM bilhetes_pessoais" in sql:
            self._r = self.bilhetes
        elif "FROM match_statistics" in sql:
            self._r = self.jogos
        elif "SELECT DISTINCT fixture_id FROM player_match_stats" in sql:
            self._r = [{"fixture_id": f["fixture_id"]} for f in self.fichas]
        elif "FROM player_match_stats" in sql:
            self._r = self.fichas
        elif sql.strip().startswith("UPDATE bilhetes_pessoais"):
            self.updates.append(params)
            self._r = []

    def fetchall(self):
        return list(self._r)


def test_liquidar_pendentes_fecha_o_bilhete_com_o_motivo_de_cada_perna():
    agora = dt.datetime(2026, 10, 8, 12)
    cur = Cur(
        bilhetes=[{"id": 5, "created_at": dt.datetime(2026, 10, 6, 15),
                   "games": json.dumps([perna_time(), perna_jogador()])}],
        jogos=[{"fixture_id": 10, "match_date": dt.datetime(2026, 10, 6, 21), **JOGO}],
        fichas=[{"fixture_id": 10, "player_id": 77, "minutes": 90, "shots_on": 1,
                 "shots_total": 3, "goals_total": None, "assists": None, "fouls_committed": 0,
                 "fouls_drawn": 1, "tackles_total": 0, "saves": None, "cards_yellow": None}],
    )
    assert bp.liquidar_pendentes(cur, user_id=1, agora=agora) == 1
    games, final, obs, *_ , bid = cur.updates[0]
    assert final == "GREEN" and bid == 5 and obs is None
    pernas = json.loads(games)
    assert [p["resultado"] for p in pernas] == ["GREEN", "GREEN"]
    assert pernas[0]["valor"] == 11


def test_bilhete_pendente_nao_conta_como_fechado():
    cur = Cur(bilhetes=[{"id": 6, "created_at": dt.datetime(2026, 10, 6, 15),
                         "games": [perna_time(fixture_id=99)]}], jogos=[], fichas=[])
    assert bp.liquidar_pendentes(cur, user_id=1, agora=dt.datetime(2026, 10, 7)) == 0
    assert cur.updates[0][1] is None


# ── banca ──────────────────────────────────────────────────────────────────
def test_ninguem_segue_bilhete_pessoal_pelo_id():
    import routers.banca as banca
    assert banca._pode_seguir(None, {"plan": "admin"}, "pessoal", 5) is False


def test_bilhete_pessoal_e_cartela_da_banca_e_fica_fora_do_placar_da_ia():
    import routers.banca as banca
    import pick_sources
    assert banca._TABELAS_CARTELA["pessoal"] == "bilhetes_pessoais"
    assert "pessoal" in banca.STAKE_LIMITS
    fonte = open(pick_sources.__file__, encoding="utf-8").read()
    assert "bilhetes_pessoais" not in fonte, "aposta do usuario nao e' resultado da IA"


def test_desfazer_apaga_o_bilhete_so_do_dono():
    fonte = open(os.path.join(os.path.dirname(__file__), "..", "routers", "banca.py"), encoding="utf-8").read()
    i = fonte.index("def unfollow_pick")
    assert "DELETE FROM bilhetes_pessoais WHERE id = %s AND user_id = %s" in fonte[i:i + 2000]


# ── 1o e 2o tempo ──────────────────────────────────────────────────────────
JOGO_1T = {**JOGO, "home_corners_1h": 4, "away_corners_1h": 1, "home_goals_ht": 1, "away_goals_ht": 0}


def test_escanteios_por_tempo():
    t1 = perna_time(linha=4.5, periodo="1t")
    assert bp.liquidar_perna(t1, JOGO_1T, None, False, False)[:2] == ("GREEN", 5)
    # 2o tempo = total (11) - 1o (5) = 6
    t2 = perna_time(linha=6.5, periodo="2t")
    assert bp.liquidar_perna(t2, JOGO_1T, None, False, False)[:2] == ("RED", 6)
    do_time = perna_time(mercado="escanteios_time", lado_time="away", linha=0.5, periodo="1t")
    assert bp.liquidar_perna(do_time, JOGO_1T, None, False, False)[:2] == ("GREEN", 1)


def test_sem_folha_do_1o_tempo_espera():
    assert bp.liquidar_perna(perna_time(periodo="1t"), JOGO, None, False, False)[0] is None


def test_faltas_so_no_jogo_inteiro_e_tempo_desconhecido_recusado():
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([perna_time(mercado="faltas", linha=22.5, periodo="1t")])
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([perna_time(periodo="prorrogacao")])
    assert bp.validar_pernas([perna_time()])[0]["periodo"] == "total"


def test_chutes_e_faltas_de_um_time_so():
    alvo = perna_time(mercado="chutes_alvo_time", lado_time="home", linha=4.5)
    assert bp.liquidar_perna(alvo, JOGO, None, False, False)[:2] == ("GREEN", 5)
    faltas = perna_time(mercado="faltas_time", lado_time="away", linha=12.5, direcao="menos")
    assert bp.liquidar_perna(faltas, JOGO, None, False, False)[:2] == ("RED", 13)
    with pytest.raises(bp.PernaInvalida):
        bp.validar_pernas([perna_time(mercado="faltas_time", lado_time="away", periodo="1t")])


# ── odd de cada selecao (07/10) ────────────────────────────────────────────
def test_perna_guarda_a_odd_so_quando_e_odd():
    assert bp.validar_pernas([{**perna_time(), "odd": "1.85"}])[0]["odd"] == 1.85
    assert "odd" not in bp.validar_pernas([{**perna_time(), "odd": "abc"}])[0]
    assert "odd" not in bp.validar_pernas([{**perna_time(), "odd": 0.5}])[0]


def test_odd_recalculada_tira_a_perna_anulada():
    pernas = [{"resultado": "GREEN", "odd": 1.5}, {"resultado": "VOID", "odd": 2.0}]
    assert bp.odd_recalculada(pernas, 3.0) == 1.5
    # anulada sem odd: nao da' pra saber, fica a registrada
    assert bp.odd_recalculada([{"resultado": "VOID"}], 3.0) is None
    assert bp.odd_recalculada([{"resultado": "GREEN", "odd": 2}], 3.0) is None
