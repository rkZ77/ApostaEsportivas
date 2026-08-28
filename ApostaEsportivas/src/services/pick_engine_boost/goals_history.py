"""Historico de GOLS -- inteiro e do primeiro tempo -- pro Pick Boost.

POR QUE UM LEITOR PROPRIO, E NAO MatchStatsService
--------------------------------------------------
O Pick Boost precisa de duas colunas que nenhum leitor existente devolve:
`home_goals_ht` e `away_goals_ht`. Elas estao em `match_statistics` desde
sempre (o collector as grava, ver match_statistics_sync_service), mas
`get_all_matches_full` nao as seleciona -- e ela e' a funcao que alimenta o
motor Pre Live, que esta' congelado. Acrescentar coluna la' seria mexer no
caminho de leitura do Pre Live por conveniencia deste motor.

O recorte de competicao e' o MESMO do Pre Live, e isso nao e' coincidencia: e'
a regra do projeto, nao preferencia de um motor. Liga -> so' aquela liga e
temporada; copa de clube e selecao -> todas as competicoes, porque a propria
competicao nao acumula jogo suficiente e travar nela reprova a partida inteira
em silencio (competition_profile.uses_all_competitions_history).

`structural_change_date` tambem e' respeitado: jogo anterior a uma troca de
tecnico/elenco marcada nao descreve o time de hoje.
"""
from __future__ import annotations

from services.pick_engine import competition_profile as cp
from utils.db_utils import linhas_dict

#: Teto de jogos lidos por time. Dez e' o recorte principal que o metodo
#: declara analisar; catorze da folga pra o corte por mando ainda sobrar
#: amostra util (um time tem ~metade dos jogos em cada mando).
LIMITE_JOGOS = 14

#: So' jogo terminado entra. Adiado/interrompido com linha gravada traz o que
#: estiver na folha, que num modelo de gols e' zero -- e zero por ausencia de
#: dado e' o erro que ja' gravou RED num pick GREEN em 05/08.
STATUS_FIM = ("FT", "AET", "PEN")

_COLUNAS = """
    ms.fixture_id, ms.match_date, ms.league_id, ms.season, ms.status,
    ms.home_team_id, ms.away_team_id,
    ms.home_goals, ms.away_goals, ms.total_goals,
    ms.home_goals_ht, ms.away_goals_ht
"""


def _nome_do_adversario(team_id_col: str) -> str:
    return f"(SELECT t.name FROM teams t WHERE t.team_id = {team_id_col})"


def carregar(cur, team_id: int, league_id, season, *, since_date=None,
             limite: int = LIMITE_JOGOS) -> list[dict]:
    """Ultimos jogos do time, com gols de FT e de HT.

    Devolve do mais recente pro mais antigo -- a mesma ordem de todo leitor de
    historico do projeto, e a ordem que `amostra.do_time` assume ao fatiar os
    dez primeiros pra exibicao.
    """
    todas_competicoes = cp.uses_all_competitions_history(league_id)

    filtros = ["(ms.home_team_id = %s OR ms.away_team_id = %s)",
               f"ms.status IN {STATUS_FIM}"]
    params: list = [team_id, team_id]
    if not todas_competicoes:
        filtros.append("ms.league_id = %s AND ms.season = %s")
        params += [league_id, season]
    if since_date:
        filtros.append("ms.match_date >= %s")
        params.append(since_date)

    cur.execute(f"""
        SELECT {_COLUNAS},
               CASE WHEN ms.home_team_id = %s
                    THEN {_nome_do_adversario('ms.away_team_id')}
                    ELSE {_nome_do_adversario('ms.home_team_id')}
               END AS opponent_name
          FROM match_statistics ms
         WHERE {' AND '.join(filtros)}
      ORDER BY ms.match_date DESC
         LIMIT %s
    """, (team_id, *params, limite))

    jogos = linhas_dict(cur)
    # Gol e' o unico contador deste motor: linha sem o placar de FT nao serve
    # pra nada aqui e so' inflaria a contagem de amostra.
    return [j for j in jogos
            if j.get("home_goals") is not None and j.get("away_goals") is not None]


def com_ht(jogos: list[dict]) -> list[dict]:
    """So' os jogos que tem o placar do INTERVALO publicado.

    Separado de proposito: a cobertura de HT e' menor que a de FT (o provedor
    nem sempre publica o parcial), e misturar as duas amostras faria a
    frequencia de Under 2.5 HT ser contada sobre jogos que nao tem HT --
    ou seja, tratada como zero gol no primeiro tempo. Ausencia de dado nunca
    vira evidencia de jogo fraco.
    """
    return [j for j in jogos
            if j.get("home_goals_ht") is not None and j.get("away_goals_ht") is not None]
