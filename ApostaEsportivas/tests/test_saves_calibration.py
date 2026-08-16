"""Recalibragem das constantes de defesas (services/pick_engine/saves_calibration).

Roda dentro do pipeline de goleiros desde 2026-08-16, entao decide probabilidade
de pick em producao. O teste mais importante daqui e' o do pareamento de lado:
`home_goalkeeper_saves` e' a defesa do goleiro da casa contra os chutes do
VISITANTE, e cruzar o mesmo lado inverteria a relacao inteira sem erro nenhum.
"""
import pytest

from services.pick_engine import goalkeeper_model as gm
from services.pick_engine import saves_calibration as sc


class _Cursor:
    """Cursor falso com linhas (casa_defesas, fora_chutes, fora_defesas, casa_chutes)."""

    def __init__(self, linhas):
        self._linhas = linhas

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self._linhas


# --------------------------------------------------------------------------
# Leitura do banco
# --------------------------------------------------------------------------
def test_pareia_defesa_com_o_chute_do_adversario():
    """O goleiro da casa defende o que o VISITANTE chutou. Trocar o lado aqui
    inverte o sinal do modelo inteiro."""
    atuacoes = sc.carregar_atuacoes(_Cursor([(7, 10, 3, 4)]))

    assert atuacoes == [(7.0, 10.0), (3.0, 4.0)]


# --------------------------------------------------------------------------
# A conta
# --------------------------------------------------------------------------
def test_medir_calcula_as_tres_constantes():
    # defesas [1,1,1,5,5,5] com 2 chutes cada: media 3, variancia amostral 4.8.
    atuacoes = [(1, 2), (1, 2), (1, 2), (5, 2), (5, 2), (5, 2)]

    m = sc.medir(atuacoes)

    assert m["league_mean_saves"] == pytest.approx(3.0)
    assert m["save_rate_per_shot_on"] == pytest.approx(18 / 12)
    # r = mu^2 / (var - mu) = 9 / 1.8
    assert m["dispersion_r"] == pytest.approx(5.0)
    assert m["base_rate_over_15"] == pytest.approx(0.5)
    assert m["variancia_sobre_media"] == pytest.approx(1.6)
    assert m["atuacoes"] == 6


def test_sem_superdispersao_nao_calcula_r():
    """Se a base deixar de ser superdispersa, a Binomial Negativa nao e' o
    modelo certo e forcar a formula produziria um r sem sentido (negativo ou
    infinito). Devolve None e a constante congelada continua valendo."""
    atuacoes = [(2, 3)] * 8

    m = sc.medir(atuacoes)

    assert m["dispersion_r"] is None
    assert m["league_mean_saves"] == pytest.approx(2.0)


# --------------------------------------------------------------------------
# Mesclagem e robustez
# --------------------------------------------------------------------------
def test_amostra_curta_mantem_as_congeladas():
    cur = _Cursor([(1, 2, 5, 2)] * 3)

    constantes, diagnostico = sc.recalibrar(cur, min_atuacoes=400)

    assert constantes["dispersion_r"] == gm.DISPERSION_R
    assert constantes["league_mean_saves"] == gm.LEAGUE_MEAN_SAVES
    assert diagnostico["origem"] == "congeladas"
    assert diagnostico["atuacoes"] == 6


def test_amostra_suficiente_substitui_campo_a_campo():
    cur = _Cursor([(1, 2, 5, 2)] * 100)

    constantes, diagnostico = sc.recalibrar(cur, min_atuacoes=10)

    assert diagnostico["origem"] == "recalibradas"
    assert constantes["league_mean_saves"] == pytest.approx(3.0)
    assert constantes["save_rate_per_shot_on"] == pytest.approx(1.5)
    assert diagnostico["trocadas"], "mudanca grande tem que ser reportada"


def test_r_incalculavel_preserva_o_congelado_sem_perder_a_media():
    """Substituicao e' campo a campo: a media entra mesmo quando a dispersao
    nao pode ser medida."""
    cur = _Cursor([(2, 3, 2, 3)] * 100)

    constantes, diagnostico = sc.recalibrar(cur, min_atuacoes=10)

    assert diagnostico["origem"] == "recalibradas"
    assert constantes["dispersion_r"] == gm.DISPERSION_R      # congelado
    assert constantes["league_mean_saves"] == pytest.approx(2.0)  # recalibrado


def test_falha_de_banco_devolve_as_congeladas_sem_levantar():
    class _Quebrado:
        def execute(self, *a, **k):
            raise RuntimeError("timeout")

    constantes, diagnostico = sc.recalibrar(_Quebrado())

    assert constantes["dispersion_r"] == gm.DISPERSION_R
    assert diagnostico["origem"] == "congeladas"
    assert "timeout" in diagnostico["erro"]


# --------------------------------------------------------------------------
# Injecao no modelo
# --------------------------------------------------------------------------
def test_modelo_sem_constantes_mantem_o_comportamento_congelado():
    """Quem chama sem saber da recalibragem tem que ver os numeros de 01/08."""
    sem = gm.expected_saves(opponent_shots_on_avg=4.0, sample_size=10)

    assert sem == pytest.approx(round(4.0 * gm.SAVE_RATE_PER_SHOT_ON, 3), abs=0.35)


def test_modelo_usa_a_taxa_injetada():
    injetadas = {"save_rate_per_shot_on": 1.0, "league_mean_saves": 4.0}

    com = gm.expected_saves(opponent_shots_on_avg=4.0, sample_size=50,
                            constantes=injetadas)
    sem = gm.expected_saves(opponent_shots_on_avg=4.0, sample_size=50)

    assert com > sem


def test_dispersao_injetada_muda_a_probabilidade():
    base = gm.analyze_saves_market(4.0, None, 10, odd=2.0, line=2.5)
    outra = gm.analyze_saves_market(4.0, None, 10, odd=2.0, line=2.5,
                                    constantes={"dispersion_r": 50.0})

    assert base["probability"] != outra["probability"]
