"""O veto por direção existe, e no pré-jogo ele está DESLIGADO.

A história, porque ela é o teste: em 24/09/2026 cartão Over media 36,7% e
-13,57u contra 79,7% e +21,98u do Under, em 89 pernas, consistente nos cinco
produtos e nos quatro meses. O veto foi ligado e revertido no mesmo dia, ao
separar os picks pela data em que o peso por força do adversário foi aposentado
(15/09):

    antes de 15/09    Over  25 pernas  24,0%  -15,30u
    depois de 15/09   Over   5 pernas  80,0%   +1,73u

Os "quatro meses consistentes" eram quatro meses do mesmo peso defeituoso. A
nota inteira está em config.py::familias_somente_under.

O que estes testes travam: o mecanismo funciona quando alguém o ligar, e ele
nasce desligado. Um default que voltasse a ("cards",) sem medição nova quebra o
primeiro teste, e é ele que segura a lição.
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


# ── O default: nenhuma família vetada no pré-jogo ─────────────────────────
def test_nenhuma_familia_esta_vetada_por_padrao():
    """Ligar de novo exige medição nova, com 25+ pernas nascidas depois de
    15/09 · ver a nota em config.py."""
    assert DEFAULT_CONFIG.familias_somente_under == ()


def test_cartao_over_continua_saindo_com_o_default():
    aprovados = ranking.rank_all_candidates(
        [candidato("cards", "over")], DEFAULT_CONFIG)

    assert len(aprovados) == 1


# ── O mecanismo, pra quando a medição pedir ───────────────────────────────
def _com_cartoes_vetados() -> PickEngineConfig:
    return PickEngineConfig(familias_somente_under=("cards",))


def test_veto_ligado_reprova_o_over_da_familia():
    assert ranking.rank_all_candidates(
        [candidato("cards", "over")], _com_cartoes_vetados()) == []


def test_veto_ligado_nao_toca_no_under():
    """O lado que mediu +21,98u não pode cair junto: o erro é direcional e a
    regra tem de ser também."""
    aprovados = ranking.rank_all_candidates(
        [candidato("cards", "under")], _com_cartoes_vetados())

    assert len(aprovados) == 1


def test_veto_ligado_nao_toca_em_outra_familia():
    """Escanteios Over mediu 70,9% e +18,79u · o veto é de uma família."""
    aprovados = ranking.rank_all_candidates(
        [candidato("corners", "over")], _com_cartoes_vetados())

    assert len(aprovados) == 1


def test_familia_sem_direcao_passa_batido():
    """Resultado e dupla chance não têm over/under, e não precisam de exceção
    escrita à mão pra isso."""
    aprovados = ranking.rank_all_candidates(
        [candidato("result", "home")], _com_cartoes_vetados())

    assert len(aprovados) == 1


def test_o_motivo_do_descarte_nomeia_a_direcao():
    """Silêncio de motor não é ausência de pick: quem investigar "por que não
    saiu cartão" tem de achar a resposta no motivo."""
    _, descartados = ranking.rank_all_candidates_debug(
        [candidato("cards", "over")], _com_cartoes_vetados())

    assert any("so' entra em UNDER" in r
               for c in descartados for r in c["discard_reasons"])
