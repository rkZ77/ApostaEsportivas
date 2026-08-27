"""Leitura de `player_match_stats` -- a base do Player Stats.

FILTRO DE MINUTOS E' A REGRA PRINCIPAL
--------------------------------------
Uma atuacao de 12 minutos e uma de 90 nao sao a mesma observacao, e tratar as
duas como uma linha de historico e' o jeito mais rapido de subestimar a media
de qualquer contador. Passes e' o caso obvio (um lateral titular faz 60 passes
e o substituto dele faz 8), mas vale pra todos.

O motor NAO normaliza por minuto. Normalizar produziria uma media "por 90" que
depois teria que ser desnormalizada por uma expectativa de minutos que ninguem
tem antes do jogo -- duas aproximacoes onde cabe uma. Em vez disso, o
historico so' conta atuacoes de titular efetivo (MIN_MINUTOS), que e' o regime
em que o jogador vai estar se a aposta fizer sentido.

GOLEIRO E' O CASO ESPECIAL, E JA' ERA
-------------------------------------
`goleiros_conhecidos` mantem o vinculo goleiro->time que o antigo pipeline de
goleiros ja' usava, com a mesma justificativa: sem saber por qual time o
goleiro joga, nao da' pra escolher de qual adversario pegar o volume ofensivo,
e usar o lado errado INVERTE a previsao.

A COMPETICAO E' RECORTE, NAO DETALHE (2026-08-27)
-------------------------------------------------
Ate' aqui `carregar()` lia as 15 ultimas atuacoes do jogador em QUALQUER
competicao e QUALQUER temporada. O mesmo atacante entrava na conta com jogo de
Brasileirao, de Libertadores e da temporada passada, tudo na mesma media.

Isso deixava o motor incoerente DENTRO DO MESMO PICK: `volume_do_adversario`,
logo abaixo, sempre filtrou por `league_id` e `season` -- com a justificativa,
escrita la', de que a media misturada nao descreve nem um caso nem o outro. O
lado do time era recortado e o lado do jogador nao.

E nao e' um recorte novo inventado aqui: e' o MESMO de
`competition_profile.uses_all_competitions_history`, que o lado dos times ja'
usa desde sempre e que decide os dois casos:

  · fixture de LIGA        -> historico daquela liga e temporada. Chute em
                              Brasileirao e chute em Libertadores nao sao a
                              mesma populacao;
  · fixture de COPA/SELECAO -> todas as competicoes da temporada, porque a
                              propria competicao nao acumula jogo suficiente e
                              travar nela reprova a fixture inteira em silencio.

Chamador que nao passar `league_id` continua lendo tudo, que e' o comportamento
antigo -- backtest e teste dependem dele.
"""
from __future__ import annotations

from services.pick_engine import competition_profile

#: Atuacao curta demais nao descreve o regime de titular. 60 minutos e' a
#: fronteira usual de "jogou o jogo" -- quem entrou no segundo tempo fica de
#: fora, quem saiu aos 70 continua.
MIN_MINUTOS = 60

#: Teto de atuacoes lidas por jogador. Igual ao teto de exibicao da amostra
#: (engine_audit.amostra.MAX_JOGOS) multiplicado por uma folga: o motor pode
#: ler mais do que exibe, mas ler a carreira inteira nao melhora a estimativa
#: de um jogador que trocou de time duas vezes.
LIMITE_ATUACOES = 15


def carregar(cur, player_id: int, coluna: str, *, limite: int = LIMITE_ATUACOES,
             min_minutos: int = MIN_MINUTOS,
             league_id: int | None = None, season: int | None = None) -> list[dict]:
    """Atuacoes recentes do jogador com o contador `coluna` publicado.

    `coluna` vem do catalogo de metodos (methods.Metodo.coluna), nunca de
    entrada de usuario -- por isso entra por f-string. A mesma convencao de
    utils/data_br.py.

    `league_id`/`season` sao a competicao da PARTIDA DE HOJE, e o recorte que
    sai deles esta explicado no topo do modulo. Sem `league_id`, le tudo (o
    comportamento anterior a 27/08).
    """
    filtros, params = [], [player_id, min_minutos]
    if league_id is not None:
        # Temporada sempre entra quando ha' recorte, inclusive no caminho
        # multi-competicao: "todas as competicoes" e' sobre COMPETICAO, nunca
        # sobre ANO. Sem isso um jogador com poucos jogos puxaria a temporada
        # passada -- de outro clube, possivelmente de outro pais.
        if season is not None:
            filtros.append("AND season = %s")
            params.append(season)
        if not competition_profile.uses_all_competitions_history(league_id):
            filtros.append("AND league_id = %s")
            params.append(league_id)

    cur.execute(f"""
        SELECT fixture_id, match_date, team_id, team_name, league_id, season,
               minutes, position, {coluna} AS valor
          FROM player_match_stats
         WHERE player_id = %s
           AND {coluna} IS NOT NULL
           AND COALESCE(minutes, 0) >= %s
           {" ".join(filtros)}
      ORDER BY match_date DESC
         LIMIT %s
    """, tuple(params) + (limite,))
    return [dict(r) if not isinstance(r, dict) else r for r in cur.fetchall()]


def composicao(atuacoes: list) -> dict:
    """De onde vieram as atuacoes desta media · pra gravar junto do pick.

    Mesmo papel que `multi_competicao` tem na amostra do time: sem isso, uma
    media tirada de duas competicoes e uma tirada de uma so' sao o mesmo numero
    na tela, e o unico jeito de saber qual e' qual e' reproduzir a consulta.
    """
    ligas = [a.get("league_id") for a in (atuacoes or []) if a.get("league_id")]
    por_liga: dict = {}
    for liga in ligas:
        por_liga[liga] = por_liga.get(liga, 0) + 1
    return {
        "atuacoes": len(atuacoes or []),
        "competicoes": sorted(por_liga),
        "por_competicao": por_liga,
        "multi_competicao": len(por_liga) > 1,
    }


def jogadores_dos_times(cur, team_ids: list, *, posicoes=None,
                        min_atuacoes: int = 3) -> list[dict]:
    """Quem joga por estes times, com quantas atuacoes cada um tem.

    O vinculo jogador->time sai da PROPRIA `player_match_stats` (o time em que
    ele mais atuou recentemente), e nao de um cadastro de elenco: o projeto nao
    tem tabela de elenco, e a folha de jogo e' a fonte que existe e que ja'
    provou funcionar no pipeline de goleiros.

    `posicoes` restringe por cargo ("G" pra goleiro). Vazio traz todos.
    """
    if not team_ids:
        return []

    filtro_posicao, params_posicao = "", []
    if posicoes:
        filtro_posicao = "AND p.position = ANY(%s)"
        params_posicao = [list(posicoes)]

    cur.execute(f"""
        WITH recentes AS (
            SELECT p.player_id, p.player_name, p.team_id, p.team_name, p.position,
                   COUNT(*) AS atuacoes,
                   MAX(p.match_date) AS ultima
              FROM player_match_stats p
             WHERE p.team_id = ANY(%s)
               AND COALESCE(p.minutes, 0) >= %s
               {filtro_posicao}
             GROUP BY p.player_id, p.player_name, p.team_id, p.team_name, p.position
        )
        SELECT * FROM (
            SELECT r.*,
                   -- Um jogador pode aparecer por dois times na base (foi
                   -- transferido). Fica o time em que ele atuou MAIS
                   -- recentemente: e' o unico dos dois que ele pode
                   -- representar na partida de hoje.
                   ROW_NUMBER() OVER (PARTITION BY r.player_id
                                      ORDER BY r.ultima DESC, r.atuacoes DESC) AS ordem
              FROM recentes r
        ) x
        WHERE x.ordem = 1 AND x.atuacoes >= %s
    """, (list(team_ids), MIN_MINUTOS, *params_posicao, min_atuacoes))
    return [dict(r) if not isinstance(r, dict) else r for r in cur.fetchall()]


def volume_do_adversario(cur, team_id: int, coluna: str, mando: str,
                         league_id, season, *, limite: int = 10) -> tuple:
    """(media, amostra) do volume que o adversario produz, NO MANDO de hoje.

    E' o sinal forte dos metodos que dependem do outro time -- defesas de
    goleiro acima de tudo. O recorte por mando nao e' detalhe: mandante e
    visitante produzem chute no alvo em taxas diferentes, e a media misturada
    nao descreve nem um caso nem o outro.

    `coluna` e' o sufixo da folha de time em match_statistics
    (`home_shots_on` / `away_shots_on`), montado a partir do catalogo.
    """
    lado = "home" if mando == "home" else "away"
    coluna_time = f"{lado}_{coluna}"
    coluna_id = f"{lado}_team_id"

    filtro_liga, params_liga = "", []
    if league_id and season:
        filtro_liga = "AND ms.league_id = %s AND ms.season = %s"
        params_liga = [league_id, season]

    cur.execute(f"""
        SELECT ms.{coluna_time} AS valor
          FROM match_statistics ms
         WHERE ms.{coluna_id} = %s
           AND ms.status IN ('FT','AET','PEN')
           AND ms.{coluna_time} IS NOT NULL
           {filtro_liga}
      ORDER BY ms.match_date DESC
         LIMIT %s
    """, (team_id, *params_liga, limite))
    valores = [float(r["valor"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()]
    if not valores:
        return (None, 0)
    return (round(sum(valores) / len(valores), 3), len(valores))
