"""Recalibragem da tabela de faltas (services/pick_engine/fouls_calibration).

Este modulo passou a rodar DENTRO do pipeline em 2026-08-16, entao ele decide
probabilidade de pick em producao. O que os testes travam e' o que nao pode
quebrar em silencio: ausencia de lookahead, o mando fazer o que diz, celula com
amostra fraca nao substituir a medida em 159 jogos, e falha de banco nunca
derrubar a geracao.
"""
from datetime import date, timedelta

import pytest

from services.pick_engine import fouls_calibration as fc
from services.pick_engine.fouls_model import (
    LINHAS_SUPORTADAS, _FAIXAS_POR_LINHA, prob_over,
)


def _jogo(fid, home, away, hf, af):
    return {"fixture_id": fid, "match_date": date(2026, 1, 1) + timedelta(days=fid),
            "home_team_id": home, "away_team_id": away,
            "home_fouls": float(hf), "away_fouls": float(af)}


# --------------------------------------------------------------------------
# Lookahead
# --------------------------------------------------------------------------
def test_o_jogo_nunca_entra_na_propria_previsao():
    """A previsao do jogo N usa so' os jogos ANTERIORES. Se o proprio jogo
    entrasse, a tabela ficaria otimista de um jeito que so' aparece em
    producao, com dinheiro real."""
    jogos = [_jogo(i, 1, 2, 10, 12) for i in range(1, 6)]
    jogos.append(_jogo(6, 1, 2, 999, 999))

    amostras = fc.previsoes(jogos, usar_mando=False)

    # QUANTAS amostras saem depende de MIN_JOGOS_TIME, que e' decisao de
    # produto e ja' mudou (5 -> 4 em 28/08). O que este teste protege e' o
    # LOOKAHEAD, e ele nao depende do piso: a previsao do jogo do outlier tem
    # que ignorar o proprio outlier.
    outlier = next(a for a in amostras if a["fixture_id"] == 6)
    assert outlier["real"] == pytest.approx(1998.0)
    assert outlier["previsto"] == pytest.approx(22.0), \
        "o jogo entrou na propria previsao"


def test_amostra_so_aparece_com_historico_minimo():
    """Menos que MIN_JOGOS_TIME de cada lado nao vira amostra -- e' a mesma
    exigencia que expected_fouls faz na hora de gerar pick."""
    jogos = [_jogo(i, 1, 2, 10, 12) for i in range(1, 5)]

    assert fc.previsoes(jogos, usar_mando=False) == []


# --------------------------------------------------------------------------
# Mando
# --------------------------------------------------------------------------
def test_mando_separado_muda_a_previsao():
    """O time 1 faz 10 faltas em casa e 30 fora. Com mando misturado a media
    dele vira 20, que nao descreve nenhum dos dois casos."""
    jogos = [_jogo(i, 1, 2, 10, 12) for i in range(1, 6)]
    jogos += [_jogo(5 + i, 3, 1, 5, 30) for i in range(1, 6)]
    jogos.append(_jogo(11, 1, 2, 0, 0))

    por_mando = fc.previsoes(jogos, usar_mando=True)
    misturado = fc.previsoes(jogos, usar_mando=False)

    alvo_mando = next(a for a in por_mando if a["fixture_id"] == 11)
    alvo_misto = next(a for a in misturado if a["fixture_id"] == 11)

    # Em casa o time 1 faz 10; o time 2 fora faz 12.
    assert alvo_mando["previsto"] == pytest.approx(22.0)
    # Misturado: (10*5 + 30*5)/10 = 20, mais os 12 do visitante.
    assert alvo_misto["previsto"] == pytest.approx(32.0)


# --------------------------------------------------------------------------
# Mesclagem com a tabela congelada
# --------------------------------------------------------------------------
def test_celula_com_amostra_fraca_mantem_a_congelada():
    linha = LINHAS_SUPORTADAS[0]
    congelada = _FAIXAS_POR_LINHA[linha]
    medida = {linha: {0: (0.999, fc.MIN_AMOSTRA_CELULA - 1)}}

    tabela, resumo = fc.mesclar(medida)

    assert tabela[linha][0] == congelada[0]
    assert resumo["celulas_trocadas"] == 0


def test_celula_com_amostra_suficiente_substitui():
    linha = LINHAS_SUPORTADAS[0]
    taxa_antiga = _FAIXAS_POR_LINHA[linha][0][1]
    nova_taxa = round(min(0.95, taxa_antiga + 0.20), 4)
    medida = {linha: {0: (nova_taxa, fc.MIN_AMOSTRA_CELULA + 10)}}

    tabela, resumo = fc.mesclar(medida)

    limite, taxa, n = tabela[linha][0]
    assert taxa == pytest.approx(nova_taxa)
    assert n == fc.MIN_AMOSTRA_CELULA + 10
    assert limite == _FAIXAS_POR_LINHA[linha][0][0]
    assert resumo["celulas_trocadas"] == 1
    assert resumo["mudancas"], "mudanca de 20pp tem que aparecer no relatorio"


def test_tabela_mesclada_continua_consumivel_por_prob_over():
    """Formato e' contrato: prob_over percorre a lista comparando previsto com
    o limite de cada faixa. Uma tabela mesclada com faixa faltando devolveria
    None e o pipeline pararia de gerar pick sem erro nenhum."""
    tabela, _ = fc.mesclar(fc.medir([
        {"fixture_id": i, "previsto": 25.0, "real": 24.0} for i in range(60)
    ]))

    assert set(tabela) == set(_FAIXAS_POR_LINHA)
    for linha, faixas in tabela.items():
        assert len(faixas) == len(_FAIXAS_POR_LINHA[linha])
        assert prob_over(25.0, linha, faixas=tabela) is not None


# --------------------------------------------------------------------------
# Injecao no modelo
# --------------------------------------------------------------------------
def test_prob_over_sem_faixas_usa_a_congelada():
    """Quem chama sem saber da recalibragem tem que continuar vendo os numeros
    medidos em 01/08 -- e' o que os testes de fouls_model travam."""
    assert prob_over(29.0, 22.5) == (_FAIXAS_POR_LINHA[22.5][-1][1],
                                     _FAIXAS_POR_LINHA[22.5][-1][2])


def test_prob_over_com_faixas_usa_a_injetada():
    injetada = {22.5: [(999.0, 0.123, 77)]}

    assert prob_over(29.0, 22.5, faixas=injetada) == (0.123, 77)


# --------------------------------------------------------------------------
# Robustez
# --------------------------------------------------------------------------
class _CursorQuebrado:
    def execute(self, *a, **k):
        raise RuntimeError("banco fora do ar")


def test_falha_de_banco_devolve_a_congelada_sem_levantar():
    """Calibragem e' melhoria, nao requisito. Derrubar a geracao de pick porque
    a remedicao falhou seria trocar um problema pequeno por um grande."""
    tabela, diagnostico = fc.recalibrar(_CursorQuebrado())

    assert tabela == _FAIXAS_POR_LINHA
    assert diagnostico["origem"] == "congelada"
    assert "banco fora do ar" in diagnostico["erro"]


def test_banco_vazio_devolve_a_congelada():
    class _CursorVazio:
        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return []

    tabela, diagnostico = fc.recalibrar(_CursorVazio())

    assert tabela == _FAIXAS_POR_LINHA
    assert diagnostico["origem"] == "congelada"
    assert diagnostico["erro"] is None
