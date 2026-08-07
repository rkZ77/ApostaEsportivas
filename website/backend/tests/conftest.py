import os
import sys

import pytest

# Evita RuntimeError de JWT_SECRET ausente ao importar auth_utils em dev/CI.
os.environ.setdefault("APP_ENV", "development")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _sem_banco_no_teste(monkeypatch):
    """Nenhum teste fala com banco nenhum.

    Nao e' zelo abstrato: `.env` na raiz do repo tem DB_HOST_PROD, e
    `database.get_connection()` cai nela quando DB_HOST nao existe. Ou seja, um
    teste que chamasse qualquer funcao com acesso a banco escrevia em PRODUCAO
    a partir da maquina de quem rodou `pytest` -- ja aconteceu, com duas linhas
    de teste indo parar na tabela payment_events de producao.

    Quem precisar de banco de verdade um dia pede o fixture explicitamente e
    desliga este.
    """
    def _recusa(*_a, **_kw):
        raise RuntimeError(
            "Teste tentou abrir conexao de banco. Use dublê ou monkeypatch: "
            "a suite nao pode tocar em banco real."
        )

    import database
    monkeypatch.setattr(database, "get_connection", _recusa)
    for modulo in ("routers.payments", "routers.admin", "auth_utils"):
        alvo = sys.modules.get(modulo)
        if alvo is not None and hasattr(alvo, "get_connection"):
            monkeypatch.setattr(alvo, "get_connection", _recusa)
