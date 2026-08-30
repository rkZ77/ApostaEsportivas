# -*- coding: utf-8 -*-
"""A faixa de odd do Pick Boost tem que caber no que o mercado paga.

O DEFEITO, MEDIDO EM 2026-08-29
-------------------------------
O produto quase nao publicava, e `engine_decisions` dizia o motivo em quase
todo jogo: "odd fora da faixa de sanidade", sempre com a perna do primeiro
tempo em 1.07 ou 1.08.

    FT 1.35, HT 1.08, par 1.458
    FT 1.38, HT 1.08, par 1.49
    FT 1.42, HT 1.07, par 1.519

Nao era coleta e nao era casamento de mercado (os nomes batem: "Goals
Over/Under" e "Goals Over/Under First Half" estao no catalogo e sao
reconhecidos). Era o piso: 1.10 num mercado cuja mediana medida e 1.09.

Menos de 2.5 gols no PRIMEIRO TEMPO e' quase certo -- a media de gols no HT
fica perto de 1 -- entao a casa paga pouco. Exigir 1.10 dali e' exigir do
mercado um numero que ele raramente produz.

O QUE ESTES TESTES PROTEGEM
---------------------------
Nao o valor 1.03 em si, e sim as duas propriedades que fazem o produto
funcionar: o piso do HT precisa caber na realidade do mercado, e a margem tem
que continuar sendo garantida por alguem -- pela odd COMBINADA, que e' a perna
que de fato paga.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.pick_engine_boost import config as cfg  # noqa: E402


#: Odds reais de Under 2.5 HT lidas do banco em 29/08 (mediana 1.09).
ODDS_HT_MEDIDAS = [1.05, 1.06, 1.07, 1.08, 1.08, 1.09, 1.09, 1.12, 1.39, 1.43]


class TestOPisoDoPrimeiroTempo:
    def test_a_mediana_do_mercado_passa_no_piso(self):
        """Se a mediana nao passa, o produto reprova metade dos jogos por um
        numero que o mercado nao produz -- que era exatamente o defeito."""
        mediana = sorted(ODDS_HT_MEDIDAS)[len(ODDS_HT_MEDIDAS) // 2]
        assert cfg.ODD_MIN_HT <= mediana

    def test_a_maioria_das_odds_reais_passa(self):
        aprovadas = [o for o in ODDS_HT_MEDIDAS if o >= cfg.ODD_MIN_HT]
        assert len(aprovadas) >= len(ODDS_HT_MEDIDAS) * 0.8

    @pytest.mark.parametrize("odd", [1.07, 1.08, 1.09])
    def test_os_casos_que_o_motor_descartou_agora_passam(self, odd):
        """Sao as odds nominais das tres decisoes gravadas no log."""
        assert cfg.ODD_MIN_HT <= odd <= cfg.ODD_MAX_HT

    def test_o_piso_do_primeiro_tempo_e_menor_que_o_do_jogo_completo(self):
        """Sao mercados de natureza diferente: um e' a aposta, o outro e' a
        ancora. Pisos iguais tratam os dois como se fossem a mesma coisa."""
        assert cfg.ODD_MIN_HT < cfg.ODD_MIN_FT


class TestOTetoContinuaProtegendo:
    def test_odd_alta_no_primeiro_tempo_ainda_reprova(self):
        """E' a metade util da regra: Under 2.5 HT pagando muito e' o mercado
        dizendo que espera gol cedo, contra o que o modelo afirma."""
        assert 1.85 > cfg.ODD_MAX_HT

    def test_over_15_sem_margem_ainda_reprova(self):
        """Over 1.5 pagando 1.05 nao deixa margem nenhuma · esse piso e' o que
        continua fazendo sentido, e nao foi tocado."""
        assert 1.05 < cfg.ODD_MIN_FT


class TestQuemGaranteAMargem:
    def test_a_odd_combinada_tem_piso_proprio(self):
        """O piso do HT deixou de ser a garantia de margem, entao a garantia
        tem que existir em outro lugar -- e ela existe, no par."""
        assert cfg.ODD_MIN_COMBINADA >= 1.30

    @pytest.mark.parametrize("ft,ht", [(1.35, 1.08), (1.38, 1.08), (1.42, 1.07)])
    def test_os_pares_descartados_estavam_dentro_da_faixa_que_importa(self, ft, ht):
        """Os tres jogos reprovados pelo piso do HT tinham par entre 1.45 e
        1.52, ou seja: o produto recusava bilhete que a regra de margem
        aprovava."""
        par = round(ft * ht, 3)
        assert cfg.ODD_MIN_COMBINADA <= par <= cfg.ODD_MAX_COMBINADA

    def test_perna_barata_demais_ainda_nao_fecha_o_par(self):
        """Sem piso nenhum no HT a margem nao fica desprotegida: um par que nao
        alcanca 1.30 continua sendo recusado."""
        par = round(1.12 * 1.03, 3)
        assert par < cfg.ODD_MIN_COMBINADA


class TestOsNomesDeMercado:
    """O catalogo casa por nome exato, e nome novo da casa some em silencio.

    Estes dois sao os que a coleta de fato grava (medido em 29/08: 318 jogos
    com "Goals Over/Under" e 199 com "Goals Over/Under First Half"). Perde-los
    devolveria o produto ao estado de "nao seleciona mercado", so' que por
    outra causa.
    """

    def test_o_nome_do_jogo_completo_esta_no_catalogo(self):
        assert "goals over/under" in cfg.NOMES_MERCADO_FT

    def test_o_nome_do_primeiro_tempo_esta_no_catalogo(self):
        assert "goals over/under first half" in cfg.NOMES_MERCADO_HT

    def test_os_nomes_estao_todos_em_minusculo(self):
        """O casamento e' feito com `.lower()` do lado da odd · uma entrada com
        maiuscula aqui nunca casaria, e o pipeline rodaria sem erro e sem
        pick, que e' o pior tipo de falha."""
        for nome in (*cfg.NOMES_MERCADO_FT, *cfg.NOMES_MERCADO_HT):
            assert nome == nome.lower()
