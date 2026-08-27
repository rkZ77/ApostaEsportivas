"""Engine Audit -- auditoria central dos motores (2026-08-27).

Tres pecas, nesta ordem de importancia:

  registry   quais motores existem, que metodos cada um tem, que versao roda
  audit      EngineRun: run_id, contagens, status e o registro por jogo
  amostra    quais jogos o motor leu, em formato exibivel

Uso tipico dentro de um pipeline:

    from services.engine_audit import EngineRun

    with EngineRun("PICK_BOOST", "over15_under25ht") as run:
        for fixture in fixtures:
            ...
            run.analisado(fixture, selecionado=True, score=94, dados={...})

Os pipelines de pre-jogo nao precisam nem disso: `decision_log` le a execucao
corrente sozinho (ver audit.run_atual), entao embrulhar a funcao de entrada no
`with` ja' carimba run_id em tudo que eles ja' gravavam.
"""
from services.engine_audit.audit import (  # noqa: F401
    COMPLETED,
    DESCARTADO,
    FAILED,
    PARTIAL,
    RUNNING,
    SELECIONADO,
    EngineRun,
    auditar,
    run_atual,
)
from services.engine_audit import amostra, registry  # noqa: F401

__all__ = [
    "EngineRun", "auditar", "run_atual", "amostra", "registry",
    "RUNNING", "COMPLETED", "FAILED", "PARTIAL",
    "SELECIONADO", "DESCARTADO",
]
