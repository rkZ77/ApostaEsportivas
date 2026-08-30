# -*- coding: utf-8 -*-
"""Pick ao vivo com resultado irreversivel nao espera o apito.

O CASO QUE O USUARIO VIU
------------------------
Um "Mais de 11 escanteios" com 12 escanteios em campo, aos 75', marcado como
Pendente e com a faixa de "odd vencida" na tela. Escanteio nao volta: aquele
GREEN estava fechado havia 15 minutos e o site nao dizia.

A causa era um corte em `liquidar_pendentes`: `if status not in FT_STATUSES:
continue`. Ou seja, o Live so olhava jogo encerrado.

A regra do early-lock ja existia no projeto, em `_locked_leg_result` -- e o que
o ticker de Minhas Apostas usa pra pintar o pick como resolvido antes do apito.
O Live simplesmente nao a chamava.
"""
import pytest

from routers.live import _travado_antes_do_apito as travado


class TestOverTrava:
    @pytest.mark.parametrize("linha,valor", [
        ("Over 11.0", 12),
        ("Mais de 11", 12),
        ("Over 8.5", 9),
        ("Over 2.5", 3),
    ])
    def test_over_ja_batido_e_green(self, linha, valor):
        assert travado("Escanteios Mais/Menos", linha, valor) == "GREEN"

    @pytest.mark.parametrize("linha,valor", [
        ("Over 11.0", 11),   # empatou na linha cheia: ainda pode virar PUSH
        ("Over 11.0", 10),
        ("Over 8.5", 8),
    ])
    def test_over_ainda_aberto_nao_trava(self, linha, valor):
        assert travado("Escanteios Mais/Menos", linha, valor) is None


class TestUnderSoTravaParaRed:
    def test_under_estourado_e_red(self):
        assert travado("Escanteios Mais/Menos", "Under 11.0", 12) == "RED"

    def test_under_ainda_abaixo_nao_e_green(self):
        """AQUI MORA O ERRO CARO. Um Under 11 com 9 escanteios aos 80' parece
        ganho e nao esta: ainda cabem dois. Travar como GREEN pagaria o
        seguidor por uma aposta que a casa ainda nao pagou."""
        assert travado("Escanteios Mais/Menos", "Under 11.0", 9) is None


class TestLinhaDeQuarto:
    """Meia-vitoria e meia-derrota existem, e travar como GREEN pagaria o
    dobro do que a casa paga."""

    def test_over_de_um_quarto_precisa_passar_do_inteiro(self):
        # Over 11.25 com 12: GREEN inteiro (12 > 11).
        assert travado("Escanteios", "Over 11.25", 12) == "GREEN"
        # Com 11 exatos o final e HALF-LOSS, entao nao trava.
        assert travado("Escanteios", "Over 11.25", 11) is None

    def test_over_de_tres_quartos_precisa_passar_do_seguinte(self):
        # Over 11.75 com 12 terminaria HALF-WIN · nao trava.
        assert travado("Escanteios", "Over 11.75", 12) is None
        # Com 13 e' GREEN inteiro.
        assert travado("Escanteios", "Over 11.75", 13) == "GREEN"


class TestOQueNaoTrava:
    def test_sem_valor_observado_nao_decide(self):
        assert travado("Escanteios", "Over 11.0", None) is None

    def test_mercado_sem_linha_numerica_espera_o_apito(self):
        """Resultado e placar exato nao passam por aqui: quem vence pode mudar
        ate' o fim, e a funcao devolve None em vez de arriscar."""
        assert travado("Resultado Final", "Casa", 1) is None


class TestALiquidacaoUsaIsso:
    def test_liquidar_pendentes_nao_exige_mais_apenas_FT(self):
        """Trava a correcao no lugar onde ela foi desfeita antes: o `continue`
        em qualquer status que nao fosse FT era a linha inteira do defeito."""
        import inspect

        from routers import live_picks

        fonte = inspect.getsource(live_picks.liquidar_pendentes)
        assert "_travado_antes_do_apito" in fonte
        assert "status not in FT_STATUSES and status not in LIVE_STATUSES" in fonte

    def test_jogo_em_andamento_nao_anula_por_falta_de_estatistica(self):
        """Anular com a bola rolando seria desistir cedo: o provedor ainda pode
        publicar a folha antes do apito."""
        import inspect

        from routers import live_picks

        fonte = inspect.getsource(live_picks.liquidar_pendentes)
        # A anulacao continua existindo -- ela e' a rede do jogo ENCERRADO cuja
        # folha o provedor nunca publicou.
        assert "_anulacao_sem_estatistica" in fonte
        # E o caminho de jogo em andamento sai antes de chegar nela: sem trava,
        # `continue`. Sao as duas linhas coladas, e e' isso que o teste fixa.
        corpo = fonte[fonte.index("resultado = _travado_antes_do_apito"):]
        assert corpo[:200].count("continue") == 1
