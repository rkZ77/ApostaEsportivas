"""Cada chamada do site a' API-Football com rotulo proprio (11/10/2026).

As seis chamadas de routers/live.py (placar, placar em lote, estatistica, odds
por jogo, odds do mundo, odds pre-jogo) eram todas contadas como "live", e o
/admin nao tinha como dizer qual delas gastava a cota. Nenhum teste toca rede.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers import admin  # noqa: E402

_LIVE = os.path.join(os.path.dirname(__file__), "..", "routers", "live.py")


def test_nenhuma_chamada_do_live_fica_com_o_rotulo_generico():
    codigo = open(_LIVE, encoding="utf-8").read()
    rotulos = re.findall(r'api_quota\.registrar\([^)]*\),\s*"([^"]+)"\)', codigo)
    assert "live" not in rotulos
    assert {"live:placar", "live:placar-lote", "live:estatistica",
            "live:odds-jogo", "live:odds-mundo", "live:odds-pre"} <= set(rotulos)


def test_painel_do_ao_vivo_soma_o_rotulo_antigo_e_os_novos():
    assert admin._e_do_ao_vivo("live")            # dias antes da troca
    assert admin._e_do_ao_vivo("motor_live")
    assert admin._e_do_ao_vivo("live:odds-mundo")
    assert not admin._e_do_ao_vivo("lineups")
    assert not admin._e_do_ao_vivo("fixtures")
    assert not admin._e_do_ao_vivo(None)
