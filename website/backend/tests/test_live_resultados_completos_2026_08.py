# -*- coding: utf-8 -*-
"""Os CINCO resultados no Ao Vivo, do lucro ao aviso.

O produto nasceu medindo GREEN e RED, e as linhas de quarto (`.25` e `.75`)
existem no cardapio dele desde o comeco -- ou seja, HALF-WIN e HALF-LOSS nao
sao caso raro, sao metade das linhas de gols e escanteios. PUSH entra por dois
caminhos: linha cheia empatada e a anulacao por folha que o provedor nao
publicou.

Tres coisas precisam valer pros cinco, e cada uma ja quebrou em algum produto:

  1. O LUCRO. `_profit_for_result` e a mesma tabela do settlement, e o Live
     chama ela em vez de ter aritmetica propria.
  2. A BANCA. `banca._compute_follow_pnl` aceita os cinco -- se recusasse um, a
     aposta de quem seguiu ficaria fora do saldo.
  3. O AVISO. A liquidacao do Live escrevia direto em `user_followed_picks` e
     pulava `_sync_followed_result`, que e' o ponto unico do sino. O saldo
     mudava em silencio.
"""
import pytest

from routers.live import _profit_for_result
from routers import banca


RESULTADOS = ["GREEN", "RED", "PUSH", "HALF-WIN", "HALF-LOSS"]


class TestLucroPorResultado:
    @pytest.mark.parametrize("resultado,odd,esperado", [
        ("GREEN",     2.00,  1.0),
        ("GREEN",     1.40,  0.4),
        ("RED",       2.00, -1.0),
        ("PUSH",      2.00,  0.0),
        # Meia-vitoria paga metade do lucro; meia-derrota custa metade da
        # entrada. Nao e' "metade do RED": e' metade da UNIDADE.
        ("HALF-WIN",  2.00,  0.5),
        ("HALF-WIN",  1.40,  0.2),
        ("HALF-LOSS", 2.00, -0.5),
        ("HALF-LOSS", 1.40, -0.5),
    ])
    def test_a_tabela_do_settlement_vale_no_live(self, resultado, odd, esperado):
        assert _profit_for_result(resultado, odd) == pytest.approx(esperado)

    def test_meia_derrota_nao_depende_da_odd(self):
        """Custa metade da entrada, e a entrada e' 1u em qualquer odd."""
        assert _profit_for_result("HALF-LOSS", 1.10) == _profit_for_result("HALF-LOSS", 9.90)


class TestBancaAceitaOsCinco:
    @pytest.mark.parametrize("resultado", RESULTADOS)
    def test_o_pnl_do_seguidor_cobre_todo_resultado(self, resultado):
        """Resultado que a banca nao conhece vira aposta sem saldo.

        `_compute_follow_pnl` recusa o que nao esta na lista dela, e essa lista
        e' escrita a mao -- foi assim que produtos novos ficaram de fora antes.
        """
        follow = {"stake_units": 2, "actual_odd": 2.0, "cashout_amount": None}
        rotulo, profit_u, pnl_r = banca._compute_follow_pnl(
            {"result": resultado, "odd": 2.0}, follow, 10.0)
        assert rotulo == resultado, f"{resultado} nao produziu P&L"
        assert profit_u is not None and pnl_r is not None

    def test_meia_vitoria_paga_metade_da_vitoria(self):
        follow = {"stake_units": 2, "actual_odd": 2.0, "cashout_amount": None}
        _r, _u, cheio = banca._compute_follow_pnl({"result": "GREEN", "odd": 2.0}, follow, 10.0)
        _r, _u, metade = banca._compute_follow_pnl({"result": "HALF-WIN", "odd": 2.0}, follow, 10.0)
        assert metade == pytest.approx(cheio / 2)

    def test_meia_derrota_custa_metade_da_derrota(self):
        follow = {"stake_units": 2, "actual_odd": 2.0, "cashout_amount": None}
        _r, _u, inteira = banca._compute_follow_pnl({"result": "RED", "odd": 2.0}, follow, 10.0)
        _r, _u, metade = banca._compute_follow_pnl({"result": "HALF-LOSS", "odd": 2.0}, follow, 10.0)
        assert metade == pytest.approx(inteira / 2)


class TestAvisoDeResultado:
    def test_a_liquidacao_do_live_passa_pelo_ponto_do_sino(self):
        """Le o arquivo de proposito.

        O defeito nao era de calculo e nenhum teste de valor o pegaria: a
        liquidacao gravava o resultado certo e simplesmente nao avisava
        ninguem, porque escrevia em `user_followed_picks` com UPDATE cru em vez
        de chamar `_sync_followed_result`. O que trava isso e' garantir que o
        UPDATE cru nao volte.
        """
        import inspect

        from routers import live_picks

        fonte = inspect.getsource(live_picks.liquidar_pendentes)
        assert "_sync_followed_result" in fonte, (
            "a liquidacao do Live precisa passar pelo ponto unico do sino")
        assert "UPDATE user_followed_picks" not in fonte, (
            "UPDATE cru em user_followed_picks pula a notificacao de resultado")
