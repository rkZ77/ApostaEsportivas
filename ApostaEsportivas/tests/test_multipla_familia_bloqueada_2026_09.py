"""Escanteios não entra em bilhete combinado.

Medido em 15/09/2026 no `picks_ledger`, que liquida cada perna por conta
própria, sobre as pernas de múltipla já encerradas:

    escanteios   26 pernas   71,4% previsto   42,3% real   -8,12u
    gols         14 pernas   75,4% previsto   71,4% real   +0,44u
    cartões      13 pernas   68,9% previsto   53,8% real   -1,25u

Sozinha, a família perdeu mais do que a múltipla inteira. Com 26 pernas, 11
acertos onde a previsão dizia 18,6 fica a 3,3 desvios: não é ruído.

O gate é da COMBINAÇÃO, não do mercado. Escanteios continua saindo no VIP e no
ao vivo, onde o erro custa uma aposta; dentro do bilhete ele multiplica com o
da outra perna e derruba as duas.
"""
from services.pick_engine_multipla import component, config as cfg, reasons


def perna(market_type, **extra):
    """Perna que passa em todos os outros gates, pra o teste falar de um só."""
    base = {
        "market_type": market_type, "ev": 0.12, "edge": 0.10,
        "data_quality_score": 0.95, "taxa_real": 0.75, "amostra": 20,
        "risco": "BAIXO", "confidence": 0.80, "projection_margin": 2.0,
        "projecao": {"margem_desvios": 1.5},
    }
    base.update(extra)
    return base


def test_escanteios_nao_entra_na_multipla():
    avaliada = component.avaliar(perna("corners"))
    assert reasons.PERNA_FAMILIA_BLOQUEADA in avaliada["motivos"]
    assert avaliada["aprovada"] is False


def test_gols_continua_entrando():
    avaliada = component.avaliar(perna("goals"))
    assert reasons.PERNA_FAMILIA_BLOQUEADA not in avaliada["motivos"]


def test_o_bloqueio_e_configuravel_e_nao_uma_regra_escrita_na_pedra():
    """Quando a calibragem de escanteios for corrigida, a lista volta a ser
    vazia -- e o teste garante que isso basta."""
    import dataclasses
    liberado = dataclasses.replace(cfg.padrao(), familias_bloqueadas=())
    avaliada = component.avaliar(perna("corners"), liberado)
    assert reasons.PERNA_FAMILIA_BLOQUEADA not in avaliada["motivos"]


def test_a_familia_bloqueada_hoje_e_escanteios():
    assert cfg.FAMILIAS_BLOQUEADAS == ("corners",)
