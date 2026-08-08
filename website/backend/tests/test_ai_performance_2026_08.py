"""Painel de desempenho por modelo de IA (/api/admin/ai-performance).

A conta que esta rota faz e' a unica coisa no site que responde "vale ligar o
enforce?", e ela e' facil de errar pro lado otimista: contar pick que a IA
nunca viu, creditar veto a modelo errado, ou comparar modelo com modelo
misturando pipelines de dificuldade diferente. Cada teste aqui trava um desses.

Nada toca banco: o cursor e' dublê e devolve linha canonica por trecho de SQL.
"""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.admin as admin  # noqa: E402


class _FakeCursor:
    """Responde por trecho do SQL, nao por ordem de chamada: a rota pode
    reordenar as consultas sem quebrar o teste."""

    def __init__(self, legs, eventos, tem_coluna=True):
        self._legs = legs
        self._eventos = eventos
        self._tem_coluna = tem_coluna
        self._rows = []

    def execute(self, sql, params=None):
        if "information_schema.columns" in sql:
            self._rows = [{"exists": 1}] if self._tem_coluna else []
        elif "FROM picks_ledger" in sql:
            self._rows = list(self._legs)
        elif "ai_pick_review_events" in sql:
            self._rows = list(self._eventos)
        else:
            raise AssertionError(f"consulta inesperada: {sql[:80]}")

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *_a, **_kw):
        return self._cursor

    def rollback(self):
        pass

    def close(self):
        pass


def _rodar(monkeypatch, legs, eventos, tem_coluna=True, days=60):
    cur = _FakeCursor(legs, eventos, tem_coluna)
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    return admin.ai_performance(days=days, current_user={"id": 1, "plan": "admin"})


def _leg(**kw):
    base = {
        "pick_type": "vip", "ai_provider": "openai", "ai_model": "gpt-5.4",
        "ai_decision": "approve", "ai_status": "ok",
        "result": "GREEN", "profit": 1.0, "clv": 0.02, "dia": "2026-08-01",
    }
    return {**base, **kw}


def _evento(**kw):
    base = {"provider": "openai", "model": "gpt-5.4", "pipeline": "vip",
            "dia": "2026-08-01", "n": 10, "cache": 4, "vetos": 2, "falhas": 0}
    return {**base, **kw}


def test_veto_que_separa_bem_da_lift_positivo(monkeypatch):
    """Aprovados ganhando e vetados perdendo = o veto esta' certo."""
    legs = (
        [_leg(result="GREEN") for _ in range(8)]
        + [_leg(result="RED", profit=-1.0) for _ in range(2)]
        + [_leg(ai_decision="reject", result="RED", profit=-1.0) for _ in range(9)]
        + [_leg(ai_decision="reject", result="GREEN", profit=1.0)]
    )
    dados = _rodar(monkeypatch, legs, [_evento()])
    modelo = dados["modelos"][0]

    assert modelo["aprovados"]["hit"] == 80.0
    assert modelo["vetados"]["hit"] == 10.0
    assert modelo["lift"] == 70.0
    # O veto teria poupado 8 unidades (9 reds evitados, 1 green perdido).
    assert modelo["economia_do_veto"] == 8.0


def test_pick_sem_parecer_valido_nao_entra_na_conta_de_nenhum_modelo(monkeypatch):
    """`unavailable` e `disabled` significam que NENHUM modelo olhou o pick --
    o gate falha aberto. Creditar esse green a um modelo inflaria justamente o
    numero que decide se o enforce entra."""
    legs = [
        _leg(result="GREEN"),
        _leg(ai_status="unavailable", result="GREEN"),
        _leg(ai_status="disabled", ai_model=None, ai_provider=None, result="GREEN"),
        _leg(ai_status=None, ai_model=None, ai_provider=None, result="GREEN"),
    ]
    dados = _rodar(monkeypatch, legs, [_evento()])

    assert dados["modelos"][0]["aprovados"]["n"] == 1
    assert dados["cobertura"]["com_parecer"] == 1
    assert dados["cobertura"]["sem_parecer"] == 3
    assert {f["status"] for f in dados["falhas"]} == {"unavailable", "disabled"}


def test_pick_antigo_sem_autor_e_atribuido_pelo_pipeline_do_dia(monkeypatch):
    """Pick anterior ao carimbo de provider/model nao diz quem o revisou. O
    modelo que revisou aquele pipeline naquele dia e' a melhor atribuicao
    possivel, e ela precisa ficar marcada como inferida."""
    legs = [_leg(ai_model=None, ai_provider=None, pick_type="free", dia="2026-08-01")]
    eventos = [_evento(provider="anthropic", model="claude-sonnet-5", pipeline="dica")]

    dados = _rodar(monkeypatch, legs, eventos)

    assert dados["cobertura"]["autor_inferido"] == 1
    assert dados["cobertura"]["autor_gravado"] == 0
    assert dados["modelos"][0]["model"] == "claude-sonnet-5"


def test_sem_evento_no_dia_o_pick_fica_sem_dono_em_vez_de_ir_pro_modelo_errado(monkeypatch):
    legs = [_leg(ai_model=None, ai_provider=None, dia="2026-07-01")]
    eventos = [_evento(dia="2026-08-01")]

    dados = _rodar(monkeypatch, legs, eventos)

    assert dados["cobertura"]["autor_desconhecido"] == 1
    assert all(m["aprovados"]["n"] == 0 for m in dados["modelos"])


def test_push_nao_conta_como_acerto_nem_como_erro(monkeypatch):
    legs = [_leg(result="GREEN"), _leg(result="PUSH", profit=0.0), _leg(result=None, profit=None)]
    dados = _rodar(monkeypatch, legs, [_evento()])
    aprovados = dados["modelos"][0]["aprovados"]

    assert aprovados["hit"] == 100.0
    assert aprovados["resolvidos"] == 1
    assert aprovados["push"] == 1
    assert aprovados["pendentes"] == 1


def test_recorte_por_pipeline_nao_mistura_fluxos(monkeypatch):
    """Comparar dois modelos pelo total mistura mercados de dificuldade
    diferente. O recorte por pipeline e' o que torna a comparacao honesta."""
    legs = [
        _leg(pick_type="vip", result="GREEN"),
        _leg(pick_type="faltas", ai_provider="anthropic",
             ai_model="claude-sonnet-5", result="RED", profit=-1.0),
    ]
    eventos = [_evento(), _evento(provider="anthropic", model="claude-sonnet-5", pipeline="faltas")]

    dados = _rodar(monkeypatch, legs, eventos)
    por_tipo = {p["pick_type"]: p for p in dados["por_pipeline"]}

    assert por_tipo["vip"]["aprovados"]["hit"] == 100.0
    assert por_tipo["faltas"]["aprovados"]["hit"] == 0.0
    assert por_tipo["vip"]["model"] != por_tipo["faltas"]["model"]


def test_modelo_sem_pick_resolvido_ainda_aparece_com_o_custo(monkeypatch):
    """Modelo que so' gastou chamada e ainda nao tem pick resolvido nao pode
    sumir da tela: o custo ja' existe e precisa estar visivel."""
    dados = _rodar(monkeypatch, [], [_evento(n=12, cache=5, vetos=3, falhas=1)])
    modelo = dados["modelos"][0]

    assert modelo["reviews"] == 12
    assert modelo["chamadas"] == 7
    assert modelo["falhas"] == 1
    assert modelo["taxa_veto"] == 25.0
    assert modelo["lift"] is None


def test_ledger_sem_as_colunas_novas_avisa_em_vez_de_estourar(monkeypatch):
    dados = _rodar(monkeypatch, [], [], tem_coluna=False)
    assert dados["migration_pending"] is True
    assert dados["modelos"] == []


def test_janela_de_dias_e_limitada(monkeypatch):
    assert _rodar(monkeypatch, [], [], days=9999)["days"] == 365
    assert _rodar(monkeypatch, [], [], days=0)["days"] == 1


@pytest.mark.parametrize("pick_type,pipeline", [
    ("free", "dica"), ("vip", "vip"), ("multipla", "multipla"),
    ("alavancagem", "alavancagem"), ("faltas", "faltas"), ("goleiros", "goleiros"),
])
def test_todo_tipo_de_pick_tem_pipeline_correspondente(pick_type, pipeline):
    """O ledger fala 'free' e o gate fala 'dica'. Um mapa incompleto faria o
    pipeline sumir da atribuicao retroativa em silencio."""
    assert admin._PIPELINE_POR_PICK_TYPE[pick_type] == pipeline
