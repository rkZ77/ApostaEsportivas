import os
import sys
import psycopg2
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection
from utils.stat_sheet import folha_publicada, ler_valor, somar
from utils.api_client import buscar

API_KEY = os.getenv("API_FOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API_FOOTBALL_KEY não definida")

# Recursos da API-Football, no formato que `utils.api_client.buscar` espera
# (caminho relativo, nao URL inteira). Quem monta header, timeout, retry,
# checagem de `errors` e paginacao e' o api_client.

FIXTURES_URL = "fixtures"
STATS_URL = "fixtures/statistics"


#: Status que contam como jogo apitado. Mesma tripla que o resto do projeto
#: usa pra "encerrado" -- ver stats_sweep._FINALIZADOS e o predicado do
#: backfill de cartao.
_REFEREE_FINALIZADOS = ("FT", "AET", "PEN")


def load_leagues_from_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT league_id, season FROM leagues WHERE COALESCE(ativa, TRUE);")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"league_id": r[0], "season": r[1]} for r in rows]


def extract_stat(stats, stat_name, publicada=None):
    """Valor do contador, ou None quando a API nao publicou esse numero.

    A regra mora em utils/stat_sheet -- inclusive a distincao que faltava aqui
    e' que custou 87% da amostra de cartoes: numa folha PUBLICADA, `value:
    null` num contador significa ZERO, e "Red Cards" e' o unico tipo que a API
    escreve assim. Devolver None nesse caso apagava o vermelho de todo jogo em
    que ninguem foi expulso (agosto/2026: 95 jogos FT, 12 com vermelho no
    banco, ZERO com vermelho igual a zero).

    Folha ausente continua virando None em tudo -- e' o bug de 2026-07-25, que
    deixou 99 jogos FT com escanteio, falta e chute todos em 0, e a invariante
    1 de services/settlement.py.
    """
    return ler_valor(stats, stat_name, publicada)


def _sum_stats(*parts):
    """Total que respeita ausencia: parcela desconhecida -> total desconhecido."""
    return somar(*parts)


#: Contadores do 1o TEMPO gravados por lado: (tipo na folha, sufixo da coluna).
#:
#: Saem de `statistics_1h`, que a API devolve na MESMA requisicao quando se
#: pede `half=true` -- custo zero de cota. Sem eles o motor so' conhecia o
#: placar do intervalo, e todo mercado de 1o tempo que nao fosse gol (escanteio,
#: cartao, chute) era invisivel pro historico e liquidado contra o jogo inteiro.
#:
#: FALTA FICA DE FORA DE PROPOSITO. Na folha do 1o tempo a API nao publica
#: "Fouls" (medido em 27/09/2026, Athletico x ? fixture 1492380: o tipo existe
#: na folha cheia e some da 1h, que traz "Free Kicks" no lugar). Gravar a
#: coluna so' serviria pra ela ficar NULL -- ou, pior, pra alguem aplicar a
#: regra da folha robusta e transformar essa ausencia sistematica em zero.
CONTADORES_1T = (
    ("Corner Kicks",  "corners_1h"),
    ("Yellow Cards",  "yellow_cards_1h"),
    ("Red Cards",     "red_cards_1h"),
    ("Shots on Goal", "shots_on_1h"),
    ("Total Shots",   "total_shots_1h"),
)

#: FINALIZACAO POR ZONA E xG (2026-09-27). Vem na folha do JOGO INTEIRO, na
#: mesma resposta, e era descartada. Gol e' evento raro e barulhento (0 num
#: jogo, 3 no outro); chute dentro da area e xG medem a chance criada, que e'
#: o que se repete. "expected_goals" so' existe nas ligas grandes (Premier
#: League sim, Brasileirao nao, medido em 27/09) -- ausente fica NULL.
#: (tipo na folha, sufixo da coluna, tipo SQL)
CONTADORES_FINALIZACAO = (
    ("Shots insidebox",  "shots_insidebox",  "INTEGER"),
    ("Shots outsidebox", "shots_outsidebox", "INTEGER"),
    ("expected_goals",   "xg",               "NUMERIC(5,2)"),
)
COLUNAS_FINALIZACAO = tuple(f"{lado}_{sufixo}" for _, sufixo, _ in CONTADORES_FINALIZACAO
                            for lado in ("home", "away"))

#: Todas as colunas de 1o tempo, na ordem casa/fora de cada contador.
COLUNAS_1T = tuple(f"{lado}_{sufixo}" for _, sufixo in CONTADORES_1T
                   for lado in ("home", "away"))


def ler_primeiro_tempo(folha_1h) -> dict:
    """{sufixo: valor} de uma folha `statistics_1h`, sem a regra da folha robusta.

    `robusta=False` e' a diferenca que importa. A folha do 1o tempo e' outro
    produto da API, com outro conjunto de tipos (sem "Fouls", por exemplo), e a
    regra que transforma "contador ausente numa folha cheia" em zero foi medida
    na folha do jogo inteiro. Aplicada aqui, ela fabricaria zeros sempre que a
    API omitisse um tipo no 1o tempo -- e zero fabricado vira Under ganho no
    historico. O vermelho em `null` continua zero, porque essa regra e' da API
    e nao da folha (ver utils/stat_sheet._VAZIO_E_ZERO).
    """
    publicada = folha_publicada(folha_1h)
    return {sufixo: ler_valor(folha_1h, tipo, publicada, robusta=False)
            for tipo, sufixo in CONTADORES_1T}


#: Fuso de Brasilia · o mesmo de collectors/fixture_collector_service.py.
_TZ_BR = ZoneInfo("America/Sao_Paulo")


def _br_naive(dt):
    """Datetime da API em horario de Brasilia SEM fuso, ou None.

    E' a convencao de `fixtures.match_datetime`, e agora tambem a de
    `match_statistics.match_datetime`.

    ACEITA STRING de proposito. `fx["match_date"]` chega como datetime pelo
    caminho do lote e como ISO cru por outros -- e um `AttributeError` aqui
    derrubaria a gravacao inteira da partida por causa de uma coluna
    acessoria. Nao dar pra ler vira None: fica sem hora, que e' exatamente o
    estado de antes desta coluna existir.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not hasattr(dt, "tzinfo"):
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(_TZ_BR).replace(tzinfo=None)


def _ultimas_rodadas(response: list, quantas: int) -> list:
    """So' os jogos das N rodadas mais recentes da resposta.

    Agrupa por `league.round` (texto cru da API) e ordena as rodadas pela data
    do jogo mais recente de cada uma -- e nao pelo numero no rotulo, que muda de
    formato entre competicoes ("Regular Season - 12", "Group Stage - 2"). Jogo
    sem rodada no rotulo fica de fora do recorte, porque sem rodada nao ha' como
    dizer se ele e' recente.
    """
    por_rodada: dict = {}
    for fx in response:
        rodada = ((fx.get("league") or {}).get("round") or "").strip()
        if not rodada:
            continue
        data = ((fx.get("fixture") or {}).get("date") or "")
        atual = por_rodada.setdefault(rodada, {"data": data, "jogos": []})
        atual["jogos"].append(fx)
        if data > atual["data"]:
            atual["data"] = data
    recentes = sorted(por_rodada.values(), key=lambda r: r["data"], reverse=True)
    escolhidos = []
    for bloco in recentes[:quantas]:
        escolhidos.extend(bloco["jogos"])
    return escolhidos


class MatchStatisticsSyncService:

    def __init__(self):
        self.conn = None
        self.cur = None

    def _open(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor()
        self._ensure_columns()

    def _ensure_columns(self):
        """Colunas que nasceram depois da tabela.

        PLACAR DOS 90 MINUTOS, separado do placar final.

        `goals` da API-Football e' o placar do jogo inteiro: num jogo decidido
        na prorrogacao ele ja' inclui os gols do tempo extra (Belgium x
        Senegal, fixture 1567308: goals 3x2, mas score.fulltime 2x2). Casa de
        aposta liquida Over/Under e 1X2 pelos 90 minutos -- liquidar pelo 3x2
        e' liquidar por um jogo que o apostador nao apostou.

        Auto-provisionado aqui (mesmo padrao de
        services/picks_ledger_sync_service.py::_create_table_if_needed) porque
        migracao em PROD nao roda sozinha depois do merge.
        """
        for coluna in ("home_goals_90", "away_goals_90"):
            self.cur.execute(
                f"ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS {coluna} INTEGER;")

        # RODADA (2026-08-11). `fixtures.round` sempre existiu, mas
        # fixture_status_sync DELETA a linha da fixture assim que o jogo acaba
        # -- entao a rodada existia enquanto o jogo era futuro e sumia depois.
        # match_statistics e' o registro permanente e nao tinha onde guardar.
        #
        # Sem ela nao da' pra dizer de que fase foi um jogo passado: a
        # inferencia de ida/volta precisou virar heuristica de data, e a tela de
        # estatistica nao consegue recortar por rodada.
        self.cur.execute(
            "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS round TEXT;")

        # JOGOS APITADOS, ao lado dos jogos que sustentam a media (2026-08-27).
        #
        # `referee_stats.games` virou "quantos jogos tem folha de cartao",
        # porque e' esse numero que o gate de cartoes le como amostra. O total
        # apitado nao podia sumir junto: a distancia entre os dois e' o quanto
        # de coleta falta pra aquele arbitro, e sem ela "3 jogos" nao distingue
        # arbitro estreante de arbitro com folha faltando.
        self.cur.execute(
            "ALTER TABLE referee_stats ADD COLUMN IF NOT EXISTS games_total INTEGER;")

        # FOLHA DO 1o TEMPO (2026-09-27). Ver CONTADORES_1T.
        #
        # `stats_1h_checked_at` marca que a folha por tempo JA foi pedida pra
        # esta partida, tenha vindo ou nao. Sem ela o backfill nao distingue
        # "ainda nao busquei" de "a API nao cobre o 1o tempo desta liga", e
        # pagaria de novo, todo dia, pelas partidas que nunca vao ter o dado.
        for coluna in COLUNAS_1T:
            self.cur.execute(
                f"ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS {coluna} INTEGER;")
        self.cur.execute(
            "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS stats_1h_checked_at TIMESTAMP;")
        for _, sufixo, tipo in CONTADORES_FINALIZACAO:
            for lado in ("home", "away"):
                self.cur.execute(f"ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS "
                                 f"{lado}_{sufixo} {tipo};")
        # Marca que a folha ja' foi lida COM estes campos -- a do 1o tempo
        # nao serve de marca, porque 543 partidas de PROD tiveram o 1o tempo
        # coletado antes destes campos existirem.
        self.cur.execute(
            "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS finalizacao_checked_at TIMESTAMP;")
        self.conn.commit()

    def _close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    # ---------------------------------------------------------
    # LOAD FIXTURES (COM GOLS)
    # ---------------------------------------------------------
    def _load_fixtures(self, use_date_filter=True, days=3, apenas_liga=None,
                       temporada=None, exigir_os_dois_times=True,
                       ultimas_rodadas=None):
        """`temporada` (2026-09-24): sobrescreve o `season` que vem de
        `leagues`. Serve pro backfill da temporada ANTERIOR, que e' o que
        devolve amostra pra liga que reiniciou -- ver
        scripts/coletar_temporada_anterior.py e a nota do piso em
        pick_engine/config.py. None mantem o comportamento diario.

        `exigir_os_dois_times=False` aceita a partida em que so' UM dos lados
        e' time da liga hoje. E' obrigatorio no backfill: na temporada passada
        metade dos adversarios era time rebaixado, que nao esta mais em `teams`
        com este league_id -- exigir os dois descartaria justamente os jogos que
        o time atual disputou. Nao ha FK pra `teams`, e o nome do adversario sai
        do join com `league_standings`; ausente, ele fica neutro, que e' a regra
        do motor pra dado que falta.

        `ultimas_rodadas` (int): so' as N rodadas mais recentes da temporada,
        agrupando por `league.round` da propria resposta. E' controle de COTA:
        a temporada inteira de uma liga custa ~380 requisicoes de folha, e o
        motor nao precisa dela inteira -- precisa de ~16 jogos por time, que
        sao as ultimas 10 a 16 rodadas.
        """
        leagues = load_leagues_from_db()
        league_ids = tuple([l["league_id"] for l in leagues])
        if apenas_liga is not None:
            # Backfill de liga recem-cadastrada: sem esse recorte, "temporada
            # inteira" significa a temporada inteira de TODAS as ligas, e o
            # custo em requisicao (uma por jogo) e' o que ja' estourou a cota
            # uma vez -- ver o comentario da coleta de amistosos em
            # atualizar_jogos.py.
            league_ids = tuple(lid for lid in league_ids if lid == apenas_liga)
            # E O LACO DE JOGOS TAMBEM (2026-09-24). `apenas_liga` estreitava
            # so' a consulta de `teams` acima; o laco la' embaixo seguia varrendo
            # TODAS as ligas cadastradas, uma requisicao de listagem cada, e
            # aplicando a `temporada` pedida a todas elas.
            #
            # Ficou invisivel enquanto o filtro de time exigia os DOIS lados: o
            # jogo de outra liga caia porque os times dela nao estavam em
            # valid_team_ids. Com `exigir_os_dois_times=False` ele passa a
            # entrar -- um jogo de Champions tem os dois times cadastrados pelas
            # ligas nacionais deles -- e o backfill de UMA liga comecou a gravar
            # a temporada passada de OUTRAS. As linhas gravadas estavam corretas
            # (cada uma com o seu proprio league_id), mas nenhuma foi pedida.
            leagues = [l for l in leagues if l["league_id"] == apenas_liga]
            if not league_ids:
                print(f"[MATCH_STATS] Liga {apenas_liga} nao esta cadastrada em `leagues`.")
                return []

        self.cur.execute(
            "SELECT team_id FROM teams WHERE league_id IN %s;", (league_ids,))
        valid_team_ids = {row[0] for row in self.cur.fetchall()}

        if not valid_team_ids:
            print("[MATCH_STATS] AVISO: tabela 'teams' está vazia ou sem times para as ligas cadastradas · nenhum jogo será carregado.")
            print("[MATCH_STATS] Execute o Stage 1 (sync de times) antes do Stage 4.")

        # Jogos cuja estatística já está no banco E já estabilizou. Sem isso o
        # Stage 4 rebaixava /fixtures/statistics de TODO jogo finalizado da
        # janela (ATUALIZAR_JOGOS_DAYS, padrão 7), todo dia -- o mesmo jogo era
        # baixado 7 vezes, uma requisição cada.
        #
        # O corte é `last_updated > match_date + 24h` em vez de "existe no
        # banco" porque a API-Football revisa contagem de escanteios/cartões
        # algumas horas depois do apito final (é a razão de existir o
        # reverify_recent_stats_results em routers/live.py). Com essa regra cada
        # jogo é coletado no máximo 2 vezes: logo após o FT e uma vez no dia
        # seguinte, que é quando o número já não muda mais.
        #
        # A folha tem que estar COMPLETA pra o jogo contar como estabilizado:
        # linha com escanteios/faltas/chutes em NULL e' justamente aquela em
        # que a API respondeu sem estatistica, e e' a que mais precisa de uma
        # segunda passada. Sem essa condicao o jogo seria pulado pra sempre
        # com a folha vazia.
        self.cur.execute("""
            SELECT fixture_id FROM match_statistics
            WHERE last_updated IS NOT NULL
              AND last_updated > match_date + INTERVAL '24 hours'
              AND total_corners IS NOT NULL
              AND total_yellow_cards IS NOT NULL
              -- VERMELHO entra na definicao de "folha completa" desde
              -- 2026-08-26. Sem ele, o jogo cuja unica lacuna era o vermelho
              -- era pulado PRA SEMPRE (a coleta so' volta em folha
              -- incompleta) -- e o vermelho era a lacuna da grande maioria.
              AND total_red_cards IS NOT NULL
              AND home_fouls IS NOT NULL
              AND home_total_shots IS NOT NULL
        """)
        settled_fixture_ids = {row[0] for row in self.cur.fetchall()}

        fixtures = []
        skipped = 0
        rodadas_a_gravar: list = []

        if use_date_filter:
            limit_date = datetime.now(timezone.utc) - timedelta(days=days)

        for lg in leagues:
            season_da_liga = temporada if temporada is not None else lg["season"]
            params = {
                "league": lg["league_id"],
                "season": season_da_liga
            }

            # PAGINA. Uma temporada de liga passa de 100 jogos com
            # folga, e a API entrega 100 por pagina: esta chamada lia so' a
            # primeira e devolvia uma resposta bem formada e incompleta, sem
            # erro nenhum. Tambem nao tinha timeout -- era a unica chamada do
            # projeto que podia pendurar a coleta indefinidamente.
            response = buscar(FIXTURES_URL, params, origem="coletor_stats")
            # CALENDARIO (2026-09-27): a mesma resposta traz a temporada inteira,
            # passado e futuro -- ver collectors/calendario_service. Gravado
            # ANTES do recorte de `ultimas_rodadas`, que e' so' pra folha.
            # SAVEPOINT: falha no calendario desfaz so' o calendario, e a
            # coleta da folha segue na mesma transacao sem ser abortada.
            try:
                from collectors.calendario_service import gravar_temporada
                self.cur.execute("SAVEPOINT calendario")
                gravar_temporada(self.cur, response, lg["league_id"], season_da_liga)
                self.cur.execute("RELEASE SAVEPOINT calendario")
            except Exception as e:
                try:
                    self.cur.execute("ROLLBACK TO SAVEPOINT calendario")
                except Exception:
                    pass
                print(f"[CALENDARIO] liga {lg['league_id']}: {e}")
            if ultimas_rodadas:
                response = _ultimas_rodadas(response, ultimas_rodadas)

            for fx in response:
                fixture = fx["fixture"]
                teams = fx["teams"]
                goals = fx["goals"]

                status = fixture["status"]["short"]

                if status not in ("FT", "AET", "PEN"):
                    continue

                match_date = datetime.fromisoformat(
                    fixture["date"].replace("Z", "+00:00")
                )

                if use_date_filter and match_date < limit_date:
                    continue

                home_id = teams["home"]["id"]
                away_id = teams["away"]["id"]

                if exigir_os_dois_times:
                    if home_id not in valid_team_ids or away_id not in valid_team_ids:
                        continue
                elif home_id not in valid_team_ids and away_id not in valid_team_ids:
                    # Backfill: basta um lado ser time da liga hoje. Ver a
                    # docstring -- o outro lado costuma ser time rebaixado.
                    continue

                # A RODADA E' GRAVADA MESMO NO JOGO JA ESTABILIZADO.
                #
                # `league.round` vem nesta mesma resposta e ate' 2026-08-11 era
                # descartado: ficava so' em `fixtures`, e fixture_status_sync
                # DELETA a linha assim que o jogo acaba (FT/AET/PEN e afins).
                # Ou seja, a rodada existia enquanto o jogo era futuro e sumia
                # depois -- match_statistics, que e' o registro permanente, nao
                # tinha a coluna. Sem ela nao da' pra dizer de que fase foi um
                # jogo passado, e a inferencia de ida/volta precisou virar
                # heuristica de data (ver match_context_model.inferir_leg).
                #
                # Fica ANTES do `continue` de propósito: preenche o historico
                # inteiro na proxima passada, sem UMA requisicao a mais.
                rodada = (fx.get("league") or {}).get("round")
                if rodada:
                    rodadas_a_gravar.append((rodada, fixture["id"]))

                if fixture["id"] in settled_fixture_ids:
                    skipped += 1
                    continue

                score = fx.get("score", {}) or {}
                ht = score.get("halftime") or {}
                ft90 = score.get("fulltime") or {}

                fixtures.append({
                    "fixture_id": fixture["id"],
                    "league_id": lg["league_id"],
                    # A temporada COLETADA, nunca a de `leagues`. Gravar o
                    # backfill com o season corrente faria o jogo de 2025
                    # contar como jogo de 2026 -- o oposto do que ele existe
                    # pra fazer, e invisivel em qualquer contagem.
                    "season": season_da_liga,
                    "home_id": home_id,
                    "away_id": away_id,
                    "match_date": match_date,
                    "status": status,
                    # SEM `or 0` (2026-08-27). O `or 0` que ficava aqui
                    # transformava "a API nao publicou o placar" em "o jogo
                    # terminou 0x0" -- mesmo defeito que o cartao vermelho
                    # teve ate' 26/08, e mais caro: gol e' a familia mais
                    # usada do motor, e um 0x0 falso nao aparece em nenhuma
                    # contagem de cobertura (zero nao e' nulo). Placar
                    # ausente agora chega None e `_save_stats` recusa a
                    # linha, entao a partida continua visivel como buraco
                    # em vez de virar media errada.
                    "home_goals": goals["home"],
                    "away_goals": goals["away"],
                    "home_goals_ht": ht.get("home"),
                    "away_goals_ht": ht.get("away"),
                    "home_goals_90": ft90.get("home"),
                    "away_goals_90": ft90.get("away"),
                    "referee": fixture.get("referee"),
                })

        self._gravar_rodadas(rodadas_a_gravar)

        print(f"[INFO] {len(fixtures)} jogos carregados "
              f"({skipped} pulados · estatística já estabilizada no banco)")
        return fixtures

    def _gravar_rodadas(self, pares: list):
        """Grava `round` nos jogos que ainda nao tem, em lote.

        Idempotente e barato: nao chama API nenhuma (o dado ja veio junto da
        listagem de fixtures) e so' escreve onde esta faltando, entao rodar
        todo dia nao gera escrita a toa."""
        if not pares:
            return
        from psycopg2.extras import execute_values
        execute_values(self.cur, """
            UPDATE match_statistics ms
               SET round = dados.round
              FROM (VALUES %s) AS dados(round, fixture_id)
             WHERE ms.fixture_id = dados.fixture_id
               AND ms.round IS DISTINCT FROM dados.round
        """, pares)
        if self.cur.rowcount > 0:
            print(f"[MATCH_STATS] rodada gravada em {self.cur.rowcount} jogo(s).")
        self.conn.commit()

    def _fetch_match_stats(self, fixture_id):
        # `half=true` devolve `statistics_1h`/`statistics_2h` ao lado da folha
        # cheia, na mesma requisicao. A folha cheia (`statistics`) nao muda.
        return buscar(STATS_URL, {"fixture": fixture_id, "half": "true"},
                      origem="coletor_stats")

    @staticmethod
    def _separar_lados(stats, home_id):
        """(folha casa, folha fora, 1o tempo casa, 1o tempo fora) pelo team.id.

        Um lugar so' pra os tres caminhos de coleta (lote, pendentes, avulsa)
        nao repetirem a comparacao de id -- a API nao garante que o indice 0
        seja o mandante."""
        casa, fora = (stats[0], stats[1]) if stats[0]["team"]["id"] == home_id \
            else (stats[1], stats[0])
        return (casa.get("statistics") or [], fora.get("statistics") or [],
                casa.get("statistics_1h"), fora.get("statistics_1h"))

    # ---------------------------------------------------------
    # SAVE COMPLETO
    # ---------------------------------------------------------
    def _save_stats(self, fx, home_stats, away_stats,
                    home_1h=None, away_1h=None) -> bool:
        """Grava a linha da partida. False = nao gravou (placar ausente).

        O PLACAR E' PRE-REQUISITO, NAO UM CAMPO A MAIS (2026-08-27).

        Ate' aqui um `goals` nulo da API virava 0 e a linha era gravada como
        se o jogo tivesse terminado 0x0. Isso e' pior que nao ter a linha por
        dois motivos: entra na media de gols como jogo real (e gol e' a
        familia que mais mercado gera), e some da varredura -- que procura
        jogo ENCERRADO SEM LINHA e nunca mais volta naquela partida.

        E' a mesma regra que a folha ja' seguia desde 26/08 ("linha oca
        esconde a partida pra sempre"), agora aplicada ao placar.
        """
        home_goals = fx["home_goals"]
        away_goals = fx["away_goals"]
        if home_goals is None or away_goals is None:
            print(f"[MATCH_STATS] fixture_id={fx['fixture_id']} sem placar na API "
                  f"(status={fx.get('status')}) · linha NAO gravada, a partida "
                  f"continua na lista de buracos.")
            return False
        total_goals = _sum_stats(home_goals, away_goals)

        # A folha e' classificada UMA vez, antes de ler campo nenhum: e' essa
        # classificacao que separa "a API nao respondeu" (tudo None) de "a API
        # respondeu e o contador e' zero". Ver utils/stat_sheet.
        pub_home = folha_publicada(home_stats)
        pub_away = folha_publicada(away_stats)

        home_corners = extract_stat(home_stats, "Corner Kicks", pub_home)
        away_corners = extract_stat(away_stats, "Corner Kicks", pub_away)

        home_yellow = extract_stat(home_stats, "Yellow Cards", pub_home)
        away_yellow = extract_stat(away_stats, "Yellow Cards", pub_away)

        home_red = extract_stat(home_stats, "Red Cards", pub_home)
        away_red = extract_stat(away_stats, "Red Cards", pub_away)

        home_shots_on = extract_stat(home_stats, "Shots on Goal", pub_home)
        away_shots_on = extract_stat(away_stats, "Shots on Goal", pub_away)

        home_shots_off = extract_stat(home_stats, "Shots off Goal", pub_home)
        away_shots_off = extract_stat(away_stats, "Shots off Goal", pub_away)

        home_total_shots = extract_stat(home_stats, "Total Shots", pub_home)
        away_total_shots = extract_stat(away_stats, "Total Shots", pub_away)

        home_blocked = extract_stat(home_stats, "Blocked Shots", pub_home)
        away_blocked = extract_stat(away_stats, "Blocked Shots", pub_away)

        home_saves = extract_stat(home_stats, "Goalkeeper Saves", pub_home)
        away_saves = extract_stat(away_stats, "Goalkeeper Saves", pub_away)

        home_fouls = extract_stat(home_stats, "Fouls", pub_home)
        away_fouls = extract_stat(away_stats, "Fouls", pub_away)

        home_offsides = extract_stat(home_stats, "Offsides", pub_home)
        away_offsides = extract_stat(away_stats, "Offsides", pub_away)

        home_possession = extract_stat(home_stats, "Ball Possession", pub_home)
        away_possession = extract_stat(away_stats, "Ball Possession", pub_away)

        home_passes = extract_stat(home_stats, "Total passes", pub_home)
        away_passes = extract_stat(away_stats, "Total passes", pub_away)

        home_pass_acc = extract_stat(home_stats, "Passes %", pub_home)
        away_pass_acc = extract_stat(away_stats, "Passes %", pub_away)

        self.cur.execute("""
            INSERT INTO match_statistics (
                fixture_id, league_id, season,
                home_team_id, away_team_id,
                home_goals, away_goals, total_goals,
                home_goals_ht, away_goals_ht,
                home_goals_90, away_goals_90,
                home_corners, away_corners, total_corners,
                home_yellow_cards, away_yellow_cards, total_yellow_cards,
                home_red_cards, away_red_cards, total_red_cards,
                status, match_date, match_datetime,

                home_shots_on, away_shots_on,
                home_shots_off, away_shots_off,
                home_total_shots, away_total_shots,
                home_blocked_shots, away_blocked_shots,
                home_goalkeeper_saves, away_goalkeeper_saves,
                home_fouls, away_fouls,
                home_offsides, away_offsides,
                home_possession, away_possession,
                home_passes, away_passes,
                home_passes_accuracy, away_passes_accuracy,

                referee,
                last_updated
            )
            VALUES (
                %s,%s,%s,
                %s,%s,
                %s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,

                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,

                %s,
                NOW()
            )
            ON CONFLICT (fixture_id)
            DO UPDATE SET
                -- COALESCE tambem no placar (2026-08-27), pelo mesmo motivo
                -- do resto das colunas: recoleta que volte sem placar nao pode
                -- apagar o que ja' estava certo.
                home_goals = COALESCE(EXCLUDED.home_goals, match_statistics.home_goals),
                away_goals = COALESCE(EXCLUDED.away_goals, match_statistics.away_goals),
                total_goals = COALESCE(EXCLUDED.total_goals, match_statistics.total_goals),
                home_goals_ht = COALESCE(EXCLUDED.home_goals_ht, match_statistics.home_goals_ht),
                away_goals_ht = COALESCE(EXCLUDED.away_goals_ht, match_statistics.away_goals_ht),
                home_goals_90 = COALESCE(EXCLUDED.home_goals_90, match_statistics.home_goals_90),
                away_goals_90 = COALESCE(EXCLUDED.away_goals_90, match_statistics.away_goals_90),

                -- COALESCE em toda estatistica: agora que "nao publicado" chega
                -- como NULL (ver extract_stat), uma coleta em que a API
                -- respondeu incompleta nao pode apagar o numero certo ja
                -- gravado numa coleta anterior. Placar e status seguem
                -- sobrescrevendo direto: vem de /fixtures, nao da folha de
                -- estatistica, e sao sempre confiaveis.
                home_corners = COALESCE(EXCLUDED.home_corners, match_statistics.home_corners),
                away_corners = COALESCE(EXCLUDED.away_corners, match_statistics.away_corners),
                total_corners = COALESCE(EXCLUDED.total_corners, match_statistics.total_corners),

                home_yellow_cards = COALESCE(EXCLUDED.home_yellow_cards, match_statistics.home_yellow_cards),
                away_yellow_cards = COALESCE(EXCLUDED.away_yellow_cards, match_statistics.away_yellow_cards),
                total_yellow_cards = COALESCE(EXCLUDED.total_yellow_cards, match_statistics.total_yellow_cards),

                home_red_cards = COALESCE(EXCLUDED.home_red_cards, match_statistics.home_red_cards),
                away_red_cards = COALESCE(EXCLUDED.away_red_cards, match_statistics.away_red_cards),
                total_red_cards = COALESCE(EXCLUDED.total_red_cards, match_statistics.total_red_cards),

                status = EXCLUDED.status,
                match_date = EXCLUDED.match_date,
                -- COALESCE porque recoleta que volte sem a hora nao pode
                -- apagar a que ja' estava gravada · mesma regra do resto.
                match_datetime = COALESCE(EXCLUDED.match_datetime,
                                          match_statistics.match_datetime),

                home_shots_on = COALESCE(EXCLUDED.home_shots_on, match_statistics.home_shots_on),
                away_shots_on = COALESCE(EXCLUDED.away_shots_on, match_statistics.away_shots_on),
                home_shots_off = COALESCE(EXCLUDED.home_shots_off, match_statistics.home_shots_off),
                away_shots_off = COALESCE(EXCLUDED.away_shots_off, match_statistics.away_shots_off),
                home_total_shots = COALESCE(EXCLUDED.home_total_shots, match_statistics.home_total_shots),
                away_total_shots = COALESCE(EXCLUDED.away_total_shots, match_statistics.away_total_shots),
                home_blocked_shots = COALESCE(EXCLUDED.home_blocked_shots, match_statistics.home_blocked_shots),
                away_blocked_shots = COALESCE(EXCLUDED.away_blocked_shots, match_statistics.away_blocked_shots),
                home_goalkeeper_saves = COALESCE(EXCLUDED.home_goalkeeper_saves, match_statistics.home_goalkeeper_saves),
                away_goalkeeper_saves = COALESCE(EXCLUDED.away_goalkeeper_saves, match_statistics.away_goalkeeper_saves),
                home_fouls = COALESCE(EXCLUDED.home_fouls, match_statistics.home_fouls),
                away_fouls = COALESCE(EXCLUDED.away_fouls, match_statistics.away_fouls),
                home_offsides = COALESCE(EXCLUDED.home_offsides, match_statistics.home_offsides),
                away_offsides = COALESCE(EXCLUDED.away_offsides, match_statistics.away_offsides),
                home_possession = COALESCE(EXCLUDED.home_possession, match_statistics.home_possession),
                away_possession = COALESCE(EXCLUDED.away_possession, match_statistics.away_possession),
                home_passes = COALESCE(EXCLUDED.home_passes, match_statistics.home_passes),
                away_passes = COALESCE(EXCLUDED.away_passes, match_statistics.away_passes),
                home_passes_accuracy = COALESCE(EXCLUDED.home_passes_accuracy, match_statistics.home_passes_accuracy),
                away_passes_accuracy = COALESCE(EXCLUDED.away_passes_accuracy, match_statistics.away_passes_accuracy),

                referee = COALESCE(EXCLUDED.referee, match_statistics.referee),
                last_updated = NOW();
        """, (
            fx["fixture_id"], fx["league_id"], fx["season"],
            fx["home_id"], fx["away_id"],
            home_goals, away_goals, total_goals,
            fx.get("home_goals_ht"), fx.get("away_goals_ht"),
            fx.get("home_goals_90"), fx.get("away_goals_90"),
            home_corners, away_corners, _sum_stats(home_corners, away_corners),
            home_yellow, away_yellow, _sum_stats(home_yellow, away_yellow),
            home_red, away_red, _sum_stats(home_red, away_red),
            fx["status"], fx["match_date"],
            # EM BRASILIA SEM FUSO, igual `fixtures.match_datetime` -- e ao
            # contrario de `match_date`, na linha de cima, que vai em UTC (ver
            # o aviso das duas convencoes em utils/data_br.py). A escolha e'
            # pela coluna com que ela sera comparada e exibida, nao pela
            # vizinha de tabela.
            _br_naive(fx["match_date"]),

            home_shots_on, away_shots_on,
            home_shots_off, away_shots_off,
            home_total_shots, away_total_shots,
            home_blocked, away_blocked,
            home_saves, away_saves,
            home_fouls, away_fouls,
            home_offsides, away_offsides,
            home_possession, away_possession,
            home_passes, away_passes,
            home_pass_acc, away_pass_acc,

            fx.get("referee"),
        ))

        self._gravar_primeiro_tempo(fx["fixture_id"], home_1h, away_1h)
        self._gravar_finalizacao(fx["fixture_id"], home_stats, away_stats)
        self.conn.commit()
        print(f"[OK] {fx['fixture_id']}")
        return True

    def _gravar_finalizacao(self, fixture_id, home_stats, away_stats):
        """Chute dentro/fora da area e xG da folha cheia, e a marca de lidos.

        Folha nao publicada nao marca: a partida volta no backfill. Publicada
        sem o tipo (xG fora das ligas grandes) marca com o campo NULL -- a API
        nao vai passar a publicar depois, e pedir de novo so' gastaria cota."""
        if not (folha_publicada(home_stats) and folha_publicada(away_stats)):
            return
        valores = {}
        for lado, folha in (("home", home_stats), ("away", away_stats)):
            for tipo, sufixo, _ in CONTADORES_FINALIZACAO:
                # robusta=False pelo mesmo motivo do 1o tempo: ausencia de xG
                # e' o caso normal fora das ligas grandes, nunca zero.
                valores[f"{lado}_{sufixo}"] = ler_valor(folha, tipo, True, robusta=False)
        sets = ", ".join(f"{col} = COALESCE(%s, {col})" for col in COLUNAS_FINALIZACAO)
        self.cur.execute(
            f"UPDATE match_statistics SET {sets}, finalizacao_checked_at = NOW() "
            f"WHERE fixture_id = %s;",
            tuple(valores[col] for col in COLUNAS_FINALIZACAO) + (fixture_id,))

    def _gravar_primeiro_tempo(self, fixture_id, home_1h, away_1h):
        """Grava os contadores do 1o tempo e marca que a folha foi pedida.

        UPDATE separado do INSERT principal de proposito: o backfill das
        partidas antigas passa so' por aqui, sem reescrever a folha cheia que
        ja' esta' estabilizada no banco.

        `None` nos dois lados = a resposta nem trouxe a chave `statistics_1h`
        (chamada sem `half=true`); nada e' marcado, pra a partida continuar
        elegivel ao backfill. Lista vazia = a API respondeu e nao cobre o 1o
        tempo desta partida; ai' a marca entra e os contadores ficam NULL.
        COALESCE pelo mesmo motivo da folha cheia: recoleta incompleta nao
        apaga numero certo ja' gravado.
        """
        if home_1h is None and away_1h is None:
            return
        casa = ler_primeiro_tempo(home_1h or [])
        fora = ler_primeiro_tempo(away_1h or [])
        valores = {}
        for _, sufixo in CONTADORES_1T:
            valores[f"home_{sufixo}"] = casa[sufixo]
            valores[f"away_{sufixo}"] = fora[sufixo]
        sets = ", ".join(f"{col} = COALESCE(%s, {col})" for col in COLUNAS_1T)
        self.cur.execute(
            f"UPDATE match_statistics SET {sets}, stats_1h_checked_at = NOW() "
            f"WHERE fixture_id = %s;",
            tuple(valores[col] for col in COLUNAS_1T) + (fixture_id,))

    # ---------------------------------------------------------
    # UPSERT ÁRBITRO → retorna referee_id (ou None se sem nome)
    # ---------------------------------------------------------
    def _upsert_referee(self, name: str) -> int | None:
        if not name:
            return None
        self.cur.execute("""
            INSERT INTO referees (name, created_at, last_updated)
            VALUES (%s, NOW(), NOW())
            ON CONFLICT (name) DO UPDATE SET last_updated = NOW()
            RETURNING referee_id;
        """, (name,))
        return self.cur.fetchone()[0]

    # ---------------------------------------------------------
    # RECALCULA MÉDIAS DO ÁRBITRO PARA UMA TEMPORADA
    # ---------------------------------------------------------
    def _recalculate_referee_stats(self, referee_id: int, referee_name: str, season: int):
        self.cur.execute("""
            INSERT INTO referee_stats (
                referee_id, season,
                games, games_total,
                avg_yellow, avg_red, avg_fouls,
                avg_corners, avg_goals,
                max_yellow, min_yellow,
                last_updated
            )
            SELECT
                %s, %s,
                -- `games` e' lido como AMOSTRA: cards_referee_min_games
                -- (config.py) usa esse numero pra liberar ou bloquear o
                -- mercado de cartoes. Enquanto ele era COUNT(*) da temporada
                -- e a media era AVG (que ignora NULL), os dois saiam de
                -- conjuntos diferentes -- arbitro com 5 jogos apitados e 2
                -- folhas passava no gate de 3 com media tirada de 2.
                COUNT(*) FILTER (WHERE ms.total_yellow_cards IS NOT NULL),
                COUNT(*),
                ROUND(AVG(ms.total_yellow_cards)::numeric, 2),
                ROUND(AVG(ms.total_red_cards)::numeric, 2),
                ROUND(AVG(ms.home_fouls + ms.away_fouls)::numeric, 2),
                ROUND(AVG(ms.total_corners)::numeric, 2),
                ROUND(AVG(ms.total_goals)::numeric, 2),
                MAX(ms.total_yellow_cards),
                MIN(ms.total_yellow_cards),
                NOW()
            FROM match_statistics ms
            WHERE ms.referee = %s
              AND ms.season  = %s
              -- Status entra desde 2026-08-27. Sem ele, linha de jogo nao
              -- finalizado (adiado, interrompido) entrava na media do arbitro
              -- com o placar parcial que estivesse gravado -- e o backfill de
              -- cartao ja' filtrava por status, entao as duas contas do mesmo
              -- numero discordavam.
              AND ms.status IN %s
            ON CONFLICT (referee_id, season) DO UPDATE SET
                games        = EXCLUDED.games,
                games_total  = EXCLUDED.games_total,
                avg_yellow   = EXCLUDED.avg_yellow,
                avg_red      = EXCLUDED.avg_red,
                avg_fouls    = EXCLUDED.avg_fouls,
                avg_corners  = EXCLUDED.avg_corners,
                avg_goals    = EXCLUDED.avg_goals,
                max_yellow   = EXCLUDED.max_yellow,
                min_yellow   = EXCLUDED.min_yellow,
                last_updated = NOW();
        """, (referee_id, season, referee_name, season, _REFEREE_FINALIZADOS))

    # ---------------------------------------------------------
    # PROCESSA LOTE DE ÁRBITROS AO FINAL DO SYNC
    # referee_batch = set of (referee_name, season)
    # ---------------------------------------------------------
    def _sync_referee_stats(self, referee_batch: set):
        if not referee_batch:
            return
        print(f"[REFEREE] Atualizando stats de {len(referee_batch)} árbitro(s)...")
        for referee_name, season in referee_batch:
            referee_id = self._upsert_referee(referee_name)
            if referee_id:
                self._recalculate_referee_stats(referee_id, referee_name, season)
        self.conn.commit()
        print("[REFEREE] Stats de árbitros atualizados.")

    # ---------------------------------------------------------
    # SYNC DIRETO POR FIXTURE_ID (para pendentes em picks_vip)
    # Não depende da tabela teams · busca tudo via API por ID.
    # ---------------------------------------------------------
    def sync_pending_fixtures(self, include_resolved: bool = False):
        """Busca a folha de estatistica dos jogos que sustentam picks.

        include_resolved=True inclui tambem picks JA' resolvidos cuja folha
        esta ausente ou incompleta. E' o que quebra o circulo vicioso que
        deixou o caso Fortaleza x Palmeiras (fixture 1546854) sem folha
        nenhuma no banco: o caminho ao vivo gravou um resultado a partir de
        estatistica vazia, e a partir dai o pick nao era mais "pendente",
        entao a coleta nunca ia buscar o numero certo. Usado pela
        re-resolucao (scripts/reauditar_resultados.py).
        """
        print("[MATCH_STATS] Sincronizando fixtures pendentes das sugestões...")

        self._open()

        # Coleta fixture_ids pendentes das tabelas de sugestões
        pending_ids = set()
        import json as _json

        filtro = "" if include_resolved else "AND result IS NULL"

        # picks_boost e picks_live entraram em 28/08. Os dois liquidam pela
        # FOLHA DA PARTIDA, igual VIP/Free, entao dependiam desta coleta e nao
        # estavam nela -- ficavam esperando que outro produto pedisse a mesma
        # fixture por acaso.
        #
        # picks_player_stats fica FORA de proposito: prop de jogador liquida
        # por player_match_stats, que vem do PlayerStatsCollectorService
        # (`python main.py player_stats`), nao daqui. Incluir a tabela aqui
        # gastaria requisicao buscando a folha do time, que aquele pick nao le.
        for table in ("picks_vip", "picks_free", "picks_faltas", "picks_goleiros",
                      "picks_boost", "picks_live"):
            try:
                self.cur.execute(
                    f"SELECT DISTINCT fixture_id FROM {table} "
                    f"WHERE fixture_id IS NOT NULL {filtro};")
            except Exception as e:
                print(f"[MATCH_STATS] Aviso: {table} indisponivel ({e})")
                self.conn.rollback()
                continue
            for row in self.cur.fetchall():
                if row[0] is not None:
                    pending_ids.add(row[0])

        # Alavancagem: ate' tres fixtures por pick (a perna 3 nao era lida aqui)
        self.cur.execute(
            f"SELECT fixture_id_1, fixture_id_2, fixture_id_3 FROM picks_alavancagem "
            f"WHERE TRUE {filtro};")
        for row in self.cur.fetchall():
            for fid in row:
                if fid is not None:
                    pending_ids.add(fid)

        # Múltiplas e Bingo: extraem fixture_ids do JSON das legs. As duas
        # tabelas tem a MESMA forma (`games` JSONB com uma perna por item),
        # entao o mesmo laco cobre as duas.
        #
        # picks_bingo pode nao existir no ambiente: e' tabela que o MOTOR cria
        # (bingo_pipeline._create_table_if_needed), como picks_live. Um erro
        # aqui sujaria a transacao e derrubaria a varredura inteira -- por isso
        # o try/rollback, no mesmo padrao do laco de tabelas acima.
        for tabela in ("picks_multiplas", "picks_bingo"):
            try:
                self.cur.execute(f"SELECT games FROM {tabela} WHERE TRUE {filtro};")
            except Exception as e:
                print(f"[MATCH_STATS] Aviso: {tabela} indisponivel ({e})")
                self.conn.rollback()
                continue
            for (games_raw,) in self.cur.fetchall():
                try:
                    games = _json.loads(games_raw) if isinstance(games_raw, str) else games_raw
                    for leg in (games if isinstance(games, list) else []):
                        fid = leg.get("fixture_id")
                        if fid is not None:
                            pending_ids.add(fid)
                except Exception:
                    pass

        # Remove os que já têm a folha COMPLETA. Antes bastava existir a linha:
        # um jogo gravado com a folha vazia nunca era rebuscado.
        if pending_ids:
            self.cur.execute("""
                SELECT fixture_id FROM match_statistics
                WHERE fixture_id = ANY(%s)
                  AND total_corners IS NOT NULL
                  AND total_yellow_cards IS NOT NULL
                  AND total_red_cards IS NOT NULL
                  AND home_fouls IS NOT NULL
                  AND home_total_shots IS NOT NULL;
            """, (list(pending_ids),))
            already = {row[0] for row in self.cur.fetchall()}
            pending_ids -= already

        if not pending_ids:
            print("[MATCH_STATS] Nenhum fixture pendente sem stats.")
            self._close()
            return

        print(f"[MATCH_STATS] {len(pending_ids)} fixture(s) sem stats · buscando na API...")

        referee_batch = set()

        for fixture_id in pending_ids:
            try:
                self._sync_uma_fixture(fixture_id, referee_batch)
            except Exception as e:
                print(f"[MATCH_STATS] Erro ao processar fixture_id={fixture_id}: {e}")

        self._sync_referee_stats(referee_batch)
        self._close()
        print("[MATCH_STATS] Sync de pendentes concluído.")

    # ---------------------------------------------------------
    # UMA PARTIDA
    # ---------------------------------------------------------
    #: Estados possiveis de uma coleta unitaria. Sao devolvidos em vez de
    #: impressos porque o /admin mostra o motivo na tela -- "nao coletou" sem
    #: motivo e' o tipo de resposta que faz alguem clicar cinco vezes.
    FINISHED = {"FT", "AET", "PEN"}

    def _sync_uma_fixture(self, fixture_id: int, referee_batch: set,
                          criar_sem_folha: bool = False) -> str:
        """Busca /fixtures + /fixtures/statistics de UMA partida e grava.

        Extraido de `sync_pending_fixtures` pra que o botao "Rodar" do /admin
        (routers/admin.py::coletar_partida) colete uma partida avulsa pelo
        MESMO caminho do lote. Ter um segundo jeito de escrever em
        `match_statistics` e' o que ja' produziu duas leituras divergentes da
        folha -- ver o cabecalho de utils/stat_sheet.

        Custa 2 requisicoes. Requer a conexao ja' aberta (`self._open()`).
        """
        response = buscar(FIXTURES_URL, {"id": fixture_id}, origem="coletor_stats")

        if not response:
            print(f"[MATCH_STATS] fixture_id={fixture_id} não encontrado na API.")
            return "nao_encontrada"

        item = response[0]
        fixture_info = item["fixture"]
        status = fixture_info["status"]["short"]

        if status not in self.FINISHED:
            print(f"[MATCH_STATS] fixture_id={fixture_id} status={status} · jogo ainda não finalizado.")
            return "nao_finalizada"

        goals = item["goals"]
        score = item.get("score", {}) or {}
        ht = score.get("halftime") or {}
        ft90 = score.get("fulltime") or {}
        home_id = item["teams"]["home"]["id"]
        fx = {
            "fixture_id": fixture_id,
            "league_id": item["league"]["id"],
            "season": item["league"]["season"],
            "home_id": home_id,
            "away_id": item["teams"]["away"]["id"],
            "match_date": datetime.fromisoformat(fixture_info["date"].replace("Z", "+00:00")),
            "status": status,
            # Ver o comentario em _load_fixtures: placar ausente e' None,
            # nunca 0.
            "home_goals": goals["home"],
            "away_goals": goals["away"],
            "home_goals_ht": ht.get("home"),
            "away_goals_ht": ht.get("away"),
            "home_goals_90": ft90.get("home"),
            "away_goals_90": ft90.get("away"),
            "referee": fixture_info.get("referee"),
        }

        stats = self._fetch_match_stats(fixture_id)

        if not stats or len(stats) < 2:
            # Nao grava linha vazia de proposito: `match_statistics` sem folha
            # e' pior que a ausencia da linha -- a varredura procura jogo
            # ENCERRADO SEM LINHA, entao a linha oca esconderia a partida dela
            # pra sempre.
            #
            # `criar_sem_folha` e' a excecao, e ela so' chega por clique
            # explicito no /admin: e' o jogo que a API nunca vai publicar, e a
            # linha oca e' o que permite digitar os numeros a mao depois. O
            # placar, o status e o arbitro ai' vem de /fixtures, que responde
            # mesmo quando a folha nao existe -- so' os contadores ficam NULL.
            print(f"[MATCH_STATS] fixture_id={fixture_id} sem stats de jogo na API.")
            if not criar_sem_folha:
                return "sem_folha"
            if not self._save_stats(fx, [], []):
                return "sem_placar"
            if fx.get("referee"):
                referee_batch.add((fx["referee"], fx["season"]))
            return "linha_sem_folha"

        home_stats, away_stats, home_1h, away_1h = self._separar_lados(stats, home_id)

        if not self._save_stats(fx, home_stats, away_stats, home_1h, away_1h):
            return "sem_placar"

        if fx.get("referee"):
            referee_batch.add((fx["referee"], fx["season"]))
        return "gravada"

    def sync_one_fixture(self, fixture_id: int, criar_sem_folha: bool = False) -> dict:
        """`_sync_uma_fixture` com conexao propria · o que o /admin chama."""
        self._open()
        referee_batch: set = set()
        try:
            situacao = self._sync_uma_fixture(fixture_id, referee_batch, criar_sem_folha)
            self._sync_referee_stats(referee_batch)
            return {"fixture_id": fixture_id, "situacao": situacao}
        finally:
            self._close()

    # ---------------------------------------------------------
    # MAIN
    # ---------------------------------------------------------
    def sync_all_finished_fixtures(self, use_date_filter=True, days=3, apenas_liga=None,
                                   temporada=None, exigir_os_dois_times=True,
                                   ultimas_rodadas=None, teto_requisicoes=None):
        """`teto_requisicoes` (2026-09-24): para a rodada depois de N folhas
        buscadas. E' o freio de COTA do backfill de temporada anterior -- a
        varredura e' idempotente (o jogo com folha completa entra em
        `settled_fixture_ids` e nao volta), entao parar no meio e' seguro e
        continuar e' so' rodar de novo. Os outros parametros novos estao
        documentados em `_load_fixtures`.
        """
        print("[MATCH_STATS] START")

        self._open()

        fixtures = self._load_fixtures(
            use_date_filter, days, apenas_liga=apenas_liga, temporada=temporada,
            exigir_os_dois_times=exigir_os_dois_times,
            ultimas_rodadas=ultimas_rodadas)
        referee_batch = set()
        buscadas = 0

        for fx in fixtures:
            if teto_requisicoes is not None and buscadas >= teto_requisicoes:
                print(f"[MATCH_STATS] Teto de {teto_requisicoes} requisicoes atingido · "
                      f"{len(fixtures) - buscadas} jogo(s) ficaram pra proxima rodada.")
                break
            buscadas += 1
            stats = self._fetch_match_stats(fx["fixture_id"])

            if not stats or len(stats) < 2:
                continue

            home_stats, away_stats, home_1h, away_1h = self._separar_lados(
                stats, fx["home_id"])

            if not self._save_stats(fx, home_stats, away_stats, home_1h, away_1h):
                continue

            if fx.get("referee"):
                referee_batch.add((fx["referee"], fx["season"]))

        self._sync_referee_stats(referee_batch)
        self._close()
        print("[MATCH_STATS] DONE")

    # ---------------------------------------------------------
    # BACKFILL DO 1o TEMPO
    # ---------------------------------------------------------
    def backfill_primeiro_tempo(self, teto_requisicoes: int = 100,
                                temporada_minima: int = 2024) -> dict:
        """Busca a folha por tempo das partidas JA gravadas que nunca a tiveram.

        A coleta diaria passou a pedir `half=true` em 27/09/2026, entao so' o
        historico anterior precisa disto. Cada partida custa 1 requisicao, e o
        historico inteiro passa de mil -- por isso o teto, e por isso a ordem:
        da mais recente pra mais antiga, que e' a que o motor le primeiro
        (`temporal_decay_weight` pesa menos o jogo velho).

        `temporada_minima`: a API so' publica estatistica por tempo a partir da
        temporada 2024; pedir antes disso e' gastar cota pra receber vazio.

        Idempotente: `stats_1h_checked_at` tira a partida da fila tenha a folha
        vindo ou nao, entao rodar de novo continua de onde parou.
        """
        gastas_no_placar = self.backfill_placar_intervalo(teto_requisicoes)
        teto_requisicoes -= gastas_no_placar
        if teto_requisicoes <= 0:
            return {"buscadas": 0, "com_folha": 0, "sem_folha": 0, "restantes": None}

        self._open()
        try:
            self.cur.execute("""
                SELECT fixture_id, home_team_id
                  FROM match_statistics
                 WHERE (stats_1h_checked_at IS NULL OR finalizacao_checked_at IS NULL)
                   AND status IN %s
                   AND season >= %s
                 ORDER BY match_date DESC
                 LIMIT %s;
            """, (tuple(self.FINISHED), temporada_minima, teto_requisicoes))
            fila = self.cur.fetchall()
            com_folha = sem_folha = 0
            for fixture_id, home_id in fila:
                try:
                    stats = self._fetch_match_stats(fixture_id)
                except Exception as e:
                    # Falha de rede nao marca a partida: ela volta na proxima.
                    print(f"[MATCH_STATS_1T] fixture_id={fixture_id}: {e}")
                    continue
                if not stats or len(stats) < 2:
                    self._gravar_primeiro_tempo(fixture_id, [], [])
                    # Sem folha nenhuma: marca a finalizacao tambem, senao a
                    # partida voltaria todo dia pela segunda condicao da fila.
                    self.cur.execute("UPDATE match_statistics SET finalizacao_checked_at = NOW() "
                                     "WHERE fixture_id = %s", (fixture_id,))
                    sem_folha += 1
                else:
                    home_cheia, away_cheia, home_1h, away_1h = self._separar_lados(stats, home_id)
                    self._gravar_primeiro_tempo(fixture_id, home_1h or [], away_1h or [])
                    self._gravar_finalizacao(fixture_id, home_cheia, away_cheia)
                    if folha_publicada(home_1h) and folha_publicada(away_1h):
                        com_folha += 1
                    else:
                        sem_folha += 1
                self.conn.commit()
            self.cur.execute("""
                SELECT COUNT(*) FROM match_statistics
                 WHERE (stats_1h_checked_at IS NULL OR finalizacao_checked_at IS NULL)
                   AND status IN %s AND season >= %s;
            """, (tuple(self.FINISHED), temporada_minima))
            restantes = self.cur.fetchone()[0]
        finally:
            self._close()
        resumo = {"buscadas": com_folha + sem_folha, "com_folha": com_folha,
                  "sem_folha": sem_folha, "restantes": restantes}
        print(f"[MATCH_STATS_1T] {resumo}")
        return resumo

    #: Quantas partidas `/fixtures?ids=` aceita numa requisicao (limite da API).
    _IDS_POR_REQUISICAO = 20

    def backfill_placar_intervalo(self, teto_requisicoes: int = 100) -> int:
        """Completa `home_goals_ht`/`away_goals_ht` onde estao NULL. Devolve
        quantas requisicoes gastou.

        Medido em DEV em 27/09/2026: 403 de 926 partidas encerradas sem placar
        do intervalo. E' a familia mais valiosa do 1o tempo (gol) com quase
        metade da amostra faltando, e a folha por tempo nao resolve -- o placar
        vem de /fixtures, nao de /fixtures/statistics.

        Barato: `/fixtures?ids=` devolve 20 partidas por requisicao, entao o
        buraco inteiro de DEV custa ~21. Placar ausente na resposta continua
        NULL (nunca 0x0, ver o comentario em _load_fixtures), e a partida volta
        na proxima passada.
        """
        self._open()
        gastas = 0
        preenchidas = 0
        try:
            self.cur.execute("""
                SELECT fixture_id FROM match_statistics
                 WHERE (home_goals_ht IS NULL OR away_goals_ht IS NULL)
                   AND status IN %s
                 ORDER BY match_date DESC
                 LIMIT %s;
            """, (tuple(self.FINISHED), teto_requisicoes * self._IDS_POR_REQUISICAO))
            ids = [r[0] for r in self.cur.fetchall()]
            for i in range(0, len(ids), self._IDS_POR_REQUISICAO):
                lote = ids[i:i + self._IDS_POR_REQUISICAO]
                try:
                    resposta = buscar(FIXTURES_URL, {"ids": "-".join(map(str, lote))},
                                      origem="coletor_stats")
                except Exception as e:
                    print(f"[MATCH_STATS_1T] placar do intervalo, lote {lote[0]}..: {e}")
                    continue
                finally:
                    gastas += 1
                pares = []
                for item in resposta or []:
                    ht = (item.get("score") or {}).get("halftime") or {}
                    if ht.get("home") is None or ht.get("away") is None:
                        continue
                    pares.append((ht["home"], ht["away"], item["fixture"]["id"]))
                if pares:
                    from psycopg2.extras import execute_values
                    execute_values(self.cur, """
                        UPDATE match_statistics ms
                           SET home_goals_ht = d.h, away_goals_ht = d.a
                          FROM (VALUES %s) AS d(h, a, fixture_id)
                         WHERE ms.fixture_id = d.fixture_id
                    """, pares)
                    preenchidas += len(pares)
                self.conn.commit()
        finally:
            self._close()
        print(f"[MATCH_STATS_1T] placar do intervalo: {preenchidas} partida(s) "
              f"em {gastas} requisicao(oes).")
        return gastas