# -*- coding: utf-8 -*-
"""O motor ao vivo dorme quando nao ha jogo, e acorda sozinho quando ha.

O QUE MUDOU (2026-08-30, pedido do usuario)
-------------------------------------------
O laco rodava a passada completa de 8 em 8 minutos o tempo todo, inclusive de
madrugada. Cada passada custa pelo menos a varredura `/fixtures?live=all` --
barata sozinha, cara repetida 180 vezes por dia pra receber "nenhuma partida
elegivel". Foi consumo dessa forma que estourou a cota em 01/08 e custou o
agendador do projeto.

A PERGUNTA "HA JOGO AGORA?" E RESPONDIDA NO BANCO, e por isso a hibernacao
custa ZERO requisicao: `fixtures` ja sabe o horario de cada partida das ligas
ativas.

E ninguem precisa religar nada. O laco continua vivo e volta ao ritmo normal
na primeira checagem que encontrar partida em campo -- e' esse o "liga
automaticamente".
"""
import pytest

from routers import live_picks


class TestAJanelaDeJogo:
    def test_a_consulta_nao_toca_a_api(self):
        """O ponto inteiro da mudanca: descobrir que nao ha jogo nao pode
        custar requisicao, senao a economia vira contabilidade."""
        import inspect

        fonte = inspect.getsource(live_picks._ha_jogo_na_janela)
        for proibido in ("_fetch_fixture", "_fetch_stats", "requests.", "api-football"):
            assert proibido not in fonte, f"{proibido} custa API e nao pode estar aqui"
        assert "FROM fixtures" in fonte

    def test_so_liga_ativa_conta(self):
        """Jogo de competicao desligada nao acorda o motor · ele nao publicaria
        pick dela de qualquer jeito."""
        import inspect

        fonte = inspect.getsource(live_picks._ha_jogo_na_janela)
        assert "COALESCE(l.ativa, TRUE)" in fonte

    def test_partida_encerrada_ou_adiada_nao_acorda(self):
        import inspect

        fonte = inspect.getsource(live_picks._ha_jogo_na_janela)
        for status in ("'FT'", "'PST'", "'CANC'"):
            assert status in fonte

    def test_a_janela_cobre_um_jogo_inteiro_com_folga(self):
        """90 de bola rolando + intervalo + acrescimo + atraso de inicio.

        Errar pra mais so' faz o motor acordar antes da hora; errar pra menos
        faz ele dormir com jogo em campo, que e o unico erro que custa pick.
        """
        assert live_picks._JANELA_DE_JOGO_MIN >= 120


class TestFalhaAberta:
    def test_erro_de_banco_deixa_o_motor_rodar(self, monkeypatch):
        """Um SELECT que falhou nao e prova de que nao ha jogo. Dormir por
        engano custa pick; acordar por engano custa uma varredura."""
        def explode():
            raise RuntimeError("banco fora")

        monkeypatch.setattr(live_picks, "get_connection", explode)
        assert live_picks._ha_jogo_na_janela() is True


class TestOLacoHiberna:
    def test_o_laco_checa_antes_de_rodar(self):
        import inspect

        fonte = inspect.getsource(live_picks._laco_de_acompanhamento)
        assert "_ha_jogo_na_janela" in fonte
        # A checagem vem ANTES da rodada · depois seria pagar pra descobrir.
        # `_rodar(body, origem=...)` desde 05/09, quando o log passou a saber
        # se a rodada foi do botao ou do laco. O que o teste guarda e' a ORDEM.
        assert fonte.index("_ha_jogo_na_janela") < fonte.index("await _rodar(body")

    def test_hibernar_nao_e_desligar(self):
        """O laco continua vivo (`continue`, nao `break`): e o que faz ele
        voltar sozinho quando a proxima partida comeca."""
        import inspect

        fonte = inspect.getsource(live_picks._laco_de_acompanhamento)
        trecho = fonte[fonte.index("if hibernando:"):]
        assert "continue" in trecho[:900]
        assert "break" not in trecho[:900]

    def test_a_espera_ociosa_e_mais_longa_que_a_normal(self):
        assert live_picks._INTERVALO_HIBERNANDO_MIN > live_picks._INTERVALO_MIN_MINUTOS


class TestAPaginaTambemEconomiza:
    @pytest.mark.parametrize("funcao", ["feed", "_atualizar_leitura"])
    def test_o_enriquecimento_depende_do_motor_em_campo(self, funcao):
        """`_enriquecer` e `_fetch_stats` custam requisicao e existem pra
        mostrar o jogo ACONTECENDO. Sem jogo em campo, pagar por eles e'
        confirmar que nada mudou."""
        import inspect

        fonte = inspect.getsource(getattr(live_picks, funcao))
        assert "hibernando" in fonte

    def test_sem_enriquecer_devolve_as_mesmas_chaves(self):
        """Quem consome e o mesmo card · faltar chave quebraria a tela em vez
        de mostra-la mais simples."""
        pick = {
            "id": 1, "fixture_id": 99, "market": "Escanteios", "line": "Over 9.5",
            "market_type": "corners", "minute_at_creation": 22,
            "home_goals_at_creation": 1, "away_goals_at_creation": 0,
            "observed_at_creation": 4, "result": None,
        }
        saida = live_picks._sem_enriquecer(pick)
        for chave in ("live_status", "elapsed", "home_goals", "away_goals",
                      "current_val", "stat_label", "direction", "is_live",
                      "is_ft", "pick_status"):
            assert chave in saida

    def test_o_card_nao_finge_acompanhamento(self):
        """`is_live` False e o que faz o card se desenhar como leitura
        registrada em vez de partida sendo acompanhada por ninguem."""
        saida = live_picks._sem_enriquecer({"id": 1, "result": None})
        assert saida["is_live"] is False

    def test_pick_liquidado_continua_marcado_como_encerrado(self):
        saida = live_picks._sem_enriquecer({"id": 1, "result": "GREEN"})
        assert saida["is_ft"] is True
