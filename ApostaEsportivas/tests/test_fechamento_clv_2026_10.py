"""O CLV nao media nada · tres defeitos encontrados em 2026-10-02.

1. FUSO DO MINUTO DO RETRATO. `fixtures.match_datetime` e' Brasilia sem fuso;
   a conta `match_datetime - NOW()` rodava num banco em UTC e todo retrato saia
   180 min menor. Um retrato 30 min antes do apito virava -150 ("ao vivo") e
   os leitores do fechamento o descartavam.
2. NAO HAVIA RETRATO PERTO DO APITO. A unica coleta do dia era a da manha, a
   mesma que gera o pick: fechamento = odd do pick, CLV ~0 por construcao.
   capturar_fechamento.py coleta so' os jogos com pick, 30 min antes.
3. RETENCAO APAGAVA O CLV. Coberto em test_clv_cruzado.py.

Sem banco: o SQL emitido e' verificado por cursores de mentira.
"""
import pytest


# ── 1. fuso ───────────────────────────────────────────────────────────────
def test_minuto_do_retrato_le_o_kickoff_como_horario_de_brasilia():
    from collectors import odds_collector_service as mod
    assert "AT TIME ZONE 'America/Sao_Paulo'" in mod.MINUTOS_ATE_O_APITO_SQL


def test_insert_do_retrato_usa_a_conta_com_fuso(monkeypatch):
    from collectors import odds_collector_service as mod
    emitido = []
    monkeypatch.setattr(mod, "_create_odds_snapshots_table", lambda cur: None)
    monkeypatch.setattr(mod, "execute_batch",
                        lambda cur, sql, linhas, page_size=None: emitido.append((sql, linhas)))
    mod._inserir_retratos(object(), [(1, 8, 5, "Over 2.5", None, 1.9, "2026-10-02 16:00")])
    sql, linhas = emitido[0]
    assert mod.MINUTOS_ATE_O_APITO_SQL in sql
    assert "(%s - NOW())" not in sql
    assert len(linhas[0]) == 9


def test_correcao_recalcula_das_colunas_de_origem():
    """Idempotente: recalcula de match_datetime e captured_at, nao soma 180."""
    import inspect
    from collectors import odds_collector_service as mod
    fonte = inspect.getsource(mod.corrigir_minuto_dos_retratos)
    assert "captured_at AT TIME ZONE 'UTC'" in fonte
    assert "minutes_to_kickoff + 180" not in fonte


class _ConnCorrecao:
    """Conexao falsa: `marcado` diz se a correcao ja' rodou; ids 1..450000."""

    def __init__(self, marcado):
        self.marcado = marcado
        self.sql = []
        self.commits = 0
        conn = self

        class Cur:
            rowcount = 0

            def execute(self, sql, params=None):
                conn.sql.append((" ".join(sql.split()), params))
                self.rowcount = 7 if sql.strip().startswith("UPDATE") else 0

            def fetchone(self):
                ultimo = conn.sql[-1][0]
                if "FROM migracoes_motor" in ultimo:
                    return (1,) if conn.marcado else None
                if "to_regclass" in ultimo:
                    return (True,)
                return (1, 450_000)

            def close(self):
                pass

        self._cur = Cur()

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_correcao_roda_em_lotes_e_marca():
    from collectors import odds_collector_service as mod
    conn = _ConnCorrecao(marcado=False)
    assert mod.corrigir_minuto_dos_retratos(conn) == 7 * 3      # 3 lotes de 200 mil
    updates = [s for s, _ in conn.sql if s.startswith("UPDATE")]
    assert len(updates) == 3
    assert any(s.startswith("INSERT INTO migracoes_motor") for s, _ in conn.sql)


def test_correcao_nao_roda_duas_vezes():
    from collectors import odds_collector_service as mod
    conn = _ConnCorrecao(marcado=True)
    assert mod.corrigir_minuto_dos_retratos(conn) is None
    assert not [s for s, _ in conn.sql if s.startswith("UPDATE")]


# ── 2. a coleta perto do apito ────────────────────────────────────────────
class _Cursor:
    def __init__(self, linhas):
        self.linhas = linhas
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))

    def fetchall(self):
        return self.linhas


def test_so_coleta_dentro_da_janela_e_sem_retrato():
    import capturar_fechamento as mod
    cur = _Cursor([
        (1, 20.0, False),    # dentro da janela, sem retrato -> coleta
        (2, 20.0, True),     # dentro da janela, ja' tem retrato -> nao
        (3, 200.0, False),   # longe do apito -> ainda nao
    ])
    agora, por_comecar = mod._pendentes(cur, {1, 2, 3})
    assert agora == [1]
    assert por_comecar == 3


def test_sem_pick_nao_consulta_nem_gasta():
    import capturar_fechamento as mod
    cur = _Cursor([])
    assert mod._pendentes(cur, set()) == ([], 0)
    assert cur.sql == []


def test_janela_cabe_no_corte_do_ledger():
    """Retrato tirado pela coleta tem que valer como fechamento no ledger."""
    import capturar_fechamento as mod
    from services import picks_ledger_sync_service as ledger
    assert mod.JANELA_MINUTOS + mod.INTERVALO_MINUTOS <= ledger.FECHAMENTO_MAX_MINUTOS


def test_jogos_com_pick_cobre_todos_os_produtos():
    import capturar_fechamento as mod
    sql = " ".join(mod._FIXTURES_COM_PICK)
    for tabela in ("picks_vip", "picks_free", "picks_faltas", "picks_player_stats",
                   "picks_boost", "picks_multiplas", "picks_bingo", "picks_alavancagem"):
        assert tabela in sql, tabela


def test_retrato_de_fechamento_nao_toca_odds_values(monkeypatch):
    """odds_values e' o que os motores leem: um pick gerado depois veria preco
    de outro momento do dia."""
    from collectors import odds_collector_service as mod

    class Cur:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append(sql)

        def fetchone(self):
            return ("2026-10-02 16:00",)

        def close(self):
            pass

    class Conn:
        def __init__(self):
            self.cur = Cur()

        def cursor(self):
            return self.cur

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    conn = Conn()
    gravado = []
    monkeypatch.setattr(mod, "get_connection", lambda *a, **k: conn)
    monkeypatch.setattr(mod, "_inserir_retratos", lambda cur, linhas: gravado.extend(linhas))
    coletor = mod.OddsCollectorService()
    coletor._casas = {8}
    n = coletor.save_snapshot_only(1, [
        {"id": 8, "bets": [{"id": 5, "values": [{"value": "Over 2.5", "odd": "1.90"}]}]},
        {"id": 99, "bets": [{"id": 5, "values": [{"value": "Over 2.5", "odd": "2.10"}]}]},
    ])
    assert n == 1, "casa fora das ativas nao entra"
    assert gravado[0][:6] == (1, 8, 5, "Over 2.5", None, 1.9)
    assert not any("odds_values" in s for s in conn.cur.sql)


def test_comando_fechamento_fica_fora_do_tudo():
    import main
    cmd = main.COMANDOS_POR_NOME["fechamento"]
    assert not cmd.etapa
