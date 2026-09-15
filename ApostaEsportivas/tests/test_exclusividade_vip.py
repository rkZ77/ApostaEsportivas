"""Exclusividade entre a Dica gratuita e o VIP · a ordem inverteu em 2026-09-15.

DE ONDE VEIO. Entre 2026-08-05 e 2026-09-14 o VIP rodava primeiro e RESERVAVA a
partida: a Free descia uma escada de três degraus (jogo livre com mercado novo,
jogo livre com mercado repetido, jogo do VIP com outro mercado) e só publicava o
que tivesse sobrado. A escada funcionava exatamente como prometia, e era esse o
problema: a Free é UM pick por dia e é a isca de aquisição, então ela tinha que
ser o melhor pick do dia · por construção, ela era o melhor pick RESTANTE.

O QUE VALE AGORA. A Free roda primeiro e escolhe o maior final_score do dia, sem
escada e sem reserva. O VIP continua avaliando todas as fixtures, inclusive a que
a Free pegou, e continua publicando um pick por partida · ele só não repete a
aposta IDÊNTICA (mesmo jogo + mesmo market_type + mesma linha). Repetir o jogo é
permitido, repetir o mercado em outro jogo é permitido.

O QUE ESTES TESTES PROTEGEM: que o veto do pick idêntico exista dos DOIS lados.
Ele não pode viver só no lado que roda por último, porque não existe "o lado que
roda por último": o /admin dispara cada pipeline como subprocesso separado, e foi
assim que Internacional x Remo saiu idêntico em picks_vip e picks_free em
17/08/2026 ("Ambas as Equipes Marcam Yes @1.90", Free 19:26:44, VIP 19:27:21).
"""
import inspect

import pytest

from engine_pipelines.dica_pipeline import _repete_pick_do_vip
from engine_pipelines.vip_pipeline import _escolher_pick

JOGO_A, JOGO_B = 111, 222


def _pick(market_type="goals", value_label="Over 2.5", **extra):
    return {"market_type": market_type, "value_label": value_label, **extra}


def _publicado(fixture_id=JOGO_A, market_type="goals", value_label="Over 2.5"):
    return {(fixture_id, market_type, value_label.strip().lower())}


# ═══════════════════════════════════════════════════════════════════════════
# Lado da Free: ela escolhe primeiro, então quase nada a limita
# ═══════════════════════════════════════════════════════════════════════════

def test_free_pode_pegar_o_jogo_que_o_vip_usou():
    """A reserva de partida acabou · só a aposta inteira é exclusiva."""
    assert _repete_pick_do_vip(_pick("corners", "Over 9.5"), JOGO_A, _publicado()) is False


def test_free_pode_repetir_o_mercado_do_vip_em_outro_jogo():
    assert _repete_pick_do_vip(_pick("goals", "Over 2.5"), JOGO_B, _publicado()) is False


def test_free_pode_trocar_a_linha_no_mesmo_jogo():
    """Over 2.5 e Under 3.5 são apostas distintas, não o mesmo pick."""
    assert _repete_pick_do_vip(_pick("goals", "Under 3.5"), JOGO_A, _publicado()) is False


def test_free_recusa_a_aposta_identica():
    assert _repete_pick_do_vip(_pick("goals", "Over 2.5"), JOGO_A, _publicado()) is True


def test_free_sem_vip_no_dia_nao_recusa_nada():
    """O caso normal desde a inversão: a Free roda com picks_vip ainda vazia."""
    assert _repete_pick_do_vip(_pick(), JOGO_A, set()) is False


@pytest.mark.parametrize("label_vip,label_free", [
    ("Over 2.5", "over 2.5"),
    ("OVER 2.5", "Over 2.5"),
    ("Over 2.5", " Over 2.5 "),
])
def test_comparacao_de_linha_ignora_caixa_e_espaco(label_vip, label_free):
    """A linha vem de fontes diferentes (motor e banco) · comparar cru deixaria
    o pick idêntico passar por diferença de formatação."""
    assert _repete_pick_do_vip(
        _pick("goals", label_free), JOGO_A, _publicado(value_label=label_vip)) is True


# ═══════════════════════════════════════════════════════════════════════════
# Lado do VIP: quem agora se acomoda, e só no pick, nunca no jogo
# ═══════════════════════════════════════════════════════════════════════════

def test_vip_mantem_o_melhor_do_jogo_quando_nao_ha_free():
    picks = [_pick("goals", "Over 2.5", is_best_pick=True), _pick("corners", "Over 9.5")]

    assert _escolher_pick(picks, JOGO_A, set())["market_type"] == "goals"


def test_vip_desce_pro_segundo_colocado_quando_o_melhor_e_o_da_free():
    """Ele não perde a partida · perde só aquela aposta."""
    picks = [_pick("goals", "Over 2.5", is_best_pick=True), _pick("corners", "Over 9.5")]

    escolhido = _escolher_pick(picks, JOGO_A, _publicado())

    assert escolhido is not None
    assert escolhido["market_type"] == "corners"


def test_vip_fica_sem_pick_no_jogo_quando_todos_repetem_a_free():
    picks = [_pick("goals", "Over 2.5", is_best_pick=True)]

    assert _escolher_pick(picks, JOGO_A, _publicado()) is None


def test_vip_publica_no_mesmo_jogo_com_outra_linha():
    picks = [_pick("goals", "Under 3.5", is_best_pick=True)]

    assert _escolher_pick(picks, JOGO_A, _publicado())["value_label"] == "Under 3.5"


def test_vip_respeita_a_ordem_do_ranking():
    """O is_best_pick vem primeiro mesmo quando não é o primeiro da lista."""
    picks = [_pick("corners", "Over 9.5"), _pick("goals", "Over 2.5", is_best_pick=True)]

    assert _escolher_pick(picks, JOGO_A, set())["market_type"] == "goals"


# ═══════════════════════════════════════════════════════════════════════════
# A trava de verdade é no BANCO, e agora precisa existir nos dois INSERTs
# ═══════════════════════════════════════════════════════════════════════════
#
# Ler o conjunto no começo da rodada é select-then-insert: entre o SELECT e o
# INSERT o outro pipeline pode ter commitado. Enquanto a ordem era fixa, só a
# Free precisava se defender; com a inversão, o VIP passou a ser o que pode
# chegar depois · e nenhum dos dois pode assumir que chegou primeiro.

def test_o_insert_da_free_checa_picks_vip_na_mesma_instrucao():
    from engine_pipelines import dica_pipeline

    fonte = inspect.getsource(dica_pipeline._save_pick)
    assert "NOT EXISTS" in fonte, "o INSERT precisa checar picks_vip atomicamente"
    assert "picks_vip" in fonte
    assert "fixture_id" in fonte and "market_type" in fonte
    assert "LOWER(TRIM(" in fonte, "a linha compara sem caixa/espaço"


def test_o_insert_do_vip_checa_picks_free_na_mesma_instrucao():
    """O espelho · nasceu com a inversão de 2026-09-15."""
    from engine_pipelines import vip_pipeline

    fonte = inspect.getsource(vip_pipeline._save_pick)
    assert "NOT EXISTS" in fonte, "o INSERT precisa checar picks_free atomicamente"
    assert "picks_free" in fonte
    assert "fixture_id" in fonte and "market_type" in fonte
    assert "LOWER(TRIM(" in fonte, "a linha compara sem caixa/espaço"


def test_a_free_nao_espera_mais_o_vip_rodar():
    """O gate que barrava a Free enquanto o VIP não tivesse rodado saiu junto
    com a escada · ele existia só porque a escada lia uma tabela que, vazia,
    era ambígua entre "o VIP não rodou" e "o VIP não achou nada"."""
    from engine_pipelines import dica_pipeline

    assert not hasattr(dica_pipeline, "_vip_ja_rodou_hoje")
    fonte = inspect.getsource(dica_pipeline.run_dica_engine)
    assert "engine_decisions" not in fonte
