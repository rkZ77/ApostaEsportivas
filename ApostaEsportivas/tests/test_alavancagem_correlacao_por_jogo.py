"""Correlacao na alavancagem e' por JOGO, nao por familia solta.

A regra antiga rejeitava todo combo cujas pernas tivessem o mesmo market_type,
sem olhar de que partida vinham. Como o teto de odd de 1.55 faz o motor
produzir quase so' mercado de gols (Over 0.5 / Under 4.5 / Under 5.5), na
pratica isso vetava TODA dupla e TODA tripla: em 08/08 foram 12 pernas
candidatas, todas `goals`, e o dia terminou sem alavancagem.

O que continua vetado e' o que e' correlacao de verdade: duas pernas do mesmo
jogo e da mesma familia.
"""
import pytest

from engine_pipelines.alavancagem_pipeline import (
    ODD_COMBINED_MAX, ODD_COMBINED_MIN, _find_combo,
)


def perna(fixture_id, market_type, odd, confidence=0.75, final_score=0.7):
    return {
        "_fixture": {"fixture_id": fixture_id},
        "market_type": market_type,
        "odd": odd,
        "confidence": confidence,
        "final_score": final_score,
    }


def _combinar(legs):
    return _find_combo(legs, ODD_COMBINED_MIN, ODD_COMBINED_MAX)


def test_mesma_familia_em_jogos_diferentes_agora_combina():
    """O caso real de 08/08: duas pernas de gols, partidas diferentes."""
    combo = _combinar([perna(1, "goals", 1.39), perna(2, "goals", 1.11)])
    assert combo is not None
    pernas, _conf, odd = combo
    assert len(pernas) == 2
    assert odd == pytest.approx(1.5429, abs=1e-4)
    assert ODD_COMBINED_MIN <= odd <= ODD_COMBINED_MAX


def test_mesma_familia_no_mesmo_jogo_continua_vetada():
    """'Over 1.5 gols' e 'Under 4.5 gols' no mesmo jogo e' a mesma aposta."""
    assert _combinar([perna(7, "goals", 1.39), perna(7, "goals", 1.11)]) is None


def test_familias_do_mesmo_dado_bruto_contam_como_uma_so():
    """cards e handicap_cards saem do mesmo contador -- correlation_group
    junta os dois, mesmo criterio que _today_used_pairs ja usa."""
    assert _combinar([perna(7, "cards", 1.39), perna(7, "handicap_cards", 1.11)]) is None


def test_mercados_diferentes_no_mesmo_jogo_continuam_permitidos():
    """Formato "dois mercados no mesmo jogo" e' valido por decisao de produto."""
    combo = _combinar([perna(7, "goals", 1.39), perna(7, "corners", 1.11)])
    assert combo is not None
    assert len(combo[0]) == 2


def test_tripla_da_mesma_familia_em_tres_jogos():
    combo = _combinar([perna(1, "goals", 1.15), perna(2, "goals", 1.12),
                       perna(3, "goals", 1.10)])
    assert combo is not None
    pernas, _conf, odd = combo
    assert len(pernas) == 3
    assert ODD_COMBINED_MIN <= odd <= ODD_COMBINED_MAX


def test_faixa_continua_valendo():
    """Afrouxar a correlacao nao pode ter afrouxado a faixa de odd.

    Os dois casos precisam falhar nos TRES formatos (dupla, tripla e simples),
    senao o teste passa por acidente: uma dupla fora da faixa ainda cai pro
    formato simples, e ai o que responde e' a odd de uma perna so'.
    """
    # dupla baixa demais (1.22) e nenhuma perna sozinha alcanca 1.40
    assert _combinar([perna(1, "goals", 1.10), perna(2, "corners", 1.11)]) is None
    # dupla alta demais (1.76) e nenhuma perna sozinha alcanca 1.40
    assert _combinar([perna(1, "goals", 1.35), perna(2, "corners", 1.30)]) is None


def test_dupla_fora_da_faixa_cai_pro_formato_simples():
    """Nao e' fallback de odd (aquele foi removido em 07/08): e' o terceiro
    formato valido, com a MESMA faixa. A dupla da 2.10 e nao serve; a perna de
    1.50 esta dentro de [1.40, 1.55] e vira o bilhete."""
    combo = _combinar([perna(1, "goals", 1.50), perna(2, "corners", 1.40)])
    assert combo is not None
    pernas, _conf, odd = combo
    assert len(pernas) == 1
    assert odd == 1.50


def test_prefere_combo_a_perna_solteira():
    """Simples fica por ultimo: uma perna de 1.45 nao pode vencer uma dupla
    que tambem fecha na faixa (bug real, as 30 primeiras alavancagens sairam
    todas como 'simples')."""
    combo = _combinar([perna(1, "goals", 1.45), perna(2, "goals", 1.25),
                       perna(3, "corners", 1.20)])
    assert combo is not None
    assert len(combo[0]) == 2


def test_escolhe_o_bilhete_de_maior_confianca():
    """Confianca do BILHETE e' o produto, nao a media das pernas."""
    combo = _combinar([
        perna(1, "goals", 1.20, confidence=0.90, final_score=0.9),
        perna(2, "corners", 1.20, confidence=0.90, final_score=0.9),
        perna(3, "cards", 1.20, confidence=0.60, final_score=0.8),
    ])
    assert combo is not None
    pernas, conf, _odd = combo
    assert conf == pytest.approx(0.81, abs=1e-4)
    assert {p["_fixture"]["fixture_id"] for p in pernas} == {1, 2}
