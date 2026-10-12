"""DDL de auto-provisionamento que NAO trava o site (11/10/2026).

O PROBLEMA ("quando rodo o Atualizar Jogos o banco do site cai")
-----------------------------------------------------------------
Os coletores garantem as proprias colunas ao abrir, com `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`. O IF NOT EXISTS tira o EFEITO, mas nao o PEDIDO de
lock: todo ALTER TABLE pede ACCESS EXCLUSIVE, que nao convive nem com leitura.
O coletor de estatistica fazia ~25 deles em `match_statistics` -- a tabela que
o site mais le' -- numa transacao so', sem `lock_timeout`.

Basta o site ter uma consulta aberta na tabela pro ALTER entrar na fila; e na
fila, TODA leitura que chega depois fica atras dele. As conexoes do pool do
site vao ficando presas esperando, o pool esgota, e o site para de responder
com o banco de pe'. E' o mesmo defeito que `engine_pipelines/decision_log.py`
corrigiu em 05/09 (leitura de 0,2s levando 118s, medido em DEV) -- so' que
corrigido la' e nao nos coletores.

A REGRA
-------
1. Pergunta ao catalogo antes (information_schema / to_regclass): sem lock.
2. Roda SO' o que falta. Num banco em dia -- toda execucao depois da primeira
   -- nenhum DDL e' emitido e o site nao sente o coletor.
3. O que precisar rodar, roda com `lock_timeout` de 3s: desiste em vez de
   enfileirar o site atras dele.
"""
from __future__ import annotations

import re

LOCK_TIMEOUT = "3s"

_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(?P<tabela>\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(?P<coluna>\w+)",
    re.I)
_CREATE_INDEX = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+(?P<nome>\w+)", re.I)
_CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(?P<nome>\w+)", re.I)
_DROP_INDEX = re.compile(r"DROP\s+INDEX\s+IF\s+EXISTS\s+(?P<nome>\w+)", re.I)
_DROP_CONSTRAINT = re.compile(
    r"ALTER\s+TABLE\s+(?P<tabela>\w+)\s+DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+(?P<nome>\w+)", re.I)


def _existe_restricao(cur, tabela: str, nome: str) -> bool:
    cur.execute("""SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname = %s AND c.conname = %s""", (tabela, nome))
    return cur.fetchone() is not None


def _valor(linha):
    if linha is None:
        return None
    return list(linha.values())[0] if isinstance(linha, dict) else linha[0]


def _existe_relacao(cur, nome: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{nome}",))
    return bool(_valor(cur.fetchone()))


def _colunas(cur, tabela: str, cache: dict) -> set:
    if tabela not in cache:
        cur.execute("""SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s""", (tabela,))
        cache[tabela] = {_valor(r) for r in cur.fetchall()}
    return cache[tabela]


def faltando(cur, comandos) -> list[str]:
    """Os comandos que ainda tem efeito. Nao pega lock nenhum."""
    cache: dict = {}
    pendentes = []
    for sql in comandos:
        texto = " ".join(str(sql).split())
        m = _ADD_COLUMN.search(texto)
        if m:
            if m["coluna"].lower() not in {c.lower() for c in _colunas(cur, m["tabela"], cache)}:
                pendentes.append(sql)
            continue
        m = _DROP_CONSTRAINT.search(texto)
        if m:
            if _existe_restricao(cur, m["tabela"], m["nome"]):
                pendentes.append(sql)
            continue
        m = _DROP_INDEX.search(texto)
        if m:
            if _existe_relacao(cur, m["nome"]):
                pendentes.append(sql)
            continue
        m = _CREATE_INDEX.search(texto) or _CREATE_TABLE.search(texto)
        if m:
            if not _existe_relacao(cur, m["nome"]):
                pendentes.append(sql)
            continue
        pendentes.append(sql)   # DDL que nao sei checar: roda (com o timeout)
    return pendentes


def garantir(cur, comandos) -> int:
    """Roda so' o DDL que falta, com lock_timeout. Devolve quantos rodaram.

    Nao faz commit: quem chama ja' comita (o comportamento de antes). Se o lock
    nao vier em 3s o erro sobe -- rapido, em vez de travar o site.
    """
    pendentes = faltando(cur, comandos)
    if pendentes:
        cur.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        for sql in pendentes:
            cur.execute(sql)
    return len(pendentes)


def ddl(cur, sql: str) -> int:
    """Um comando so' · troca direta de `cur.execute(<DDL>)` nos setups."""
    return garantir(cur, [sql])
