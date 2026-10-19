"""Lacunas do historico (18/10/2026): mede, preenche no teto, mede de novo."""
from collectors import lacunas_service as ls


def test_preenche_so_o_que_falta_e_um_tipo_nao_derruba_o_outro(monkeypatch, capsys):
    medidas = iter([{"1o tempo": (1793, 3051), "eventos": (0, 4000), "escalacao": (50, 4000)},
                    {"1o tempo": (1493, 3051), "eventos": (0, 4000), "escalacao": (0, 4000)}])
    monkeypatch.setattr(ls, "cobertura", lambda: next(medidas))
    monkeypatch.setattr(ls, "de_graca", lambda: {"rodada": 810, "arbitro": 91})
    monkeypatch.setattr(ls, "_restante_da_cota", lambda: None)      # cota desconhecida: teto fixo
    chamados = []

    def _preencher(rotulo, teto):
        chamados.append((rotulo, teto))
        if rotulo == "1o tempo":
            raise RuntimeError("API fora")
    monkeypatch.setattr(ls, "_preencher", _preencher)
    ls.preencher()
    assert chamados == [("1o tempo", 300), ("escalacao", 30)]       # eventos sem fila: nada
    saida = capsys.readouterr().out
    assert "1o tempo falhou" in saida and "faltam 1493 de 3051" in saida
    assert "copiado do calendario" in saida


def test_escala_multiplica_os_tetos(monkeypatch):
    monkeypatch.setattr(ls, "cobertura", lambda: {"1o tempo": (10, 10), "eventos": (10, 10), "escalacao": (10, 10)})
    monkeypatch.setattr(ls, "de_graca", lambda: {})
    monkeypatch.setattr(ls, "_restante_da_cota", lambda: None)
    chamados = []
    monkeypatch.setattr(ls, "_preencher", lambda r, t: chamados.append(t))
    ls.preencher(escala=2)
    assert chamados == [600, 60, 60]


def test_teto_do_1o_tempo_usa_a_cota_que_sobra():
    """19/10/2026: "tem que pegar tudo de uma vez" · acima da reserva."""
    assert ls.teto_pela_cota(300, 815, None) == 300                  # sem medida: fixo
    assert ls.teto_pela_cota(300, 815, 7400) == 915                  # tudo (+100 do placar)
    assert ls.teto_pela_cota(300, 815, 5600) == 600                  # so' o que passa da reserva
    assert ls.teto_pela_cota(300, 815, 2000) == 300                  # cota curta: nunca menos que o fixo
    assert ls.teto_pela_cota(300, 10, 7400) == 300


def test_madrugada_com_cota_cheia_pega_tudo(monkeypatch, capsys):
    monkeypatch.setattr(ls, "cobertura", lambda: {"1o tempo": (815, 3318), "eventos": (0, 1), "escalacao": (0, 1)})
    monkeypatch.setattr(ls, "de_graca", lambda: {})
    monkeypatch.setattr(ls, "_restante_da_cota", lambda: 7450)
    chamados = []
    monkeypatch.setattr(ls, "_preencher", lambda r, t: chamados.append((r, t)))
    ls.preencher()
    assert chamados == [("1o tempo", 915)]
    assert "teto 300 -> 915" in capsys.readouterr().out
