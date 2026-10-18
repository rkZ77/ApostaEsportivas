"""Lacunas do historico (18/10/2026): mede, preenche no teto, mede de novo."""
from collectors import lacunas_service as ls


def test_preenche_so_o_que_falta_e_um_tipo_nao_derruba_o_outro(monkeypatch, capsys):
    medidas = iter([{"1o tempo": (1793, 3051), "eventos": (0, 4000), "escalacao": (50, 4000)},
                    {"1o tempo": (1493, 3051), "eventos": (0, 4000), "escalacao": (0, 4000)}])
    monkeypatch.setattr(ls, "cobertura", lambda: next(medidas))
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


def test_escala_multiplica_os_tetos(monkeypatch):
    monkeypatch.setattr(ls, "cobertura", lambda: {"1o tempo": (10, 10), "eventos": (10, 10), "escalacao": (10, 10)})
    chamados = []
    monkeypatch.setattr(ls, "_preencher", lambda r, t: chamados.append(t))
    ls.preencher(escala=2)
    assert chamados == [600, 60, 60]
