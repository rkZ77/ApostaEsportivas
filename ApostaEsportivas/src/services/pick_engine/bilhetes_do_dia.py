"""Pernas que os BILHETES do dia ja' consumiram.

O PROBLEMA (achado do usuario, 2026-09-10)
------------------------------------------
Cada produto de bilhete cruzava as pernas contra picks_vip/picks_free, mas nao
contra os OUTROS bilhetes. O bingo entao podia repetir a entrada exata que a
multipla ja' tinha publicado -- e a decisao antiga dizia isso em voz alta
("a multipla NAO entra nesta consulta"), com o argumento de nao esvaziar o
pool em dia curto.

O argumento nao se sustenta no risco: bilhete e' tudo ou nada. A mesma perna
em dois bilhetes nao dobra a exposicao como dois picks avulsos dobram -- ela
derruba os DOIS bilhetes inteiros de uma vez, junto com as outras 5 ou 6
pernas que nada tinham a ver. Quem seguiu os dois produtos perde os dois no
mesmo minuto, achando que tinha diversificado.

A regra passa a ser: perna que ja' esta dentro de um bilhete do dia nao entra
noutro. O escopo e' (fixture_id, correlation_group) -- o mesmo veto que cada
bilhete ja' usa dentro de si mesmo, e o mesmo que a alavancagem usa contra o
VIP: familia repetida em OUTRA partida continua liberada, senao nenhum bilhete
fecharia.

A ordem de execucao (main.py) e' VIP -> Dica -> Multipla -> Bingo ->
Alavancagem, entao cada produto ja' encontra gravado o que veio antes dele.
"""

from __future__ import annotations

import json

from services.pick_engine import ranking


#: (tabela, formato). `cartela` guarda as pernas num JSONB `games`;
#: `colunas` espalha em fixture_id_1..3 (ver pick_legs_extractor, que
#: documenta o mesmo desalinhamento historico).
_TABELAS = (
    ("picks_multiplas", "cartela"),
    ("picks_bingo", "cartela"),
    ("picks_alavancagem", "colunas"),
)


def _pares_de_cartela(cur, tabela: str, hoje_sql: str) -> set:
    pares = set()
    cur.execute(f"SELECT games FROM {tabela} WHERE match_date = {hoje_sql}")
    for (games_raw,) in cur.fetchall():
        if not games_raw:
            continue
        games = games_raw if isinstance(games_raw, list) else json.loads(games_raw)
        for g in games:
            fid, mt = g.get("fixture_id"), g.get("market_type")
            if fid and mt:
                pares.add((fid, ranking.correlation_group(mt)))
    return pares


def _pares_de_colunas(cur, tabela: str, hoje_sql: str) -> set:
    pares = set()
    cur.execute(f"""
        SELECT fixture_id_1, market_type_1, fixture_id_2, market_type_2,
               fixture_id_3, market_type_3
        FROM {tabela} WHERE match_date = {hoje_sql}
    """)
    for row in cur.fetchall():
        for i in (0, 2, 4):
            fid, mt = row[i], row[i + 1]
            if fid and mt:
                pares.add((fid, ranking.correlation_group(mt)))
    return pares


def pares_em_bilhetes(cur, hoje_sql: str, exceto: tuple = ()) -> set:
    """{(fixture_id, correlation_group)} ja' dentro de um bilhete de hoje.

    `exceto` pula a propria tabela de quem chama -- o produto ja' cuida da
    exclusividade dentro do dia dele. Tabela que ainda nao existe no banco nao
    derruba o motor: o bilhete nao sair por causa de um SELECT quebrado seria
    trocar um risco por outro pior.
    """
    pares = set()
    for tabela, formato in _TABELAS:
        if tabela in exceto:
            continue
        try:
            if formato == "cartela":
                pares |= _pares_de_cartela(cur, tabela, hoje_sql)
            else:
                pares |= _pares_de_colunas(cur, tabela, hoje_sql)
        except Exception as e:
            # Rollback: no psycopg um erro deixa a transacao abortada e
            # TODA consulta seguinte falha ate' alguem limpar.
            print(f"[BILHETES_DO_DIA] Nao consegui ler {tabela}: {e}")
            try:
                cur.connection.rollback()
            except Exception:
                pass
    return pares
