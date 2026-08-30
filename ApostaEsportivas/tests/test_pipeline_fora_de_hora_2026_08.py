"""O que acontece quando o pipeline roda FORA da janela util do dia.

Contexto (2026-08-11): o usuario rodou o pipeline com bastante jogo marcado pro
dia seguinte e nao saiu pick nenhum. A causa nao foi o motor rejeitar candidato
-- foi a etapa de ODDS esvaziar a base antes dos geradores rodarem.

Todo gerador de pick filtra `f.match_datetime::date = HOJE_BR`. Quando os jogos
de hoje ja comecaram, nenhum esta mais em NS/TBD e a coleta de odds nao tem o
que buscar. So' que ela dava TRUNCATE em odds_values/odds_markets/
odds_bookmakers ANTES de descobrir isso, e repunha zero. Os seis geradores
seguintes rodavam contra uma tabela de cotacoes vazia, cada um "terminando OK"
sem gerar nada -- nenhuma etapa falhava, entao nada no log apontava pra causa.

Nao ha banco aqui: o TRUNCATE e' verificado pelo SQL que o codigo emite, com um
cursor de mentira que grava o que recebeu.
"""

import os
import re

import pytest


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _fonte(caminho: str) -> str:
    with open(os.path.join(SRC, caminho), encoding="utf-8") as fh:
        return fh.read()


# ── Cursor/conexao de mentira ─────────────────────────────────────────────
class CursorFalso:
    def __init__(self, registro, fixtures):
        self.registro = registro
        self._fixtures = fixtures
        self._ultimo = ""

    def execute(self, sql, params=None):
        self._ultimo = sql
        self.registro.append(" ".join(sql.split()))

    def fetchall(self):
        if "FROM fixtures" in self._ultimo:
            return [(fid,) for fid in self._fixtures]
        return []

    def fetchone(self):
        return (0,)

    def close(self):
        pass


class ConexaoFalsa:
    def __init__(self, registro, fixtures):
        self.registro = registro
        self._fixtures = fixtures

    def cursor(self, **kwargs):
        return CursorFalso(self.registro, self._fixtures)

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def odds_main(monkeypatch):
    """Devolve uma fabrica: `odds_main(fixtures)` -> (OddsMain, sql_executado)."""
    import capturar_odds as mod

    def fabricar(fixtures):
        registro = []
        monkeypatch.setattr(mod, "get_connection",
                            lambda *a, **k: ConexaoFalsa(registro, fixtures))
        monkeypatch.setattr(mod, "prune_odds_snapshots", lambda cur: 0)
        main = mod.OddsMain()
        # Nao ha API neste teste: se a coleta tentar sair pra rede, falha alto.
        monkeypatch.setattr(main.odds_collector, "fetch_odds_by_fixture",
                            lambda fid: None)
        return main, registro

    return fabricar


def _truncou(registro) -> bool:
    return any("TRUNCATE" in sql for sql in registro)


# ── O caso que quebrou ────────────────────────────────────────────────────
def test_sem_jogo_pre_jogo_nao_trunca_as_odds(odds_main):
    """A regressao de 2026-08-11, em uma linha: dia sem NS/TBD nao pode apagar
    a base de cotacoes."""
    main, registro = odds_main(fixtures=[])
    main.run()
    assert not _truncou(registro), \
        "TRUNCATE rodou num dia sem jogo pre-jogo: odds_values ficaria vazia"


def test_sem_jogo_pre_jogo_ainda_faz_a_retencao_dos_retratos(monkeypatch):
    """A limpeza de odds_snapshots e' historico, nao depende de haver coleta."""
    import capturar_odds as mod
    registro = []
    chamou = []
    monkeypatch.setattr(mod, "get_connection",
                        lambda *a, **k: ConexaoFalsa(registro, []))
    monkeypatch.setattr(mod, "prune_odds_snapshots",
                        lambda cur: chamou.append(True) or 0)
    mod.OddsMain().run()
    assert chamou, "retencao de odds_snapshots deixou de rodar no dia vazio"


def test_com_jogo_pre_jogo_o_truncate_continua_acontecendo(odds_main):
    """O comportamento normal nao muda: havendo o que coletar, a base e'
    substituida como sempre foi."""
    main, registro = odds_main(fixtures=[101, 102])
    main.run()
    assert _truncou(registro)


def test_truncate_vem_depois_da_consulta_de_fixtures(odds_main):
    """A ordem E' a correcao. Consultar primeiro e' o que permite decidir."""
    main, registro = odds_main(fixtures=[101])
    main.run()
    i_select = next(i for i, s in enumerate(registro) if "FROM fixtures" in s)
    i_trunc = next(i for i, s in enumerate(registro) if "TRUNCATE" in s)
    assert i_select < i_trunc, "voltou a truncar antes de saber se ha coleta"


def test_run_nao_consulta_fixtures_duas_vezes(odds_main):
    """A lista consultada no run() e' repassada pro collect_odds."""
    main, registro = odds_main(fixtures=[101])
    main.run()
    assert sum(1 for s in registro if "FROM fixtures" in s) == 1


# ── Filtro de status dos geradores ────────────────────────────────────────
def _status_do_pipeline(arquivo: str) -> set:
    """Le a lista de status aceita pelo SELECT de fixtures do pipeline."""
    fonte = _fonte(os.path.join("engine_pipelines", arquivo))
    m = re.search(r"f\.status\s+IN\s+\(([^)]*)\)", fonte)
    if m:
        return set(re.findall(r"'([A-Z0-9]+)'", m.group(1)))
    m = re.search(r"f\.status\s*=\s*'([A-Z0-9]+)'", fonte)
    return {m.group(1)} if m else set()


def test_nenhum_gerador_pre_jogo_aceita_jogo_em_andamento():
    """Pick pre-jogo le historico e odd de abertura, nao placar. O dica era o
    unico que aceitava 'LIVE' e por isso podia sugerir aposta pre-jogo pra
    partida ja em andamento, com odd que ja nao existia mais."""
    for arquivo in ("dica_pipeline.py", "alavancagem_pipeline.py",
                    "faltas_pipeline.py", "player_stats_pipeline.py"):
        assert "LIVE" not in _status_do_pipeline(arquivo), arquivo


def test_vip_e_alavancagem_exigem_horario_confirmado():
    """'TBD' e' jogo com data no dia mas sem horario confirmado. Os dois
    pipelines de aposta paga exigem 'NS'."""
    assert _status_do_pipeline("alavancagem_pipeline.py") == {"NS"}
    assert "TBD" not in _fonte(os.path.join("services", "fixtures_service.py")).split(
        "def get_ns_without_suggestions")[1]


def test_todo_gerador_filtra_pelo_dia_em_brasilia():
    """`CURRENT_DATE` e' a data UTC do banco e diverge do Brasil entre 21h e
    meia-noite -- ver utils/data_br. Nenhum pipeline pode voltar a usar isso."""
    for arquivo in ("dica_pipeline.py", "alavancagem_pipeline.py",
                    "faltas_pipeline.py", "player_stats_pipeline.py"):
        fonte = _fonte(os.path.join("engine_pipelines", arquivo))
        assert "HOJE_BR" in fonte, arquivo
        assert "match_datetime::date = CURRENT_DATE" not in fonte, arquivo


def test_coletor_de_odds_cobre_os_status_que_os_geradores_pedem():
    """A coleta busca NS/TBD; se um gerador aceitasse status fora disso, ele
    pediria odd de um jogo que a coleta nunca baixa."""
    odds = _fonte("capturar_odds.py")
    # `f.status`, com o alias, e nao o primeiro `status IN` do arquivo: desde
    # 30/08 a consulta tem DOIS -- o do historico dos times ('FT','AET','PEN',
    # que decide se a partida tem base) e o das fixtures a coletar. Pegar o
    # primeiro fazia o teste comparar o gerador com a lista errada.
    m = re.search(r"f\.status\s+IN\s+\(([^)]*)\)", odds)
    aceitos_pela_coleta = set(re.findall(r"'([A-Z]+)'", m.group(1)))
    for arquivo in ("dica_pipeline.py", "alavancagem_pipeline.py",
                    "faltas_pipeline.py", "player_stats_pipeline.py"):
        assert _status_do_pipeline(arquivo) <= aceitos_pela_coleta, arquivo
