# -*- coding: utf-8 -*-
"""`"Red Cards": null` numa folha PUBLICADA e' ZERO, nao ausencia.

O DEFEITO
---------
A API-Football publica zero explicito em todo contador da folha de
/fixtures/statistics -- escanteio, falta, impedimento, chute, amarelo. O UNICO
tipo que ela devolve como `null` e' "Red Cards", e ela faz isso no caso normal:
ninguem foi expulso.

Medido em 2026-08-26 sobre 10 partidas FT sorteadas (20 folhas):

    tipo              null   zero explicito   >0
    Corner Kicks         0                1   19
    Offsides             0                4   16
    Yellow Cards         0                1   19
    Red Cards           18                1    1
    (demais)             0                0   20

Os tres leitores de folha do projeto tratavam esse null como "nao publicado".
Consequencia no banco (DEV, agosto/2026): 95 jogos FT, 12 com vermelho -- os 12
em que houve expulsao. ZERO jogos com vermelho igual a zero. O motor derruba do
pool de cartoes todo jogo sem vermelho (stats_model._tem_folha_de_cartao_
completa), entao 87% da amostra de cartoes evaporava, e nenhum mercado de
cartao liquidava ao vivo (_stat_value soma amarelo+vermelho e devolve None se
faltar um).

O QUE ESTE TESTE PROTEGE
------------------------
As duas metades ao mesmo tempo, porque corrigir uma quebrando a outra ja'
aconteceu duas vezes neste codigo:

  * folha PUBLICADA + campo vazio -> ZERO
  * folha AUSENTE (vazia ou so' de nulls) -> None em TUDO

A segunda e' a invariante 1 de services/settlement.py, nascida dos 99 jogos FT
gravados com escanteio, falta e chute todos em 0 quando a API nao respondeu.
"""
import pytest

from utils import stat_sheet


def _folha_completa(red=None):
    """Folha como a API manda num FT normal: tudo preenchido, vermelho vazio."""
    return [
        {"type": "Shots on Goal", "value": 3},
        {"type": "Total Shots", "value": 11},
        {"type": "Fouls", "value": 14},
        {"type": "Corner Kicks", "value": 0},
        {"type": "Offsides", "value": 0},
        {"type": "Ball Possession", "value": "44%"},
        {"type": "Yellow Cards", "value": 1},
        {"type": "Red Cards", "value": red},
        {"type": "Goalkeeper Saves", "value": 3},
    ]


# ── folha publicada: vazio e' zero ───────────────────────────────────────
def test_vermelho_vazio_em_folha_publicada_e_zero():
    assert stat_sheet.ler_valor(_folha_completa(), "Red Cards") == 0


def test_vermelho_explicito_continua_valendo():
    assert stat_sheet.ler_valor(_folha_completa(red=2), "Red Cards") == 2
    assert stat_sheet.ler_valor(_folha_completa(red=0), "Red Cards") == 0


def test_zero_explicito_de_outro_contador_nao_vira_ausencia():
    """Escanteio 0 e impedimento 0 sao numeros reais e tem que sobreviver."""
    folha = _folha_completa()
    assert stat_sheet.ler_valor(folha, "Corner Kicks") == 0
    assert stat_sheet.ler_valor(folha, "Offsides") == 0


def test_tipo_fora_da_folha_ROBUSTA_e_zero():
    """MUDOU EM 2026-08-28, a pedido do usuario.

    Ate' aqui a ausencia da chave era tratada como "nao veio", e o jogo saia do
    pool daquela familia. O diagnostico do /admin mostrou o custo: de 1.809
    jogos, 30 sem escanteio, 45 sem falta, 49 sem chute -- numeros DIFERENTES
    por familia, o que descarta "a folha nao veio" e prova que a folha veio com
    um contador faltando.

    Numa folha que a API publicou com quinze contadores, o decimo sexto que
    falta e' evento que nao aconteceu. A API nao omite o que aconteceu.
    """
    assert stat_sheet.ler_valor(_folha_completa(), "Dangerous Attacks") == 0


# ── folha ausente: nada vira zero (invariante 1 do settlement) ───────────
def test_folha_vazia_nao_produz_zero():
    assert stat_sheet.ler_valor([], "Red Cards") is None
    assert stat_sheet.ler_valor([], "Corner Kicks") is None
    assert stat_sheet.ler_folha([]) == {}


def test_folha_so_de_nulls_nao_produz_zero():
    """O stub que a API devolve quando nao tem o jogo: nenhum valor preenchido.

    E' o caso que fabricou 99 jogos FT com escanteio, falta e chute em 0 -- 94
    deles com gol.
    """
    stub = [{"type": t, "value": None}
            for t in ("Corner Kicks", "Fouls", "Total Shots", "Red Cards")]
    assert stat_sheet.folha_publicada(stub) is False
    assert stat_sheet.ler_valor(stub, "Corner Kicks") is None
    assert stat_sheet.ler_valor(stub, "Red Cards") is None
    assert stat_sheet.ler_folha(stub) == {}


# ── folha ROBUSTA: o contador que falta e' zero ──────────────────────────
@pytest.mark.parametrize("tipo", ["Corner Kicks", "Fouls", "Yellow Cards",
                                  "Shots on Goal", "expected_goals"])
def test_vazio_numa_folha_robusta_e_zero(tipo):
    """A regra deixou de ser estreita em 2026-08-28 · decisao do usuario:
    "se vem zerado coloca 0, nao faz sentido deixar zerado, isso ferra na
    media".

    E ele estava certo sobre o efeito: contador ausente derruba o jogo do pool
    daquela familia (stats_model._tem_folha_da_familia), entao a media do time
    sai de uma amostra menor sem sintoma nenhum.

    O que NAO mudou e' o caso que produziu o bug de julho -- ver os testes de
    folha ausente e folha magra logo abaixo.
    """
    folha = [i for i in _folha_completa() if i["type"] != tipo]
    folha.append({"type": tipo, "value": None})
    assert stat_sheet.ler_valor(folha, tipo) == 0
    assert stat_sheet.ler_folha(folha)[tipo] == 0


@pytest.mark.parametrize("tipo", ["Ball Possession", "Passes %"])
def test_percentual_NUNCA_vira_zero(tipo):
    """Posse 0% e precisao de passe 0% sao impossiveis num jogo que aconteceu.

    Nas contagens, zero e' um valor legitimo -- o jogo pode ter tido zero
    impedimento. Aqui nao e', e um zero fabricado entraria direto na media.

    E ha' uma razao a mais: a propria tela de Dados usa a posse como AFERICAO
    ("posse media longe de 50 e' coleta torta, nao jogo estranho"). Fabricar
    zero ali quebraria o instrumento que detecta coleta ruim.
    """
    folha = [i for i in _folha_completa() if i["type"] != tipo]
    folha.append({"type": tipo, "value": None})
    assert stat_sheet.ler_valor(folha, tipo) is None
    assert tipo not in stat_sheet.ler_folha(folha)


def test_folha_MAGRA_nao_autoriza_zero():
    """A fronteira que impede o bug de 2026-07-25 de voltar.

    Uma folha com um contador so' foi "publicada" (tem um valor), mas nao
    autoriza conclusao sobre os outros dezoito. Era assim que a folha ausente
    virava zero em tudo: 99 jogos FT com escanteio, falta e chute zerados, 94
    deles COM GOL.
    """
    magra = [{"type": "Corner Kicks", "value": 4}]

    assert stat_sheet.folha_publicada(magra) is True
    assert stat_sheet.folha_robusta(magra) is False
    assert stat_sheet.ler_valor(magra, "Fouls") is None
    assert "Fouls" not in stat_sheet.ler_folha(magra)


def test_ao_vivo_a_folha_incompleta_continua_sendo_ausencia():
    """A MESMA folha significa coisas OPOSTAS antes e depois do apito.

        jogo encerrado    contador que falta = evento que nao aconteceu = 0
        jogo em andamento contador que falta = o provedor ainda nao publicou

    Ao vivo, tratar ausencia como zero destruiria a deteccao de dado atrasado
    do motor Live (`live_state.DELAYED`), que percebe justamente pelo contador
    que falta -- e um Over de escanteio decidido em cima de "zero escanteios
    aos 60'" seria pick tomado com dado que nao existe.
    """
    # `value: None` e nao remocao do item: `ler_folha` devolve "a folha como
    # dicionario" e so' enxerga o que ESTA' nela · tipo que nem aparece nao tem
    # como virar chave. Quem resolve tipo ausente e' `ler_valor`, que recebe o
    # nome do tipo (e e' o caminho que o coletor usa, coluna por coluna).
    folha = [i for i in _folha_completa() if i["type"] != "Corner Kicks"]
    folha.append({"type": "Corner Kicks", "value": None})

    assert stat_sheet.ler_folha(folha)["Corner Kicks"] == 0
    assert "Corner Kicks" not in stat_sheet.ler_folha(folha, jogo_encerrado=False)

    # E pelo caminho do coletor, tipo AUSENTE tambem separa os dois casos.
    sem_o_tipo = [i for i in _folha_completa() if i["type"] != "Corner Kicks"]
    assert stat_sheet.ler_valor(sem_o_tipo, "Corner Kicks") == 0
    assert stat_sheet.ler_valor(sem_o_tipo, "Corner Kicks", robusta=False) is None


def test_o_motor_ao_vivo_desliga_a_regra():
    """Fonte, e nao comportamento: o `False` tem que estar la' na chamada · sem
    ele o motor Live herda a regra do jogo encerrado em silencio."""
    import os

    caminho = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(stat_sheet.__file__))),
        "services", "pick_engine_live", "live_feed.py")
    with open(caminho, encoding="utf-8") as fh:
        fonte = fh.read()

    assert "jogo_encerrado=False" in fonte


def test_o_corte_de_robustez_e_o_mesmo_que_o_admin_ja_usava():
    """Cinco contadores · a mesma definicao de "folha completa" de
    routers/admin.py::_COLUNAS_DA_FOLHA. Numero novo aqui seria uma terceira
    definicao de folha completa no projeto."""
    assert stat_sheet.MIN_CONTADORES_ROBUSTA == 5

    quatro = [{"type": f"T{i}", "value": 1} for i in range(4)]
    assert stat_sheet.folha_robusta(quatro) is False
    assert stat_sheet.folha_robusta(quatro + [{"type": "T4", "value": 1}]) is True


def test_percentual_preenchido_perde_o_simbolo():
    assert stat_sheet.ler_valor(_folha_completa(), "Ball Possession") == 44.0


# ── soma que respeita ausencia ───────────────────────────────────────────
def test_soma_com_parcela_desconhecida_e_desconhecida():
    assert stat_sheet.somar(2, None) is None
    assert stat_sheet.somar(2, 0) == 2


# ── os tres leitores concordam ───────────────────────────────────────────
def test_coletor_em_lote_grava_zero_no_vermelho():
    """collectors/match_statistics_sync_service.extract_stat."""
    from collectors.match_statistics_sync_service import extract_stat
    assert extract_stat(_folha_completa(), "Red Cards") == 0
    assert extract_stat([], "Red Cards") is None


def test_motor_ao_vivo_le_zero_no_vermelho():
    """services/pick_engine_live/live_feed.ler_estatisticas."""
    from services.pick_engine_live.live_feed import ler_estatisticas, total_da_familia
    bruto = [{"team": {"id": 10}, "statistics": _folha_completa()},
             {"team": {"id": 20}, "statistics": _folha_completa()}]
    casa, fora = ler_estatisticas(bruto, 10, 20)
    assert casa["Red Cards"] == 0 and fora["Red Cards"] == 0
    # amarelo 1 + vermelho 0, dos dois lados, com vermelho valendo 2 pontos
    assert total_da_familia(casa, fora, "cards") == 2


def test_motor_ao_vivo_sem_folha_nao_inventa_zero():
    from services.pick_engine_live.live_feed import ler_estatisticas
    bruto = [{"team": {"id": 10}, "statistics": []},
             {"team": {"id": 20}, "statistics": []}]
    assert ler_estatisticas(bruto, 10, 20) == ({}, {})
