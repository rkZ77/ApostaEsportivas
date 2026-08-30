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


class TestLeituraAtualizada:
    """O bloco "a IA esta lendo" mostra o JOGO DE AGORA, sem estourar a cota.

    Ele nasceu lendo `live_match_observations` cru, que e a leitura do motor e
    so muda quando ele varre. Com 46 minutos entre duas varreduras -- numero
    real, visto pelo usuario -- o cartao ficava congelado ao lado de cards de
    pick que mostravam o jogo andando.

    A correcao tem um limite que nao pode se perder: `_fetch_stats` custa UMA
    requisicao por partida, e a tela pesquisa de 15 em 15 segundos.
    """

    def test_o_cache_das_estatisticas_e_bem_mais_longo_que_o_do_resto(self):
        """20s x 12 jogos x 4 leituras por minuto e como a cota morre.

        O TTL daqui e proposital e precisa continuar folgado em relacao ao TTL
        de jogo ao vivo do resto do modulo.
        """
        from routers import live, live_picks

        assert live_picks._LEITURA_STATS_TTL >= 4 * live._TTL_LIVE

    def test_existe_teto_de_partidas_com_folha_por_passada(self):
        from routers import live_picks

        assert 1 <= live_picks._LEITURA_STATS_MAX <= 20

    def test_o_placar_nao_passa_pelo_caminho_caro(self):
        """Minuto e placar saem do bulk (uma requisicao pra vinte jogos), e a
        folha e' o unico custo por partida. Trocar o bulk por `_fetch_fixture`
        num laco multiplicaria a conta por doze sem mudar uma linha da tela."""
        import inspect

        from routers import live_picks

        fonte = inspect.getsource(live_picks._atualizar_leitura)
        assert "_fetch_fixtures_bulk" in fonte
