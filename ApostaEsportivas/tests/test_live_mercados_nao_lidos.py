"""O catalogo de mercados que a casa cota ao vivo e o motor ainda nao le.

Existe porque a pergunta "que outro mercado ao vivo da' pra abrir?" nunca teve
resposta baseada em dado -- NOMES_POR_FAMILIA foi levantado uma vez, contra uma
amostra, e desde entao so' um payload lido na mao responderia. A rodada agora
responde sozinha, de graca: as odds ja' foram baixadas pra cotar as familias
triadas.

O que estes testes travam e' o RECORTE. Uma lista que devolve tudo nao informa
nada -- e' a lista inteira de mercados da casa, com dezenas de linhas que este
motor nao sabe precificar nem em principio.
"""
from services.pick_engine_live import live_odds


def _ou(nome, *pares, suspensos=()):
    """Mercado Over/Under com (direcao, odd, linha)."""
    valores = [{"value": d, "odd": o, "handicap": l} for d, o, l in pares]
    valores += [{"value": d, "odd": o, "handicap": l, "suspended": True}
                for d, o, l in suspensos]
    return {"name": nome, "values": valores}


def test_lista_o_mercado_de_contagem_que_o_motor_ignora():
    achados = live_odds.mercados_nao_lidos([
        _ou("Total Shots", ("Over", "1.80", "22.5"), ("Under", "1.95", "22.5")),
        _ou("Total Offsides", ("Over", "1.88", "3.5")),
    ])
    assert [m["mercado"] for m in achados] == ["Total Offsides", "Total Shots"]


def test_nao_repete_o_que_o_motor_ja_cota():
    """goals/corners/cards ja' viram pick · listar seria ruido."""
    achados = live_odds.mercados_nao_lidos([
        _ou("Match Goals", ("Over", "1.85", "2.5")),
        _ou("Total Corners", ("Over", "1.90", "9.5")),
        _ou("Total Cards", ("Over", "2.00", "4.5")),
    ])
    assert achados == []


def test_fora_do_escopo_nao_entra():
    """Nao e' falta de modelo, e' outro tipo de aposta.

    Mercado de TEMPO tem contador que a folha nao separa (mesmo corte do
    pre-jogo); resultado, handicap e placar nao sao contagem, entao o modelo
    de residual deste motor nao os descreve nem em principio. Listar os quatro
    como "possivel" mandaria alguem tentar abrir o que nao da'.
    """
    achados = live_odds.mercados_nao_lidos([
        _ou("1st Half Total Shots", ("Over", "2.20", "9.5")),
        _ou("Asian Handicap Corners", ("Over", "1.90", "1.5")),
        {"name": "Correct Score", "values": [{"value": "2:1", "odd": "8.0"}]},
        {"name": "Match Winner", "values": [{"value": "Home", "odd": "1.70"}]},
    ])
    assert achados == []


def test_mercado_sem_par_over_under_nao_e_contagem():
    """O criterio e' a FORMA da aposta, nao o nome. Sem linha Over/Under nao
    ha' o que este motor saiba precificar, por mais que o nome sugira um
    contador."""
    achados = live_odds.mercados_nao_lidos([
        {"name": "First Team to Get a Corner",
         "values": [{"value": "Home", "odd": "1.90"}]},
    ])
    assert achados == []


def test_linha_suspensa_nao_conta_como_disponivel():
    """Mercado so' com linha suspensa nao aceita aposta -- e' a mesma regra da
    entrada de `extrair_linhas`, e vale aqui pelo mesmo motivo: listar seria
    prometer o que nao da' pra abrir."""
    achados = live_odds.mercados_nao_lidos([
        _ou("Total Fouls", suspensos=[("Over", "1.90", "21.5")]),
    ])
    assert achados == []


def test_junta_as_linhas_do_mesmo_mercado_sem_repetir():
    achados = live_odds.mercados_nao_lidos([
        _ou("Total Shots",
            ("Over", "1.80", "22.5"), ("Under", "1.95", "22.5"),
            ("Over", "2.10", "24.5")),
    ])
    assert achados == [{"mercado": "Total Shots", "linhas": [22.5, 24.5]}]
