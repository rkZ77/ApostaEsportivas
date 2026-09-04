"""O nome do mercado de prop mudou e o motor parou de enxergar a oferta.

O QUE ACONTECEU (2026-09-04)
----------------------------
A Bet365 publicava "Player Shots On Target" (mercado 242), uma lista so' com os
jogadores dos dois times. Passou a publicar o mesmo produto separado por mando:
269 "Home Player Shots On Target Total" e 275 "Away Player Shots On Target
Total" -- e o mesmo para chutes (240/241). O `value_name` nao mudou: continua
"Fulano - 2".

O catalogo casa mercado POR NOME, entao a mudanca zerou os metodos `shots` e
`shots_on` sem erro nenhum: medido em PROD no dia, 2.765 ofertas de prop de
jogador foram descartadas antes da primeira conta e a auditoria registrou
"nenhuma casa ofereceu mercado de jogador".

Por isso os casos daqui sao NOMES DE MERCADO, e nao probabilidade: o ponto onde
o motor cegou fica antes de qualquer modelo.

A ARMADILHA DO NOME PARECIDO
----------------------------
"Away Player Shots Total" (276, Betano) e "Away Player Shots On Target Total"
(275, Bet365) diferem por tres palavras e sao produtos diferentes: o primeiro e'
o total de chutes do TIME, publicado como "Over 3.5". Aceitar os dois faria o
motor tratar linha de time como prop de jogador.
"""
from engine_pipelines.player_stats_pipeline import _ofertas_do_metodo
from services.player_stats_engine import methods as cat

CASA, VISITANTE = 1001, 1002


def _oferta(market_name, value_name, odd=1.50, market_id=999):
    return {"market_name": market_name, "value_name": value_name, "odd": odd,
            "market_id": market_id, "bookmaker_name": "Bet365"}


# ── chutes no alvo ────────────────────────────────────────────────────────
def test_chutes_no_alvo_por_mando_da_bet365():
    cruas = [
        _oferta("Home Player Shots On Target Total", "Eduardo Pepe - 1", market_id=269),
        _oferta("Away Player Shots On Target Total", "Pedro Jesus - 2", market_id=275),
    ]
    ofertas = _ofertas_do_metodo(cruas, cat.SHOTS_ON)
    assert [(o["nome_ofertado"], o["n"], o["lado"]) for o in ofertas] == [
        ("Eduardo Pepe", 1, "home"),
        ("Pedro Jesus", 2, "away"),
    ]


def test_o_nome_antigo_continua_valendo():
    """A casa pode voltar atras, e a base tem pick gravado com o nome antigo."""
    ofertas = _ofertas_do_metodo(
        [_oferta("Player Shots On Target", "Neymar - 1", market_id=242)], cat.SHOTS_ON)
    assert len(ofertas) == 1
    assert ofertas[0]["lado"] is None


# ── chutes ────────────────────────────────────────────────────────────────
def test_chutes_por_mando_da_bet365():
    cruas = [_oferta("Home Player Shots", "Gabriel Veron - 3", market_id=240),
             _oferta("Away Player Shots", "Alexandre Parsemain - 1", market_id=241)]
    assert len(_ofertas_do_metodo(cruas, cat.SHOTS)) == 2


def test_total_do_time_nao_e_prop_de_jogador():
    """"Away Player Shots Total" e' linha de TIME, apesar do nome."""
    cruas = [_oferta("Away Player Shots Total", "Over 3.5", market_id=276)]
    assert _ofertas_do_metodo(cruas, cat.SHOTS) == []
    assert _ofertas_do_metodo(cruas, cat.SHOTS_ON) == []


# ── o mercado de um metodo nao vaza pro outro ─────────────────────────────
def test_chute_no_alvo_nao_entra_como_chute():
    cruas = [_oferta("Home Player Shots On Target Total", "Eduardo Pepe - 1")]
    assert _ofertas_do_metodo(cruas, cat.SHOTS) == []


def test_defesa_de_goleiro_nao_mudou_de_nome():
    cruas = [_oferta("Goalkeeper Saves", "Everson - 3", market_id=267)]
    assert len(_ofertas_do_metodo(cruas, cat.SAVES)) == 1


# ── auditoria por metodo ──────────────────────────────────────────────────
def test_o_motivo_do_descarte_e_por_metodo():
    """Antes, um jogo sem odds devolvia UM motivo pro jogo inteiro, e a
    execucao de cada metodo tinha que adivinhar se ele valia pra ela."""
    import engine_pipelines.player_stats_pipeline as P

    class _OddsVazio:
        def load_odds_by_fixture(self, _fixture_id):
            return []

    candidatos, motivos = P._avaliar_fixture(
        {"fixture_id": 1, "home_team_id": CASA, "away_team_id": VISITANTE},
        cur=None, odds_service=_OddsVazio(), match_stats=None,
        calibragem={}, constantes_saves={})

    assert candidatos == []
    assert motivos == {m.slug: P.MOTIVO_SEM_ODDS for m in cat.METODOS}
