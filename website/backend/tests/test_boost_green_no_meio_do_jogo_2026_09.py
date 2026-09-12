"""O Pick Boost fecha com a bola rolando, como os outros produtos.

O QUE ACONTECIA
---------------
O Boost era o UNICO produto que esperava o apito final. O bloco dele em
`resolve_all_pending` comecava com `if status in FT_STATUSES` e nao olhava
mais nada antes disso.

Todos os outros ja' fechavam cedo: VIP, free, ao vivo, faltas e as pernas de
multipla, bingo e alavancagem passam por `_locked_leg_result`, que chama
`_travado_antes_do_apito` assim que o contador passa o teto da linha. Por isso
o usuario via o pick VIP de um jogo fechado como GREEN enquanto o Boost do
MESMO jogo seguia "Pendente".

A REGRA, E POR QUE ELA NAO E' CHUTE
-----------------------------------
As duas pernas sao de linha fixa: Over 1.5 no jogo e Under 2.5 no primeiro
tempo. Gol nao desmarca, entao contador de gol so' SOBE -- e e' isso que
torna cada conclusao abaixo definitiva, nao uma previsao:

  Over 1.5 FT   2 gols        -> GREEN em qualquer minuto
                <= 1 gol      -> so' no apito (ainda da' tempo)
  Under 2.5 HT  3 gols no 1T  -> RED na hora, e o BILHETE inteiro cai junto
                <= 2 no fim do 1T -> GREEN
                <= 2 durante o 1T -> nada ainda (cabe o terceiro)

E' o mesmo raciocinio de `settlement.settle_over_under_com_piso`: um piso so'
autoriza a conclusao que o desconhecido nao pode desfazer.
"""
import inspect

from routers import live


# ── As quatro decisoes da regra ──────────────────────────────────────────────

def test_segundo_gol_fecha_a_perna_do_jogo_no_ato():
    """2 gols aos 30' ja' e' Over 1.5. Sair o terceiro nao muda nada."""
    res_ft, _ = live._pernas_do_boost("1H", gols_agora=2, gols_1t=2)
    assert res_ft == "GREEN"


def test_um_gol_so_nao_fecha_nada_antes_do_apito():
    """Over 1.5 com 1 gol nao e' RED: falta jogo pra sair o segundo."""
    res_ft, res_ht = live._pernas_do_boost("2H", gols_agora=1, gols_1t=1)
    assert res_ft is None
    assert res_ht == "GREEN"   # o 1T acabou com 1, essa perna ja' era


def test_terceiro_gol_no_primeiro_tempo_perde_na_hora():
    """3 no 1T estoura o Under 2.5 HT, e o quarto so' confirma."""
    _, res_ht = live._pernas_do_boost("1H", gols_agora=3, gols_1t=3)
    assert res_ht == "RED"


def test_dois_gols_no_primeiro_tempo_ainda_nao_e_green():
    """2 gols aos 20' ainda comportam o terceiro antes do intervalo."""
    _, res_ht = live._pernas_do_boost("1H", gols_agora=2, gols_1t=2)
    assert res_ht is None


def test_intervalo_fecha_a_perna_do_primeiro_tempo():
    """No apito do 1T o placar daquele tempo nao muda mais."""
    for status in ("HT", "2H", "ET", "FT"):
        _, res_ht = live._pernas_do_boost(status, gols_agora=2, gols_1t=2)
        assert res_ht == "GREEN", status


def test_o_bilhete_inteiro_fecha_quando_as_duas_travam():
    """1T terminou com 2 e o segundo gol ja' saiu: GREEN antes do apito."""
    res_ft, res_ht = live._pernas_do_boost("2H", gols_agora=2, gols_1t=2)
    assert (res_ft, res_ht) == ("GREEN", "GREEN")


def test_sem_placar_nao_afirma_nada():
    """Estatistica ausente nunca vira zero (invariante 1 do settlement)."""
    assert live._pernas_do_boost("1H", None, None) == (None, None)


# ── As cercas que o bloco da varredura precisa manter ────────────────────────

def _bloco_do_boost() -> str:
    fonte = inspect.getsource(live.resolve_all_pending)
    ini = fonte.index("── PICK BOOST")
    fim = fonte.index("── ANULACAO POR FALTA DE ESTATISTICA", ini)
    return fonte[ini:fim]


def test_a_perna_que_nao_travou_nao_e_inventada():
    """Com o HT em RED, `result_ft` fica como esta' -- inclusive NULL.

    A coluna existe pra responder QUAL perna quebrou. Preenche-la com "RED"
    so' porque o bilhete caiu transforma a unica fonte dessa resposta em
    ruido: um mes de Boost vermelho deixaria de distinguir o modelo de gols do
    jogo do modelo de primeiro tempo.
    """
    bloco = _bloco_do_boost()
    assert 'elif res_ht == "RED":' in bloco
    depois = bloco[bloco.index('elif res_ht == "RED":'):]
    trecho = depois[:depois.index("elif res_ft")]
    assert 'res_ft = res_ft or "RED"' not in trecho


def test_no_apito_as_duas_pernas_fecham():
    """Encerrado, o que nao travou antes cai no lado que sobrou."""
    bloco = _bloco_do_boost()
    assert 'res_ft = res_ft or "RED"' in bloco
    assert 'res_ht = res_ht or "GREEN"' in bloco


def test_sem_os_dois_numeros_continua_pendente():
    """A invariante de 05/08 segue de pe': ausencia nunca vira zero."""
    bloco = _bloco_do_boost()
    assert "if gols_agora is None or gols_1t is None:" in bloco


def test_a_folha_nao_e_consultada_com_o_jogo_rolando():
    """`match_statistics` descreve jogo encerrado.

    Ela e' preenchida pelo `stats_sweep`, que nao acompanha partida em
    andamento. Usa-la como segunda chance no meio do jogo misturaria um
    retrato velho com o placar de agora.
    """
    bloco = _bloco_do_boost()
    assert "if folha_fechada and status not in LIVE_STATUSES:" in bloco


def test_prorrogacao_continua_liquidando_pelos_90():
    """AET/PEN le' `score.fulltime`, como o resto do site."""
    bloco = _bloco_do_boost()
    assert 'if status in ("AET", "PEN") else gols' in bloco
