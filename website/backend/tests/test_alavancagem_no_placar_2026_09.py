"""A alavancagem entra no placar publico pela conta DELA.

De 19/08 a 04/09 ela valeu zero. O zero nunca foi desprezo pelo produto: era a
falta da conta certa. Somar o `profit` perna a perna, como o UNION faz com todo
o resto, descreve seis entradas independentes de 1u num produto onde existe
UMA -- nos dados de PROD de 04/09, +14,6u pela soma ingenua contra os +42,9u
que o caminho de fato rendeu.

A conta certa ja' existia na banca de quem apostou (`_alav_unidades`). Este
modulo e' ela aplicada aos picks publicados, e o que os casos daqui protegem
sao as quatro coisas que, erradas, dao um numero plausivel e falso:

  1. o RED custa a ENTRADA, nao o saldo acumulado. Cair no sexto passo com o
     dinheiro multiplicado por cinco custa 1u, igual a cair no primeiro;
  2. caminho ABERTO vale zero. Composto em andamento nao e' dinheiro;
  3. lucro e stake andam JUNTOS -- 1u de stake por caminho FECHADO. Mexer no
     lucro sem mexer na stake faz o ROI saltar por um fator que nao existe;
  4. o recorte de data vem DEPOIS do caminho. Pedir "agosto" nao pode
     recomecar a contagem no dia 1o.
"""
import re

import alavancagem_caminho
from stake_plan import STAKE_PADRAO, conta_em_unidades


# ── a regra do produto ────────────────────────────────────────────────────
def test_a_meta_tem_um_dono_so():
    """Ate' 04/09 ela morava em banca.py. Com o placar contando tambem, duas
    copias viravam dois produtos com o mesmo nome no primeiro ajuste."""
    from routers import banca
    assert banca.ALAV_META_PADRAO is alavancagem_caminho.META_PADRAO


def test_um_pick_sozinho_continua_sem_peso():
    """`STAKE_PADRAO` responde "quanto vale UM pick", e um passo de caminho nao
    vale nada sozinho. Nao e' a mesma pergunta que "a fonte entra no placar"."""
    assert STAKE_PADRAO["alavancagem"] == 0
    assert not conta_em_unidades("alavancagem")


# ── a conta, lida no SQL ──────────────────────────────────────────────────
def _sql():
    return " ".join(alavancagem_caminho.subquery_dos_caminhos().split())


def test_o_red_custa_a_entrada_e_nao_o_saldo():
    """-1u fixo, e nao `saldo - 1`. Um caminho que ja' multiplicou o dinheiro
    por cinco e leva RED no sexto passo perde a entrada, nao os cinco."""
    sql = _sql()
    assert "CASE WHEN encerra THEN ROUND(saldo - 1, 4) ELSE 0 END" in sql
    # RED zera o saldo (multiplicador 0), entao `saldo - 1` = -1 sozinho.
    assert re.search(r"ELSE 0\s+END AS mult", sql) or "ELSE 0 END AS mult" in sql


def test_passo_de_caminho_aberto_nao_rende_nada():
    sql = _sql()
    assert "CASE WHEN encerra THEN 1 ELSE 0 END::numeric AS caminho_stake" in sql


def test_lucro_e_stake_saem_da_mesma_condicao():
    """A regra 1 de stake_plan: os dois andam juntos ou o ROI mente."""
    sql = _sql()
    lucro = re.search(r"CASE WHEN (\w+) THEN ROUND\(saldo", sql)
    stake = re.search(r"CASE WHEN (\w+) THEN 1 ELSE 0 END::numeric AS caminho_stake", sql)
    assert lucro and stake and lucro.group(1) == stake.group(1) == "encerra"


def test_a_meta_fecha_o_caminho():
    assert f">= {alavancagem_caminho.META_PADRAO}" in _sql()


def test_o_multiplicador_segue_a_matematica_do_projeto():
    """Mesma tabela de settlement.py: GREEN paga a odd, PUSH devolve, meia
    vitoria paga metade do lucro, meia derrota devolve metade."""
    sql = _sql()
    for termo in ("WHEN 'GREEN'", "WHEN 'HALF-WIN'", "WHEN 'HALF-LOSS'", "WHEN 'PUSH'"):
        assert termo in sql, termo


# ── o encaixe no placar ───────────────────────────────────────────────────
def test_o_recorte_de_data_vem_depois_do_caminho():
    """O caminho e' construido sobre a tabela INTEIRA. Filtrar antes
    recomecaria a contagem no primeiro dia do recorte e inventaria um caminho
    que nunca existiu."""
    from routers import public
    sql = public._sub_alav("AND TO_CHAR(match_date, 'YYYY-MM') = %s")
    interno = sql[sql.index("WITH RECURSIVE"):sql.index("cam ON cam.pick_id")]
    assert "TO_CHAR" not in interno
    assert "TO_CHAR" in sql


def test_o_placar_le_o_caminho_e_nao_o_profit_da_linha():
    from routers import public
    sql = public._sub_alav("")
    assert "cam.caminho_profit" in sql and "cam.caminho_stake" in sql
    assert "pa.profit" not in sql


def test_a_fonte_continua_no_historico():
    """Peso proprio nao pode virar remocao: os picks continuam aparecendo, com
    resultado, na quebra por fonte e na taxa de acerto."""
    from routers import public
    sql = public._sub_alav("")
    assert "'alavancagem' AS source" in sql
    assert "pa.result" in sql
    assert "pa.home_team_1" in sql


def test_a_subquery_e_fechada_em_parenteses():
    """Ela entra num ramo de UNION ALL, e `WITH` solto ali e' erro de sintaxe.
    Dentro de um `FROM (...)` e' valido -- e foi assim que a primeira versao
    quebrou."""
    bruto = alavancagem_caminho.subquery_dos_caminhos().strip()
    assert bruto.startswith("(") and bruto.endswith(")")
    assert "WITH RECURSIVE" in bruto
