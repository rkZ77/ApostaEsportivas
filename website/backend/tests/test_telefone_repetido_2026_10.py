"""Telefone repetido sai da conta que nao fica com ele (12/10/2026). Sem banco."""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import migrations  # noqa: E402

FONTE = inspect.getsource(migrations.run_startup_migrations)


def test_limpa_antes_de_contar_e_de_criar_o_indice():
    limpa = FONTE.index("SET phone = NULL, phone_verified = FALSE, whatsapp_opt_in = FALSE")
    conta = FONTE.index("GROUP BY phone HAVING COUNT(*) > 1\n            ) d")
    indice = FONTE.index("CREATE UNIQUE INDEX IF NOT EXISTS users_phone_uniq")
    assert limpa < conta < indice


def test_quem_fica_com_o_numero():
    """Verificou > plano pago > mais antiga, nessa ordem."""
    ordem = FONTE[FONTE.index("ORDER BY COALESCE(phone_verified"):]
    assert ordem.index("phone_verified") < ordem.index("'free'") < ordem.index("id ASC")
    assert "r.ordem > 1" in FONTE        # a primeira da fila nunca e' tocada


def test_log_nao_leva_o_numero():
    trecho = FONTE[FONTE.index("telefone repetido tirado"):][:200]
    assert "phone" not in trecho.split(")")[0].replace("telefone", "")
