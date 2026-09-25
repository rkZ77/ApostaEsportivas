"""Cartão só entra por UNDER, e o Under continua entrando.

MEDIDO EM PROD EM 2026-09-24, 89 pernas liquidadas de 10/06 a 22/09:

    cards Over    30 pernas   36,7%   -13,57u
    cards Under   59 pernas   79,7%   +21,98u

A assimetria aparece nos cinco produtos, nos quatro meses e nos três escopos --
não é recorte. A nota inteira, com a parte do viés que tem causa nomeada (a
liquidação conta só cartão de quem estava em campo desde 10/09, a média
histórica conta banco e comissão técnica), está em config.py::
familias_somente_under.

O teste que importa aqui é o segundo: vetar a FAMÍLIA jogaria fora +21,98u. O
erro é direcional, e a regra tem de ser também.
"""
from services.pick_engine import ranking
from services.pick_engine.config import DEFAULT_CONFIG, PickEngineConfig


def candidato(market_type: str, value: str) -> dict:
    """Passa em todos os outros gates, pra isolar a direção."""
    return {
        "market_type": market_type, "value": value,
        "value_label": f"{value.title()} 4.5", "odd": 1.80,
        "taxa_real": 0.70, "ev": 0.20, "edge": 0.10, "confidence": 0.75,
        "amostra": 12, "bookmakers_count": 3,
    }


def test_cartao_over_nao_e_aprovado():
    assert ranking.rank_all_candidates(
        [candidato("cards", "over")], DEFAULT_CONFIG) == []


def test_cartao_under_continua_aprovado():
    """O lado que paga +21,98u não pode cair junto."""
    aprovados = ranking.rank_all_candidates(
        [candidato("cards", "under")], DEFAULT_CONFIG)

    assert len(aprovados) == 1


def test_over_de_outra_familia_nao_e_afetado():
    """Escanteios Over mediu 70,9% e +18,79u · o veto é de cartão, não de Over."""
    aprovados = ranking.rank_all_candidates(
        [candidato("corners", "over")], DEFAULT_CONFIG)

    assert len(aprovados) == 1


def test_familia_sem_direcao_passa_batido():
    """Resultado e dupla chance não têm over/under, e não precisam de exceção
    escrita à mão pra isso."""
    aprovados = ranking.rank_all_candidates(
        [candidato("result", "home")], DEFAULT_CONFIG)

    assert len(aprovados) == 1


def test_o_motivo_do_descarte_nomeia_a_direcao():
    """Silêncio de motor não é ausência de pick: quem investigar "por que não
    saiu cartão hoje" tem de achar a resposta no motivo."""
    _, descartados = ranking.rank_all_candidates_debug(
        [candidato("cards", "over")], DEFAULT_CONFIG)

    assert any("so' entra em UNDER" in r
               for c in descartados for r in c["discard_reasons"])


def test_lista_vazia_desliga_a_regra():
    """Religar é trocar uma tupla, não editar o gate -- é o que permite remedir
    depois de corrigir a média histórica de cartão."""
    cfg = PickEngineConfig(familias_somente_under=())

    aprovados = ranking.rank_all_candidates([candidato("cards", "over")], cfg)

    assert len(aprovados) == 1
