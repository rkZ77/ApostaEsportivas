"""news_score: desfalque tem que DERRUBAR a nota, nao levantar.

ranking.final_score() soma news_score com peso fixo e nao tem como saber que
o numero deveria ser lido ao contrario. A versao anterior devolvia
`0.5 + total`: quanto mais titular fora, MAIOR o Score Final -- um jogo com o
elenco desfalcado dos dois lados batia o teto (1.0) e passava na frente de um
jogo com todo mundo a disposicao.
"""
import pytest

from services.pick_engine import news_model, ranking


def _sinal(titulares_home=0, outros_home=0, titulares_away=0, outros_away=0):
    def _lista(n, prefixo):
        return [{"name": f"{prefixo}{i}", "type": "Injured", "reason": "",
                 "starts_recentes": 1} for i in range(n)]
    return {
        "is_approximation": True,
        "home": {"titulares_desfalcados": _lista(titulares_home, "H"),
                 "outros_desfalcados": _lista(outros_home, "h")},
        "away": {"titulares_desfalcados": _lista(titulares_away, "A"),
                 "outros_desfalcados": _lista(outros_away, "a")},
    }


def test_sem_desfalque_e_neutro():
    assert news_model.news_score(_sinal()) == pytest.approx(0.5)


def test_sem_sinal_devolve_none():
    assert news_model.news_score(None) is None


def test_titular_desfalcado_derruba_o_score():
    assert news_model.news_score(_sinal(titulares_home=2)) < 0.5


def test_mais_desfalque_derruba_mais():
    um = news_model.news_score(_sinal(titulares_home=1))
    tres = news_model.news_score(_sinal(titulares_home=3))
    assert tres < um < 0.5


def test_titular_pesa_mais_que_reserva():
    titular = news_model.news_score(_sinal(titulares_home=1))
    reserva = news_model.news_score(_sinal(outros_home=1))
    assert titular < reserva < 0.5


def test_score_nunca_passa_do_piso():
    """Teto de 0.5 de desconto -- desfalque nunca zera a nota sozinho."""
    assert news_model.news_score(_sinal(titulares_home=20, titulares_away=20)) == pytest.approx(0.0)


def test_desfalque_reduz_o_score_final_do_candidato():
    """O efeito que importa: no ranking, o jogo desfalcado tem que pontuar
    MENOS que o mesmo jogo com elenco completo."""
    base = {"confidence": 0.75, "Q": 1.0, "context_score": 0.5, "profile_score": 0.5}

    completo = ranking.final_score({**base, "news_score": news_model.news_score(_sinal())})
    desfalcado = ranking.final_score({
        **base, "news_score": news_model.news_score(_sinal(titulares_home=3, titulares_away=2))})

    assert desfalcado < completo
