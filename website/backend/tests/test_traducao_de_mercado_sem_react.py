"""A tradução do backend não pode ser um subconjunto da do front.

O React aplica `translateMarket` em toda tela, então um nome cru em inglês em
`picks.market` fica invisível ali. Mas `routers/suggestions.py::_tr` é o que
serve as respostas em **markdown** e o **servidor MCP** · os caminhos SEM React.
Enquanto essa tabela for menor que a do front, o inglês vaza exatamente por eles.

Caso real (17/08/2026): o pick free saiu `Total Shots` porque
`odds_values.market_pt` vinha NULL (o coletor não tinha a chave) e o motor grava
`market_pt or market_name`. A raiz foi corrigida em
`odds_collector_service._MARKET_NAME_PT_FALLBACK`; esta tabela cobre o histórico
já gravado, que não é reprocessado.
"""
import pytest

from routers.suggestions import _tr


@pytest.mark.parametrize("cru, esperado", [
    ("Total Shots", "Finalizações Mais/Menos"),
    ("Total ShotOnGoal", "Finalizações no Gol Mais/Menos"),
    ("Offsides Total", "Impedimentos Mais/Menos"),
    ("Offsides Home Total", "Impedimentos Casa Mais/Menos"),
    ("Fouls. Total", "Faltas Mais/Menos"),
    ("Goalkeeper Saves", "Defesas do goleiro"),
    ("Home Team Total Goals", "Total de Gols Casa"),
    ("Away Team Total Goals", "Total de Gols Visitante"),
])
def test_mercado_cru_vira_portugues(cru, esperado):
    assert _tr(cru) == esperado


def test_chute_no_alvo_nao_vira_chute_total():
    """São mercados DIFERENTES: chute no alvo gira ~8-10 por jogo, chute total
    ~20-25. Traduzir um pelo outro descreve a aposta errada para o assinante."""
    assert _tr("Total ShotOnGoal") != _tr("Total Shots")


def test_traducao_ignora_caixa_e_espaco():
    assert _tr("  total shots  ") == "Finalizações Mais/Menos"


def test_o_que_ja_funcionava_continua():
    assert _tr("Both Teams Score") == "Ambas as Equipes Marcam"
    assert _tr("Corners Over/Under") == "Escanteios Mais/Menos"


def test_mercado_desconhecido_passa_direto_sem_quebrar():
    """Nunca inventar tradução: o que não está no mapa sai como veio."""
    assert _tr("Mercado Que Nao Existe") == "Mercado Que Nao Existe"
    assert _tr("") == ""


def test_o_backend_cobre_as_familias_que_o_motor_publica():
    """Trava o buraco pela CAUSA, não pelos nomes de hoje.

    O motor publica estas famílias (stats_model.classify_market). Se uma delas
    não tiver tradução aqui, o markdown e o MCP mostram inglês."""
    from routers.suggestions import _MARKET_PT

    for chave in ("total shots", "offsides total", "fouls. total",
                  "goalkeeper saves", "home team total goals"):
        assert chave in _MARKET_PT, f"{chave!r} falta na tabela do backend"
