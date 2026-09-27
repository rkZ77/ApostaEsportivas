"""Registra sozinho, a cada deploy de producao, a mudanca que subiu (2026-09-27).

Pedido do usuario: registrar TODA mudanca do motor pra ver como ficou depois.
Cadastro a mao esquece; o deploy nao. O Railway expoe no container a mensagem
e o hash do commit que subiu (RAILWAY_GIT_COMMIT_MESSAGE / _SHA), e o merge
pra `main` deste projeto ja' descreve a mudanca ("merge: <o que mudou> vai pra
producao"). A primeira linha vira o titulo em motor_mudancas, com a data do dia.

So' no ambiente `production`: o noprod aponta pro MESMO banco e registraria a
mesma mudanca antes dela chegar ao assinante. Commit que nao e' merge (hotfix
direto) nao entra -- ai' o registro e' manual, pelo /admin. Deploy que nao
mexeu em motor tambem entra; o /admin tem o botao de remover.
"""
from __future__ import annotations

import os
import re

_PREFIXO = re.compile(r"^merge\s*:\s*", re.IGNORECASE)
_SUFIXO = re.compile(r"\s+(vai|vao|vão)\s+(pra|para)\s+produ[cç][aã]o\s*\.?$", re.IGNORECASE)


def titulo_do_merge(mensagem: str | None) -> str | None:
    """Titulo legivel a partir da mensagem do merge, ou None se nao for merge."""
    if not mensagem:
        return None
    primeira = mensagem.strip().splitlines()[0].strip()
    if not _PREFIXO.match(primeira):
        return None
    titulo = _SUFIXO.sub("", _PREFIXO.sub("", primeira)).strip()
    if not titulo:
        return None
    return titulo[0].upper() + titulo[1:]


def registrar(get_connection, logger) -> bool:
    if (os.getenv("RAILWAY_ENVIRONMENT_NAME") or "").lower() != "production":
        return False
    titulo = titulo_do_merge(os.getenv("RAILWAY_GIT_COMMIT_MESSAGE"))
    if not titulo:
        return False
    sha = (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:8]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO motor_mudancas (dia, titulo, descricao)
            VALUES (CURRENT_DATE, %s, %s)
            ON CONFLICT (dia, titulo) DO NOTHING
        """, (titulo[:300], f"Registrado sozinho no deploy ({sha})." if sha else "Registrado sozinho no deploy."))
        conn.commit()
        logger.info("[DEPLOY] mudanca registrada: %s", titulo)
        return True
    except Exception as e:
        conn.rollback()
        logger.warning("[DEPLOY] registro da mudanca falhou: %s", e)
        return False
    finally:
        cur.close()
        conn.close()
