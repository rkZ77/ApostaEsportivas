"""Dias sem pick de jogador e o log so' dizia "nenhum candidato passou".
O funil agrupa onde cada candidato morreu."""
from engine_pipelines.player_stats_pipeline import MOTIVO_SEM_MERCADO, _funil


def test_funil_agrupa_motivos_sem_os_numeros():
    sem = [({"fixture_id": 1}, {"saves": MOTIVO_SEM_MERCADO}),
           ({"fixture_id": 2}, {"saves": MOTIVO_SEM_MERCADO}),
           ({"fixture_id": 3}, {"shots": MOTIVO_SEM_MERCADO})]
    descartados = [({}, "probabilidade 55% abaixo do mínimo (62%)"),
                   ({}, "probabilidade 58% abaixo do mínimo (62%)"),
                   ({}, "margem +1.2% abaixo do mínimo (4%)")]
    linha = _funil("saves", sem, set(), descartados, excedentes=0, salvos=0)
    assert f"jogo: {MOTIVO_SEM_MERCADO}: 2" in linha
    assert "probabilidade abaixo do mínimo: 2" in linha
    assert "margem abaixo do mínimo: 1" in linha
    assert "salvos 0" in linha


def test_funil_vazio():
    assert "nada avaliado" in _funil("saves", [], set(), [], 0, 0)
