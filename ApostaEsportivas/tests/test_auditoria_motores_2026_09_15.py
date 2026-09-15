"""Os quatro defeitos da auditoria de 15/09, cada um com o seu caso real.

Nenhum deles aparecia como erro: o motor rodava, gravava e publicava. O que
falhava era o NUMERO (peso de adversario), o que a tela mostrava (amostra e
liga) e o que o banco deixava acontecer (um caminho de alavancagem por dia).

Nenhum teste toca banco.
"""
import dataclasses

from services.engine_audit import amostra
from services.pick_engine import stats_model as sm
from services.pick_engine.config import (DEFAULT_CONFIG, DICA_CONFIG,
                                          VIP_CONFIG)


def jogo(data, home_id, away_id, gols_casa, gols_fora, rank=None, league_id=72):
    return {
        "match_date": data, "league_id": league_id, "status": "FT",
        "home_team_id": home_id, "away_team_id": away_id,
        "home_goals": gols_casa, "away_goals": gols_fora,
        "total_goals": gols_casa + gols_fora,
        "home_goals_90": gols_casa, "away_goals_90": gols_fora,
        "opponent_rank": rank, "opponent_name": "Adversario",
    }


# ---------------------------------------------------------------- peso
def test_o_peso_de_adversario_esta_neutro_nos_tres_niveis():
    """A medicao de 15/09 aposentou o 2.0/1.0/0.5 -- ver config.py.

    O teste trava os TRES campos, e nao so' o topo: foi a razao 4:1 entre a
    ponta de cima e a de baixo que enviesava a taxa, entao zerar so' um lado
    deixaria metade do vies de pe'."""
    for config in (DEFAULT_CONFIG, VIP_CONFIG, DICA_CONFIG):
        assert config.opponent_top_weight == 1.0
        assert config.opponent_mid_weight == 1.0
        assert config.opponent_weak_weight == 1.0


def test_adversario_forte_e_fraco_pesam_igual_na_taxa():
    """O caso do pick Free de 15/09, reduzido ao essencial.

    Cinco jogos em casa: os dois contra o lider ficaram abaixo da linha, os
    tres contra o lanterna passaram dela. A taxa honesta e' 2 de 5 (40%); com
    o peso antigo os dois jogos "pesados" viravam maioria e a taxa passava de
    50%, que e' exatamente como um Under sem lastro virava pick."""
    historico = [
        jogo("2026-09-10", 1, 9, 1, 0, rank=1),   # 1 gol  -> Under 2.5 bate
        jogo("2026-09-05", 1, 8, 0, 1, rank=2),   # 1 gol  -> bate
        jogo("2026-08-30", 1, 7, 3, 1, rank=19),  # 4 gols -> nao bate
        jogo("2026-08-25", 1, 6, 2, 2, rank=20),  # 4 gols -> nao bate
        jogo("2026-08-20", 1, 5, 3, 2, rank=18),  # 5 gols -> nao bate
    ]
    taxa = sm.compute_taxa("goals", "total", "under", "2.5", historico, [],
                           None, DEFAULT_CONFIG, None, 1, None)
    assert taxa["taxa_bruta"] == 0.4
    # Sem o peso de adversario a ponderada so' pode se afastar da bruta pela
    # recencia, que e' um fator suave -- nunca virar maioria.
    assert taxa["taxa_ponderada"] < 0.6

    antigo = dataclasses.replace(DEFAULT_CONFIG, opponent_top_weight=2.0,
                                 opponent_weak_weight=0.5)
    taxa_antiga = sm.compute_taxa("goals", "total", "under", "2.5", historico,
                                  [], None, antigo, None, 1, None)
    assert taxa_antiga["taxa_ponderada"] > taxa["taxa_ponderada"]


# ---------------------------------------------------------------- amostra
def test_a_amostra_gravada_so_traz_o_mando_do_jogo():
    """`pool_and_field` filtra por mando desde 10/08 e a amostra EXIBIDA nao
    filtrava: a tela listava jogos que o motor nao usou, ao lado de uma barra
    que o site monta por mando. Duas amostras da mesma decisao."""
    historico = [
        jogo("2026-09-10", 1, 2, 1, 1),
        jogo("2026-09-05", 3, 1, 2, 0),   # o time 1 jogou FORA
        jogo("2026-08-30", 1, 4, 0, 0),
    ]
    casa = amostra.do_time(historico, 1, "Time", mando_do_jogo="casa")
    assert [j["mando"] for j in casa["jogos"]] == ["casa", "casa"]
    assert casa["jogos_lidos"] == 2

    fora = amostra.do_time(historico, 1, "Time", mando_do_jogo="fora")
    assert [j["mando"] for j in fora["jogos"]] == ["fora"]


def test_a_amostra_gravada_e_a_mesma_que_o_pool_do_motor():
    """O ponto do modulo inteiro: o que a tela mostra e o que o motor leu tem
    que ser o mesmo recorte, nao dois parecidos."""
    casa = [jogo("2026-09-10", 1, 2, 1, 1), jogo("2026-09-05", 3, 1, 2, 0)]
    fora = [jogo("2026-09-09", 5, 6, 1, 0), jogo("2026-09-02", 6, 9, 0, 2)]
    pool, _ = sm.pool_and_field("goals", "total", casa, fora, None, 1, 6)
    exibida = amostra.build(home_team_id=1, away_team_id=6,
                            historico_home=casa, historico_away=fora)
    assert (exibida["mandante"]["jogos_lidos"]
            + exibida["visitante"]["jogos_lidos"]) == len(pool)


# ---------------------------------------------------------------- liga no VIP
def test_o_insert_do_vip_grava_a_liga_e_os_parametros_batem():
    """As colunas existiam na tabela e o INSERT nunca as preencheu, entao o
    site caia num fallback que so' resolve DEPOIS do jogo.

    O teste conta os `%s` contra os parametros de proposito: o INSERT do VIP e'
    um SELECT de placeholders posicionais seguido de quatro parametros do
    WHERE NOT EXISTS, e acrescentar coluna sem acrescentar placeholder desloca
    TODOS os valores seguintes -- erro que nao levanta excecao, so' grava o
    campo errado no campo errado."""
    import inspect
    from engine_pipelines import vip_pipeline

    fonte = inspect.getsource(vip_pipeline._save_pick)
    assert "league_id, league_name" in fonte

    capturado = {}

    class CursorFalso:
        rowcount = 1

        def execute(self, sql, params=None):
            capturado["sql"] = sql
            capturado["params"] = params

    fixture = {
        "fixture_id": 1, "match_datetime": __import__("datetime").datetime(2026, 9, 15, 20, 0),
        "home_team_id": 10, "away_team_id": 20,
        "home_team": "A", "away_team": "B",
        "league_id": 72, "league_name": "Brasileirao Serie B",
    }
    pick = {"market_name": "Gols Mais/Menos", "value_label": "Under 3.0", "odd": 1.53,
            "best_bookmaker": "Bet365", "market_type": "goals", "market_id": 5,
            "confidence": 0.8, "ev": 0.1, "taxa_real": 0.66,
            "amostra": 18, "amostra_label": "RICO", "edge": 0.1,
            "prob_implicita": 0.65, "risco": "MEDIO"}
    vip_pipeline._save_pick(CursorFalso(), fixture, pick, 0.9)

    sql = capturado["sql"]
    # O SELECT de valores + os quatro do WHERE NOT EXISTS.
    assert sql.count("%s") == len(capturado["params"])
    assert 72 in capturado["params"]
    assert "Brasileirao Serie B" in capturado["params"]


# ---------------------------------------------------------------- alavancagem
def test_a_alavancagem_solta_o_unique_de_match_date():
    """MAX_CAMINHOS_POR_DIA=5 nunca valeu em PROD: `match_date DATE UNIQUE`
    derrubava o segundo caminho com excecao, e a excecao abortava a transacao
    e o resto da rodada junto (os FAILED de 08 e 09/09)."""
    from engine_pipelines import alavancagem_pipeline as ap

    comandos = []

    class CursorFalso:
        def execute(self, sql, params=None):
            comandos.append(" ".join(sql.split()))

    ap._create_table_if_needed(CursorFalso())
    criacao = next(c for c in comandos if "CREATE TABLE" in c)
    assert "match_date DATE UNIQUE" not in criacao
    assert any("DROP CONSTRAINT IF EXISTS picks_alavancagem_match_date_key" in c
               for c in comandos)
    assert ap.MAX_CAMINHOS_POR_DIA > 1
