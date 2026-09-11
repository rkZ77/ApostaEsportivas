"""O motor ao vivo lia linha redonda como se fosse meia linha.

O CASO QUE ABRIU (Sao Bernardo x Londrina, 10/09/2026)
-----------------------------------------------------
Pick publicado: "Escanteios Mais e/ou Menos, Mais de 6.0" aos 45', com 3
escanteios no placar, odd 1.50, anunciado a 73%.

A linha e' REDONDA. Terminar com exatamente 6 escanteios nao e' RED na casa de
apostas: a aposta e' devolvida (PUSH). `settlement._straight` ja' liquidava
isso certo desde sempre -- valor igual a' linha devolve fator 0 -- e o pre-jogo
ja' modelava isso certo desde sempre, em `pm.poisson_prob_for_line`. O motor ao
vivo era o unico caminho do projeto que nao sabia:

    pm.prob_over(3.0, lam)  =  P(X > 3)   <- conta o empate exato como derrota

A chance que a aposta tem e' a condicional a ela ser DECIDIDA:

    P(green | nao push) = P(green) / (1 - P(empate exato))

O erro SUBESTIMAVA, e por isso nunca apareceu como pick ruim: probabilidade
menor vira EV menor, e EV menor reprova no gate. O custo era pick que deveria
existir e nao existia, e um numero na tela que nao era a mesma grandeza que os
outros motores publicam.

Estes testes prendem as tres grades (meia, redonda, quarter) no mesmo lugar, e
prendem o acordo com a liquidacao -- que e' quem diz o que da' green de verdade.
"""
import pytest

from services import settlement
from services.pick_engine import probability_model as pm
from services.pick_engine_live import residual_model as rm

PHI = pm.dispersao("corners", "total")


# ── a grade da linha ─────────────────────────────────────────────────────

@pytest.mark.parametrize("linha, grade", [
    (6.0, "whole"), (6.5, "half"), (6.25, "quarter"), (6.75, "quarter"),
])
def test_a_grade_do_motor_e_a_mesma_da_liquidacao(linha, grade):
    """Quem decide green e red e' `settlement`. Se o motor classificar a linha
    de um jeito e a liquidacao de outro, o pick e' avaliado numa aposta que nao
    e' a que foi feita."""
    assert settlement.line_grid(linha) == grade
    if grade == "whole":
        assert rm._e_inteira(linha) and not rm._e_quarter(linha)
    elif grade == "quarter":
        assert rm._e_quarter(linha) and not rm._e_inteira(linha)
    else:
        assert not rm._e_quarter(linha) and not rm._e_inteira(linha)


# ── linha redonda ────────────────────────────────────────────────────────

def test_linha_redonda_desconta_o_push_e_sobe_a_probabilidade():
    """O caso da tela: Mais de 6.0 com 3 aos 45', lambda residual ~3.2."""
    lam = 3.2
    antiga = pm.prob_over(3.0, lam, PHI)             # o que o motor lia
    nova = rm.probabilidade_da_linha(lam, 6.0, "over", 3, PHI)
    push = pm.nb_pmf(3, lam, PHI)
    assert nova == pytest.approx(antiga / (1 - push), abs=1e-4)
    assert nova > antiga
    assert push > 0.15                                # o empate nao e' residual


def test_linha_redonda_no_under_tira_o_empate_do_numerador():
    """prob_under usa floor e INCLUI o empate exato. Se ele nao sair do
    numerador, Under vira o espelho errado do Over e as duas pontas somam
    mais que 1."""
    lam = 3.2
    over = rm.probabilidade_da_linha(lam, 6.0, "over", 3, PHI)
    under = rm.probabilidade_da_linha(lam, 6.0, "under", 3, PHI)
    assert over + under == pytest.approx(1.0, abs=1e-3)


def test_meia_linha_nao_mudou_nada():
    """Linha .5 nunca empata, entao a correcao nao pode encostar nela."""
    lam = 3.2
    for linha, direcao in ((6.5, "over"), (6.5, "under"), (9.5, "over")):
        esperado = (pm.prob_over(linha - 3, lam, PHI) if direcao == "over"
                    else pm.prob_under(linha - 3, lam, PHI))
        assert rm.probabilidade_da_linha(lam, linha, direcao, 3, PHI) == \
            pytest.approx(esperado, abs=1e-6)


def test_under_que_so_pode_empatar_ou_perder_vai_a_zero():
    """Under 6.0 com 6 no placar: o melhor desfecho possivel e' devolucao.
    Nao precisa de gate proprio, a conta ja' devolve zero."""
    assert rm.probabilidade_da_linha(3.2, 6.0, "under", 6, PHI) == 0.0


def test_over_redondo_com_a_linha_empatada_ainda_vale_a_pena():
    """Mais de 6.0 com 6 no placar nao esta' perdido: qualquer escanteio a
    mais e' green, e o empate devolve. Nao pode ser tratado como resolvido."""
    p = rm.probabilidade_da_linha(1.5, 6.0, "over", 6, PHI)
    assert p > 0.9


# ── as tres grades continuam concordando entre si ────────────────────────

def test_quarter_fica_entre_as_duas_vizinhas():
    """Quarter e' meia aposta em cada vizinha, entao ela mora entre elas.
    O ramo redondo foi extraido de dentro do quarter nesta mudanca -- este
    teste e' quem garante que a extracao nao mudou o valor."""
    lam = 3.2
    meia = rm.probabilidade_da_linha(lam, 6.5, "over", 3, PHI)
    quarter = rm.probabilidade_da_linha(lam, 6.75, "over", 3, PHI)
    redonda = rm.probabilidade_da_linha(lam, 7.0, "over", 3, PHI)
    assert meia > quarter > redonda
    assert quarter == pytest.approx((meia + redonda) / 2, abs=1e-5)


def test_a_convencao_e_a_mesma_do_pre_jogo():
    """Sem observado nenhum, o ao vivo tem que dar o MESMO numero que
    `poisson_prob_for_line` da' no pre-jogo pra a mesma linha redonda. Duas
    convencoes pro mesmo mercado e' o que faz dois motores discordarem."""
    lam = 3.2
    for linha in (3.0, 4.0, 5.0):
        for direcao in ("over", "under"):
            pre = pm.poisson_prob_for_line(lam, linha, direcao,
                                           family="corners", scope="total")
            ao_vivo = rm.probabilidade_da_linha(lam, linha, direcao, 0, PHI)
            assert ao_vivo == pytest.approx(pre, abs=1e-3), (linha, direcao)
