"""A frase de fato do "Como esse mercado vem se comportando".

Formato que o apostador reconhece das casas ("O Internacional passou de 26.5
chutes em 4 dos últimos 5 jogos em casa"). Sai dos MESMOS números que desenham
as barras · `resumo()` já devolve greens/resolved/average e nada aqui recalcula.

A regra que estes testes protegem: a frase NÃO é texto de venda. Ela conta os
jogos em que a linha bateu mesmo quando isso contraria o pick. Mostrar só o lado
favorável seria o mesmo defeito que o motor tem quando publica a taxa otimista e
esconde as estimativas que discordam dela.
"""
import pytest

from market_form import frase_da_serie


def _serie(op="over", line=26.5, greens=4, resolved=5, average=30.6,
           label="Chutes"):
    return {"op": op, "line": line, "greens": greens, "resolved": resolved,
            "average": average, "label": label}


def test_over_no_mando_de_casa():
    f = frase_da_serie("Internacional", _serie(), "home")
    assert f == ("O Internacional passou de 26.5 chutes em 4 dos últimos "
                 "5 jogos em casa · média de 30.6.")


def test_under_no_mando_de_fora():
    f = frase_da_serie("Remo", _serie(op="under", greens=3, average=24.8), "away")
    assert f == ("O Remo ficou abaixo de 26.5 chutes em 3 dos últimos "
                 "5 jogos fora · média de 24.8.")


def test_a_frase_conta_o_que_contraria_o_pick():
    """O caso real de 17/08: num Over 26.5, o visitante só passou em 2 de 5.
    A frase tem que dizer 2, não maquiar."""
    f = frase_da_serie("Remo", _serie(greens=2, average=24.8), "away")
    assert " em 2 dos últimos 5 jogos fora" in f
    assert "24.8" in f


def test_ambas_marcam_fala_do_mercado_e_nao_da_regua():
    """O contador do BTTS é o placar do time que menos marcou, e a régua do
    gráfico é 0.5. Dizer "passou de 0.5 gols" descreveria a régua, não o
    mercado · a frase tem que falar como o apostador fala."""
    f = frase_da_serie("Internacional",
                       _serie(op="yes", line=0.5, greens=4,
                              label="Gols do time que menos marcou"), "home")
    assert f == "As duas equipes marcaram em 4 dos últimos 5 jogos do Internacional em casa."
    assert "0.5" not in f


def test_sem_jogo_resolvido_nao_ha_frase():
    """Silêncio em vez de afirmação sem amostra · mesma regra que faz a seção
    inteira sumir quando nada resolve."""
    assert frase_da_serie("Time", _serie(greens=0, resolved=0)) is None


def test_sem_linha_nao_ha_frase():
    """Mercado sem linha numérica (resultado, placar exato) não tem o que
    afirmar neste formato. Nunca inventar."""
    assert frase_da_serie("Time", _serie(line=None)) is None


def test_direcao_desconhecida_nao_vira_frase():
    assert frase_da_serie("Time", _serie(op="")) is None
    assert frase_da_serie("Time", _serie(op="home")) is None


def test_sem_mando_a_frase_sai_sem_o_complemento():
    f = frase_da_serie("Time", _serie(), None)
    assert "em casa" not in f and " fora" not in f
    assert "em 4 dos últimos 5 jogos" in f


def test_sem_media_a_frase_omite_a_cauda():
    f = frase_da_serie("Time", _serie(average=None), "home")
    assert "média" not in f
    assert f.endswith("jogos em casa.")


@pytest.mark.parametrize("label, plural", [
    ("Escanteios", "escanteios"),
    ("Cartões", "cartões"),
    ("Faltas", "faltas"),
    ("Chutes", "chutes"),
    ("Chutes no Alvo", "chutes no alvo"),
    ("Impedimentos", "impedimentos"),
    ("Gols", "gols"),
])
def test_a_unidade_acompanha_o_contador(label, plural):
    f = frase_da_serie("Time", _serie(label=label), "home")
    assert f" {plural} " in f, f"{label!r} deveria render {plural!r}: {f}"


def test_linha_inteira_nao_ganha_casa_decimal():
    """"passou de 10 escanteios", não "10.0"."""
    f = frase_da_serie("Time", _serie(line=10.0, label="Escanteios"), "home")
    assert "de 10 escanteios" in f


def test_rotulo_desconhecido_nao_quebra_a_frase():
    """Contador novo sem unidade mapeada sai sem a palavra, nunca com lixo."""
    f = frase_da_serie("Time", _serie(label="Contador Novo"), "home")
    assert f is not None and "passou de 26.5 em 4" in f
