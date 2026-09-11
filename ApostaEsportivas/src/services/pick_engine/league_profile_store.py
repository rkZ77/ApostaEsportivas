"""O parecer da liga, lido do banco para o gate de IA.

POR QUE ELE NAO VIRA NUMERO NO MOTOR
------------------------------------
O perfil e' PROSA: "tendencia de gols, de BTTS, de cartoes, de escanteios,
volatilidade" (ver LEAGUE_ANALYSIS_PROMPT). E os numeros que o texto descreve o
motor ja' le' direto do banco, com precisao e sem IA -- sao `baselines_por_liga`
e as medias de `team_statistics`, as mesmas que alimentaram o proprio prompt.

Entao ligar isto na projecao seria trocar um numero auditavel por uma opiniao
que muda entre duas chamadas iguais. E' exatamente o que a docstring de
`competition_rules_store` ja' recusou pro contexto de partida, e a recusa vale
igual aqui.

ONDE ELE ENTRA, E POR QUE ALI
-----------------------------
No GATE DE IA (`ai_review`), que e' onde a IA ja' atua e onde ela SO' VETA --
nunca define o pick. O revisor recebe o perfil junto do resto do payload e pode
usar a tendencia da liga pra sustentar um veto que ja' faria; ele nao ganha
poder novo, ganha contexto.

Isso mantem as tres propriedades que fazem o regulamento por IA valer a pena:

  1. E' por LIGA E TEMPORADA, nao por partida. Uma resposta serve o ano inteiro.
  2. E' ESTAVEL. O comportamento de uma liga nao vira do avesso no meio do ano.
  3. Sai FORA do laco de pick: quem gera e' `atualizar_ligas.py`, sob demanda.
     O motor so' LE esta tabela.

E o custo de errar e' baixo por construcao: o gate falha aberto, entao perfil
ausente nao segura pick nenhum -- devolve None e o payload vai sem ele.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Cache de processo, mesmo motivo do `competition_rules_store`: o pipeline
#: percorre varias fixtures da MESMA liga, e sem isto cada uma faria a mesma
#: consulta pra receber o mesmo texto.
_cache: dict[tuple, str | None] = {}


def limpar_cache() -> None:
    _cache.clear()


def perfil_da_liga(league_id, season=None) -> str | None:
    """O parecer da liga, com conexao propria.

    SEM `season` PEGA A MAIS RECENTE, e e' o caminho normal: quem chama e' o
    gate de IA, que recebe o `fixture` montado por cada pipeline -- e nem todos
    carregam a temporada ali. Uma consulta por liga POR EXECUCAO graças ao
    cache abaixo; o pipeline percorre varias fixtures da mesma liga.
    """
    if league_id is None:
        return None
    chave = (int(league_id), str(season) if season is not None else "*")
    if chave in _cache:
        return _cache[chave]

    texto = None
    conn = None
    try:
        from utils.db_utils import get_connection
        conn = get_connection()
        cur = conn.cursor()
        if season is None:
            cur.execute("""
                SELECT analysis_text FROM league_analysis
                 WHERE league_id = %s
                 ORDER BY season DESC LIMIT 1;
            """, (chave[0],))
        else:
            cur.execute("""
                SELECT analysis_text FROM league_analysis
                 WHERE league_id = %s AND season::text = %s
                 LIMIT 1;
            """, (chave[0], chave[1]))
        linha = cur.fetchone()
        if linha:
            texto = (linha[0] or "").strip() or None
        cur.close()
    except Exception as e:
        # Inclui "tabela nao existe", que e' o estado de todo banco onde
        # `atualizar_ligas` nunca rodou -- ou seja, o estado normal hoje.
        logger.debug("[LEAGUE_PROFILE] sem parecer para %s: %s", league_id, str(e)[:120])
        texto = None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    _cache[chave] = texto
    return texto


def perfil_com_cursor(cur, league_id, season) -> str | None:
    """O texto do parecer, ou None quando nao ha' (o normal ate' alguem rodar
    `atualizar_ligas`).

    Nunca levanta: tabela ausente, coluna faltando ou banco recusando viram
    None. Este e' um enfeite de contexto pro gate -- derrubar a geracao de pick
    por causa dele seria trocar um pick por um paragrafo.
    """
    if league_id is None or season is None:
        return None
    chave = (int(league_id), str(season))
    if chave in _cache:
        return _cache[chave]

    texto = None
    try:
        cur.execute("""
            SELECT analysis_text
              FROM league_analysis
             WHERE league_id = %s AND season::text = %s
             LIMIT 1;
        """, (chave[0], chave[1]))
        linha = cur.fetchone()
        if linha:
            texto = (linha[0] or "").strip() or None
    except Exception as e:
        # Inclui o caso "tabela nao existe", que e' o estado de qualquer banco
        # onde `atualizar_ligas` nunca rodou.
        logger.debug("[LEAGUE_PROFILE] sem parecer para %s/%s: %s",
                     league_id, season, str(e)[:120])
        texto = None

    _cache[chave] = texto
    return texto
