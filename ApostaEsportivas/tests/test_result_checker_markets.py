"""evaluate_pick() ponta a ponta: do texto do mercado ate' o resultado.

test_settlement.py cobre a matematica pura. Aqui e' a camada de cima -- a que
decide QUAL estatistica cada mercado le, de que lado, e quando se recusar a
liquidar. Foi nessa camada que o caso relatado quebrou: a matematica de
`10 > 9.5` estava certa, o que chegava nela e' que era zero.
"""
from decimal import Decimal

import pytest

from services.ai_result_checker_service import AIResultCheckerService


@pytest.fixture
def checker():
    return AIResultCheckerService()


def stats(**overrides):
    """Folha de estatistica no formato de get_fixture_result(). O padrao e' um
    jogo completo e conhecido; cada teste sobrescreve so' o que importa (e
    passa None onde quer simular contador nao publicado)."""
    base = {
        "home_goals": 3, "away_goals": 2, "total_goals": 5,
        "home_goals_ht": 1, "away_goals_ht": 1, "total_goals_ht": 2,
        "home_corners": 6, "away_corners": 4, "total_corners": 10,
        "home_yellow": 1, "away_yellow": 0, "total_yellow": 1,
        "home_red": 0, "away_red": 0, "total_red": 0,
        "home_cards": 1, "away_cards": 0, "total_cards": 1,
        "home_offsides": 1, "away_offsides": 0, "total_offsides": 1,
        "home_fouls": 12, "away_fouls": 8, "total_fouls": 20,
        "home_shots_on": 4, "away_shots_on": 4, "total_shots_on": 8,
        "home_shots": 14, "away_shots": 14, "total_shots": 28,
        "home_saves": 2, "away_saves": 1, "total_saves": 3,
        "status": "FT",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# O caso relatado, com os numeros reais do jogo
# ─────────────────────────────────────────────────────────────────────────────
def test_caso_fortaleza_x_palmeiras_over_9_5_escanteios(checker):
    """Fixture 1546854, 05/08/2026: Fortaleza EC 3 x 2 Palmeiras, 6 + 4 = 10
    escanteios. Pick VIP #1563 e free #64, 'Escanteios Mais/Menos · Over 9.5'.
    Producao gravou RED."""
    resultado, factor = checker.evaluate_pick(
        "Escanteios Mais/Menos", "Over 9.5", 1.70,
        stats(), "Fortaleza EC", "Palmeiras", market_type="corners")
    assert resultado == "GREEN"
    assert checker.calculate_profit(factor, Decimal("1.70")) == Decimal("0.70")


def test_escanteios_sem_folha_publicada_segue_pendente(checker):
    """A causa raiz: com a folha ainda nao publicada, o pick NAO resolve --
    nem GREEN nem RED. Volta pendente e e' reavaliado na proxima passada."""
    sem_folha = stats(home_corners=None, away_corners=None, total_corners=None)
    assert checker.evaluate_pick("Escanteios Mais/Menos", "Over 9.5", 1.70,
                                 sem_folha, market_type="corners") == (None, Decimal("0"))


def test_zero_escanteios_de_verdade_continua_resolvendo(checker):
    """Sem confundir ausencia com zero: um jogo que de fato teve 0 escanteios
    perde o Over 9.5 normalmente."""
    zerado = stats(home_corners=0, away_corners=0, total_corners=0)
    assert checker.evaluate_pick("Escanteios Mais/Menos", "Over 9.5", 1.70,
                                 zerado, market_type="corners")[0] == "RED"


# ─────────────────────────────────────────────────────────────────────────────
# Cada mercado le a estatistica certa
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("market,market_type,line,esperado", [
    # escanteios: total 10, casa 6, fora 4
    ("Escanteios Mais/Menos",           "corners", "Over 9.5",  "GREEN"),
    ("Escanteios Casa Mais/Menos",      "corners", "Over 5.5",  "GREEN"),
    ("Escanteios Casa Mais/Menos",      "corners", "Over 6.5",  "RED"),
    ("Escanteios Visitante Mais/Menos", "corners", "Over 3.5",  "GREEN"),
    ("Escanteios Visitante Mais/Menos", "corners", "Under 3.5", "RED"),
    # gols: total 5, casa 3, fora 2
    ("Gols Mais/Menos",                 "goals",   "Over 3.5",  "GREEN"),
    ("Gols Mais/Menos",                 "goals",   "Under 3.5", "RED"),
    ("Total de Gols Casa",              "goals",   "Over 2.5",  "GREEN"),
    ("Total de Gols Visitante",         "goals",   "Under 2.5", "GREEN"),
    # cartoes: 1 amarelo da casa, nenhum vermelho
    ("Cartões Mais/Menos",              "cards",   "Under 5.5", "GREEN"),
    ("Cartões Mais/Menos",              "cards",   "Over 5.5",  "RED"),
    ("Total de Cartões Casa",           "cards",   "Under 2.5", "GREEN"),
    ("Total de Cartões Visitante",      "cards",   "Under 0.5", "GREEN"),
    # faltas: 12 + 8 = 20
    ("Fouls. Total",                    "fouls",   "Over 19.5", "GREEN"),
    ("Total de Faltas",                 "fouls",   "Under 19.5", "RED"),
    # chutes no alvo (8) vs chutes totais (28) · familias diferentes
    ("Total ShotOnGoal",                None,      "Under 9.5", "GREEN"),
    ("Chutes no Alvo",                  None,      "Over 7.5",  "GREEN"),
    ("Total de Chutes",                 "shots",   "Over 27.5", "GREEN"),
    # impedimentos: 1 + 0
    ("Offsides Home Total",             "offsides", "Over 0.5", "GREEN"),
    # defesas de goleiro (time): 2 + 1
    ("Defesas do Goleiro",              "saves",   "Over 2.5",  "GREEN"),
])
def test_cada_mercado_le_a_propria_estatistica(checker, market, market_type, line, esperado):
    assert checker.evaluate_pick(market, line, 1.8, stats(),
                                 market_type=market_type)[0] == esperado


def test_chutes_no_alvo_nao_e_chutes_totais(checker):
    """4 chutes no alvo x 14 chutes totais por time: somar as duas familias
    estourava a linha Under e dava RED errado (pick #114, fixture 1520774)."""
    assert checker.detect_market_type("Total ShotOnGoal") == "shots_on_target"
    assert checker.detect_market_type("Total de Chutes") == "shots"
    assert checker.evaluate_pick("Total ShotOnGoal", "Under 9.5", 1.8, stats())[0] == "GREEN"
    assert checker.evaluate_pick("Total de Chutes", "Under 9.5", 1.8, stats())[0] == "RED"


def test_finalizacoes_no_gol_e_chute_no_alvo(checker):
    """O nome em PT que a casa usa · custou -11,26u antes de ser visto.

    "Finalizações no Gol Mais/Menos" e' chute NO ALVO, mas contem "finaliza" e
    caia na regra generica de `shots` -- liquidado contra ~28 chutes totais em
    vez de ~8 no alvo, estourando toda linha Under por construcao. Foram 13 RED
    em 18 picks desse mercado em PROD, e NOVE deles tinham ganhado na folha.
    """
    assert checker.detect_market_type("Finalizações no Gol Mais/Menos") == "shots_on_target"
    assert checker.evaluate_pick("Finalizações no Gol Mais/Menos", "Under 8.5",
                                 1.75, stats())[0] == "GREEN"


def test_finalizacoes_sem_gol_continua_sendo_chute_total(checker):
    """O outro lado do par nao pode ser arrastado junto · sem "no Gol" E' total,
    e puxar os dois pra "no alvo" so' trocaria a direcao do mesmo erro."""
    assert checker.detect_market_type("Finalizações Mais/Menos") == "shots"
    assert checker.evaluate_pick("Finalizações Mais/Menos", "Under 8.5",
                                 1.75, stats())[0] == "RED"


@pytest.mark.parametrize("market_type, esperado", [
    ("shots_on_target", "GREEN"),   # 8 no alvo, sob a linha 8.5
    ("shots",           "RED"),     # 28 totais, muito acima
])
def test_market_type_gravado_vence_o_texto(checker, market_type, esperado):
    """A coluna estruturada decide o par shots/shots_on_target ANTES do nome.

    Era o inverso: `detect_market_type` so' consultava o market_type depois de
    o texto ja' ter decidido, entao um nome ambiguo mandava no pick mesmo com a
    familia certa gravada ao lado. live.py::_stat_for_market ja' seguia esta
    regra -- os dois motores de liquidacao deviam concordar e nao concordavam.
    """
    assert checker.evaluate_pick("Mercado Com Nome Ambiguo de Finalização",
                                 "Under 8.5", 1.75, stats(),
                                 market_type=market_type)[0] == esperado


def test_cartao_vermelho_vale_dois(checker):
    """Mesma convencao de stats_model._cards_points: gradear com uma regra e
    prever com outra deixa a confidence sem relacao com o resultado."""
    com_vermelho = stats(home_cards=1 + 2 * 1, total_cards=1 + 2 * 1, home_red=1)
    assert checker.evaluate_pick("Cartões Mais/Menos", "Over 2.5", 1.8,
                                 com_vermelho, market_type="cards")[0] == "GREEN"


def test_mercado_so_de_amarelo_ignora_o_peso_do_vermelho(checker):
    com_vermelho = stats(home_cards=3, total_cards=3, home_red=1,
                         home_yellow=1, total_yellow=1)
    assert checker.evaluate_pick("Cartões Amarelos Mais/Menos", "Under 2.5", 1.8,
                                 com_vermelho, market_type="cards")[0] == "GREEN"


def test_mercado_de_primeiro_tempo_usa_o_placar_do_intervalo(checker):
    """Jogo 3x2 no total, 1x1 no intervalo. O mercado de 1° tempo tem que ler
    os 2 gols do intervalo, nao os 5 do jogo: Over 2.5 e' RED no HT e seria
    GREEN se lesse o placar final."""
    assert checker.evaluate_pick("Gols Mais/Menos - 1° Tempo", "Over 2.5", 1.8,
                                 stats(), market_type="goals")[0] == "RED"
    assert checker.evaluate_pick("Gols Mais/Menos - 1° Tempo", "Over 1.5", 1.8,
                                 stats(), market_type="goals")[0] == "GREEN"
    assert checker.evaluate_pick("Gols Mais/Menos", "Over 2.5", 1.8,
                                 stats(), market_type="goals")[0] == "GREEN"


def test_primeiro_tempo_sem_dado_de_intervalo_nao_liquida(checker):
    sem_ht = stats(home_goals_ht=None, away_goals_ht=None, total_goals_ht=None)
    assert checker.evaluate_pick("Gols Mais/Menos - 1° Tempo", "Over 1.5", 1.8,
                                 sem_ht, market_type="goals") == (None, Decimal("0"))


# ─────────────────────────────────────────────────────────────────────────────
# Handicap asiatico em cada familia
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("market,market_type,line,esperado", [
    # gols 3 x 2
    ("Handicap Asiático",           "handicap_goals",   "Home -0.5",  "GREEN"),
    ("Handicap Asiático",           "handicap_goals",   "Home -1",    "PUSH"),
    ("Handicap Asiático",           "handicap_goals",   "Home -1.5",  "RED"),
    ("Handicap Asiático",           "handicap_goals",   "Home -0.75", "HALF-WIN"),
    ("Handicap Asiático",           "handicap_goals",   "Home -1.25", "HALF-LOSS"),
    ("Handicap Asiático",           "handicap_goals",   "Away +1.5",  "GREEN"),
    ("Handicap Asiático",           "handicap_goals",   "Away +1",    "PUSH"),
    # escanteios 6 x 4
    ("Escanteios Handicap Asiático", "handicap_corners", "Home -0.5",  "GREEN"),
    ("Escanteios Handicap Asiático", "handicap_corners", "Home -2",    "PUSH"),
    ("Corners Asian Handicap",       "handicap_corners", "Away +5.5",  "GREEN"),
    ("Corners Asian Handicap",       "handicap_corners", "Away -5.5",  "RED"),
    # cartoes 1 x 0
    ("Cartões Handicap Asiático",    "handicap_cards",   "Home -0.5",  "GREEN"),
    ("Cartões Handicap Asiático",    "handicap_cards",   "Away +0.5",  "RED"),
])
def test_handicap_por_familia(checker, market, market_type, line, esperado):
    assert checker.evaluate_pick(market, line, 1.9, stats(),
                                 market_type=market_type)[0] == esperado


def test_handicap_de_cartoes_nao_e_liquidado_como_under(checker):
    """'Cartões Handicap Asiático' com linha 'Home +0.5' nao tinha caminho
    proprio: caia no ramo de over/under com op=None, e o `else` de cada bloco
    tratava operador ausente como UNDER -- o pick era graduado contra uma
    linha de total que ninguem apostou. Havia 3 desses em producao."""
    resultado, _ = checker.evaluate_pick("Cartões Handicap Asiático", "Home +0.5", 1.9,
                                         stats(), market_type="handicap_cards")
    assert resultado == "GREEN"  # 1 + 0.5 > 0 · casa cobre


def test_handicap_sem_lado_reconhecido_nao_liquida(checker):
    assert checker.evaluate_pick("Handicap Asiático", "-0.5", 1.9,
                                 stats(), market_type="handicap_goals") == (None, Decimal("0"))


# ─────────────────────────────────────────────────────────────────────────────
# Resultado, dupla chance, BTTS
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("market,line,casa,fora,esperado", [
    ("Resultado Final (1X2)", "Home",      3, 2, "GREEN"),
    ("Resultado Final (1X2)", "Home",      1, 1, "RED"),
    ("Resultado Final (1X2)", "Away",      1, 1, "RED"),
    ("Resultado Final (1X2)", "X",         1, 1, "GREEN"),
    ("Dupla Chance",          "Draw/Away", 1, 1, "GREEN"),
    ("Dupla Chance",          "Draw/Away", 3, 2, "RED"),
    ("Dupla Chance",          "Home/Draw", 1, 1, "GREEN"),
])
def test_resultado_e_dupla_chance(checker, market, line, casa, fora, esperado):
    st = stats(home_goals=casa, away_goals=fora, total_goals=casa + fora)
    assert checker.evaluate_pick(market, line, 1.9, st)[0] == esperado


def test_1x2_empatado_com_selecao_de_casa_e_red(checker):
    """A regressao do '(1X2)' no nome do mercado casando com a chave de dupla
    chance '1x': o pick virava '1 ou X' e era gravado GREEN no empate."""
    empate = stats(home_goals=1, away_goals=1, total_goals=2)
    assert checker.evaluate_pick("Resultado Final (1X2)", "Home", 2.5, empate)[0] == "RED"


@pytest.mark.parametrize("line,casa,fora,esperado", [
    ("Sim", 3, 2, "GREEN"), ("Sim", 3, 0, "RED"),
    ("Não", 3, 0, "GREEN"), ("No",  3, 2, "RED"),
])
def test_btts(checker, line, casa, fora, esperado):
    st = stats(home_goals=casa, away_goals=fora, total_goals=casa + fora)
    assert checker.evaluate_pick("Ambas as Equipes Marcam", line, 1.8, st,
                                 market_type="btts")[0] == esperado


# ─────────────────────────────────────────────────────────────────────────────
# Classificacao de mercado
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("market,market_type,esperado", [
    ("Escanteios Mais/Menos",              "corners",  "corners"),
    ("Escanteios Mais/Menos",              "goals",    "corners"),   # texto vence o rotulo errado
    ("Escanteios Casa Mais/Menos (Türkiye)", "corners", "corners"),
    ("Cartões Mais/Menos",                 "unknown",  "cards"),
    ("Ambas as Equipes Marcam",            "unknown",  "btts"),
    ("Gols Mais/Menos",                    None,       "goals"),
    ("Total - Home Goals Over/Under",      None,       "goals"),
    ("Resultado Final (1X2)",              "outcome",  "result_1x2"),
    ("Dupla Chance",                       "result",   "double_chance"),
    ("Offsides Home Total",                "offsides", "offsides"),
    ("Fouls. Total",                       "fouls",    "fouls"),
])
def test_classificacao_de_mercado(checker, market, market_type, esperado):
    assert checker.detect_market_type(market, market_type) == esperado


def test_rotulo_do_banco_so_decide_quando_o_texto_nao_decide(checker):
    """Existe pick em producao com market_type='goals' e market='Escanteios
    Mais/Menos'. Quem tem razao e' o texto -- e os dois motores precisam
    concordar nisso, senao o mesmo pick e' liquidado de dois jeitos."""
    assert checker.detect_market_type("Escanteios Mais/Menos", "goals") == "corners"
    assert checker.detect_market_type("Mercado Estranho", "corners") == "corners"


@pytest.mark.parametrize("market,line", [
    ("Placar Exato", "3:2"),
    ("Mercado Que Nao Existe", "Over 2.5"),
    ("Escanteios Mais/Menos", ""),
    ("Escanteios Mais/Menos", "linha ilegivel"),
])
def test_mercado_ou_linha_nao_suportados_nao_liquidam(checker, market, line):
    assert checker.evaluate_pick(market, line, 1.8, stats()) == (None, Decimal("0"))


# ─────────────────────────────────────────────────────────────────────────────
# Prorrogacao · casa liquida pelos 90 minutos
# ─────────────────────────────────────────────────────────────────────────────
def prorrogacao(**overrides):
    """Belgium 3 x 2 Senegal (AET, fixture 1567308): 2 x 2 nos 90 minutos,
    1 x 0 na prorrogacao. 6 escanteios contados nos 120."""
    base = dict(status="AET",
                home_goals=3, away_goals=2, total_goals=5,
                home_goals_90=2, away_goals_90=2, total_goals_90=4,
                home_goals_ht=0, away_goals_ht=1, total_goals_ht=1,
                home_corners=4, away_corners=2, total_corners=6)
    base.update(overrides)
    return stats(**base)


def test_gols_na_prorrogacao_sao_liquidados_pelos_90_minutos(checker):
    """Over 4.5: 5 gols no total, 4 nos 90 minutos. A casa paga pelos 90 --
    RED, nao GREEN."""
    assert checker.evaluate_pick("Gols Mais/Menos", "Over 4.5", 1.7,
                                 prorrogacao(), market_type="goals")[0] == "RED"
    assert checker.evaluate_pick("Gols Mais/Menos", "Over 3.5", 1.7,
                                 prorrogacao(), market_type="goals")[0] == "GREEN"
    assert checker.evaluate_pick("Gols Mais/Menos", "Over 4", 1.7,
                                 prorrogacao(), market_type="goals")[0] == "PUSH"


def test_resultado_na_prorrogacao_sai_do_placar_dos_90(checker):
    """2 x 2 nos 90 minutos e' empate, mesmo o jogo tendo terminado 3 x 2."""
    assert checker.evaluate_pick("Resultado Final (1X2)", "Home", 2.5,
                                 prorrogacao())[0] == "RED"
    assert checker.evaluate_pick("Resultado Final (1X2)", "X", 3.2,
                                 prorrogacao())[0] == "GREEN"


def test_btts_na_prorrogacao_usa_o_placar_dos_90(checker):
    assert checker.evaluate_pick("Ambas as Equipes Marcam", "Sim", 1.8,
                                 prorrogacao(), market_type="btts")[0] == "GREEN"
    so_casa_nos_90 = prorrogacao(home_goals_90=2, away_goals_90=0, total_goals_90=2)
    assert checker.evaluate_pick("Ambas as Equipes Marcam", "Sim", 1.8,
                                 so_casa_nos_90, market_type="btts")[0] == "RED"


def test_escanteios_na_prorrogacao_nao_sao_liquidados(checker):
    """/fixtures/statistics soma os 120 minutos sem separar por periodo: o
    numero dos 90 nao existe. Nao liquida -- e nao inventa um PUSH, que e'
    uma afirmacao financeira ('stake devolvida') que ninguem conferiu."""
    assert checker.evaluate_pick("Escanteios Mais/Menos", "Over 9.5", 1.7,
                                 prorrogacao(), market_type="corners") == (None, Decimal("0"))
    assert checker.evaluate_pick("Cartões Mais/Menos", "Under 5.5", 1.8,
                                 prorrogacao(), market_type="cards") == (None, Decimal("0"))
    assert checker.evaluate_pick("Offsides Home Total", "Over 1.5", 1.7,
                                 prorrogacao(), market_type="offsides") == (None, Decimal("0"))


def test_prorrogacao_sem_placar_dos_90_coletado_nao_liquida(checker):
    """Jogo antigo, coletado antes de home_goals_90 existir: sem o placar dos
    90 minutos nao da' pra liquidar nada, nem gols."""
    sem_90 = prorrogacao(home_goals_90=None, away_goals_90=None, total_goals_90=None)
    assert checker.evaluate_pick("Gols Mais/Menos", "Over 3.5", 1.7,
                                 sem_90, market_type="goals") == (None, Decimal("0"))


def test_prorrogacao_nao_afeta_mercado_de_primeiro_tempo(checker):
    """HT e' tempo normal por definicao: 0 x 1 no intervalo."""
    assert checker.evaluate_pick("Gols Mais/Menos - 1° Tempo", "Under 2.5", 1.7,
                                 prorrogacao(), market_type="goals")[0] == "GREEN"
    assert checker.evaluate_pick("Gols Mais/Menos - 1° Tempo", "Over 1.5", 1.7,
                                 prorrogacao(), market_type="goals")[0] == "RED"


def test_jogo_normal_nao_precisa_do_placar_dos_90(checker):
    """Em jogo sem prorrogacao o placar final JA' e' o dos 90 minutos: a
    coluna nova nao pode virar requisito pra liquidar o dia a dia."""
    normal = stats(home_goals_90=None, away_goals_90=None, total_goals_90=None)
    assert checker.evaluate_pick("Gols Mais/Menos", "Over 4.5", 1.7,
                                 normal, market_type="goals")[0] == "GREEN"


# ─────────────────────────────────────────────────────────────────────────────
# Lado do mercado
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("market,esperado", [
    ("Escanteios Casa Mais/Menos", "home"),
    ("Escanteios Visitante Mais/Menos", "away"),
    ("Escanteios Mais/Menos", "total"),
    ("Total de Gols Casa", "home"),
    ("Total de Cartões Visitante", "away"),
])
def test_deteccao_de_lado(checker, market, esperado):
    assert checker.detect_side(market) == esperado


def test_lado_pelo_nome_do_time_no_mercado(checker):
    """'Escanteios France Mais/Menos' e' o total DA FRANCA, nao do jogo."""
    assert checker.detect_side("Escanteios France Mais/Menos", "France", "Haiti") == "home"
    st = stats(home_corners=6, away_corners=4, total_corners=10)
    assert checker.evaluate_pick("Escanteios France Mais/Menos", "Over 5.5", 1.8,
                                 st, "France", "Haiti", market_type="corners")[0] == "GREEN"
    assert checker.evaluate_pick("Escanteios France Mais/Menos", "Over 6.5", 1.8,
                                 st, "France", "Haiti", market_type="corners")[0] == "RED"


# ─────────────────────────────────────────────────────────────────────────────
# Grade de linhas ponta a ponta, no mercado real
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("linha,esperado", [
    ("Over 9",      "GREEN"), ("Over 9.0",   "GREEN"),
    ("Over 9.25",   "GREEN"), ("Over 9.5",   "GREEN"),
    ("Over 9.75",   "HALF-WIN"),
    ("Over 10",     "PUSH"),  ("Over 10.0",  "PUSH"),
    ("Over 10.25",  "HALF-LOSS"),
    ("Over 10.5",   "RED"),   ("Over 10.75", "RED"), ("Over 11", "RED"),
    ("Under 9",     "RED"),   ("Under 9.5",  "RED"),
    ("Under 9.75",  "HALF-LOSS"),
    ("Under 10",    "PUSH"),
    ("Under 10.25", "HALF-WIN"),
    ("Under 10.5",  "GREEN"), ("Under 11",   "GREEN"),
])
def test_grade_completa_em_escanteios_com_10(checker, linha, esperado):
    """Os 10 escanteios do jogo real, contra toda a grade de 9 a 11."""
    assert checker.evaluate_pick("Escanteios Mais/Menos", linha, 1.8, stats(),
                                 market_type="corners")[0] == esperado
