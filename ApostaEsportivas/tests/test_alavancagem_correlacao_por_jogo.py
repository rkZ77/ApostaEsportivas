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


def perna(fixture_id, market_type, odd, confidence=0.75, final_score=0.7,
          taxa_real=None, amostra=25, data_quality_score=85.0, risco="BAIXO",
          direcao="over", linha=1.5, scope="total"):
    """Perna COMPLETA, como o pick_engine entrega.

    Ate' a V2 estes testes montavam pernas com quatro campos (fixture, mercado,
    odd, confidence), porque `_find_combo` so' olhava esses quatro. A camada de
    combinacao olha o resto -- probabilidade calibrada, edge, EV, amostra,
    qualidade de dado, risco --, entao a perna de mentira precisa ser uma perna
    de verdade, senao o que o teste mede e' o motor reprovando dado faltando.

    `taxa_real` sai da odd por padrao, com +15% de EV embutido. Fixar uma taxa
    chapada pra todas as odds (0.75 pra 1.11 e pra 1.39) produzia perna de EV
    NEGATIVO sem ninguem notar: 0.75 x 1.11 = 0.83, ou seja, um candidato que o
    motor real nunca teria aprovado.
    """
    taxa = taxa_real if taxa_real is not None else min(0.97, round(1.15 / odd, 4))
    return {
        "_fixture": {"fixture_id": fixture_id},
        "market_type": market_type,
        "market_name": market_type,
        "value_label": f"{direcao.title()} {linha}",
        "scope": scope,
        "odd": odd,
        "confidence": confidence,
        "final_score": final_score,
        "taxa_real": taxa,
        "edge": round(taxa - (1.0 / odd) + 0.09, 4),
        "ev": round(taxa * odd - 1.0, 4),
        "amostra": amostra,
        "data_quality_score": data_quality_score,
        "risco": risco,
        "_direction": direcao,
        "_line_val": linha,
    }


def _combinar(legs):
    resultado = _find_combo(legs, ODD_COMBINED_MIN, ODD_COMBINED_MAX)
    if resultado is None:
        return None
    pernas, confidence, odd, _avaliacao = resultado
    return pernas, confidence, odd


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


def test_ambas_marcam_e_gols_no_mesmo_jogo_nao_combinam():
    """O exemplo que a docstring de _find_combo sempre citou como correlacao de
    verdade -- e que passava, porque "btts" tinha grupo proprio (2026-08-10).

    "Under 2.5 + Ambas Marcam" so' paga em 1-1: o produto das probabilidades
    anunciava ~28% onde a chance real e' ~12%. E "Under 1.5 + Ambas Marcam" e'
    impossivel."""
    assert _combinar([perna(7, "goals", 1.39), perna(7, "btts", 1.11)]) is None


def test_ambas_marcam_em_outro_jogo_continua_combinando():
    """Correlacao e' por JOGO. Ambas Marcam num jogo e gols em outro sao times
    diferentes, em estadios diferentes -- o veto nao pode voltar a ser global."""
    combo = _combinar([perna(1, "goals", 1.39), perna(2, "btts", 1.11)])
    assert combo is not None
    assert len(combo[0]) == 2


def test_mercados_diferentes_no_mesmo_jogo_continuam_permitidos():
    """Formato "dois mercados no mesmo jogo" e' valido por decisao de produto.

    A V2 nao o removeu, so' passou a cobrar dele uma condicao: gols e escanteios
    no mesmo jogo tem correlacao MEDIA (pressao ofensiva move os dois), e a
    aproximacao pelo produto so' vale quando a dependencia empurra pro lado
    conservador. Duas pernas "over" apontam pro mesmo regime de jogo: ganham
    juntas, o produto SUBESTIMA, e o bilhete e' melhor do que o motor anuncia.
    """
    combo = _combinar([perna(7, "goals", 1.39, direcao="over"),
                       perna(7, "corners", 1.11, direcao="over")])
    assert combo is not None
    assert len(combo[0]) == 2


def test_mesmo_jogo_com_direcoes_opostas_nao_combina():
    """O contraponto: "over" de um lado e "under" do outro no MESMO jogo
    apontam pra regimes opostos. A dependencia vira negativa e o produto
    SUPERESTIMA -- e' o erro que quebra bilhete, o mesmo de "Under 2.5 + Ambas
    Marcam" (~28% anunciado contra ~12% real)."""
    assert _combinar([perna(7, "goals", 1.39, direcao="over"),
                      perna(7, "corners", 1.11, direcao="under")]) is None


def test_familias_sem_mecanismo_mapeado_no_mesmo_jogo_sao_desconhecidas():
    """§16: sem mecanismo mapeado nao se assume independencia. Impedimentos e
    defesas de goleiro no mesmo jogo caem em DESCONHECIDA, e correlacao
    desconhecida nao passa no gate."""
    from services.pick_engine import combo_engine

    par = combo_engine.classificar_correlacao(
        perna(7, "offsides", 1.20), perna(7, "saves", 1.25))
    assert par["nivel"] in (combo_engine.MEDIA, combo_engine.DESCONHECIDA)

    par_livre = combo_engine.classificar_correlacao(
        perna(1, "offsides", 1.20), perna(2, "saves", 1.25))
    assert par_livre["nivel"] == combo_engine.BAIXA


def test_tripla_da_mesma_familia_em_tres_jogos_nao_sai_mais():
    """§39/§40: a tripla ficou excepcional, e a mesma familia tres vezes nao e'
    excepcional -- e' a mesma estimativa aplicada tres vezes. Tres pernas de
    gols em tres jogos sao independentes no gramado e nao no MODELO: se a
    projecao de gols estiver enviesada hoje, as tres erram juntas, e o erro de
    cada uma multiplica o das outras duas.

    E' o segundo RED do historico escrito como regra (23/08: Under 3.5 + Under
    4.5, os dois `goals`, em jogos diferentes)."""
    assert _combinar([perna(1, "goals", 1.15), perna(2, "goals", 1.12),
                      perna(3, "goals", 1.10)]) is None


def test_tripla_de_familias_diferentes_ainda_e_possivel():
    """Excepcional nao e' proibido. Tres jogos diferentes, tres familias
    diferentes (correlacao BAIXA), todas as pernas com probabilidade alta e
    amostra cheia: a tripla passa, que e' exatamente o caso que o §39 descreve
    como o unico que a justifica."""
    combo = _combinar([perna(1, "goals", 1.15), perna(2, "corners", 1.12),
                       perna(3, "cards", 1.10)])
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
    # As duas pernas cabem sozinhas na faixa, entao quem decide entre elas nao
    # e' mais a ordem da lista: e' o COMBINATION_SCORE, que nao pontua preco.
    # A de 1.40 carrega a probabilidade calibrada maior e vence -- pagar menos
    # por uma chance melhor e' a escolha certa num produto de faixa fixa.
    assert odd == pytest.approx(1.40)


def test_prefere_a_simples_quando_a_dupla_nao_entrega_mais_probabilidade():
    """A REGRA QUE SE INVERTEU NA V2, e o motivo e' aritmetico.

    Este teste dizia o contrario ("simples fica por ultimo") e essa preferencia
    nasceu de uma leitura de produto: combo seria o formato preferido, entao
    dupla devia ser tentada antes. So' que a faixa [1.40, 1.55] e' do TOTAL do
    bilhete -- uma dupla nessa faixa paga EXATAMENTE o que uma simples nessa
    faixa paga. Nao ha' premio de preco pelo formato: a segunda perna nao
    aumenta o retorno, so' acrescenta uma segunda maneira de perder.

    A simples de 1.45 aqui vale 88% calibrados. A dupla 1.25 x 1.20 = 1.50
    multiplica duas pernas pra ~84% depois dos descontos -- nao supera a
    simples, entao nao sai. Pelo motor antigo a dupla sairia, porque ela cabia
    na faixa e era tentada primeiro.
    """
    combo = _combinar([perna(1, "goals", 1.45, taxa_real=0.88),
                       perna(2, "goals", 1.25), perna(3, "corners", 1.20)])
    assert combo is not None
    assert len(combo[0]) == 1
    assert combo[2] == pytest.approx(1.45)


def test_a_dupla_sai_quando_entrega_mais_probabilidade_pelo_mesmo_preco():
    """O outro lado da mesma regra. Aqui a simples de 1.45 vale 79% e a dupla
    1.25 x 1.20 = 1.50 entrega ~84% ja' descontada: mais chance pelo mesmo
    preco, entao o combo passa na frente. A regra nao e' "simples sempre" --
    e' "o formato nao vale nada, quem vale e' a probabilidade"."""
    combo = _combinar([perna(1, "goals", 1.45), perna(2, "goals", 1.25),
                       perna(3, "corners", 1.20)])
    assert combo is not None
    assert len(combo[0]) == 2


def test_confianca_do_bilhete_e_o_produto_das_pernas():
    """Confianca do BILHETE e' o produto, nao a media das pernas."""
    combo = _combinar([
        perna(1, "goals", 1.20, confidence=0.90, final_score=0.9),
        perna(2, "corners", 1.25, confidence=0.90, final_score=0.9),
    ])
    assert combo is not None
    pernas, conf, _odd = combo
    assert len(pernas) == 2
    assert conf == pytest.approx(0.81, abs=1e-4)
