"""08/10/2026: recalibracao em sombra, chave MOTOR_1T e os scripts de medicao
do 1o e do 2o tempo."""
import ast
import datetime as dt
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))

import pytest  # noqa: E402

from services.pick_engine import recalibracao as rc  # noqa: E402


def _pares(prob, n, acertos):
    return [(prob, i < acertos) for i in range(n)]


# ── recalibracao ────────────────────────────────────────────────────────────
def test_curva_puxa_o_otimista_para_o_acerto():
    # 370 pernas prometendo 0.74 e acertando 66.8% (a medicao de PROD)
    curva = rc.ajustar_curva(_pares(0.74, 370, 247))
    [(x, y, n)] = curva
    assert x == 0.74 and n == 370
    assert 0.667 < y < 0.70        # perto do acerto, encolhido um pouco pra promessa


def test_amostra_pequena_fica_fora():
    assert rc.ajustar_curva(_pares(0.74, 10, 5)) == []


def test_curva_sempre_crescente():
    pares = _pares(0.66, 100, 70) + _pares(0.75, 100, 60)   # faixa alta acertou menos
    ys = [y for _, y, _ in rc.ajustar_curva(pares)]
    assert ys == sorted(ys)


def test_aplicar_interpola_e_desloca_nas_pontas():
    curva = [(0.60, 0.56, 100), (0.74, 0.67, 300)]
    assert rc.aplicar(0.67, curva) == pytest.approx(0.615, abs=1e-3)
    assert rc.aplicar(0.85, curva) == pytest.approx(0.78, abs=1e-3)   # carrega -0.07
    assert rc.aplicar(0.50, curva) == pytest.approx(0.46, abs=1e-3)
    assert rc.aplicar(74, curva) == pytest.approx(0.67, abs=1e-3)     # em %, tambem
    assert rc.aplicar(0.7, []) is None and rc.aplicar(None, curva) is None


def test_curva_em_cache_nunca_levanta(monkeypatch):
    import utils.db_utils as db
    monkeypatch.setattr(db, "get_connection", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem banco")))
    rc._cache.update(em=0.0, curva=None)
    assert rc.curva_em_cache() == []
    rc._cache.update(em=0.0, curva=None)


def test_recalibrada_e_so_sombra_no_orchestrator():
    """A chave existe no candidato e nenhuma linha de DECISAO le' ela."""
    fonte = open(os.path.join(RAIZ, "src", "services", "pick_engine", "orchestrator.py"),
                 encoding="utf-8").read()
    usos = [l for l in fonte.splitlines()
            if "prob_recalibrada_sombra" in l and not l.strip().startswith("#")]
    assert len(usos) == 1 and '"prob_recalibrada_sombra":' in usos[0]


# ── MOTOR_1T ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("valor, esperado", [(None, "on"), ("off", "off"), ("OFF ", "off"),
                                             ("on", "on"), ("talvez", "on")])
def test_modo_1t(monkeypatch, valor, esperado):
    from services.pick_engine.orchestrator import modo_1t
    if valor is None:
        monkeypatch.delenv("MOTOR_1T", raising=False)
    else:
        monkeypatch.setenv("MOTOR_1T", valor)
    assert modo_1t() == esperado


# ── scripts ─────────────────────────────────────────────────────────────────
def test_detector_de_primeiro_tempo():
    from scripts.medir_primeiro_tempo import e_primeiro_tempo
    assert e_primeiro_tempo({"market_type": "corners_1h", "market": "Escanteios"})
    assert e_primeiro_tempo({"market_type": "goals", "market": "Gols Mais/Menos - 1º Tempo"})
    assert e_primeiro_tempo({"market_type": None, "market": "Goals Over/Under First Half"})
    assert not e_primeiro_tempo({"market_type": "corners", "market": "Escanteios Mais/Menos"})


def test_segundo_tempo_e_total_menos_primeiro():
    from scripts.medir_segundo_tempo import contagem, media_faz_cede
    j = {"home_team_id": 1, "away_team_id": 2, "home_goals": 3, "away_goals": 1,
         "home_goals_ht": 1, "away_goals_ht": 1, "home_corners": 7, "away_corners": 4,
         "home_corners_1h": 3, "away_corners_1h": None}
    assert contagem(j, "gols", "2t", "home") == 2 and contagem(j, "gols", "2t", "away") == 0
    assert contagem(j, "escanteios", "2t", "home") == 4
    assert contagem(j, "escanteios", "2t", "away") is None     # sem folha, sem numero
    hist = [dict(j, match_date=dt.date(2026, 9, d)) for d in range(1, 7)]
    faz, cede = media_faz_cede(hist, 2, "gols", "2t")           # time 2 jogou fora
    assert (faz, cede) == (0, 2)
    assert media_faz_cede(hist[:3], 2, "gols", "2t") is None    # menos de 5 jogos


def test_scripts_sao_so_leitura():
    for nome in ("medir_primeiro_tempo.py", "medir_segundo_tempo.py", "medir_recalibracao.py"):
        fonte = open(os.path.join(RAIZ, "src", "scripts", nome), encoding="utf-8").read()
        ast.parse(fonte)
        for proibido in ("INSERT ", "UPDATE ", "DELETE ", "commit("):
            assert proibido not in fonte, (nome, proibido)
