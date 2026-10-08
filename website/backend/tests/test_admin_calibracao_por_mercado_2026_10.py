"""Admin · calibracao por mercado (08/10/2026): o que o motor prometeu, o que o
preco dizia e o que aconteceu, so' nas pernas decididas."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers.admin import _add, _bucket, _fechar  # noqa: E402


def test_prometido_implicita_e_acerto_da_mesma_amostra():
    b = _bucket()
    _add(b, {"result": "GREEN", "odd": 2.0, "probability": 0.60, "profit": 1.0, "clv": 0.04})
    _add(b, {"result": "RED", "odd": 1.6, "probability": 70, "profit": -1.0})   # em %, tambem vale
    _add(b, {"result": None, "odd": 1.5, "probability": 0.9})                    # pendente fica fora
    _add(b, {"result": "PUSH", "odd": 1.9, "probability": 0.5, "profit": 0})     # push fica fora
    r = _fechar(b)
    assert r["prometido"] == 65.0
    assert r["implicita"] == round((0.5 + 0.625) / 2 * 100, 1)
    assert r["hit"] == 50.0 and r["clv"] == 4.0 and r["n_clv"] == 1


def test_sem_probabilidade_nao_inventa():
    b = _bucket()
    _add(b, {"result": "GREEN", "odd": 2.0, "profit": 1.0})
    r = _fechar(b)
    assert r["prometido"] is None and r["implicita"] == 50.0
