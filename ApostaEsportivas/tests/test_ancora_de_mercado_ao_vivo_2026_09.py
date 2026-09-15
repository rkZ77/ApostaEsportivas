"""A ancora de mercado do motor ao vivo tem que descrever um mercado que existe.

Achado em 15/09/2026, nos 190 picks ao vivo ja' gravados em PROD: em 133 deles
a probabilidade de mercado ficou ACIMA da implicita da odd publicada -- o que
nenhum no-vig honesto pode produzir, porque ele tira margem, nao inventa
probabilidade. Em escanteios era 100% dos picks.

A causa: `corners` casa com cinco nomes de mercado ("total corners", "asian
corners", "match corners"...), e o par Over/Under era montado com a MELHOR odd
de cada lado, cada uma podendo vir de um bloco diferente. A soma das
implicitas caia abaixo de 1 e o no-vig passava a inflar. Como
`encolher_contra_mercado` puxa a estimativa PARA a ancora, a probabilidade
publicada subia junto.

Mesmo defeito que o pre-jogo mediu e corrigiu em 14/08 (resolve_prob_baseline).

Nenhum teste toca banco nem rede.
"""
from services.pick_engine_live import live_odds


def bloco(nome, linha, over, under):
    return {"name": nome, "values": [
        {"value": "Over", "handicap": str(linha), "odd": str(over)},
        {"value": "Under", "handicap": str(linha), "odd": str(under)},
    ]}


def por_direcao(entradas):
    return {e["direcao"]: e for e in entradas}


def test_o_no_vig_nao_pareia_blocos_diferentes():
    """O caso real: europeu e asiatico cotando a mesma linha de escanteios.

    Misturar o melhor Over (1.67, europeu) com o melhor Under (3.41, asiatico)
    da' uma soma de implicitas de 0.89 -- uma arbitragem de 11% que nenhuma
    casa oferece. A ancora do Over tem que sair do par europeu."""
    odds = [bloco("Total Corners", 11.0, 1.67, 2.15),
            bloco("Asian Corners", 11.0, 1.55, 3.41)]
    linhas = por_direcao(live_odds.extrair_linhas(odds, ("corners",)))
    over = linhas["over"]
    assert over["origem_prob_mercado"] == "no_vig"
    # Par europeu: 1/1.67 / (1/1.67 + 1/2.15).
    assert abs(over["prob_mercado"] - 0.5628) < 0.001
    # E o que o defeito produzia: ancora acima da implicita da propria odd.
    assert over["prob_mercado"] < 1 / over["odd"]


def test_a_odd_publicada_continua_sendo_a_melhor():
    """A correcao e' sobre a ANCORA, nao sobre o preco: quem aposta continua
    levando a melhor odd que alguma casa cotou."""
    odds = [bloco("Total Corners", 11.0, 1.67, 2.15),
            bloco("Asian Corners", 11.0, 1.55, 3.41)]
    linhas = por_direcao(live_odds.extrair_linhas(odds, ("corners",)))
    assert linhas["over"]["odd"] == 1.67
    assert linhas["under"]["odd"] == 3.41


def test_par_que_soma_menos_que_um_e_recusado():
    """Mesmo dentro de um bloco so': odd ao vivo se mexe o tempo todo, e as
    duas pontas podem ter sido lidas em segundos diferentes. Um par que soma
    menos que 1 nao e' mercado barato, e' leitura inconsistente -- o motor cai
    na implicita, que e' um numero que a casa publicou."""
    odds = [bloco("Total Corners", 11.0, 1.67, 3.41)]
    linhas = por_direcao(live_odds.extrair_linhas(odds, ("corners",)))
    for e in linhas.values():
        assert e["origem_prob_mercado"] == "implied"
        assert abs(e["prob_mercado"] - 1 / e["odd"]) < 0.001


def test_bloco_unico_e_coerente_segue_usando_no_vig():
    """A correcao nao pode desligar o no-vig do caso normal."""
    linhas = por_direcao(live_odds.extrair_linhas(
        [bloco("Total Corners", 9.5, 1.80, 2.00)], ("corners",)))
    over = linhas["over"]
    assert over["origem_prob_mercado"] == "no_vig"
    assert over["prob_mercado"] < 1 / over["odd"]  # tirou margem


def test_entre_blocos_validos_vence_o_de_menor_margem():
    """Dois blocos coerentes: o de margem menor chega mais perto do justo."""
    odds = [bloco("Total Corners", 9.5, 1.80, 2.00),    # soma 1.056
            bloco("Match Corners", 9.5, 1.70, 1.90)]    # soma 1.114
    over = por_direcao(live_odds.extrair_linhas(odds, ("corners",)))["over"]
    assert abs(over["prob_mercado"] - 0.5263) < 0.001
