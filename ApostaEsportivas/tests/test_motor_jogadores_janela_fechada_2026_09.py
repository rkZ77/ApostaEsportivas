"""As tres correcoes de 2026-09-12 no Pick Jogador.

O motor parou de publicar depois que tres mudancas se empilharam: o zero
implicito (03/09) derrubou as medias pro valor real, o piso de amostra (10/09)
subiu pra 12 dentro da liga de hoje, e a V2 (11/09) passou a encolher a projecao
por um fator de minutos que comparava duas populacoes diferentes.

Estes testes cobrem o que e' DEFEITO nos tres casos. O terceiro item da lista --
remedir PROB_MINIMA e EDGE_MINIMO contra a base pos zero-fix -- nao tem teste
aqui de proposito: e' medicao, e o script e'
`src/scripts/medir_limiares_player_stats.py`.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.player_stats_engine import methods as cat
from services.player_stats_engine import minutes_model, player_history, quality


class _CursorFalso:
    """Devolve um numero de rodadas. Nao e' banco: e' a regra sendo lida."""

    def __init__(self, rodadas):
        self._rodadas = rodadas
        self.sql = None

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return (self._rodadas,)


# ---------------------------------------------------------------------------
# 1 · o fator de minutos comparava dois filtros, nao dois regimes
# ---------------------------------------------------------------------------

def _folha(minutos, titular=True):
    return {"minutes": minutos, "is_substitute": not titular, "position": "F"}


def test_titular_que_saiu_cedo_nao_encolhe_a_projecao():
    """O caso que fechava a janela.

    O historico do contador so' le' atuacoes de 60+ minutos. `esperados` conta
    TODA titularidade, inclusive a de 45. Dividir um pelo outro media a
    diferenca entre os dois filtros, nao mudanca de regime: este jogador jogou
    90 em todas as atuacoes que entraram na media, e mesmo assim saia com fator
    abaixo de 0.85 -- que e' contradicao CRITICA e reprova o pick.
    """
    # Titularidades de 90, 90, 90, 45, 45, 45: o historico do contador leu as
    # tres de 90 e projetou sobre elas.
    perfil = {"amostra": 6, "minutos_medios": 67.5,
              "minutos_como_titular": 67.5, "minutos_do_regime": 90.0,
              "titularidades": 6, "titularidades_longas": 3}
    fator = minutes_model.fator_de_minutos(
        minutes_model.minutos_do_regime(perfil), 90.0)
    assert fator == 1.0

    # Pelo caminho antigo (esperados), o mesmo jogador levava o corte.
    antigo = minutes_model.fator_de_minutos(
        minutes_model.minutos_esperados(perfil), 90.0)
    assert antigo <= 0.85


def test_mudanca_real_de_regime_continua_encolhendo():
    """A camada nao foi desligada: quem passou a jogar menos ainda e' cobrado.

    Voltando de lesao, ele agora joga 62 minutos nas titularidades longas, e a
    media do contador veio de jogos de 88.
    """
    perfil = {"amostra": 8, "minutos_medios": 62.0,
              "minutos_como_titular": 62.0, "minutos_do_regime": 62.0,
              "titularidades": 8, "titularidades_longas": 8}
    fator = minutes_model.fator_de_minutos(
        minutes_model.minutos_do_regime(perfil), 88.0)
    assert fator < 0.85


def test_sem_titularidade_longa_o_fator_sai_neutro():
    """Ausencia de dado nao vira multiplicador escondido (§33).

    Quem nao tem titularidade de 60+ na janela e' reprovado por
    `risco_de_minutos` e pelo gate dos 60 minutos, que e' onde a pergunta mora.
    """
    perfil = {"amostra": 5, "minutos_medios": 30.0,
              "minutos_como_titular": None, "minutos_do_regime": None,
              "titularidades": 0, "titularidades_longas": 0}
    assert minutes_model.minutos_do_regime(perfil) is None
    assert minutes_model.fator_de_minutos(
        minutes_model.minutos_do_regime(perfil), 88.0) == 1.0


def test_perfil_separa_titularidade_longa_da_curta(monkeypatch):
    """As duas medias saem da mesma leitura e descrevem coisas diferentes.

    Titularidades de 90, 90 e 45, mais uma entrada de 20 minutos. A media de
    TITULAR e' 75; a do REGIME, que e' a que o historico do contador tambem
    leu, e' 90.
    """
    folhas = [_folha(90), _folha(90), _folha(45), _folha(20, titular=False)]
    monkeypatch.setattr(minutes_model, "linhas_dict", lambda _cur: folhas)
    p = minutes_model.perfil(_CursorFalso(0), player_id=1)
    assert p["titularidades"] == 3
    assert p["titularidades_longas"] == 2
    assert p["minutos_como_titular"] == 75.0
    assert p["minutos_do_regime"] == 90.0


# ---------------------------------------------------------------------------
# 2 · o teto da qualidade nao pode ser inalcancavel
# ---------------------------------------------------------------------------

def _qualidade(amostra, metodo, **kw):
    base = dict(perfil_minutos={"amostra": 10}, status_titular="PROVAVEL_TITULAR",
                risco_minutos="LOW", dias_desde_ultima=5,
                adversario={"disponivel": True})
    base.update(kw)
    return quality.data_quality_score(
        amostra=amostra, min_atuacoes=metodo.min_atuacoes,
        limite_leitura=player_history.LIMITE_ATUACOES, **base)


def test_shots_on_consegue_chegar_aos_100():
    """O dobro do piso de `shots_on` sao 24 atuacoes, e o motor le' 15.

    Sem o limite de leitura na saturacao, o componente mais pesado (35 de 100)
    tinha teto real de 21.9 e o metodo entrava na auditoria final devendo 13
    pontos -- contra um minimo de 70 que e' item CRITICO.
    """
    q = _qualidade(player_history.LIMITE_ATUACOES, cat.SHOTS_ON)
    assert q["componentes"]["amostra"] == quality.PESO_AMOSTRA
    assert q["score"] == 100.0


def test_amostra_no_piso_ainda_vale_menos_que_amostra_cheia():
    """A saturacao mudou de lugar, a ordem nao: mais amostra continua valendo
    mais, senao o componente deixaria de ordenar."""
    no_piso = _qualidade(cat.SHOTS_ON.min_atuacoes, cat.SHOTS_ON)
    cheia = _qualidade(player_history.LIMITE_ATUACOES, cat.SHOTS_ON)
    assert no_piso["componentes"]["amostra"] < cheia["componentes"]["amostra"]


def test_metodo_de_piso_baixo_nao_mudou():
    """`saves` tem piso 4, e o dobro (8) cabe folgado no limite de leitura --
    entao a correcao nao pode ter deslocado o que ja' estava certo."""
    q = _qualidade(8, cat.SAVES)
    assert q["componentes"]["amostra"] == quality.PESO_AMOSTRA


# ---------------------------------------------------------------------------
# 3 · o piso de amostra nao pode ser inalcancavel por calendario
# ---------------------------------------------------------------------------

def test_liga_recem_comecada_abre_o_recorte():
    """Em setembro uma liga europeia de 2026/27 tem quatro rodadas: ninguem
    chega a 12 atuacoes nela, e o motor reprovava a fixture inteira dizendo que
    faltava historico ao JOGADOR."""
    jovem, rodadas = player_history.competicao_jovem_demais(
        _CursorFalso(4), team_id=33, league_id=39, season=2026,
        min_atuacoes=cat.SHOTS_ON.min_atuacoes)
    assert jovem is True and rodadas == 4


def test_liga_madura_continua_travada():
    """O recorte de 27/08 nao foi afrouxado: chute em Brasileirao e chute em
    Libertadores continuam sendo populacoes diferentes onde da' pra separar."""
    jovem, rodadas = player_history.competicao_jovem_demais(
        _CursorFalso(23), team_id=131, league_id=71, season=2026,
        min_atuacoes=cat.SHOTS_ON.min_atuacoes)
    assert jovem is False and rodadas == 23


def test_sem_liga_ou_temporada_nao_abre():
    """Ausencia de dado nao pode escolher o caminho mais permissivo (§33)."""
    jovem, rodadas = player_history.competicao_jovem_demais(
        _CursorFalso(0), team_id=33, league_id=None, season=None, min_atuacoes=12)
    assert jovem is False and rodadas == 0
    assert player_history.partidas_na_competicao(
        _CursorFalso(9), team_id=33, league_id=None, season=None) == 0
