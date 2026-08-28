# -*- coding: utf-8 -*-
"""Recalcular media so' de quem mudou, e nao de quem jogou (2026-08-27).

`team_statistics` e' o que o motor le', e e' DERIVADA de `match_statistics`.
Derivada nao se atualiza sozinha: coletar a partida e nao refazer a media deixa
o motor lendo a media de ontem sobre um historico de hoje -- o pior dos dois
mundos, porque parece atualizado e nao tem sintoma nenhum na tela.

AS DUAS FORMAS QUE HAVIA ERAM GROSSAS NAS DUAS PONTAS

    update_full_season_statistics()     APAGA a tabela inteira e reprocessa
                                        todo time do banco;
    update_recent_teams_statistics(3)   reprocessa todo time que TEVE JOGO nos
                                        ultimos tres dias.

A segunda era a da varredura automatica, e ela refaz a conta de dezenas de
times pra produzir exatamente o mesmo numero que ja' estava la' -- no caminho de
uma VISITA ao site. Cada time custa duas leituras da temporada inteira e dois
upserts, cada um com conexao propria.

A PERGUNTA CERTA E' OUTRA: existe partida deste time gravada DEPOIS da ultima
vez que a media dele foi escrita? Se nao existe, refazer produz o mesmo numero.

Nada toca banco: o cursor e' duble' e guarda o SQL que recebeu.
"""
import pytest

from services.team_stats_reader import TeamStatsReader
from services.team_stats_aggregator_service import TeamStatsAggregatorService


class _CursorFake:
    def __init__(self, linhas=None):
        self._linhas = linhas or []
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params or ()

    def fetchall(self):
        return list(self._linhas)

    def close(self):
        pass


class _ConnFake:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def cursor(monkeypatch):
    cur = _CursorFake(linhas=[(10, 71, 2026), (20, 71, 2026)])
    monkeypatch.setattr("services.team_stats_reader.get_connection",
                        lambda: _ConnFake(cur))
    return cur


# ── a consulta ───────────────────────────────────────────────────────────
def test_compara_a_media_com_a_ultima_partida(cursor):
    """E' a pergunta inteira: media escrita ANTES da ultima partida do time."""
    TeamStatsReader().get_teams_with_stale_statistics()

    assert "m.calculada_em < u.gravada_em" in cursor.sql


def test_time_sem_media_nenhuma_entra(cursor):
    """Media que nunca foi calculada e' o caso mais desatualizado que existe, e
    o LEFT JOIN devolve NULL -- que nao e' "menor que" nada em SQL."""
    TeamStatsReader().get_teams_with_stale_statistics()

    assert "m.calculada_em IS NULL" in cursor.sql


def test_usa_a_media_mais_velha_entre_os_contextos(cursor):
    """`team_statistics` tem uma linha por contexto (HOME/AWAY). O time so'
    esta' em dia quando A MAIS VELHA delas for mais nova que a partida -- com
    MAX, um time com HOME atualizado e AWAY parado passaria por atualizado."""
    TeamStatsReader().get_teams_with_stale_statistics()

    assert "MIN(last_updated) AS calculada_em" in cursor.sql


def test_os_dois_lados_da_partida_contam(cursor):
    """Um jogo atualiza a media do mandante E do visitante · ler so' uma coluna
    deixaria metade dos times parados pra sempre."""
    TeamStatsReader().get_teams_with_stale_statistics()

    assert "VALUES (ms.home_team_id), (ms.away_team_id)" in cursor.sql


def test_nao_ha_janela_de_dias(cursor):
    """O recalculo nao tem prazo: uma partida preenchida a mao hoje, de um jogo
    de duas semanas atras, precisa refazer a media do mesmo jeito. A janela de
    3 dias continua valendo pra COLETA, que e' outra coisa."""
    TeamStatsReader().get_teams_with_stale_statistics()

    assert "days" not in cursor.sql
    assert "interval" not in cursor.sql.lower()


def test_o_limite_e_opcional(cursor):
    TeamStatsReader().get_teams_with_stale_statistics()
    assert "LIMIT" not in cursor.sql
    assert cursor.params == ()

    TeamStatsReader().get_teams_with_stale_statistics(limite=5)
    assert "LIMIT %s" in cursor.sql
    assert cursor.params == (5,)


# ── o agregador ──────────────────────────────────────────────────────────
class _ReaderFake:
    def __init__(self, alvos):
        self.alvos = alvos
        self.pedidos = []

    def get_teams_with_stale_statistics(self, limite=0):
        self.pedidos.append(limite)
        return self.alvos


def _agregador(monkeypatch, alvos, falhar_em=()):
    ag = TeamStatsAggregatorService.__new__(TeamStatsAggregatorService)
    ag.reader = _ReaderFake(alvos)
    processados = []

    def _processa(team_id, league_id, season):
        processados.append(team_id)
        if team_id in falhar_em:
            raise RuntimeError("banco fora do ar")

    ag.process_single_team = _processa
    return ag, processados


def test_processa_exatamente_os_alvos(monkeypatch):
    alvos = [{"team_id": 1, "league_id": 71, "season": 2026},
             {"team_id": 2, "league_id": 71, "season": 2026}]
    ag, processados = _agregador(monkeypatch, alvos)

    resultado = ag.update_stale_teams_statistics()

    assert processados == [1, 2]
    assert resultado == {"total": 2, "feitos": 2, "falhas": 0}


def test_lista_vazia_nao_processa_nada(monkeypatch):
    """E' o caso COMUM: a varredura roda a cada 10 minutos e na maior parte das
    passadas nada foi coletado. Antes disso, ela recalculava dezenas de times
    do mesmo jeito."""
    ag, processados = _agregador(monkeypatch, [])

    resultado = ag.update_stale_teams_statistics()

    assert processados == []
    assert resultado["total"] == 0


def test_um_time_que_falha_nao_derruba_o_lote(monkeypatch):
    """A media dele continua velha e ele volta na proxima passada, porque o
    criterio e' o ESTADO DO BANCO e nao uma lista guardada."""
    alvos = [{"team_id": i, "league_id": 71, "season": 2026} for i in (1, 2, 3)]
    ag, processados = _agregador(monkeypatch, alvos, falhar_em={2})

    resultado = ag.update_stale_teams_statistics()

    assert processados == [1, 2, 3]
    assert resultado == {"total": 3, "feitos": 3, "falhas": 1}


def test_o_progresso_e_reportado_a_cada_time(monkeypatch):
    """O /admin desenha a barra com isto · sem o callback ele so' saberia o
    resultado no fim, que num lote longo e' o mesmo que nao saber."""
    alvos = [{"team_id": i, "league_id": 71, "season": 2026} for i in (1, 2, 3)]
    ag, _ = _agregador(monkeypatch, alvos)
    vistos = []

    ag.update_stale_teams_statistics(progresso=lambda f, t: vistos.append((f, t)))

    assert vistos == [(1, 3), (2, 3), (3, 3)]


def test_o_rebuild_completo_continua_existindo():
    """`update_full_season_statistics` APAGA a tabela · ela nao foi removida e
    nao deve ser, mas nao pode ser o caminho de uma visita ao site."""
    assert hasattr(TeamStatsAggregatorService, "update_full_season_statistics")
    assert hasattr(TeamStatsAggregatorService, "update_stale_teams_statistics")
