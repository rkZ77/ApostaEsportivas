"""O nome do mercado de prop mudou e o motor parou de enxergar a oferta.

O QUE ACONTECEU (2026-09-04)
----------------------------
A Bet365 publicava "Player Shots On Target" (mercado 242), uma lista so' com os
jogadores dos dois times. Passou a publicar o mesmo produto separado por mando:
269 "Home Player Shots On Target Total" -- e o mesmo para chutes, agora em
240 "Home Player Shots" e 241 "Away Player Shots". O `value_name` nao mudou:
continua "Fulano - 2".

O catalogo casa mercado POR NOME, entao a mudanca zerou os metodos `shots` e
`shots_on` sem erro nenhum: medido em PROD no dia, 2.765 ofertas de prop de
jogador foram descartadas antes da primeira conta e a auditoria registrou
"nenhuma casa ofereceu mercado de jogador".

Por isso os casos daqui sao NOMES DE MERCADO, e nao probabilidade: o ponto onde
o motor cegou fica antes de qualquer modelo.

AS ARMADILHAS DO NOME PARECIDO
------------------------------
Tres mercados do mesmo dia tem nome de prop de jogador e nao sao:

  275 "Away Player Shots On Target Total" -- escolha unica ("quem finaliza mais
      no alvo"): value_name e' o nome puro, sem linha, e as probabilidades
      implicitas do jogo somam 1.01. E' o nome simetrico ao 269, que E' prop;
  276 "Away Player Shots Total"           -- total de chutes do TIME ("Over 3.5");
  215 "Player Singles"                    -- copia de 240+241 sob nome generico.

Os tres passariam por um casamento frouxo de nome, e cada um estraga de um
jeito diferente: o primeiro compara contagem com produto de escolha unica, o
segundo trata linha de time como prop, o terceiro duplica o candidato.
"""
from engine_pipelines.player_stats_pipeline import _ofertas_do_metodo
from services.player_stats_engine import methods as cat

CASA, VISITANTE = 1001, 1002


def _oferta(market_name, value_name, odd=1.50, market_id=999):
    return {"market_name": market_name, "value_name": value_name, "odd": odd,
            "market_id": market_id, "bookmaker_name": "Bet365"}


# ── chutes no alvo ────────────────────────────────────────────────────────
def test_chutes_no_alvo_do_mandante_da_bet365():
    ofertas = _ofertas_do_metodo(
        [_oferta("Home Player Shots On Target Total", "Eduardo Pepe - 1", market_id=269)],
        cat.SHOTS_ON)
    assert [(o["nome_ofertado"], o["n"], o["lado"]) for o in ofertas] == [
        ("Eduardo Pepe", 1, "home")]


def test_quem_finaliza_mais_no_alvo_nao_e_prop():
    """275 tem o nome simetrico ao 269 e e' outro produto: escolha unica, sem
    linha. O value_name e' o nome puro, e a soma das probabilidades implicitas
    do jogo da' 1.01."""
    cruas = [_oferta("Away Player Shots On Target Total", "Guilherme Liberato",
                     odd=101.0, market_id=275)]
    assert _ofertas_do_metodo(cruas, cat.SHOTS_ON) == []


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


def test_player_singles_e_o_mesmo_produto_de_240_241():
    """215 republica 240+241 sob nome generico -- as 1.797 linhas batem fixture,
    jogador, linha e odd. Aceitar os tres duplicaria cada candidato."""
    cruas = [_oferta("Player Singles", "Pedro Jesus - 1", market_id=215)]
    assert _ofertas_do_metodo(cruas, cat.SHOTS) == []


def test_total_do_time_nao_e_prop_de_jogador():
    """"Away Player Shots Total" e' linha de TIME, apesar do nome."""
    cruas = [_oferta("Away Player Shots Total", "Over 3.5", market_id=276)]
    assert _ofertas_do_metodo(cruas, cat.SHOTS) == []
    assert _ofertas_do_metodo(cruas, cat.SHOTS_ON) == []


def test_o_lado_do_mercado_restringe_a_busca_de_nome():
    """"Away Player Shots" so' lista jogador do visitante, e o motor usa isso
    pra nao confundir dois homonimos do mesmo jogo."""
    ofertas = _ofertas_do_metodo(
        [_oferta("Away Player Shots", "Pedro Jesus - 2", market_id=241)], cat.SHOTS)
    assert ofertas[0]["lado"] == "away"


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


# ── a faixa de odd ────────────────────────────────────────────────────────
def test_o_piso_de_odd_e_1_44_e_nao_ha_teto():
    """Decisão do usuário em 04/09. O teto de 2.00 protegia contra o erro do
    modelo na cauda; quem segura isso agora são PROB_MINIMA e EDGE_MINIMO, que
    olham a probabilidade em vez do preço."""
    from services.player_stats_engine import config as cfg
    assert cfg.ODD_MIN == 1.44
    assert cfg.ODD_MAX is None


def test_sem_teto_a_odd_alta_chega_no_modelo():
    cruas = [_oferta("Home Player Shots", "Gabriel Veron - 5", odd=7.5, market_id=240)]
    assert len(_ofertas_do_metodo(cruas, cat.SHOTS)) == 1


def test_o_piso_continua_cortando():
    cruas = [_oferta("Home Player Shots", "Gabriel Veron - 1", odd=1.20, market_id=240)]
    assert _ofertas_do_metodo(cruas, cat.SHOTS) == []


def test_o_score_ainda_tem_uma_faixa_pra_ordenar():
    """Teto de PONTUAÇÃO não é teto de corte: sem uma referência o termo de
    segurança pontuaria toda odd como fora da faixa, que é onde a função
    despenca."""
    from services.player_stats_engine import config as cfg
    assert cfg.SCORE_ODD_ALTA == 2.00
    assert cfg.SCORE_CONFIG.conservative_odd_high == cfg.SCORE_ODD_ALTA
    assert cfg.SCORE_CONFIG.conservative_odd_low == cfg.ODD_MIN
