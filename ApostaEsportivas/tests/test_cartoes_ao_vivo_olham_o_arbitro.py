"""Familia de cartoes no motor Ao Vivo, com a media de quem apita.

POR QUE CARTAO E' A TERCEIRA FAMILIA, e nao chutes ou posse:

  1. E' a unica cujo numero ainda chega ao vivo quando /fixtures/statistics nao
     vem. Medido em 2026-08-22: statistics devolveu ZERO bloco em todas as
     partidas ao vivo das ligas acompanhadas, inclusive Serie A, enquanto
     /fixtures/events publicava cartao em parte delas.

  2. E' a unica com uma terceira estimativa independente do jogo em si -- a
     media do arbitro. A taxa empirica conta o que os TIMES fizeram; nenhuma
     das outras contas sabe quem esta apitando.

O pre-jogo ja' aprendeu isso do jeito caro (pick VIP #1579, "Cartoes Over 4.5"
a 71.8%, RED com 4 cartoes: o arbitro estava em 3.60 pontos por jogo, ABAIXO da
linha, e o numero nunca entrava na probabilidade). Estes testes garantem que o
motor ao vivo nasce com a licao aplicada.
"""
import pytest

from engine_pipelines import live_pipeline as lp
from services.pick_engine import referee_model
from services.pick_engine_live import live_state, orchestrator
from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG as CONFIG
from services.pick_engine_live.residual_model import BASELINE_PADRAO

NEUTRO = referee_model._REFEREE_CARD_POINTS_BASELINE


class _Cursor:
    """Devolve uma linha fixa. O objetivo e' testar a CONTA, nao o SQL."""

    def __init__(self, linha):
        self.linha = linha

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self.linha


def _cartao(minuto, team_id, vermelho=False):
    return {"type": "Card", "detail": "Red Card" if vermelho else "Yellow Card",
            "time": {"elapsed": minuto}, "team": {"id": team_id},
            "player": {"name": "x"}}


def _estado(eventos_brutos=None, arbitro="Paulo Cesar Zanovelli da Silva, Brazil",
            home_stats=None, away_stats=None, minuto=50):
    bruto = {
        "fixture": {"id": 1, "timestamp": 1, "referee": arbitro,
                    "status": {"short": "2H", "elapsed": minuto, "extra": None}},
        "goals": {"home": 1, "away": 0},
        "teams": {"home": {"id": 10, "name": "Casa"}, "away": {"id": 20, "name": "Fora"}},
        "league": {"id": 72, "name": "Serie B"},
    }
    eventos = live_state.ler_eventos(eventos_brutos or [], minuto)
    return live_state.montar_estado(bruto, home_stats or {}, away_stats or {}, eventos)


class TestPontosDeCartao:
    def test_vermelho_vale_dois_amarelos(self):
        """Convencao unica do projeto (stats_model._cards_points).

        Contar cabeca trataria um vermelho como um amarelo, e os dois nao se
        parecem em nada -- nem no jogo, nem na linha do mercado.
        """
        estado = _estado([_cartao(11, 10), _cartao(23, 20), _cartao(40, 20, vermelho=True)])
        assert estado["cards_points_total"] == 1 + 1 + 2

    def test_sem_cartao_publicado_fica_ausente_e_nao_zero(self):
        """statistics=0 E events=0 foi o caso real da Serie A na medicao."""
        assert _estado([])["cards_points_total"] is None

    def test_a_familia_le_os_pontos_e_nao_a_contagem(self):
        estado = _estado([_cartao(11, 10), _cartao(40, 20, vermelho=True)])
        assert orchestrator.observado_da_familia(estado, "cards") == 3

    def test_cartao_nao_ressuscita_escanteio(self):
        """Uma familia disponivel nao pode mascarar outra ausente."""
        estado = _estado([_cartao(11, 10)])
        assert orchestrator.observado_da_familia(estado, "cards") is not None
        assert orchestrator.observado_da_familia(estado, "corners") is None


class TestArbitroVemDoFeedAoVivo:
    def test_le_o_arbitro_da_propria_partida(self):
        """Vem em `fixture.referee`, no formato "Nome, Pais" -- o MESMO que
        match_statistics.referee guarda, e e' por isso que a busca pode ser por
        igualdade em vez de LIKE."""
        assert _estado()["referee"] == "Paulo Cesar Zanovelli da Silva, Brazil"

    def test_partida_sem_arbitro_publicado_nao_inventa(self):
        assert _estado(arbitro=None)["referee"] is None


class TestBaselineDoArbitro:
    def test_arbitro_rigoroso_sobe_o_baseline(self):
        estado = _estado()
        saida = lp.baseline_do_arbitro(_Cursor((5.4, 0.25, 12)), estado, CONFIG)
        assert saida["cards"] > NEUTRO

    def test_arbitro_leniente_desce_o_baseline(self):
        estado = _estado()
        saida = lp.baseline_do_arbitro(_Cursor((2.6, 0.0, 12)), estado, CONFIG)
        assert saida["cards"] < NEUTRO

    def test_os_dois_extremos_ficam_longe_um_do_outro(self):
        """E' o ponto inteiro do modelo.

        Se o encolhimento achatasse tudo pro neutro, olhar o arbitro nao mudaria
        decisao nenhuma e o campo seria enfeite.
        """
        estado = _estado()
        rigoroso = lp.baseline_do_arbitro(_Cursor((5.4, 0.25, 12)), estado, CONFIG)["cards"]
        leniente = lp.baseline_do_arbitro(_Cursor((2.6, 0.0, 12)), estado, CONFIG)["cards"]
        assert rigoroso - leniente > 1.5

    def test_amostra_curta_nao_entra(self):
        """Abaixo do minimo a alternativa nao e' "usar assim mesmo", e' cair na
        constante -- devolver vazio e' o que faz isso acontecer."""
        estado = _estado()
        assert lp.baseline_do_arbitro(_Cursor((6.0, 0.0, 2)), estado, CONFIG) == {}

    def test_media_crua_e_encolhida_e_nao_copiada(self):
        """Com amostra no limite, o numero tem que ficar ENTRE a media crua e o
        ponto neutro. Copiar a media crua e' o erro que shrink_to_baseline
        existe pra impedir."""
        estado = _estado()
        crua = 6.0
        saida = lp.baseline_do_arbitro(_Cursor((crua, 0.0, 3)), estado, CONFIG)["cards"]
        assert NEUTRO < saida < crua

    def test_sem_arbitro_no_feed_nao_consulta_nada(self):
        estado = _estado(arbitro=None)
        assert lp.baseline_do_arbitro(_Cursor((5.4, 0.25, 12)), estado, CONFIG) == {}

    def test_erro_de_banco_nao_derruba_a_rodada(self):
        """Baseline melhor e' um plus, nao um requisito · falhar aqui nao pode
        custar a partida inteira."""
        class Explode(_Cursor):
            def execute(self, *a, **k):
                raise RuntimeError("banco fora")
        assert lp.baseline_do_arbitro(Explode(None), _estado(), CONFIG) == {}

    def test_so_devolve_a_familia_de_cartoes(self):
        """Nas outras familias esta chamada tem que sair do caminho, senao ela
        sobrescreveria o baseline de liga/confronto que ja' esta certo."""
        saida = lp.baseline_do_arbitro(_Cursor((4.0, 0.0, 12)), _estado(), CONFIG)
        assert set(saida) == {"cards"}


class TestFamiliaLigadaNoMotor:
    def test_cards_entrou_nas_familias_analisadas(self):
        assert "cards" in CONFIG.familias

    def test_o_ponto_neutro_e_o_MESMO_do_pre_jogo(self):
        """Duas constantes pro mesmo conceito divergem no primeiro ajuste."""
        assert BASELINE_PADRAO["cards"] == NEUTRO

    def test_analise_entrega_a_familia_de_pe(self):
        estado = _estado([_cartao(11, 10), _cartao(23, 20), _cartao(31, 10)])
        analise = orchestrator.analisar(estado, [], CONFIG, baselines={"cards": 5.45},
                                        eventos={}, fresh=None)
        assert analise["familias"]["cards"]["disponivel"] is True
        assert analise["familias"]["cards"]["observado"] == 3
        assert analise["familias"]["cards"]["baseline"] == pytest.approx(5.45)
