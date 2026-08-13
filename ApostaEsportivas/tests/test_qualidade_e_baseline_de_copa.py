"""Qualidade da amostra e alvo do encolhimento quando o jogo e de copa.

Duas lacunas que sobreviveram a abertura do historico multi-competicao:

  1. o Data Quality Score so' CONTAVA jogos, entao 15 partidas contra
     adversario desconhecido pontuavam igual a 15 com classificacao na mao;
  2. o alvo do encolhimento vinha da propria competicao -- numa Libertadores de
     poucos jogos, o "baseline" que deveria ESTABILIZAR a estimativa era ele
     proprio instavel.

Nenhum teste toca banco: TeamStatsService._query e' substituido.
"""
from services.pick_engine import data_validation as dv
from services.team_stats_service import TeamStatsService


def jogo(rank=None, league_id=71):
    return {"match_date": "2026-08-10", "league_id": league_id,
            "home_team_id": 1, "away_team_id": 2, "opponent_rank": rank}


# ── Data Quality Score ────────────────────────────────────────────────────
def test_adversario_desconhecido_reduz_a_qualidade():
    """Nao invalida a amostra, mas cega opponent_weight -- e o DQS escala o
    min_edge exigido, entao a diferenca vira cautela extra, que e' o que se
    quer num jogo de copa."""
    conhecidos = dv.validate_history([jogo(rank=3) for _ in range(10)])
    desconhecidos = dv.validate_history([jogo(rank=None) for _ in range(10)])

    assert conhecidos["Q"] > desconhecidos["Q"]
    assert conhecidos["Q"] == conhecidos["Q_bruto"]


def test_penalidade_de_adversario_desconhecido_e_pequena():
    """Adversario desconhecido nao torna o jogo invalido. Penalidade grande
    faria copa parar de gerar pick por um dado que so' falta."""
    desconhecidos = dv.validate_history([jogo(rank=None) for _ in range(10)])

    assert desconhecidos["Q"] >= desconhecidos["Q_bruto"] * 0.8


def test_amostra_parcialmente_conhecida_fica_no_meio():
    metade = dv.validate_history([jogo(rank=3) for _ in range(5)]
                                 + [jogo(rank=None) for _ in range(5)])

    assert metade["adversario_conhecido"] == 0.5


def test_multi_competicao_e_rastro_e_nao_penalidade():
    """Historico de varias competicoes e' o comportamento DESEJADO em copa.
    Punir isso brigaria com a propria correcao que o trouxe."""
    uma = dv.validate_history([jogo(rank=3, league_id=71) for _ in range(10)])
    varias = dv.validate_history([jogo(rank=3, league_id=71) for _ in range(5)]
                                 + [jogo(rank=3, league_id=13) for _ in range(5)])

    assert uma["Q"] == varias["Q"]
    assert varias["competicoes"] == 2


def test_amostra_vazia_nao_quebra():
    vazio = dv.validate_history([])

    assert vazio["passed"] is False
    assert vazio["adversario_conhecido"] == 0.0


def test_quantidade_continua_mandando_no_passed():
    """A penalidade mexe em Q (qualidade), nunca no corte de amostra minima."""
    poucos = dv.validate_history([jogo(rank=3) for _ in range(4)])
    assert poucos["passed"] is False
    assert dv.validate_history([jogo(rank=None) for _ in range(5)])["passed"] is True


# ── Alvo do encolhimento ──────────────────────────────────────────────────
def _servico(respostas):
    svc = TeamStatsService()
    chamadas = []

    def _fake(sql, params=None):
        chamadas.append((sql, params))
        return respostas[len(chamadas) - 1]

    svc._query = _fake
    svc.chamadas = chamadas
    return svc


def test_liga_com_amostra_propria_usa_a_propria():
    svc = _servico([{"home_corners": 5.5, "linhas": 40}])

    baseline = svc.get_league_baseline(71, 2026)

    assert baseline["home_corners"] == 5.5
    assert "escopo" not in baseline
    assert len(svc.chamadas) == 1, "nao pode consultar o global a toa"


def test_competicao_de_copa_cai_no_baseline_global():
    """Fase de grupos com poucos times ja jogados: o alvo tirado dali carrega
    mais ruido do que a estimativa que ele deveria conter."""
    svc = _servico([{"home_corners": 9.9, "linhas": 4},
                    {"home_corners": 5.2, "linhas": 300}])

    baseline = svc.get_league_baseline(13, 2026)

    assert baseline["home_corners"] == 5.2
    assert baseline["escopo"] == "global"


def test_copa_nao_le_team_statistics_da_propria_competicao():
    """Coerencia dentro da MESMA fixture: a taxa empirica le 30 jogos
    multi-competicao e team_statistics descreveria os 3 a 6 da competicao. Com
    fontes diferentes, o model_disagreement_threshold disparava por causa da
    diferenca de FONTE, nao por desacordo sobre a partida."""
    svc = _servico([])

    assert svc.get_for_fixture(1, 2, 13, 2026) == (None, None)
    assert svc.chamadas == [], "nem consultou o banco"


def test_pontos_corridos_continua_lendo_team_statistics():
    """A tabela cobre mais jogos que os 15 do historico e ja vem separada por
    mando -- em liga ela e' melhor que o historico cru, e continua sendo usada."""
    svc = _servico([{"avg_corners_for": 5.5}, {"avg_corners_for": 4.1}])

    casa, fora = svc.get_for_fixture(1, 2, 71, 2026)

    assert casa["avg_corners_for"] == 5.5
    assert fora["avg_corners_for"] == 4.1


def test_sem_nenhuma_linha_na_temporada_devolve_o_proprio():
    """Sem alvo, shrink_to_baseline devolve o valor cru -- melhor que encolher
    pra um numero inventado."""
    svc = _servico([{"home_corners": None, "linhas": 0},
                    {"home_corners": None, "linhas": 0}])

    baseline = svc.get_league_baseline(13, 2026)

    assert baseline["linhas"] == 0
    assert baseline.get("escopo") is None
