"""Relatorio de descartes do motor Ao Vivo (engine_pipelines/live_pipeline).

Quase toda rodada descarta TUDO: a API devolve os jogos ao vivo do mundo
inteiro e o projeto acompanha 8 ligas. Entao esta e' a saida que o usuario ve'
na maioria das execucoes, e ela precisa dizer o que fazer a respeito.

O `pode_voltar` tambem alimenta o live_watch, que usa `fixtures_no_radar` pra
escolher entre a espera curta e a longa.
"""
from engine_pipelines.live_pipeline import imprimir_descartes, resumir_descartes


def _d(jogo, categoria, pode_voltar, liga=71, minuto=30, motivo="x"):
    return {"fixture_id": hash(jogo) % 10000, "jogo": jogo, "liga": liga,
            "minuto": minuto, "categoria": categoria, "motivo": motivo,
            "pode_voltar": pode_voltar}


def test_agrupa_por_categoria():
    resumo = resumir_descartes([
        _d("a x b", "liga", False, liga=39),
        _d("c x d", "liga", False, liga=39),
        _d("e x f", "janela", True),
    ])

    assert resumo["total"] == 3
    assert resumo["por_categoria"] == {"liga": 2, "janela": 1}
    assert resumo["por_liga"] == {39: 2}


def test_no_radar_e_so_o_que_ainda_pode_render():
    """Liga que nao e' nossa nunca entra no radar, mesmo sendo descarte. Jogo
    nosso que ja' passou da janela tambem nao: nao volta mais."""
    resumo = resumir_descartes([
        _d("fora do escopo", "liga", False, liga=999),
        _d("ja passou", "janela", False, minuto=85),
        _d("ainda entra", "janela", True, minuto=10),
        _d("pick recente", "antiflood", True, minuto=40),
        _d("teto de picks", "antiflood", False, minuto=60),
    ])

    nomes = [d["jogo"] for d in resumo["no_radar"]]
    assert nomes == ["pick recente", "ainda entra"]  # ordenado por minuto desc


def test_liga_nao_cadastrada_nunca_conta_como_radar():
    """Regressao: contar liga alheia no radar manteria o live_watch acordado no
    intervalo curto a noite inteira, queimando cota de API por nada -- sempre ha
    jogo ao vivo em ALGUMA liga do mundo."""
    resumo = resumir_descartes([_d(f"jogo {i}", "liga", False, liga=900 + i)
                                for i in range(50)])

    assert resumo["no_radar"] == []
    assert resumo["por_categoria"] == {"liga": 50}


def test_sem_descarte_nao_imprime_nada(capsys):
    imprimir_descartes(resumir_descartes([]))

    assert capsys.readouterr().out == ""


def test_saida_diz_o_que_fazer(capsys):
    imprimir_descartes(resumir_descartes([
        _d("alheio", "liga", False, liga=999),
        _d("Flamengo x Palmeiras", "janela", True, minuto=10,
           motivo="minuto 10' fora da janela 15'-80' (ainda entra)"),
    ]))
    saida = capsys.readouterr().out

    assert "no radar" in saida
    assert "Flamengo x Palmeiras" in saida
    assert "ainda entra" in saida


def test_avisa_quando_nada_pode_render(capsys):
    imprimir_descartes(resumir_descartes([_d("alheio", "liga", False, liga=999)]))

    assert "nenhuma partida das nossas ligas" in capsys.readouterr().out
