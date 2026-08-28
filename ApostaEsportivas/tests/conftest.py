import sys
from pathlib import Path

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def _sem_banco_no_teste(monkeypatch):
    """Nenhum teste do motor fala com banco nenhum.

    A suite do site ja' tinha esta trava (website/backend/tests/conftest.py); a
    do motor nao tinha, e o buraco e' o mesmo: `.env` na raiz do repo tem
    DB_HOST_PROD, e `utils/db_utils.get_connection()` cai nele quando DB_ENV
    nao esta' definido. Um teste que chame qualquer funcao com acesso a banco
    abre conexao com PRODUCAO a partir da maquina de quem rodou `pytest`.

    Nao e' hipotese: em 2026-08-28, ao envolver o agregador de medias numa
    conexao de lote, `test_medias_so_do_que_mudou` passou a imprimir
    "[DB] Conectando ao banco PROD" no meio da suite. O codigo novo estava
    certo; o que faltava era esta trava.

    Quem precisar de banco de verdade um dia pede um fixture explicito e
    desliga este.
    """
    def _recusa(*_a, **_kw):
        raise RuntimeError(
            "Teste tentou abrir conexao de banco. Use duble ou monkeypatch: "
            "a suite nao pode tocar em banco real."
        )

    import utils.db_utils as db_utils
    monkeypatch.setattr(db_utils, "get_connection", _recusa)
    # Modulos que importaram o nome direto (`from utils.db_utils import
    # get_connection`) ficam com a referencia antiga · trocar so' no modulo de
    # origem nao alcanca nenhum deles.
    for nome, modulo in list(sys.modules.items()):
        if not nome.startswith(("services", "collectors", "engine_pipelines", "utils")):
            continue
        if getattr(modulo, "get_connection", None) is not None:
            monkeypatch.setattr(modulo, "get_connection", _recusa, raising=False)
