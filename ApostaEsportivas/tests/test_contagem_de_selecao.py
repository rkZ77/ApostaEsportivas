"""A contagem da aba de Auditoria nao pode contradizer a saida do motor.

REGRESSAO REAL (2026-08-29). `registrar_selecao` fazia `len(fixtures) or 1`
pra cobrir o bilhete combinado, que tem pick sem lista de partidas. Com lista
VAZIA -- o dia em que o motor nao salvou nada -- o `or 1` disparava, e a
execucao fechava com "1 selecionado" logo abaixo de um "[VIP_ENGINE] 0 picks
salvos." impresso pelo proprio motor.

O VIP chama a funcao uma vez depois do laco, salvando ou nao, entao o caso
vazio nao e' excecao: e' o dia normal em que nenhuma partida passou.
"""
from engine_pipelines import decision_log


class _RunFalso:
    """So' o que registrar_selecao toca. Sem run_id, entao nao encosta no banco."""

    pipeline = "VIP_ENGINE"
    run_id = None
    tabela_picks = "picks_vip"

    def __init__(self):
        self.selecionados = 0

    def selecionou(self, quantos=1):
        self.selecionados += quantos


def _com_run(monkeypatch, run):
    from services.engine_audit import audit
    monkeypatch.setattr(audit, "run_atual", lambda: run)
    return run


def test_dia_sem_pick_nao_conta_selecao(monkeypatch):
    run = _com_run(monkeypatch, _RunFalso())
    decision_log.registrar_selecao("VIP_ENGINE", [])
    assert run.selecionados == 0


def test_conta_uma_selecao_por_partida(monkeypatch):
    run = _com_run(monkeypatch, _RunFalso())
    decision_log.registrar_selecao("VIP_ENGINE", [111, 222, 333])
    assert run.selecionados == 3


def test_bilhete_combinado_conta_as_pernas(monkeypatch):
    """Multipla e alavancagem passam as pernas e o id do BILHETE · a contagem
    e' de jogos analisados que viraram pick, entao cada perna conta."""
    run = _com_run(monkeypatch, _RunFalso())
    run.pipeline = "MULTIPLA_ENGINE"
    decision_log.registrar_selecao("MULTIPLA_ENGINE", [111, 222], pick_id=7)
    assert run.selecionados == 2


def test_execucao_de_outro_pipeline_nao_e_contaminada(monkeypatch):
    """Dois motores podem rodar no mesmo processo (o `tudo`). A execucao
    corrente e' uma so', e quem nao e' dela nao mexe na contagem."""
    run = _com_run(monkeypatch, _RunFalso())
    decision_log.registrar_selecao("DICA_ENGINE", [111])
    assert run.selecionados == 0
