# -*- coding: utf-8 -*-
"""O motor ao vivo passa a ler o historico do time RESPEITANDO O MANDO.

O QUE ESTAVA ERRADO
-------------------
`baseline_do_confronto` calculava a media de cada time com um UNION ALL sobre
`match_statistics` que juntava os jogos em casa e fora no mesmo saco. Isso
apaga a diferenca que o motor de pre-jogo trata como principal desde 08/08: o
mesmo time produz e cede quantidades diferentes conforme o mando.

A correcao nao inventa fonte nova. `team_statistics` ja guarda a media separada
por `context_type` HOME/AWAY desde sempre (o agregador escreve as duas linhas
por time); o Live simplesmente nunca leu. Uma consulta, zero requisicao de API.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engine_pipelines import live_pipeline as lp  # noqa: E402


ESTADO = {"home_team_id": 10, "away_team_id": 20, "league_id": 71}


class _Cursor:
    """Devolve as linhas dadas, no formato de `team_statistics`."""

    def __init__(self, linhas):
        self._linhas = linhas
        self.sql = ""
        self.params = None

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self._linhas


def linha(team_id, contexto, jogos, corners=None, goals=None, yellow=None, red=None):
    return (team_id, contexto, jogos, corners, goals, yellow, red)


class TestOLadoCerto:
    def test_combina_o_mandante_em_casa_com_o_visitante_fora(self):
        cur = _Cursor([
            linha(10, "HOME", 9, corners=11.0, goals=3.0),
            linha(20, "AWAY", 9, corners=9.0, goals=2.0),
        ])
        saida = lp.baseline_do_mando(cur, ESTADO)
        assert saida["corners"] == pytest.approx(10.0)
        assert saida["goals"] == pytest.approx(2.5)

    def test_a_consulta_pede_home_do_mandante_e_away_do_visitante(self):
        """O recorte inteiro mora nesta clausula · trocar os lados devolveria
        numero plausivel e errado, que e' o pior tipo de defeito aqui."""
        cur = _Cursor([])
        lp.baseline_do_mando(cur, ESTADO)
        assert "context_type = 'HOME'" in cur.sql
        assert "context_type = 'AWAY'" in cur.sql
        # (league_id, mandante, visitante) e nessa ordem.
        assert cur.params == (71, 10, 20)


class TestAmostra:
    def test_lado_com_poucos_jogos_nao_vale(self):
        """Trocar 12 jogos misturados por 2 do mando certo troca vies por
        ruido · a media sem mando continua valendo nesse caso."""
        cur = _Cursor([
            linha(10, "HOME", lp.MIN_JOGOS_MANDO - 1, corners=11.0, goals=3.0),
            linha(20, "AWAY", 9, corners=9.0, goals=2.0),
        ])
        assert lp.baseline_do_mando(cur, ESTADO) == {}

    def test_precisa_dos_dois_lados(self):
        cur = _Cursor([linha(10, "HOME", 9, corners=11.0, goals=3.0)])
        assert lp.baseline_do_mando(cur, ESTADO) == {}

    def test_cada_familia_cai_sozinha(self):
        """So' escanteio tem numero nos dois lados: so' escanteio sai daqui, e
        gols continua vindo de quem vinha."""
        cur = _Cursor([
            linha(10, "HOME", 9, corners=11.0, goals=None),
            linha(20, "AWAY", 9, corners=9.0, goals=2.0),
        ])
        saida = lp.baseline_do_mando(cur, ESTADO)
        assert "corners" in saida and "goals" not in saida


class TestCartao:
    def test_cartao_sai_em_pontos(self):
        """Amarelo=1, vermelho=2 · e a unidade do mercado no resto do projeto,
        e um baseline em 'numero de cartoes' seria lido como pontos."""
        cur = _Cursor([
            linha(10, "HOME", 9, corners=11.0, goals=3.0, yellow=4.0, red=0.5),
            linha(20, "AWAY", 9, corners=9.0, goals=2.0, yellow=3.0, red=0.0),
        ])
        saida = lp.baseline_do_mando(cur, ESTADO)
        # (4 + 2*0.5) = 5 em casa; (3 + 0) = 3 fora.
        assert saida["cards"] == pytest.approx(4.0)

    def test_meio_numero_nao_vira_cartao(self):
        cur = _Cursor([
            linha(10, "HOME", 9, corners=11.0, goals=3.0, yellow=4.0, red=None),
            linha(20, "AWAY", 9, corners=9.0, goals=2.0, yellow=3.0, red=0.0),
        ])
        assert "cards" not in lp.baseline_do_mando(cur, ESTADO)


class TestNuncaDerruba:
    def test_erro_de_banco_devolve_vazio(self):
        class Explode(_Cursor):
            def execute(self, *a, **k):
                raise RuntimeError("banco fora")

        assert lp.baseline_do_mando(Explode([]), ESTADO) == {}

    def test_partida_sem_os_dois_times_nao_consulta(self):
        cur = _Cursor([])
        assert lp.baseline_do_mando(cur, {"home_team_id": 10, "league_id": 71}) == {}
        assert cur.sql == ""


class TestAOrigemNaAuditoria:
    """Quem escreveu o baseline de cada familia aparece no rastro do pick.

    Ate' 29/08 o orchestrator rotulava tudo como "liga" ou "padrao", o que ja
    era falso (confronto, arbitro e h2h entravam sem aparecer) e ficou
    insustentavel com o mando: a pergunta "o motor olhou o mando?" nao tinha
    resposta na tela da Auditoria.
    """

    def test_o_orchestrator_usa_a_origem_que_o_pipeline_manda(self):
        from services.pick_engine_live import orchestrator

        estado = {"minuto": 60, "status": "2H", "home_team_id": 10, "away_team_id": 20,
                  "corners_total": 6, "goals_total": 1, "home_goals": 1, "away_goals": 0}
        saida = orchestrator.analisar(
            estado, [], baselines={"corners": 10.5},
            baseline_origens={"corners": "mando"})
        assert saida["familias"]["corners"]["baseline_origem"] == "mando"

    def test_sem_origem_o_comportamento_antigo_continua(self):
        """Chamador que nao passa o mapa (teste antigo, script solto) nao pode
        quebrar."""
        from services.pick_engine_live import orchestrator

        estado = {"minuto": 60, "status": "2H", "home_team_id": 10, "away_team_id": 20,
                  "corners_total": 6, "goals_total": 1, "home_goals": 1, "away_goals": 0}
        saida = orchestrator.analisar(estado, [], baselines={"corners": 10.5})
        assert saida["familias"]["corners"]["baseline_origem"] == "liga"
