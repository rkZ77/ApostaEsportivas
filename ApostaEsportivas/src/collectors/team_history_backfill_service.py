"""Backfill de historico POR TIME, para quem nao tem jogo suficiente no banco.

O PROBLEMA QUE ISTO RESOLVE
---------------------------
Todo o resto da coleta parte de `SELECT league_id FROM leagues WHERE ativa`:
pede /fixtures?league=X&season=Y liga por liga e ainda descarta o jogo cujos
dois times nao estejam em `teams` (match_statistics_sync_service._load_fixtures).
Consequencia numa fixture de Libertadores/Sul-Americana:

    time brasileiro    -> Brasileirao + copa no banco, ~15 jogos
    adversario         -> se o campeonato nacional dele nao esta cadastrado,
                          o UNICO jogo dele em match_statistics e' a propria
                          copa: 3 a 6 jogos

competition_profile.uses_all_competitions_history() manda o motor ler "todas as
competicoes" desse time, mas todas as competicoes DELE no banco sao a copa de
novo. A flag nao tem o que buscar.

Isso nao aparece como erro. Aparece como pick: com 5 ou 6 jogos o adversario
passa raspando em data_validation.validate_history (minimo 5) e, depois do
filtro de mando (stats_model.pool_and_field), contribui com 2 ou 3 jogos para
um pool de mercado total que o gate mede SOMADO. A taxa sai como "deste jogo"
sendo, na pratica, a do mandante.

O QUE ESTE COLETOR FAZ
----------------------
Pergunta a API pelo TIME em vez da liga: /fixtures?team=X&last=15 devolve os
ultimos jogos dele em qualquer competicao numa unica requisicao. Depois busca
a folha de estatistica de cada jogo que ainda falta e grava pelo mesmo caminho
de sempre (MatchStatisticsSyncService._save_stats), entao o formato da linha e
o ON CONFLICT sao identicos aos da coleta normal.

SO' VALE PRA COPA, NUNCA PRA PONTOS CORRIDOS
--------------------------------------------
O gatilho e' o mesmo predicado que o motor usa pra decidir a LEITURA
(competition_profile.uses_all_competitions_history). Numa fixture de liga o
motor le get_all_matches_full(season, league_id), travado naquela liga: jogo de
outra competicao que este coletor trouxesse nunca seria consultado. Alem disso
o time de liga abaixo do minimo esta so' no comeco da temporada, e a propria
liga resolve isso em algumas rodadas. Copa nao resolve nunca. Ver
_times_carentes.

CUSTO DE COTA
-------------
1 requisicao por time carente + 1 por jogo que ainda nao esta no banco. O teto
existe pra isso ser previsivel: `teto_requisicoes` corta a rodada no limite,
sem deixar pela metade o time que ja comecou. Na pratica so' a PRIMEIRA rodada
de cada time e cara -- o filtro de jogo ja estabilizado e' o mesmo de
_load_fixtures, entao no dia seguinte quase nada e' rebaixado.

LIGA DESCOBERTA ENTRA COMO HISTORICO
------------------------------------
Um jogo do Paraguaio traz league_id que nao esta em `leagues`. A linha e'
cadastrada com ativa=FALSE, que e' exatamente o estado que a coluna existe pra
representar ("ainda e' coletada? FALSE = so' historico", ver
website/backend/migrations.py). Duas razoes: nenhum coletor passa a gastar
requisicao com ela, e o nome aparece nos JOINs em vez de virar "LIGA 250" nas
telas -- que foi o que aconteceu quando a Copa do Mundo saiu da tabela.
"""
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection
from utils.data_br import HOJE_BR
from services.match_stats_service import DEFAULT_LIMIT_MULTI
from services.pick_engine import competition_profile as cp
from collectors.match_statistics_sync_service import (
    MatchStatisticsSyncService,
    HEADERS,
    FIXTURES_URL,
    STATS_URL,
)

# Jogo encerrado. AET/PEN entram na coleta porque o placar dos 90 minutos vem
# em score.fulltime e _save_stats ja sabe grava-lo separado. Nao confundir com
# o filtro de LEITURA do motor, que hoje le so' status='FT'
# (MatchStatsService.get_last_n_all_competitions) -- decisao daquele lado.
STATUS_ENCERRADO = ("FT", "AET", "PEN")

# Abaixo de quantos jogos no banco um time e' considerado carente.
#
# 5 e' o minimo duro de validate_history, mas mirar nele deixa o time em cima
# da linha: pool_and_field corta o historico pelo mando (o pool cai a
# aproximadamente metade) e sample_rich_n=8 e' o que da Q=1.0. 10 e' o ponto
# em que a leitura de 15 jogos do motor sustenta os dois lados sem estar
# raspando em nenhum.
MIN_JOGOS_PADRAO = 10

# Quantos jogos pedir por time. IMPORTADO do motor, nao copiado: guardar mais
# do que ele le seria requisicao gasta em linha que ninguem consulta, e guardar
# menos deixaria o motor com fome. Os dois numeros ja nasceram desalinhados uma
# vez (o LIMIT do motor subiu de 15 pra 30 em 2026-08-13 e este ficou pra tras
# ate o teste acusar) -- com o import, nao ha o que alinhar.
ULTIMOS_PADRAO = DEFAULT_LIMIT_MULTI

# Teto de requisicoes por rodada, e a conta que sustenta o numero:
#
#   pior caso por time = 1 listagem + ULTIMOS_PADRAO folhas = 31 requisicoes
#   120 => ~4 times vindos do zero, que e' um dia cheio de mata-mata de Conmebol
#
# "Pior caso" e' so' a PRIMEIRA rodada de cada time: na seguinte, o filtro de
# jogo ja gravado derruba o custo pra quase zero. A cota diaria e' disputada
# com a coleta de odds, entao o teto e' o que garante que este coletor nunca
# seja o motivo de faltar cota pra ela.
TETO_REQUISICOES_PADRAO = 120


class TeamHistoryBackfillService:

    def __init__(self, min_jogos: int = MIN_JOGOS_PADRAO,
                 ultimos: int = ULTIMOS_PADRAO,
                 teto_requisicoes: int = TETO_REQUISICOES_PADRAO):
        self.min_jogos = min_jogos
        self.ultimos = ultimos
        self.teto_requisicoes = teto_requisicoes
        self.requisicoes = 0
        self.conn = None
        self.cur = None
        # Composicao em vez de heranca: o que se aproveita dali e' a gravacao
        # (_save_stats, com as 60 colunas e o COALESCE de cada uma), nao a
        # descoberta de jogos, que aqui e' justamente a parte diferente.
        self.stats_sync = MatchStatisticsSyncService()

    # ---------------------------------------------------------
    # Conexao
    # ---------------------------------------------------------
    def _open(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor()
        self.stats_sync._open()

    def _close(self):
        self.stats_sync._close()
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    # ---------------------------------------------------------
    # API (toda chamada passa por aqui -- e' o unico contador de cota)
    # ---------------------------------------------------------
    def _api_get(self, url: str, params: dict) -> list:
        self.requisicoes += 1
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("response", [])

    def _cota_esgotada(self) -> bool:
        return self.requisicoes >= self.teto_requisicoes

    # ---------------------------------------------------------
    # Quem precisa de historico
    # ---------------------------------------------------------
    def _times_carentes(self) -> list:
        """Times dos jogos de HOJE com menos de `min_jogos` no banco, APENAS em
        competicao que le historico multi-competicao.

        POR QUE PONTOS CORRIDOS FICA DE FORA
        ------------------------------------
        O filtro nao e' economia, e' coerencia com o que o motor le. Numa
        fixture de liga o motor chama get_all_matches_full(season, league_id):
        historico travado naquela liga e naquela temporada. Jogo de outra
        competicao que este coletor trouxesse NUNCA seria lido -- requisicao
        gasta em linha que ninguem consulta.

        E o time de pontos corridos abaixo do minimo e' outro problema, com
        outra resposta: ele esta no comeco da temporada e a propria liga vai
        encher a amostra em algumas rodadas. Copa nao enche nunca -- fase de
        grupos da 6 jogos no teto e mata-mata da 1 a 4, e e' por isso que so'
        ela usa historico de fora.

        O predicado e' o MESMO que o motor consulta pra decidir a leitura
        (competition_profile.uses_all_competitions_history), de proposito: se um
        dia uma competicao entrar ou sair do CLUB_CUP, coleta e leitura andam
        juntas em vez de sair de sincronia.

        A contagem usa status='FT' porque e' o filtro que o motor aplica ao ler
        (get_last_n_all_competitions). Contar AET/PEN aqui faria um time
        aparecer com 8 jogos quando o motor enxerga 5, e o backfill nao
        dispararia justamente em quem mais precisa -- mata-mata e' onde a
        prorrogacao acontece.
        """
        self.cur.execute(f"""
            WITH jogos_hoje AS (
                SELECT home_team_id AS team_id, home_team AS team_name, league_id
                  FROM fixtures
                 WHERE match_datetime::date = {HOJE_BR}
                   AND status IN ('NS', 'TBD')
                UNION
                SELECT away_team_id, away_team, league_id
                  FROM fixtures
                 WHERE match_datetime::date = {HOJE_BR}
                   AND status IN ('NS', 'TBD')
            )
            SELECT j.team_id, j.team_name, j.league_id, COUNT(ms.fixture_id) AS jogos
              FROM jogos_hoje j
              LEFT JOIN match_statistics ms
                     ON (ms.home_team_id = j.team_id OR ms.away_team_id = j.team_id)
                    AND ms.status = 'FT'
             WHERE j.team_id IS NOT NULL
             GROUP BY j.team_id, j.team_name, j.league_id
            HAVING COUNT(ms.fixture_id) < %s
             ORDER BY jogos ASC, j.team_id
        """, (self.min_jogos,))

        carentes, ja_vistos = [], set()
        for team_id, team_name, league_id, jogos in self.cur.fetchall():
            if not cp.uses_all_competitions_history(league_id):
                continue
            # Um time pode ter mais de um jogo hoje (raro, mas acontece em
            # rodada remarcada). Basta UM deles ser de copa pra valer a coleta:
            # o historico e' do time, nao da partida.
            if team_id in ja_vistos:
                continue
            ja_vistos.add(team_id)
            carentes.append({"team_id": team_id, "team_name": team_name,
                             "league_id": league_id, "jogos": jogos})
        return carentes

    def _fixtures_completas(self, fixture_ids: list) -> set:
        """Jogos que ja estao no banco COM a folha preenchida.

        As colunas conferidas sao as mesmas de _load_fixtures: linha gravada
        com escanteios/faltas em NULL e' justamente aquela em que a API
        respondeu sem estatistica, e pula-la aqui a deixaria vazia pra sempre.

        O que NAO e' herdado dali e a condicao de frescor (`last_updated >
        match_date + 24h`), e a diferenca e proposital. Aquela regra existe
        porque a API-Football revisa escanteios/cartoes alguma horas depois do
        apito, entao o Stage 4 coleta cada jogo duas vezes. Aqui o alvo e
        historico ANTIGO de um time que nao tem jogo no banco: exigir a segunda
        passada faria toda rodada rebaixar de novo os 15 jogos inteiros do
        mesmo time, que e exatamente o gasto que este coletor existe pra
        evitar. O jogo de hoje, esse sim, continua sendo coletado pelo Stage 4
        com a regra completa sempre que a liga for cadastrada.
        """
        if not fixture_ids:
            return set()
        self.cur.execute("""
            SELECT fixture_id FROM match_statistics
             WHERE fixture_id = ANY(%s)
               AND total_corners IS NOT NULL
               AND total_yellow_cards IS NOT NULL
               AND home_fouls IS NOT NULL
               AND home_total_shots IS NOT NULL
        """, (list(fixture_ids),))
        return {r[0] for r in self.cur.fetchall()}

    # ---------------------------------------------------------
    # Liga descoberta -> historico
    # ---------------------------------------------------------
    def _garantir_liga(self, liga: dict):
        """Cadastra a liga do jogo como historico (ativa=FALSE) se ela ainda
        nao existir. ON CONFLICT DO NOTHING protege a liga que JA' e' coletada:
        nenhuma delas pode ser desativada por um efeito colateral daqui."""
        league_id = liga.get("id")
        if league_id is None:
            return
        nome = liga.get("name") or f"Liga {league_id}"
        pais = liga.get("country")
        # Sem o pais no nome, "Primera Division" do Paraguai, do Chile e do
        # Uruguai viram tres linhas indistinguiveis nas telas.
        if pais and pais.lower() not in ("world", nome.lower()):
            nome = f"{nome} ({pais})"
        self.cur.execute("""
            INSERT INTO leagues (league_id, name, season, ativa)
            VALUES (%s, %s, %s, FALSE)
            ON CONFLICT (league_id) DO NOTHING
        """, (league_id, nome[:100], liga.get("season")))
        if self.cur.rowcount > 0:
            print(f"[BACKFILL] Liga {league_id} ({nome}) cadastrada como historico (ativa=FALSE).")
        self.conn.commit()

    # ---------------------------------------------------------
    # Gravacao de um jogo
    # ---------------------------------------------------------
    def _salvar_jogo(self, item: dict) -> bool:
        """Busca a folha de estatistica e grava. False quando a API devolveu a
        folha incompleta (jogo antigo demais ou competicao sem cobertura de
        estatistica) -- acontece e nao e' erro."""
        fixture = item["fixture"]
        liga = item.get("league") or {}
        teams = item["teams"]
        goals = item["goals"]
        score = item.get("score") or {}
        ht = score.get("halftime") or {}
        ft90 = score.get("fulltime") or {}

        folha = self._api_get(STATS_URL, {"fixture": fixture["id"]})
        if not folha or len(folha) < 2:
            return False

        home_id = teams["home"]["id"]
        if folha[0]["team"]["id"] == home_id:
            home_stats, away_stats = folha[0]["statistics"], folha[1]["statistics"]
        else:
            home_stats, away_stats = folha[1]["statistics"], folha[0]["statistics"]

        self._garantir_liga(liga)

        fx = {
            "fixture_id": fixture["id"],
            "league_id": liga.get("id"),
            "season": liga.get("season"),
            "home_id": home_id,
            "away_id": teams["away"]["id"],
            # UTC sem converter, que e' a convencao de match_statistics.match_date
            # (ver utils/data_br.py) -- o mesmo que _load_fixtures faz.
            "match_date": datetime.fromisoformat(fixture["date"].replace("Z", "+00:00")),
            "status": fixture["status"]["short"],
            # Sem `or 0`: placar ausente e' None e _save_stats recusa a
            # linha (ver a docstring dele). O `or 0` daqui gravava 0x0 falso
            # exatamente como o do sync.
            "home_goals": goals["home"],
            "away_goals": goals["away"],
            "home_goals_ht": ht.get("home"),
            "away_goals_ht": ht.get("away"),
            "home_goals_90": ft90.get("home"),
            "away_goals_90": ft90.get("away"),
            "referee": fixture.get("referee"),
        }
        if not self.stats_sync._save_stats(fx, home_stats, away_stats):
            return False

        rodada = liga.get("round")
        if rodada:
            self.stats_sync._gravar_rodadas([(rodada, fixture["id"])])
        return True

    # ---------------------------------------------------------
    # Um time
    # ---------------------------------------------------------
    def _backfill_time(self, time_: dict) -> dict:
        team_id, nome = time_["team_id"], time_["team_name"]
        print(f"\n[BACKFILL] {nome} (id {team_id}) · {time_['jogos']} jogo(s) no banco")

        resposta = self._api_get(FIXTURES_URL, {"team": team_id, "last": self.ultimos})
        encerrados = [i for i in resposta
                      if (i.get("fixture", {}).get("status", {}) or {}).get("short") in STATUS_ENCERRADO]
        completas = self._fixtures_completas([i["fixture"]["id"] for i in encerrados])
        pendentes = [i for i in encerrados if i["fixture"]["id"] not in completas]

        print(f"[BACKFILL] {len(encerrados)} encerrado(s) na API · "
              f"{len(completas)} ja no banco · {len(pendentes)} a coletar")

        gravados = 0
        for item in pendentes:
            if self._cota_esgotada():
                print(f"[BACKFILL] Teto de {self.teto_requisicoes} requisicoes atingido.")
                break
            try:
                if self._salvar_jogo(item):
                    gravados += 1
            except Exception as e:
                # Um jogo que falha nao pode levar o time junto, e um time nao
                # pode levar a rodada -- este coletor roda ANTES dos pipelines.
                print(f"[BACKFILL] Falha no jogo {item['fixture']['id']}: {e}")

        return {"team_id": team_id, "team_name": nome, "gravados": gravados}

    # ---------------------------------------------------------
    # Rodada
    # ---------------------------------------------------------
    def run(self) -> dict:
        print("[BACKFILL] START · historico por time")
        self._open()
        resultados = []
        try:
            carentes = self._times_carentes()
            if not carentes:
                print(f"[BACKFILL] Nenhum time de copa hoje abaixo de {self.min_jogos} "
                      f"jogos. Nada a fazer (0 requisicoes).")
                return {"times": [], "requisicoes": 0}

            print(f"[BACKFILL] {len(carentes)} time(s) de copa abaixo de "
                  f"{self.min_jogos} jogos.")
            for time_ in carentes:
                if self._cota_esgotada():
                    print(f"[BACKFILL] Teto de {self.teto_requisicoes} requisicoes atingido · "
                          f"{len(carentes) - len(resultados)} time(s) ficaram para a proxima rodada.")
                    break
                try:
                    resultados.append(self._backfill_time(time_))
                except Exception as e:
                    print(f"[BACKFILL] Falha no time {time_['team_name']}: {e}")
        finally:
            self._close()

        total = sum(r["gravados"] for r in resultados)
        print(f"\n[BACKFILL] DONE · {total} jogo(s) gravado(s) em {len(resultados)} time(s) · "
              f"{self.requisicoes} requisicao(oes) de API")
        return {"times": resultados, "requisicoes": self.requisicoes}


if __name__ == "__main__":
    # Uso: python collectors/team_history_backfill_service.py [min_jogos] [teto]
    min_jogos = int(sys.argv[1]) if len(sys.argv) > 1 else MIN_JOGOS_PADRAO
    teto = int(sys.argv[2]) if len(sys.argv) > 2 else TETO_REQUISICOES_PADRAO
    TeamHistoryBackfillService(min_jogos=min_jogos, teto_requisicoes=teto).run()
