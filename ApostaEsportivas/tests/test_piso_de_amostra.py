"""O piso de amostra é 8, e o gate é o mesmo ponto onde a amostra vira rica.

MEDIDO EM PROD EM 2026-09-24, em 358 pernas liquidadas com a amostra que
decidiu gravada (engine_decisions, candidato is_best_pick, de 10/06 a 22/09):

    amostra < 8     85 pernas   53,7%   -11,57u
    amostra >= 8   273 pernas   63,4%    +4,96u

O bloco curto cabe em três valores de n -- n=5 (28,6%), n=6 (48,3%), n=7
(33,3%) -- e não há desconto de confidence que o salve: dentro dele o
confidence é anti-preditivo (0.60-0.65 dá 66,7% e +1,51u; 0.70-0.75 dá 44,0% e
-6,63u). A nota inteira, com o custo de volume, está no topo de config.py.

Estes testes existem porque o piso já foi 4 (decisão de 28/08) e já foi 5/6
antes disso. Cada volta custou semanas de RED pra ser notada, e o número
sozinho no dataclass não conta essa história -- o teste conta, e quebra se
alguém mexer sem medir de novo.
"""
from services.pick_engine.config import (
    AMOSTRA_RICA,
    DEFAULT_CONFIG,
    VIP_CONFIG,
    DICA_CONFIG,
    ALAVANCAGEM_CONFIG,
    BINGO_CONFIG,
)
from services.pick_engine import ranking, stats_model


def test_piso_de_amostra_e_oito():
    assert DEFAULT_CONFIG.min_amostra == 8


def test_piso_e_o_mesmo_ponto_em_que_a_amostra_vira_rica():
    """Os dois são a mesma afirmação ("daqui pra cima a amostra estima"). Dois
    literais 8 no arquivo é como a divergência de model_fit nasceu."""
    assert DEFAULT_CONFIG.min_amostra == DEFAULT_CONFIG.sample_rich_n == AMOSTRA_RICA


def test_todos_os_pipelines_de_pre_jogo_herdam_o_piso():
    """Nenhum pipeline tem piso próprio: a fragilidade da estimativa não é
    propriedade do produto. Múltipla e alavancagem COMBINAM pernas, então uma
    perna de 6 jogos lá é pior que no pick simples, nunca melhor."""
    for cfg in (VIP_CONFIG, DICA_CONFIG, ALAVANCAGEM_CONFIG, BINGO_CONFIG):
        assert cfg.min_amostra == 8


def _candidato(amostra: int) -> dict:
    """Candidato que passa em TODOS os outros gates, pra isolar a amostra."""
    return {
        "market_type": "goals", "value_label": "Over 2.5", "odd": 1.80,
        "taxa_real": 0.70, "ev": 0.20, "edge": 0.10, "confidence": 0.75,
        "amostra": amostra, "bookmakers_count": 3,
    }


def test_candidato_com_sete_jogos_nao_e_aprovado():
    aprovados = ranking.rank_all_candidates([_candidato(7)], DEFAULT_CONFIG)

    assert aprovados == []


def test_candidato_com_oito_jogos_e_aprovado():
    aprovados = ranking.rank_all_candidates([_candidato(8)], DEFAULT_CONFIG)

    assert len(aprovados) == 1


def test_o_motivo_do_descarte_nomeia_a_amostra():
    """Silêncio de motor não é ausência de pick: quem for investigar "por que
    não saiu" tem de achar o número no motivo."""
    _, descartados = ranking.rank_all_candidates_debug([_candidato(6)], DEFAULT_CONFIG)

    assert any("amostra insuficiente (6 < 8)" in r
               for c in descartados for r in c["discard_reasons"])


def test_amostra_no_piso_ja_nasce_rica_no_rotulo_de_qualidade():
    """Coerência que faltava: o pick aprovado agora está sempre em RICO, então
    o rótulo de qualidade e o gate de aprovação param de contar histórias
    diferentes sobre o mesmo n."""
    assert stats_model.sample_quality(DEFAULT_CONFIG.min_amostra)["label"] == "RICO"
    assert stats_model.sample_quality(DEFAULT_CONFIG.min_amostra - 1)["label"] != "RICO"
