"""Alavancagem: escolha do combo e leitura das pernas no fechamento.

Os dois bugs cobertos aqui produziam dado errado sem levantar excecao nenhuma,
entao nada no sistema reclamava -- so' dava pra ver olhando o que foi gravado.
"""
import pytest

from engine_pipelines.alavancagem_pipeline import (
    ODD_COMBINED_MAX,
    ODD_COMBINED_MIN,
    _TIPO_POR_TAMANHO,
    _find_combo,
    _today_used_pairs,
)
from services.pick_engine.config import ALAVANCAGEM_CONFIG


class _CursorFake:
    """Devolve a lista de linhas de cada tabela na ordem em que _today_used_pairs
    consulta: picks_vip primeiro, picks_free depois."""

    def __init__(self, vip, free):
        self._por_tabela = {"picks_vip": vip, "picks_free": free}
        self._atual = []

    def execute(self, sql, params=None):
        self._atual = next(
            linhas for tabela, linhas in self._por_tabela.items() if tabela in sql)

    def fetchall(self):
        return self._atual


def _leg(odd, market_type, final_score, confidence=0.80, taxa_real=None,
         fixture_id=1, amostra=25, data_quality_score=85.0, risco="BAIXO",
         direcao="over", linha=1.5):
    """Perna completa, como o pick_engine entrega.

    `taxa_real` sai da odd por padrao, com +15% de EV embutido. O default fixo
    de 0.75 que existia aqui produzia perna de EV NEGATIVO em qualquer odd
    abaixo de 1.34 (0.75 x 1.25 = 0.94) -- um candidato que o motor real nunca
    aprovaria, e que so' passava porque `_find_combo` nao olhava EV nenhum
    antes da V2.
    """
    taxa = taxa_real if taxa_real is not None else min(0.97, round(1.15 / odd, 4))
    return {
        "odd": odd,
        "market_type": market_type,
        "market_name": market_type,
        "value_label": f"{direcao.title()} {linha}",
        "scope": "total",
        "final_score": final_score,
        "confidence": confidence,
        "taxa_real": taxa,
        "edge": round(taxa - (1.0 / odd) + 0.09, 4),
        "ev": round(taxa * odd - 1.0, 4),
        "amostra": amostra,
        "data_quality_score": data_quality_score,
        "risco": risco,
        "_direction": direcao,
        "_line_val": linha,
        "_fixture": {"fixture_id": fixture_id},
    }


def _combinar(legs):
    """`_find_combo` devolve (pernas, confidence, odd, avaliacao) desde a V2 --
    a avaliacao e' o documento de decisao do bilhete (§50). Os testes daqui
    olham os tres primeiros; quem testa a avaliacao e' test_alavancagem_v2."""
    resultado = _find_combo(legs, ODD_COMBINED_MIN, ODD_COMBINED_MAX)
    if resultado is None:
        return None
    pernas, confidence, odd, _avaliacao = resultado
    return pernas, confidence, odd


def test_dupla_cabe_na_faixa_com_o_piso_de_odd_do_motor():
    """O invariante que estava quebrado sem ninguem ver, ate 2026-08-07.

    A alavancagem herdava o min_odd=1.39 do motor (piso do VIP). A dupla mais
    barata possivel virava 1.39 * 1.39 = 1.93, ja' acima do teto de 1.55 do
    bilhete: NENHUMA dupla cabia na faixa, nunca. Nao era dupla rara, era
    aritmeticamente impossivel -- e foi por isso que as 30 alavancagens geradas
    ate essa data sairam todas 'simples'. Trocar a ordem de tentativa pra
    (2, 3, 1) em 02/08 nao resolveu porque nao havia dupla pra testar.

    Este teste liga as duas pontas (config do motor e faixa do bilhete) pra que
    subir o piso de volta, ou baixar o teto, quebre aqui em vez de silenciosamente
    zerar a dupla de novo em producao.
    """
    dupla_mais_barata = ALAVANCAGEM_CONFIG.min_odd ** 2

    assert dupla_mais_barata <= ODD_COMBINED_MAX, (
        f"dupla minima {dupla_mais_barata:.4f} nao cabe em "
        f"[{ODD_COMBINED_MIN}, {ODD_COMBINED_MAX}] -- alavancagem volta a ser so' simples"
    )


def test_teto_da_perna_nao_passa_do_teto_do_bilhete():
    """Perna acima do teto do combinado nao entra em combo nenhum: sozinha ja'
    estoura a faixa, e multiplicada por outra (>= 1.05) so' se afasta mais."""
    assert ALAVANCAGEM_CONFIG.max_odd <= ODD_COMBINED_MAX


def test_o_formato_nao_decide_nada_a_probabilidade_decide():
    """A REGRA QUE A V2 INVERTEU.

    Este teste dizia "prefere combo de duas pernas a uma simples", e a ordem de
    tentativa (2, 3, 1) existia pra garantir isso. A premissa era de produto:
    combo seria o formato preferido. A aritmetica diz outra coisa -- a faixa
    [1.40, 1.55] e' do TOTAL do bilhete, entao dupla e simples nessa faixa
    pagam o MESMO. A segunda perna nao aumenta o retorno; acrescenta uma
    segunda maneira de perder.

    Entao o formato deixou de ser criterio. Com as mesmas tres pernas, muda so'
    a probabilidade da simples, e a resposta vira do avesso.
    """
    dupla = _combinar([
        _leg(1.45, "goals", 0.90, fixture_id=1),           # cabe sozinha no alvo
        _leg(1.20, "corners", 0.85, fixture_id=2),
        _leg(1.25, "cards", 0.84, fixture_id=3),           # 1.20 * 1.25 = 1.50
    ])
    assert _TIPO_POR_TAMANHO[len(dupla[0])] == "dupla"
    assert ODD_COMBINED_MIN <= dupla[2] <= ODD_COMBINED_MAX

    simples = _combinar([
        _leg(1.45, "goals", 0.90, fixture_id=1, taxa_real=0.90),
        _leg(1.20, "corners", 0.85, fixture_id=2),
        _leg(1.25, "cards", 0.84, fixture_id=3),
    ])
    assert _TIPO_POR_TAMANHO[len(simples[0])] == "simples"


def test_cai_para_simples_quando_nenhum_combo_cabe_na_faixa():
    """Perna unica continua sendo formato valido (o usuario confirmou em
    2026-08-07 que "somente um pick" serve), desde que a odd dela caia na
    faixa. Isso e' independente do fallback de ODD que foi removido: alargar
    a faixa pra 1.90 nunca mais acontece, cair pra simples dentro da faixa
    sim."""
    legs = [
        _leg(1.45, "goals", 0.90, fixture_id=1),
        _leg(1.80, "corners", 0.88, fixture_id=2),  # 1.45*1.80 = 2.61, fora do alvo
    ]

    combo, _confidence, odd_combined = _combinar(legs)

    assert len(combo) == 1
    assert _TIPO_POR_TAMANHO[len(combo)] == "simples"
    assert odd_combined == pytest.approx(1.45)


def test_recusa_combo_com_pernas_do_mesmo_mercado_no_mesmo_jogo():
    """Duas pernas da mesma familia NO MESMO JOGO sao a mesma aposta duas vezes.

    Este teste ja' existiu com as duas pernas em fixtures DIFERENTES (1 e 2) e
    passava, porque a regra de entao olhava so' o market_type. Ela vetava
    correlacao que nao existe -- dois jogos diferentes, no mesmo dia, nao sao a
    mesma aposta -- e o preco foi o produto: em 08/08 as 12 pernas candidatas
    eram todas `goals` e nenhuma dupla chegou a ter a odd calculada. Ver
    _find_combo. Aqui as duas passam a dividir o fixture 1, que e' o caso que a
    regra sempre quis pegar.
    """
    legs = [
        _leg(1.20, "corners", 0.90, fixture_id=1),
        _leg(1.25, "corners", 0.89, fixture_id=1),
    ]

    resultado = _combinar(legs)

    # Sobra so' o caminho de perna unica, e nenhuma das duas odds cabe no alvo.
    assert resultado is None


def test_aceita_mesma_familia_em_jogos_diferentes():
    """O contraponto do teste acima, que e' a mudanca de 2026-08-08.

    Continua aceito, mas deixou de ser de graca: a V2 classifica o par como
    correlacao MEDIA ("a mesma estimativa de corners sustenta as duas pernas")
    e cobra por isso um desconto na probabilidade combinada. Independente no
    gramado nao e' independente no modelo.
    """
    legs = [
        _leg(1.20, "corners", 0.90, fixture_id=1),
        _leg(1.25, "corners", 0.89, fixture_id=2),
    ]

    combo, _confidence, odd_combined = _combinar(legs)

    assert len(combo) == 2
    assert odd_combined == pytest.approx(1.50)


def test_confianca_do_combo_e_o_produto_nao_a_media():
    """A media premiava o bilhete desequilibrado (uma perna otima + uma fraca)
    contra duas boas, que e' o inverso do que interessa: a aposta so' paga se
    todas baterem."""
    equilibrado = [
        _leg(1.20, "corners", 0.90, confidence=0.80, fixture_id=1),
        _leg(1.25, "cards", 0.89, confidence=0.80, fixture_id=2),
    ]
    desequilibrado = [
        _leg(1.20, "corners", 0.95, confidence=0.95, fixture_id=3),
        _leg(1.25, "cards", 0.94, confidence=0.65, fixture_id=4),
    ]

    _, conf_equilibrado, _ = _combinar(equilibrado)
    _, conf_desequilibrado, _ = _combinar(desequilibrado)

    assert conf_equilibrado == pytest.approx(0.80 * 0.80, abs=1e-4)      # 0.64
    assert conf_desequilibrado == pytest.approx(0.95 * 0.65, abs=1e-4)   # 0.6175
    # Pela media antiga (0.80 vs 0.80) os dois empatariam e o desempate ficava
    # na ordem da lista. Pelo produto, o equilibrado ganha, que e' o correto.
    assert conf_equilibrado > conf_desequilibrado


def test_bloqueia_pick_ja_publicado_em_vip_e_free():
    """Regressao 2026-08-07: a alavancagem saiu repetindo o pick identico do VIP
    do dia. Antes ela so' PREFERIA jogo livre e, sem combo, reaproveitava o jogo
    sem olhar o mercado -- diferente da multipla, que ja' bloqueava o par."""
    cur = _CursorFake(vip=[(101, "cards")], free=[(202, "goals")])

    pares = _today_used_pairs(cur)

    assert (101, "cards") in pares
    assert (202, "goals") in pares


def test_bloqueio_pega_mercado_correlacionado_do_mesmo_jogo():
    """handicap_cards sai do mesmo dado bruto que cards: repetir um como se
    fosse outro e' o mesmo pick com outra roupa. Por isso o bloqueio e' por
    familia (correlation_group), nao pelo market_type cru."""
    cur = _CursorFake(vip=[(101, "handicap_cards")], free=[])

    pares = _today_used_pairs(cur)

    assert (101, "cards") in pares


def test_confianca_de_perna_unica_nao_muda():
    """Com 1 perna o produto e' o proprio confidence dela -- o historico de
    'simples' ja' gravado continua consistente."""
    legs = [_leg(1.45, "goals", 0.90, confidence=0.8661, fixture_id=1)]

    _, confidence, _ = _combinar(legs)

    assert confidence == pytest.approx(0.8661, abs=1e-4)
