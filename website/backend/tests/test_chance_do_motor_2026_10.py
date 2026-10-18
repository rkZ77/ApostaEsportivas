"""Casa diz x Motor diz em Meus Bilhetes (18/10/2026) · ver chance_do_motor.py."""
import chance_do_motor as cm


def _perna(**kw):
    base = {"tipo": "time", "mercado": "escanteios", "direcao": "mais", "linha": 9.5, "periodo": "total"}
    return {**base, **kw}


def test_chave_da_perna_do_jogo_inteiro():
    assert cm.chave_da_perna_pessoal(_perna()) == ("corners", "total", "over 9.5")


def test_chave_do_time_no_primeiro_tempo():
    # O caso do bilhete de 18/10: gols do Lecce (visitante) no 1o tempo, menos de 0.5.
    perna = _perna(mercado="gols_time", direcao="menos", linha=0.5, periodo="1t", lado_time="away")
    assert cm.chave_da_perna_pessoal(perna) == ("goals_1h", "away", "under 0.5")


def test_ambas_marcam_e_mercados_que_o_motor_nao_avalia():
    assert cm.chave_da_perna_pessoal({"tipo": "time", "mercado": "btts", "escolha": "nao"}) == ("btts", "total", "no")
    assert cm.chave_da_perna_pessoal({"tipo": "time", "mercado": "resultado", "escolha": "1"}) is None
    assert cm.chave_da_perna_pessoal(_perna(periodo="2t")) is None
    assert cm.chave_da_perna_pessoal({"tipo": "jogador", "estat": "chutes"}) is None


def test_anotar_casa_pela_chave_e_pelo_nome(monkeypatch):
    av = {"nome": {("escanteios mais/menos", "over 9.5"): 0.64},
          "chave": {("goals_1h", "away", "under 0.5"): 0.706}}
    monkeypatch.setattr(cm, "_avaliacoes", lambda cur, fid: av)
    bilhetes = [{"legs": [
        {"fixture_id": 1, "market": "Escanteios Mais/Menos", "line": "Over 9.5"},
        {"fixture_id": 2, "_chave_motor": ("goals_1h", "away", "under 0.5")},
        {"fixture_id": 3, "market": "Faltas", "line": "Over 22.5"},
    ]}]
    cm.anotar(None, bilhetes)
    legs = bilhetes[0]["legs"]
    assert [l["prob_motor"] for l in legs] == [0.64, 0.706, None]
    assert all("_chave_motor" not in l for l in legs)
