"""O baseline da liga -- pra onde a frequencia de um time encolhe.

POR QUE MEDIDO, E NAO CONSTANTE
-------------------------------
O encolhimento puxa a frequencia observada na direcao do "normal". Se o
normal for uma constante global, um time de 4 jogos no Brasileirao e um de 4
jogos na Eredivisie encolhem pro mesmo lugar -- e as duas ligas nao produzem
gol na mesma taxa. A constante fica como reserva, pra liga sem amostra.

E' a mesma escolha que o motor ao vivo ja' faz em `baselines_por_liga`: uma
consulta, zero API, e o rastro registra qual das duas fontes foi usada.

UMA CONSULTA POR LIGA, NAO POR JOGO
-----------------------------------
O pipeline percorre varios jogos da MESMA liga. Sem o cache de processo, cada
fixture repetiria a mesma agregacao sobre `match_statistics`. Mesmo padrao de
`competition_rules_store` e `league_profile_store`.
"""
from __future__ import annotations

import logging

from services.pick_engine_boost import config as cfg

logger = logging.getLogger(__name__)

_cache: dict = {}

#: O que o motor usa quando a liga nao tem amostra. Declarados.
GLOBAL = {
    "over15_ft": cfg.BASELINE_OVER15_FT,
    "under25_ht": cfg.BASELINE_UNDER25_HT,
    "par": cfg.BASELINE_PAR,
    "gols_ht": cfg.BASELINE_GOLS_HT,
    "fonte": "global",
    "n": 0,
}


def limpar_cache() -> None:
    _cache.clear()


def da_liga(cur, league_id) -> dict:
    """Frequencias reais da liga nos ultimos 400 dias.

    Devolve SEMPRE um dicionario utilizavel: se a liga nao tem jogos com
    placar de intervalo suficientes, volta o global com `fonte` dizendo isso.
    Nenhum chamador precisa tratar None, que e' o caminho por onde baseline
    ausente viraria zero em algum lugar.
    """
    if league_id in _cache:
        return _cache[league_id]
    saida = dict(GLOBAL)
    if league_id:
        try:
            cur.execute("""
                SELECT COUNT(*)                                                  AS n,
                       AVG(CASE WHEN (home_goals + away_goals) >= 2
                                THEN 1.0 ELSE 0.0 END)::float                    AS over15,
                       AVG(CASE WHEN (home_goals_ht + away_goals_ht) <= 2
                                THEN 1.0 ELSE 0.0 END)::float                    AS under25ht,
                       AVG(CASE WHEN (home_goals + away_goals) >= 2
                                 AND (home_goals_ht + away_goals_ht) <= 2
                                THEN 1.0 ELSE 0.0 END)::float                    AS par,
                       AVG(home_goals_ht + away_goals_ht)::float                 AS gols_ht
                  FROM match_statistics
                 WHERE league_id = %s
                   AND status IN ('FT', 'AET', 'PEN')
                   AND home_goals IS NOT NULL AND away_goals IS NOT NULL
                   AND home_goals_ht IS NOT NULL AND away_goals_ht IS NOT NULL
                   AND match_date >= NOW() - INTERVAL '400 days'
            """, (league_id,))
            linha = cur.fetchone()
        except Exception as e:  # consulta de baseline nunca derruba o motor
            logger.warning("baseline da liga %s falhou: %s", league_id, e)
            linha = None
        n = int(linha[0]) if linha and linha[0] else 0
        if n >= cfg.MIN_JOGOS_BASELINE_LIGA and linha[1] is not None:
            saida = {
                "over15_ft": round(float(linha[1]), 4),
                "under25_ht": round(float(linha[2]), 4),
                "par": round(float(linha[3]), 4),
                "gols_ht": round(float(linha[4]), 3),
                "fonte": "liga",
                "n": n,
            }
        else:
            saida = {**GLOBAL, "n": n}
    _cache[league_id] = saida
    return saida
