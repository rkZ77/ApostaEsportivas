"""Coleta de jogador que nao trava a fila (2026-10-16).

Tres defeitos do mesmo formato do Club Leon sem id na classificacao:

1. jogador com id nulo derrubava a partida inteira no NOT NULL, e ela voltava
   pra fila toda rodada;
2. partida sem folha (liga sem cobertura, folha ainda nao publicada) nunca
   ganhava linha, entao ficava sendo a "mais recente" da liga e ocupava a
   vaga dela pra sempre;
3. a chamada era feita a mao: cota esgotada nao parava a rodada.
"""
import pytest

from collectors import player_stats_collector_service as col
from utils.api_client import ApiQuotaEsgotada


def _jogador(pid, minutos):
    return {"player": {"id": pid, "name": f"J{pid}"},
            "statistics": [{"games": {"minutes": minutos, "position": "M"}}]}


def _resposta(*jogadores):
    return [{"team": {"id": 1, "name": "Time"}, "players": list(jogadores)}]


class _Cur:
    def __init__(self):
        self.sqls, self.lotes = [], []

    def execute(self, sql, params=None):
        self.sqls.append(" ".join(sql.split()))

    def executemany(self, sql, linhas):
        self.lotes.append(linhas)

    def fetchone(self):
        return (True,)   # to_regclass: tabela ja' existe

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _coletar(monkeypatch, respostas):
    cur = _Cur()
    monkeypatch.setattr(col, "get_connection", lambda: _Conn(cur))
    monkeypatch.setattr(col, "PAUSA_ENTRE_CHAMADAS", 0)
    servico = col.PlayerStatsCollectorService(debug_shape=False)
    chamadas = []

    def _buscar(fid):
        chamadas.append(fid)
        r = respostas[fid]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(servico, "_buscar", _buscar)
    servico.coletar([{"fixture_id": f} for f in respostas])
    return cur, chamadas


def _anotadas(cur):
    return [s for s in cur.sqls if s.startswith("INSERT INTO player_stats_tentativas")]


def test_jogador_sem_id_e_pulado_e_o_resto_grava(monkeypatch):
    cur, _ = _coletar(monkeypatch, {1: _resposta(_jogador(None, 90), _jogador(7, 90))})
    assert [l[1] for l in cur.lotes[0]] == [7]
    assert not _anotadas(cur)


def test_folha_sem_minutos_nao_grava_linha_oca_e_anota(monkeypatch):
    cur, _ = _coletar(monkeypatch, {1: _resposta(_jogador(7, None), _jogador(8, 0))})
    assert cur.lotes == []
    assert len(_anotadas(cur)) == 1


def test_partida_sem_jogador_e_anotada(monkeypatch):
    cur, _ = _coletar(monkeypatch, {1: []})
    assert len(_anotadas(cur)) == 1


def test_cota_esgotada_para_a_rodada(monkeypatch):
    cur, chamadas = _coletar(monkeypatch, {
        1: ApiQuotaEsgotada("fixtures/players", {"requests": "limite"}),
        2: _resposta(_jogador(7, 90)),
    })
    assert chamadas == [1]
    assert not _anotadas(cur), "cota nao e' defeito da partida"


def test_fila_respeita_espera_e_teto_de_tentativas():
    assert f"pt.tentativas < {col.MAX_TENTATIVAS}" in col._FORA_DA_ESPERA
    assert "pt.ultima_em < NOW() - INTERVAL" in col._FORA_DA_ESPERA


def test_nao_ha_mais_chamada_a_mao_na_api():
    import inspect
    fonte = inspect.getsource(col)
    assert "requests.get" not in fonte
    assert 'buscar("fixtures/players"' in fonte
