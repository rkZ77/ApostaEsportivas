"""Prop de jogador em /odds/live: o mercado existia e o motor nao o via.

O motor ao vivo tem uma ferramenta propria pra responder "que mercado da' pra
abrir?" (`live_odds.mercados_nao_lidos`), e ela era CEGA pra prop de jogador:
filtra por `value` igual a "over"/"under", e prop de jogador nao tem essa
forma. O nome do jogador e a direcao vem grudados num campo so'
("Deniz Undav/Over 1.5"), com `handicap` nulo. Entao o mercado era baixado
junto das familias de partida, a cada rodada, e sumia sem deixar rastro.

Levantado contra a API real em 2026-09-04: dos 266 tipos de aposta que
/odds/live/bets declara, 148 "Player Shots" e 153 "Player Shots on Targets"
sao contador individual. Num jogo da Bundesliga aos 11 minutos, saiam 53
entradas de 10 jogadores.

O CASO QUE MAIS IMPORTA aqui e' o do par ausente: a casa cota so' o lado Over.
Sem par nao ha no-vig, e a probabilidade de mercado cai na implicita crua, com
a margem da casa dentro. Quem for calcular edge sobre isso precisa saber, e por
isso `origem_prob_mercado` e' asserido.
"""
from services.pick_engine_live import live_odds


def _mercado(nome, valores):
    return {"id": 148, "name": nome, "values": valores}


def _v(value, odd, suspended=False):
    return {"value": value, "odd": str(odd), "handicap": None, "suspended": suspended}


# ── formato do value ──────────────────────────────────────────────────────
def test_le_nome_direcao_e_linha():
    assert live_odds.parse_valor_de_jogador("Deniz Undav/Over 1.5") == ("Deniz Undav", "over", 1.5)


def test_nome_composto_com_barra_no_meio_nao_confunde():
    assert live_odds.parse_valor_de_jogador("Sergej Milinkovic-Savic/Over 0.5") == (
        "Sergej Milinkovic-Savic", "over", 0.5)


def test_linha_de_partida_nao_e_prop():
    """"Over" puro e' a familia de partida, que sai por `extrair_linhas`."""
    assert live_odds.parse_valor_de_jogador("Over") is None


def test_escolha_unica_sem_linha_nao_e_prop():
    assert live_odds.parse_valor_de_jogador("Guilherme Liberato") is None


# ── extracao ──────────────────────────────────────────────────────────────
def test_extrai_prop_de_chutes():
    linhas = live_odds.extrair_linhas_de_jogador(
        [_mercado("Player Shots", [_v("Deniz Undav/Over 1.5", 1.9)])])
    assert len(linhas) == 1
    e = linhas[0]
    assert (e["jogador"], e["contador"], e["linha"], e["direcao"]) == (
        "Deniz Undav", "shots", 1.5, "over")
    assert e["market_type"] == "player_shots"


def test_sem_par_a_probabilidade_e_a_implicita_crua():
    """A casa so' cota Over: a ancora carrega a margem, e o campo diz isso."""
    e = live_odds.extrair_linhas_de_jogador(
        [_mercado("Player Shots", [_v("Deniz Undav/Over 1.5", 2.0)])])[0]
    assert e["tem_par"] is False
    assert e["origem_prob_mercado"] == "implied"
    assert e["prob_mercado"] == 0.5


def test_com_par_o_vig_sai():
    e = live_odds.extrair_linhas_de_jogador([_mercado("Player Shots", [
        _v("Deniz Undav/Over 1.5", 2.0), _v("Deniz Undav/Under 1.5", 2.0)])])
    assert {x["origem_prob_mercado"] for x in e} == {"no_vig"}


def test_over_de_jogadores_diferentes_nao_forma_par():
    """Dois jogadores podem finalizar no mesmo jogo -- um nao e' o complemento
    do outro, e tratar como par produziria probabilidade de coisa nenhuma."""
    linhas = live_odds.extrair_linhas_de_jogador([_mercado("Player Shots", [
        _v("Deniz Undav/Over 1.5", 2.0), _v("Angelo Stiller/Under 1.5", 2.0)])])
    assert {x["origem_prob_mercado"] for x in linhas} == {"implied"}


def test_suspenso_nao_entra():
    assert live_odds.extrair_linhas_de_jogador(
        [_mercado("Player Shots", [_v("Deniz Undav/Over 1.5", 1.9, suspended=True)])]) == []


def test_mercado_de_tempo_fica_fora():
    assert live_odds.extrair_linhas_de_jogador(
        [_mercado("Player Shots (1st Half)", [_v("Deniz Undav/Over 0.5", 1.9)])]) == []


# ── separacao entre os dois caminhos ──────────────────────────────────────
def test_prop_de_jogador_nao_entra_nas_familias_de_partida():
    brutas = [_mercado("Player Shots", [_v("Deniz Undav/Over 1.5", 1.9)])]
    assert live_odds.extrair_linhas(brutas) == []


def test_prop_de_jogador_nao_e_listado_duas_vezes():
    """Sai na lista propria, entao nao pode sair tambem em mercados_nao_lidos."""
    brutas = [_mercado("Player Shots", [_v("Deniz Undav/Over 1.5", 1.9)])]
    assert live_odds.mercados_nao_lidos(brutas) == []
    assert len(live_odds.extrair_linhas_de_jogador(brutas)) == 1
