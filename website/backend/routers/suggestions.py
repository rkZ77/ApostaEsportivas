from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.concurrency import run_in_threadpool
from typing import Optional
import json
import logging
import re
import psycopg2.extras
from database import get_connection
from auth_utils import get_current_user, get_current_user_optional, require_vip, is_vip_active
from routers.banca import _compute_bankroll_current
from routers.live import _stat_for_market, maybe_resolve_pending
import market_form
from settlement_bridge import settlement
# Perfil de competicao do MOTOR. E' quem sabe se uma liga usa historico de
# TODAS as competicoes (copa de clube e selecao) -- ver o comentario em
# _jogos_do_time. Import tolerante: sem o pipeline no caminho a serie volta ao
# recorte de liga, que e' o comportamento de antes.
try:
    from services.pick_engine import competition_profile as _competicao
except Exception:  # pragma: no cover
    _competicao = None
import alavancagem_caminho
from stake_plan import STAKE_PADRAO
from pick_sources import tabela_existe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])

_EV_IN_REASONING_RE = re.compile(r"EV[:=]\s*([+-]?\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)


def _ev_from_reasoning(text: str | None) -> float | None:
    """Fallback pra picks_alavancagem gravados antes da coluna ev_combined
    existir (ver engine_pipelines/alavancagem_pipeline.py) -- o EV sempre
    esteve no texto do reasoning, so nunca tinha sido extraido pra um campo
    estruturado. Cobre os dois formatos ja usados: motor determinístico
    ("EV: +16.8%") e o pipeline antigo de IA ("EV=+8.2%")."""
    if not text:
        return None
    m = _EV_IN_REASONING_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ".")) / 100
    except ValueError:
        return None

_MARKET_PT = {
    "match winner": "Resultado Final (1X2)",
    "double chance": "Dupla Chance",
    "both teams score": "Ambas as Equipes Marcam",
    "both teams to score": "Ambas as Equipes Marcam",
    "goals over/under": "Gols Mais/Menos",
    "goals over/under first half": "Gols Mais/Menos - 1º Tempo",
    "goals over/under second half": "Gols Mais/Menos - 2º Tempo",
    "goals over/under - second half": "Gols Mais/Menos - 2º Tempo",
    "corners over under": "Escanteios Mais/Menos",
    "corners over/under": "Escanteios Mais/Menos",
    "corners 1x2": "Escanteios 1x2",
    "cards over/under": "Cartões Mais/Menos",
    "home corners over/under": "Escanteios Casa Mais/Menos",
    "away corners over/under": "Escanteios Visitante Mais/Menos",
    "home total corners (1st half)": "Escanteios Casa (1º Tempo)",
    "away total corners (1st half)": "Escanteios Visitante (1º Tempo)",
    "total corners (1st half)": "Total de Escanteios (1º Tempo)",
    "total corners (2nd half)": "Total de Escanteios (2º Tempo)",
    "home team total cards": "Total de Cartões Casa",
    "away team total cards": "Total de Cartões Visitante",
    "home team total goals(1st half)": "Total de Gols Casa (1º Tempo)",
    "away team total goals(1st half)": "Total de Gols Visitante (1º Tempo)",
    "total - home": "Total de Gols Casa",
    "total - away": "Total de Gols Visitante",
    "first half winner": "Vencedor do 1º Tempo",
    "both teams to score - first half": "BTTS - 1º Tempo",
    # Chutes, impedimentos, faltas e defesas (2026-08-17). Existiam em
    # marketTranslate.ts (front) e faltavam aqui · esta tabela era um
    # SUBCONJUNTO da do front, e é ela que serve as respostas em markdown e o
    # servidor MCP, ou seja os caminhos SEM React. O pick free de 17/08 saiu
    # como "Total Shots" e só o React o traduzia.
    #
    # A raiz foi corrigida no coletor (odds_collector_service.
    # _MARKET_NAME_PT_FALLBACK, que deixava market_pt NULL). Estas entradas
    # cobrem o histórico já gravado em inglês, que não é reprocessado.
    "total shots": "Finalizações Mais/Menos",
    "total shotongoal": "Finalizações no Gol Mais/Menos",
    "total shots on goal": "Finalizações no Gol Mais/Menos",
    "shots on goal": "Finalizações no Gol Mais/Menos",
    "offsides total": "Impedimentos Mais/Menos",
    "offsides home total": "Impedimentos Casa Mais/Menos",
    "offsides away total": "Impedimentos Visitante Mais/Menos",
    "fouls. total": "Faltas Mais/Menos",
    "fouls. home total": "Faltas Casa Mais/Menos",
    "fouls. away total": "Faltas Visitante Mais/Menos",
    "fouls": "Faltas Mais/Menos",
    "goalkeeper saves": "Defesas do goleiro",
    "home team total goals": "Total de Gols Casa",
    "away team total goals": "Total de Gols Visitante",
    "total - home goals over/under": "Total de Gols Casa",
    "total - away goals over/under": "Total de Gols Visitante",
}
_TEAM_PAT = [
    (r"^(.+?)\s*-\s*goals over/under\s*$",   r"\1 - Gols Mais/Menos"),
    (r"^(.+?)\s*-\s*total goals?\s*$",        r"\1 - Total de Gols"),
    (r"^(.+?)\s*-\s*corners over/?under\s*$", r"\1 - Escanteios Mais/Menos"),
    (r"^(.+?)\s*-\s*total corners?\s*$",      r"\1 - Total de Escanteios"),
    (r"^(.+?)\s*-\s*cards over/?under\s*$",   r"\1 - Cartões Mais/Menos"),
]

def _tr(market: str) -> str:
    if not market:
        return market
    k = market.strip().lower()
    if k in _MARKET_PT:
        return _MARKET_PT[k]
    for pat, rep in _TEAM_PAT:
        if re.match(pat, k, re.IGNORECASE):
            return re.sub(pat, rep, market.strip(), flags=re.IGNORECASE)
    return market


def _safe_query(cur, sql, params=()):
    """Executa query e retorna resultados, ou [] se tabela não existir."""
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception:
        cur.connection.rollback()
        return []


def _safe_query_one(cur, sql, params=()):
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    except Exception:
        cur.connection.rollback()
        return None


#: A escalacao de cada pick de jogador, numa consulta separada da lista.
#:
#: POR QUE SEPARADA, E NAO UM JOIN NA CONSULTA DOS PICKS (02/09)
#: ------------------------------------------------------------
#: Porque `_safe_query` devolve LISTA VAZIA quando qualquer coisa falha, e essa
#: e' a decisao certa pra "tabela que ainda nao existe nesta instancia" -- mas
#: aplicada a consulta inteira ela transforma um detalhe ausente no
#: desaparecimento do produto. Foi exatamente o que aconteceu: com o JOIN em
#: `fixture_lineups` e a coluna `void_reason` dentro do SELECT dos picks, um
#: backend que ainda nao tinha rodado a migration parou de mostrar QUALQUER
#: pick de jogador, em silencio.
#:
#: Aqui a regra fica explicita: a lista de picks nunca depende de um campo
#: opcional. Se esta consulta falhar, os picks aparecem sem o aviso de
#: escalacao, que e' degradar o recurso novo em vez de esconder o antigo.
#:
#:   'indefinida' -- a escalacao oficial ainda nao saiu;
#:   'titular'    -- o jogador esta no XI inicial;
#:   'banco'      -- esta relacionado, comeca no banco. O PICK CONTINUA DE PE:
#:                   aposta de estatistica individual vale se ele entrar em
#:                   campo, e ele ainda pode entrar;
#:   'fora'       -- nem foi relacionado (o pick ja' foi anulado pela
#:                   varredura, e `void_reason` diz por que).
#: O que decidiu o resultado, anexado a uma lista de picks já carregada.
#:
#: MESMA REGRA DA ESCALAÇÃO, e pelo mesmo motivo: campo opcional NÃO entra na
#: consulta que traz os picks. `settled_value` e `void_reason` são colunas
#: novas, e `picks_live` nasce no motor -- uma instância sem elas faria o
#: `_safe_query` devolver lista vazia e o produto inteiro sumir da tela, que é
#: exatamente o defeito que já aconteceu com o pick de jogador em 02/09.
#:
#: Falhando aqui, os picks aparecem sem a linha de conferência. Degrada o
#: recurso novo, não esconde o antigo.
def _juntar_auditoria(cur, picks: list, tabela: str) -> None:
    """Anexa `settled_value` e `void_reason` a cada pick, se as colunas existirem."""
    ids = [p["id"] for p in picks or [] if p.get("id") is not None]
    if not ids:
        return
    linhas = _safe_query(cur, f"""
        SELECT id, settled_value, void_reason
          FROM {tabela}
         WHERE id = ANY(%s)
    """, (ids,))
    por_id = {r["id"]: r for r in linhas}
    for p in picks:
        extra = por_id.get(p.get("id"))
        p["settled_value"] = (float(extra["settled_value"])
                              if extra and extra.get("settled_value") is not None else None)
        p["void_reason"] = extra["void_reason"] if extra else None


def _juntar_escalacao(cur, picks: list) -> None:
    """Anexa `escalacao` e `void_reason` a cada pick de jogador, se der."""
    ids = [p["id"] for p in picks or [] if p.get("id") is not None]
    if not ids:
        return
    linhas = _safe_query(cur, """
        SELECT pp.id, pp.void_reason,
               CASE
                 WHEN COALESCE(fl.oficial, FALSE) = FALSE THEN 'indefinida'
                 WHEN pp.player_id = ANY(fl.titulares)     THEN 'titular'
                 WHEN pp.player_id = ANY(fl.reservas)      THEN 'banco'
                 ELSE 'fora'
               END AS escalacao
          FROM picks_player_stats pp
     LEFT JOIN fixture_lineups fl ON fl.fixture_id = pp.fixture_id
         WHERE pp.id = ANY(%s)
    """, (ids,))
    por_id = {r["id"]: r for r in linhas}
    for p in picks:
        extra = por_id.get(p.get("id"))
        p["escalacao"] = extra["escalacao"] if extra else None
        p["void_reason"] = extra["void_reason"] if extra else None


def _get_user_banca(cur, user_id: int):
    """Retorna (bankroll_current, unit_value) ou None se banca não configurada.

    Reusa _compute_bankroll_current (mesma função de GET /banca e /banca/summary)
    em vez de somar o PnL de todo o histórico aqui: sem o corte por epoch do
    último fechamento mensal, essa conta dava banca inflada pra sempre depois do
    primeiro fechamento (somava de novo o PnL que já tinha virado bankroll_start).
    """
    row = _safe_query_one(cur, """
        SELECT bankroll_start, unit_value FROM user_banca WHERE user_id = %s
    """, (user_id,))
    if not row:
        return None
    unit_value = float(row["unit_value"]) if row["unit_value"] else 0
    if unit_value <= 0:
        return None
    bankroll_start = float(row["bankroll_start"])
    bankroll = _compute_bankroll_current(cur, user_id, bankroll_start, unit_value)
    return bankroll, unit_value


#: Colunas do pick ao vivo que a aba Hoje precisa.
#:
#: E' o mesmo conjunto que o card do produto ja consome em /live-picks/feed,
#: menos o "estado agora" da partida -- este e' o unico que custa API, e a aba
#: Hoje nao acompanha jogo em andamento minuto a minuto: ela e' o resumo do
#: dia. Quem quiser o placar ao vivo tem a aba Ao Vivo ao lado.
_LIVE_COLUNAS = """
    pl.id, pl.fixture_id, pl.match_date, pl.league_id, pl.league_name,
    pl.home_team_id, pl.away_team_id,
    pl.home_team_name, pl.away_team_name,
    pl.market, pl.market_type, pl.line, pl.odd, pl.bet_house,
    pl.minute_at_creation, pl.home_goals_at_creation, pl.away_goals_at_creation,
    pl.probability, pl.probability AS prob_real, pl.ev, pl.edge, pl.confidence,
    pl.stake_units, pl.reasoning, pl.status, pl.odd_valid_until,
    pl.result, pl.profit, pl.created_at
"""


def _picks_live_do_dia(cur, where: str, params: tuple) -> list:
    """Os picks ao vivo daquele dia, rolando e liquidados.

    POR QUE ELES ENTRAM NA ABA HOJE (2026-08-29, pedido do usuario)
    ---------------------------------------------------------------
    O Ao Vivo era o unico produto que so' existia na aba dele. A aba Hoje e' o
    resumo do dia -- "o que a IA publicou e no que deu" -- e um produto inteiro
    fora dela faz o resumo mentir por omissao, principalmente no dia em que o
    ao vivo foi o unico a produzir.

    ORDEM: pendente primeiro, depois o mais recente. E' a mesma leitura da aba
    do produto, e pelo mesmo motivo -- o que ainda da' pra apostar vale mais
    que o que ja fechou.

    `picks_live` nasce do MOTOR, nao do site: onde o motor nunca rodou a tabela
    nao existe. `_safe_query` devolve lista vazia nesse caso, que e' o
    comportamento certo (o produto some da aba, nao derruba a tela).
    """
    picks = [dict(r) for r in _safe_query(cur, f"""
        SELECT {_LIVE_COLUNAS}
          FROM picks_live pl
         WHERE {where}
         ORDER BY (pl.result IS NOT NULL), pl.created_at DESC
    """, params)]
    # O número que decidiu o resultado, numa consulta separada · ver
    # _juntar_auditoria.
    _juntar_auditoria(cur, picks, "picks_live")
    return picks


def _compute_suggested_stake_units(
    pick_type: str,
    stake_pct,
    confidence,
    odd,
    ev,
    bankroll: float,
    unit_value: float,
) -> int:
    """
    Calcula unidades sugeridas baseado no tipo de pick e banca real do usuário.
    Lógica exclusiva do backend · não recalcular no frontend.

    Caps por tipo:
      VIP      → usa stake_pct do DB (calculate_stake), max 5% da banca
      Free     → Kelly ½ com max 2% da banca, max 6 unidades
      Múltipla → Kelly ¼ com max 2.5% da banca, max 3 unidades
    """
    if not bankroll or not unit_value or unit_value <= 0:
        return 1

    KELLY_FR  = {'vip': 0.50, 'free': 0.50, 'multipla': 0.25}
    kelly_frac = KELLY_FR.get(pick_type, 0.5)

    conf  = float(confidence or 0)
    odd_f = float(odd or 0)
    ev_f  = float(ev or 0)

    # EV nulo: deriva de confidence × odd como fallback (prob_real ausente em picks antigos)
    if ev_f <= 0 and conf > 0 and odd_f > 1:
        ev_f = max(0.0, conf * odd_f - 1.0)

    # VIP: stake_pct já calculado pelo backend com Kelly ajustado
    if pick_type == 'vip' and stake_pct and float(stake_pct) > 0:
        # Cap por tier de confiança · diferencia unidades em vez de sempre ir ao máximo
        if conf >= 0.80 and ev_f > 0.10:
            max_pct, max_units = 0.05, 10
        elif conf >= 0.72 and ev_f > 0.05:
            max_pct, max_units = 0.04, 7
        else:
            max_pct, max_units = 0.03, 5
        final_pct = min(float(stake_pct), max_pct)
    else:
        # Free / Múltipla / mercados próprios / VIP sem stake_pct: Kelly direto
        #
        # Os mercados de modelo próprio herdam o teto percentual do Free: são
        # picks de perna única com amostra histórica menor que a do VIP, que é
        # exatamente o critério que já definiu o teto de UNIDADES deles em
        # banca.STAKE_LIMITS. Boost fica um degrau abaixo por ser combinado.
        #
        # `live` entra com o teto do free (2%) e nao com o default de 3%: o
        # produto e' entrada simples, mas a odd pode mudar entre a publicacao e
        # a aposta -- e' o mesmo motivo que da' ao ao vivo o teto de UNIDADES
        # mais baixo do site (banca.STAKE_LIMITS['live'] = 4). Sem a chave ele
        # caia no default, que e' mais frouxo que o do free num produto mais
        # volatil que o free.
        MAX_PCT = {'free': 0.02, 'multipla': 0.025,
                   'faltas': 0.02, 'goleiros': 0.02, 'player_stats': 0.02,
                   'live': 0.02,
                   'boost': 0.015}
        max_pct = MAX_PCT.get(pick_type, 0.03)

        # EV negativo sem base sólida → stake mínimo (1u)
        if ev_f <= 0 and pick_type != 'multipla':
            return 1

        if odd_f <= 1 or conf <= 0 or conf >= 1:
            return 1

        b = odd_f - 1.0
        q = 1.0 - conf
        kelly = (b * conf - q) / b
        if kelly <= 0:
            return 1

        final_pct = min(max_pct, kelly * kelly_frac)
        final_pct = max(0.005, final_pct)

        # O TETO DE UNIDADES VEM DE banca.STAKE_LIMITS, e não de uma segunda
        # lista aqui (2026-08-28).
        #
        # Este dict tinha só `free` e `multipla`, e todo tipo novo caía no
        # default de 9999 · ou seja, SEM teto. A sugestão podia passar do que o
        # `POST /banca/follow` aceita, e o usuário só descobriria no erro,
        # depois de confirmar. É o mesmo defeito que MAX_UNITS_POR_TIPO já
        # corrigiu do lado do card.
        #
        # Import local pra não criar ciclo: banca.py importa deste módulo.
        from routers.banca import STAKE_LIMITS
        limite = STAKE_LIMITS.get(pick_type)
        max_units = limite[1] if limite else 9999

    stake_amount = final_pct * bankroll
    units = round(stake_amount / unit_value)
    return max(1, min(max_units, units))


def _sql_escudo(lado: str, perna: int, fx_alias: str | None, home_col: str, away_col: str,
                date_col: str = "pa.match_date") -> str:
    """Expressao SQL que resolve o team_id de uma perna de alavancagem.

    A FONTE E' A COLUNA DO PICK · o resto e' resgate do historico.

    Desde 2026-08-28 `picks_alavancagem` guarda `home_team_id_N` e
    `away_team_id_N`, gravados pelo motor no instante da decisao, igual
    `picks_free` e `picks_vip` sempre fizeram. Pick novo responde na primeira
    parte do COALESCE e nao encosta em mais nada.

    Os passos seguintes existem pros picks gravados ANTES dessa coluna, e pro
    que a migracao de backfill nao conseguiu reconstruir.

    POR QUE ISTO EXISTE (2026-08-28, pick Nautico x Athletic Club)
    -------------------------------------------------------------
    Antes da coluna, o escudo vinha do JOIN com `fixtures` pelo
    `fixture_id_N`, e quando esse JOIN falhava havia um plano B:

        (SELECT fx.away_team_id FROM fixtures fx
          WHERE fx.away_team = pa.away_team_1 LIMIT 1)

    Casar por NOME solto, em toda a tabela, sem data e sem ORDER BY. E
    "Athletic Club" e' o nome de dois clubes diferentes na API-Football: o de
    Minas Gerais (13975) e o Athletic Bilbao (531). O `LIMIT 1` pegava
    qualquer um · foi assim que um pick da Serie B apareceu com o escudo
    vermelho e branco do Bilbao no card e na imagem de compartilhamento.

    E o JOIN falhava justamente DEPOIS de o pick ser liquidado: `fixtures` so'
    guarda a janela corrente (ver o coletor), entao o jogo de ontem some da
    tabela e o pick de ontem perde o id. Por isso o usuario via o escudo
    enquanto o pick estava pendente e o via sumir · ou trocar de time · quando
    saia o GREEN.

    A CADEIA AGORA, do mais especifico pro mais geral:

    0. A coluna `{lado}_team_id_N` do proprio pick · fato gravado, nao
       reconsulta. E' a unica que responde pra pick novo.
    1. `fixtures` pelo `fixture_id` da perna · so' existe pras pernas 1 e 2, e
       so' enquanto o jogo esta na janela.
    2. `fixtures` pelo PAR de nomes mais a data. Identifica a partida, nao um
       time: dois clubes homonimos nao jogam contra o mesmo adversario no
       mesmo dia. E' o unico caminho que a perna 3 tem, porque ela nao guarda
       fixture_id nenhum.
    3. `teams` DESEMPATADA PELO ADVERSARIO. `teams` nao e' podada por data ·
       e' ela que devolve o escudo do pick de ontem. Mas o nome sozinho nao
       basta, e "Athletic Club" e a prova: La Liga esta entre as ligas
       acompanhadas, entao o Bilbao mora nessa tabela ao lado do mineiro.
       O desempate vem de graca do proprio pick · os dois times de uma
       partida disputam a mesma competicao, entao basta exigir que o time
       procurado apareca em alguma liga onde o ADVERSARIO tambem aparece.
       "Nautico Recife" e' unico, esta na liga 72, e so' um dos dois Athletic
       Club esta la.
    4. `teams` pelo nome apenas, quando o adversario tambem e' ambiguo ou nao
       esta cadastrado.

    Os passos 3 e 4 so' respondem quando sobra UM time: o
    `HAVING COUNT(DISTINCT t.team_id) = 1` faz o homonimo irredutivel devolver
    NULL. NULL desenha o card sem escudo, e sem escudo e' melhor que com o
    escudo errado: o card sem imagem diz "nao sei"; o card com o brasao do
    Bilbao num jogo da Serie B diz uma coisa falsa com toda a confianca.
    """
    col = f"{lado}_team_id"
    pick_col = f"pa.{lado}_team_id_{perna}"
    nome_col = home_col if lado == "home" else away_col
    adversario_col = away_col if lado == "home" else home_col

    partes = [pick_col]
    if fx_alias:
        partes.append(f"{fx_alias}.{col}")
    partes.append(
        f"(SELECT fx.{col} FROM fixtures fx"
        f"  WHERE fx.home_team = {home_col} AND fx.away_team = {away_col}"
        f"    AND fx.match_datetime::date = {date_col} LIMIT 1)"
    )
    partes.append(
        f"(SELECT MIN(t.team_id) FROM teams t"
        f"  WHERE t.name = {nome_col}"
        f"    AND t.league_id IN (SELECT adv.league_id FROM teams adv"
        f"                         WHERE adv.name = {adversario_col})"
        f" HAVING COUNT(DISTINCT t.team_id) = 1)"
    )
    partes.append(
        f"(SELECT MIN(t.team_id) FROM teams t WHERE t.name = {nome_col}"
        f" HAVING COUNT(DISTINCT t.team_id) = 1)"
    )
    return "COALESCE(" + ", ".join(partes) + ")"


def _sql_escudos_alav(pernas: int, com_fixture: int = 2, date_col: str = "pa.match_date") -> str:
    """As colunas home_team_id_N / away_team_id_N de N pernas, prontas pro SELECT.

    `com_fixture` diz quantas pernas tem coluna `fixture_id_N` na tabela (hoje
    duas) e portanto quantas tem alias de JOIN pra tentar primeiro.
    """
    linhas = []
    for n in range(1, pernas + 1):
        alias = f"f{n}" if n <= com_fixture else None
        home, away = f"pa.home_team_{n}", f"pa.away_team_{n}"
        linhas.append(f"{_sql_escudo('home', n, alias, home, away, date_col)} AS home_team_id_{n}")
        linhas.append(f"{_sql_escudo('away', n, alias, home, away, date_col)} AS away_team_id_{n}")
    return ",\n                   ".join(linhas)


def _enrich_multipla_legs(cur, rows: list) -> list:
    """Enriquece o JSONB de legs das múltiplas com home/away team IDs e nomes via fixtures.

    UMA consulta pra todas as pernas de todas as multiplas. Antes era uma por
    perna, dentro de dois lacos aninhados: tres multiplas de tres pernas viravam
    nove idas ao banco (154ms cada, ver database.py:71-82) so' pra buscar nome e
    escudo de time. O lote nao muda nada na saida -- mesmo dicionario, mesmos
    campos, mesmo fallback pro que nao existe mais em `fixtures`.
    """
    import json as _json

    # 1ª passada: normaliza o JSONB e junta os fixture_id de todo mundo.
    multiplas: list[tuple[dict, list]] = []
    fids: set[int] = set()
    for row in rows:
        m = dict(row)
        legs = m.get("legs") or []
        if isinstance(legs, str):
            try:
                legs = _json.loads(legs)
            except Exception:
                legs = []
        legs = [dict(leg) if isinstance(leg, dict) else leg
                for leg in (legs if isinstance(legs, list) else [])]
        for leg in legs:
            fid = leg.get("fixture_id") if isinstance(leg, dict) else None
            if fid:
                fids.add(fid)
        multiplas.append((m, legs))

    por_fixture: dict = {}
    if fids:
        por_fixture = {r["fixture_id"]: r for r in _safe_query(cur, """
            SELECT fixture_id, home_team, away_team, home_team_id, away_team_id, league_id
            FROM fixtures WHERE fixture_id = ANY(%s)
        """, (list(fids),))}

    # 2ª passada: aplica o que veio do lote.
    result = []
    for m, legs in multiplas:
        for leg in legs:
            fid = leg.get("fixture_id") if isinstance(leg, dict) else None
            if not fid:
                continue
            fx = por_fixture.get(fid)
            if fx:
                leg.update({
                    "home": fx["home_team"],
                    "away": fx["away_team"],
                    "home_team_id": fx["home_team_id"],
                    "away_team_id": fx["away_team_id"],
                    "league_id":    fx["league_id"],
                })
            else:
                # fixture não existe mais na tabela · usa nomes salvos no JSON
                leg.setdefault("home", leg.get("home_team", ""))
                leg.setdefault("away", leg.get("away_team", ""))
        m["legs"] = legs
        result.append(m)
    return result



def _teaser_de_multipla(row) -> dict:
    """Multipla trancada: quantas selecoes e quais jogos, sem os mercados.

    "3 selecoes, odd 4.20" ja diz se vale a pena olhar. O que cada perna e' --
    o mercado e a linha -- e' a analise, e essa fica dentro do VIP. Mesmo corte
    de public.py::pick_meta, que ja faz isso no link compartilhado.
    """
    d = dict(row)
    jogos = d.get("games")
    if isinstance(jogos, str):
        try:
            jogos = json.loads(jogos)
        except Exception:
            jogos = []
    jogos = jogos or []
    d.pop("games", None)
    d["total_legs"] = len(jogos)
    d["teams_preview"] = [
        f"{g.get('home_team', '?')} x {g.get('away_team', '?')}" for g in jogos[:4]
    ]
    return d


def _teaser_de_alavancagem(row) -> dict:
    """Alavancagem trancada: os jogos do caminho e a odd combinada."""
    d = dict(row)
    times = []
    for i in (1, 2, 3):
        casa, fora = d.pop(f"home_team_{i}", None), d.pop(f"away_team_{i}", None)
        if casa and fora:
            times.append(f"{casa} x {fora}")
    d["total_legs"] = len(times)
    d["teams_preview"] = times
    return d


def _marcar_boost_free(picks: list) -> None:
    """Marca `plano` em cada pick do Boost · o primeiro e' free, o resto e' VIP.

    A lista JA' chega ordenada por score (a consulta ordena), entao "o primeiro"
    e' "o de maior Score Estatistico" -- o mesmo criterio que ordena a lista do
    assinante. Sem isso o free podia cair no meio do ranking VIP e parecer
    escolha aleatoria.

    O campo e' explicito e nao inferido pela posicao: a tela reordena (por odd,
    por data) e a marca tem que sobreviver a isso.
    """
    for i, p in enumerate(picks or []):
        p["plano"] = "free" if i == 0 else "vip"


@router.get("/today")
def get_today_suggestions(
    current_user: dict = Depends(get_current_user),
    date: Optional[str] = Query(None, description="YYYY-MM-DD · deixar vazio para hoje"),
):
    is_vip = is_vip_active(current_user)
    # Abrir a tela de picks é o que mantém os resultados em dia: a varredura
    # roda em segundo plano (no máximo uma a cada poucos minutos, e só quando
    # há pick pendente de jogo já iniciado), então esta chamada não espera por
    # ela nem falha por causa dela. Ver routers/live.py::maybe_resolve_pending.
    try:
        maybe_resolve_pending()
    except Exception:
        logger.warning("[AUTO-RESULT] gatilho em /today falhou", exc_info=True)

    # E a estatistica das encerradas, pelo mesmo motivo e com freios proprios.
    try:
        from stats_sweep import maybe_sync_finished_stats
        maybe_sync_finished_stats()
    except Exception:
        logger.warning("[STATS-SWEEP] gatilho em /today falhou", exc_info=True)

    # E a ESCALACAO dos jogos com pick de jogador. Mesmo padrao, mesma razao:
    # a escalacao oficial sai perto do apito, e quem abre a tela nesse momento
    # e' justamente quem precisa saber se o jogador comeca. Ver
    # lineups_sweep.py -- os freios sao dele, esta chamada nao espera nada.
    try:
        from lineups_sweep import maybe_check_lineups
        maybe_check_lineups()
    except Exception:
        logger.warning("[LINEUP-SWEEP] gatilho em /today falhou", exc_info=True)

    conn = get_connection()
    cur = conn.cursor()
    try:
        result = {}

        if date:
            _d = (date,)
            _pf_where   = "pf.match_date = %s"
            _vip_where  = "s.match_date = %s"
            _m_where    = "match_date = %s"
            _alav_where = "pa.match_date = %s"
            _merc_where = "match_date = %s"
        else:
            _d = ()
            TODAY_BR    = "(NOW() AT TIME ZONE 'America/Sao_Paulo')::date"
            _pf_where   = f"pf.match_date = {TODAY_BR} OR (pf.result IS NULL AND pf.match_date >= {TODAY_BR} - INTERVAL '3 days')"
            _vip_where  = f"s.match_date = {TODAY_BR} OR (s.result IS NULL AND s.match_date >= {TODAY_BR} - INTERVAL '3 days')"
            _m_where    = f"match_date = {TODAY_BR} OR (result IS NULL AND match_date >= {TODAY_BR} - INTERVAL '3 days')"
            _alav_where = f"pa.match_date = {TODAY_BR} OR (pa.result IS NULL AND pa.match_date >= {TODAY_BR} - INTERVAL '3 days')"
            _merc_where = f"match_date = {TODAY_BR} OR (result IS NULL AND match_date >= {TODAY_BR} - INTERVAL '3 days')"

        _picks_free_sql = f"""
            SELECT pf.id, pf.fixture_id, pf.match_date, pf.home_team, pf.away_team,
                   pf.league_id, pf.league_name, pf.market, pf.market_type, pf.line, pf.odd, pf.bet_house,
                   pf.confidence, pf.prob_real, pf.prob_real AS probability, pf.edge,
                   CASE WHEN pf.prob_real IS NOT NULL AND pf.odd IS NOT NULL
                        THEN ROUND((pf.prob_real * pf.odd - 1)::numeric, 4)
                        ELSE NULL END AS ev,
                   pf.reasoning, pf.result, pf.profit,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                   f.match_datetime
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            WHERE {_pf_where}
            ORDER BY pf.match_date DESC, pf.created_at DESC
            LIMIT 1
        """

        if is_vip:
            row = _safe_query_one(cur, _picks_free_sql, _d)
            result["dica_do_dia"] = dict(row) if row else None

            # VIP picks completos com league_id e league_name
            rows = _safe_query(cur, f"""
                SELECT s.id, s.fixture_id, s.match_date,
                       s.home_team_name, s.away_team_name,
                       s.home_team_id, s.away_team_id,
                       s.market, s.line, s.odd, s.bet_house,
                       s.market_type, s.confidence, s.ev, s.probability,
                       s.stake_pct,
                       s.reasoning, s.result, s.profit,
                       f.league_id,
                       f.match_datetime,
                       l.name AS league_name
                FROM picks_vip s
                LEFT JOIN fixtures f ON f.fixture_id = s.fixture_id
                LEFT JOIN leagues l ON l.league_id = f.league_id
                WHERE {_vip_where}
                ORDER BY s.match_date DESC, s.confidence DESC
            """, _d)
            result["vip"] = [{**dict(r), "market": _tr(r["market"])} if r.get("market") else dict(r) for r in rows]

            # `confidence` continua sendo o COALESCE (compatibilidade: varios
            # consumidores ja leem esse nome). `probability` e' o campo LIMPO,
            # so' preenchido quando ha prob_combinada de verdade.
            #
            # A distincao importa no card: score_combo e' a media dos
            # final_score das pernas, nao uma probabilidade. Com um campo so',
            # o front nao tinha como saber se o numero que recebeu era chance
            # calculada ou score -- e acabava rotulando os dois igual. Com os
            # dois campos, PickProbability marca "estimada" so' na multipla
            # antiga que nao tem prob_combinada.
            rows_m = _safe_query(cur, f"""
                SELECT id, match_date,
                       games AS legs,
                       total_odd, COALESCE(prob_combinada, score_combo) AS confidence,
                       prob_combinada AS probability,
                       reasoning, result, profit, created_at
                FROM picks_multiplas
                WHERE {_m_where}
                ORDER BY match_date DESC, created_at DESC
                LIMIT 3
            """, _d)
            result["multiplas"] = _enrich_multipla_legs(cur, rows_m)

            # Alavancagem
            alav = _safe_query_one(cur, f"""
                SELECT pa.id, pa.match_date, pa.tipo,
                       pa.fixture_id_1, pa.fixture_id_2,
                       pa.home_team_1, pa.away_team_1, pa.market_1, pa.line_1, pa.odd_1, pa.bet_house_1,
                       pa.confidence_1, pa.prob_real_1, pa.reasoning_1,
                       pa.home_team_2, pa.away_team_2, pa.market_2, pa.line_2, pa.odd_2, pa.bet_house_2,
                       pa.confidence_2, pa.prob_real_2, pa.reasoning_2,
                       pa.home_team_3, pa.away_team_3, pa.market_3, pa.line_3, pa.odd_3, pa.bet_house_3,
                       pa.confidence_3, pa.prob_real_3, pa.reasoning_3,
                       pa.odd_combined, pa.confidence_media,
                       pa.result, pa.profit, pa.created_at,
                       {_sql_escudos_alav(3)}
                FROM picks_alavancagem pa
                LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
                LEFT JOIN fixtures f2 ON f2.fixture_id = pa.fixture_id_2
                WHERE {_alav_where}
                ORDER BY pa.match_date DESC
                LIMIT 1
            """, _d)
            result["alavancagem"] = dict(alav) if alav else None

            # Mercados proprios (faltas e defesas de goleiro).
            #
            # Entram no /today junto com VIP e multipla porque a aba "Mercados"
            # e' a aba do DIA, igual a de picks VIP -- pedido do usuario. Antes
            # ela lia /suggestions/faltas e /suggestions/goleiros com limit=50 e
            # sem filtro de data: era historico, entao a aba do dia mostrava
            # pick de semanas atras misturado com o de hoje.
            #
            # A janela e' a mesma dos outros (`_merc_where`): o dia escolhido,
            # mais o que ainda esta pendente ate' 3 dias atras. Sem essa cauda,
            # pick de jogo adiado sumiria da tela antes de ser resolvido.
            # ATENCAO AO EDITAR: ate 14/08 estas duas consultas rodavam aqui e
            # DE NOVO, cem linhas abaixo, num laco generico que sobrescrevia as
            # duas chaves. Eram quatro idas ao banco (com os _ufp_map junto) cujo
            # resultado nunca chegava no navegador. Pior: a segunda versao era
            # generica pras duas tabelas, entao nao trazia player_name/team_name
            # de goleiros -- o card perdia o nome do goleiro no caminho.
            #
            # Ficou so' esta versao, que e' a tipada por tabela, agora com o JOIN
            # de fixtures/leagues que so' a outra tinha (match_datetime e
            # league_name; sem eles o card fica sem horario e sem nome de liga).
            result["faltas"] = [dict(r) for r in _safe_query(cur, f"""
                SELECT pf.id, pf.fixture_id, pf.match_date,
                       pf.home_team, pf.away_team, pf.home_team_id, pf.away_team_id,
                       pf.league_id, pf.market, pf.market_type, pf.line, pf.odd,
                       pf.bet_house, pf.confidence, pf.prob_real,
                       pf.prob_real AS probability, pf.edge,
                       pf.reasoning, pf.stake_pct, pf.stake_units,
                       pf.result, pf.profit, pf.created_at,
                       f.match_datetime, l.name AS league_name
                FROM picks_faltas pf
                LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
                LEFT JOIN leagues  l ON l.league_id  = pf.league_id
                WHERE {_merc_where.replace('match_date', 'pf.match_date').replace('result IS NULL', 'pf.result IS NULL')}
                -- Ordem do laco que sobrescrevia esta consulta, nao a que estava
                -- escrita aqui: e' a que o usuario ve hoje na tela, e tirar a
                -- consulta duplicada nao pode reordenar a aba de Mercados.
                ORDER BY pf.edge DESC NULLS LAST
            """, _d)]

            result["goleiros"] = [dict(r) for r in _safe_query(cur, f"""
                SELECT pg.id, pg.fixture_id, pg.match_date,
                       pg.home_team, pg.away_team, pg.home_team_id, pg.away_team_id,
                       pg.league_id, pg.player_id, pg.player_name,
                       pg.team_id, pg.team_name,
                       pg.market, pg.market_type, pg.line, pg.line_value, pg.odd,
                       pg.bet_house, pg.confidence, pg.prob_real,
                       pg.prob_real AS probability, pg.edge,
                       pg.reasoning, pg.stake_pct, pg.stake_units,
                       pg.result, pg.profit, pg.created_at,
                       f.match_datetime, l.name AS league_name
                FROM picks_goleiros pg
                LEFT JOIN fixtures f ON f.fixture_id = pg.fixture_id
                LEFT JOIN leagues  l ON l.league_id  = pg.league_id
                WHERE {_merc_where.replace('match_date', 'pg.match_date').replace('result IS NULL', 'pg.result IS NULL')}
                ORDER BY pg.edge DESC NULLS LAST
            """, _d)]

            # PLAYER STATS (27/08) -- o sucessor de picks_goleiros. Chave
            # propria e nao mistura com `goleiros`: o card precisa saber o
            # METODO ("Chutes no alvo" nao e' "Defesas"), e um bloco unico
            # rotulado "Defesas" com pick de desarme dentro seria pior que
            # duas listas.
            result["player_stats"] = [dict(r) for r in _safe_query(cur, f"""
                SELECT pp.id, pp.fixture_id, pp.match_date,
                       pp.home_team, pp.away_team, pp.home_team_id, pp.away_team_id,
                       pp.league_id, pp.player_id, pp.player_name,
                       pp.team_id, pp.team_name, pp.method, pp.stat_column,
                       pp.market, pp.market_type, pp.line, pp.line_value, pp.odd,
                       pp.bet_house, pp.confidence, pp.prob_real,
                       pp.prob_real AS probability, pp.edge, pp.score,
                       pp.reasoning, pp.stake_pct, pp.stake_units,
                       pp.result, pp.profit, pp.created_at,
                       f.match_datetime, l.name AS league_name
                FROM picks_player_stats pp
                LEFT JOIN fixtures f ON f.fixture_id = pp.fixture_id
                LEFT JOIN leagues  l ON l.league_id  = pp.league_id
                WHERE {_merc_where.replace('match_date', 'pp.match_date').replace('result IS NULL', 'pp.result IS NULL')}
                ORDER BY pp.score DESC NULLS LAST
            """, _d)]
            # A escalacao entra DEPOIS, numa consulta propria. Ver
            # _juntar_escalacao: e' informacao opcional, e informacao opcional
            # nao pode participar da consulta que traz os picks.
            _juntar_escalacao(cur, result["player_stats"])
            _juntar_auditoria(cur, result["player_stats"], "picks_player_stats")

            # PICK BOOST (28/08) · Over 1.5 FT + Under 2.5 HT, combinacao fixa.
            #
            # Chave propria e nao junto de `vip`: aqui o mercado ja' esta'
            # definido e o que o motor escolhe sao os JOGOS. Nao ha'
            # exclusividade de partida nem "melhor pick do jogo" -- varios picks
            # no mesmo dia e' o caso ESPERADO, e misturar isso na grade VIP
            # (que e' um pick por jogo) daria a impressao de repeticao.
            #
            # Ordena por `score`, e nao por edge: no Pick Boost a odd nao
            # seleciona, ela e' faixa de sanidade. Ver pick_engine_boost/config.
            result["boost"] = [dict(r) for r in _safe_query(cur, f"""
                SELECT pb.id, pb.fixture_id, pb.match_date,
                       pb.home_team, pb.away_team, pb.home_team_id, pb.away_team_id,
                       pb.league_id, pb.market, pb.market_type, pb.line, pb.odd,
                       pb.odd_ft, pb.odd_ht, pb.bet_house_ft, pb.bet_house_ht,
                       pb.confidence, pb.prob_real, pb.prob_real AS probability,
                       pb.prob_ft, pb.prob_ht, pb.edge, pb.ev, pb.score,
                       pb.reasoning, pb.stake_pct, pb.stake_units,
                       pb.result, pb.result_ft, pb.result_ht, pb.profit, pb.created_at,
                       f.match_datetime, l.name AS league_name
                FROM picks_boost pb
                LEFT JOIN fixtures f ON f.fixture_id = pb.fixture_id
                LEFT JOIN leagues  l ON l.league_id  = pb.league_id
                WHERE {_merc_where.replace('match_date', 'pb.match_date').replace('result IS NULL', 'pb.result IS NULL')}
                ORDER BY pb.score DESC NULLS LAST
            """, _d)]
            _marcar_boost_free(result["boost"])

            # AO VIVO NA ABA HOJE. O recorte de dia e' o mesmo dos outros
            # produtos -- vem de `_merc_where`, entao a seta de dia da aba Hoje
            # move o ao vivo junto sem nenhuma regra propria.
            result["live"] = _picks_live_do_dia(
                cur,
                _merc_where.replace("match_date", "pl.match_date")
                           .replace("result IS NULL", "pl.result IS NULL"),
                _d)
        else:
            row = _safe_query_one(cur, _picks_free_sql, _d)
            result["dica_do_dia"] = dict(row) if row else None
            # Mercados proprios sao VIP. A chave existe sempre pro front nao
            # precisar checar `undefined` antes de iterar.
            result["faltas"] = []
            result["goleiros"] = []
            result["player_stats"] = []
            # Ao vivo e' 100% VIP (nao tem free do dia como o Boost), entao aqui
            # ele e' lista vazia · a chave existe sempre pro front nao precisar
            # checar `undefined` antes de iterar. O teaser do que esta trancado
            # continua saindo pelo caminho de sempre, mais abaixo.
            result["live"] = []

            # PICK BOOST TEM UM FREE POR DIA (2026-08-28, decisao do usuario).
            #
            # E' o unico mercado de modelo proprio que nao e' 100% VIP, e a
            # razao e' o formato: o Boost publica VARIOS jogos no mesmo dia (o
            # mercado e' fixo e o que se escolhe sao as partidas), entao dar um
            # nao esvazia o produto -- diferente de faltas ou de prop de
            # jogador, onde o dia costuma ter um punhado e o "de graca" seria
            # quase tudo.
            #
            # O free e' o de MAIOR SCORE, e nao o mais antigo nem o de maior
            # odd: e' o mesmo criterio que ordena a lista VIP, entao o assinante
            # nunca ve' o free numa posicao que contradiz o ranking dele.
            result["boost"] = _safe_query(cur, f"""
                SELECT pb.id, pb.fixture_id, pb.match_date,
                       pb.home_team, pb.away_team, pb.home_team_id, pb.away_team_id,
                       pb.league_id, pb.market, pb.market_type, pb.line, pb.odd,
                       pb.odd_ft, pb.odd_ht, pb.bet_house_ft, pb.bet_house_ht,
                       pb.confidence, pb.prob_real, pb.prob_real AS probability,
                       pb.prob_ft, pb.prob_ht, pb.edge, pb.ev, pb.score,
                       pb.reasoning, pb.stake_pct, pb.stake_units,
                       pb.result, pb.result_ft, pb.result_ht, pb.profit, pb.created_at,
                       f.match_datetime, l.name AS league_name
                FROM picks_boost pb
                LEFT JOIN fixtures f ON f.fixture_id = pb.fixture_id
                LEFT JOIN leagues  l ON l.league_id  = pb.league_id
                WHERE {_merc_where.replace('match_date', 'pb.match_date').replace('result IS NULL', 'pb.result IS NULL')}
                ORDER BY pb.score DESC NULLS LAST
                LIMIT 1
            """, _d)
            result["boost"] = [dict(r) for r in (result["boost"] or [])]
            _marcar_boost_free(result["boost"])

            # ── Vitrine do que esta' trancado ──────────────────────────────
            #
            # Ate' 21/08 a tela de quem nao e' VIP mostrava um retangulo de
            # cards FALSOS borrados com um cadeado em cima. Nao dizia nada:
            # nao havia como saber se tinha pick hoje, quantos, ou de que jogo.
            #
            # Agora vai o teaser de verdade, com O MESMO CONTRATO DE EXPOSICAO
            # do link publico de pick compartilhado (ver public.py::pick_meta):
            # times, liga, horario, odd. NUNCA market, line, reasoning,
            # confidence, ev, probability ou stake -- e' a analise que se paga,
            # e ela nao sai daqui. Nao ha' regra nova para divergir da antiga:
            # e' a mesma lista de colunas.
            #
            # `_safe_query` ja engole erro e devolve lista vazia, entao uma
            # tabela ausente vira "sem teaser", nunca 500 na tela de picks.
            teaser_vip = _safe_query(cur, f"""
                SELECT s.id, s.match_date,
                       s.home_team_name, s.away_team_name,
                       s.home_team_id, s.away_team_id,
                       s.odd,
                       f.league_id, f.match_datetime,
                       l.name AS league_name
                FROM picks_vip s
                LEFT JOIN fixtures f ON f.fixture_id = s.fixture_id
                LEFT JOIN leagues l ON l.league_id = f.league_id
                WHERE ({_vip_where}) AND s.result IS NULL
                ORDER BY s.match_date DESC, s.confidence DESC
            """, _d)

            teaser_mult = _safe_query(cur, f"""
                SELECT id, match_date, total_odd AS odd, games
                FROM picks_multiplas
                WHERE ({_m_where}) AND result IS NULL
                ORDER BY match_date DESC, created_at DESC
                LIMIT 1
            """, _d)

            teaser_alav = _safe_query(cur, f"""
                SELECT pa.id, pa.match_date, pa.odd_combined AS odd,
                       pa.home_team_1, pa.away_team_1,
                       pa.home_team_2, pa.away_team_2,
                       pa.home_team_3, pa.away_team_3
                FROM picks_alavancagem pa
                WHERE ({_alav_where}) AND pa.result IS NULL
                ORDER BY pa.match_date DESC, pa.created_at DESC
                LIMIT 1
            """, _d)

            # Faltas e defesas moram em duas tabelas mas viram UMA aba
            # ("Mercados"), entao viram uma lista so' aqui tambem. `pick_type`
            # vai junto porque o badge do card e' o que distingue Faltas de
            # Defesas -- sem ele os dois apareceriam como VIP.
            #
            # O nome do goleiro NAO entra, mesmo estando na tabela: ele e' o
            # sujeito da analise ("defesas do goleiro X"), nao o jogo. Entra o
            # mesmo conjunto de campos dos outros teasers, nem um a mais.
            teaser_mercados = []
            for tipo, tabela in (("faltas", "picks_faltas"),
                                 ("goleiros", "picks_goleiros"),
                                 ("player_stats", "picks_player_stats"),
                                 ("boost", "picks_boost")):
                teaser_mercados += [
                    {**dict(r), "pick_type": tipo}
                    for r in _safe_query(cur, f"""
                        SELECT p.id, p.match_date,
                               p.home_team AS home_team_name,
                               p.away_team AS away_team_name,
                               p.home_team_id, p.away_team_id,
                               p.league_id, p.odd,
                               f.match_datetime, l.name AS league_name
                        FROM {tabela} p
                        LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
                        LEFT JOIN leagues  l ON l.league_id  = p.league_id
                        WHERE ({_merc_where.replace('match_date', 'p.match_date').replace('result IS NULL', 'p.result IS NULL')})
                          AND p.result IS NULL
                        ORDER BY p.match_date DESC, p.id DESC
                    """, _d)
                ]

            result["bloqueados"] = {
                "vip": [dict(r) for r in teaser_vip],
                "multipla": _teaser_de_multipla(teaser_mult[0]) if teaser_mult else None,
                "alavancagem": _teaser_de_alavancagem(teaser_alav[0]) if teaser_alav else None,
                "mercados": teaser_mercados,
            }

        # ── is_followed de TODOS os tipos, numa consulta so' ────────────────
        #
        # Eram SEIS idas ao banco: uma por tipo de pick (vip, faltas, goleiros,
        # multipla) mais duas avulsas (dica do dia, alavancagem). A 154ms cada
        # (ver database.py:71-82), quase um segundo pra responder uma pergunta
        # que cabe numa consulta: "destes pares (tipo, id), quais este usuario
        # ja seguiu?".
        #
        # O filtro e' pick_type = ANY(...) AND pick_id = ANY(...), que e' um
        # superconjunto (casa tipo de um pick com id de outro), e nao um IN de
        # tupla. Isso e' de proposito: usa os mesmos indices simples e o
        # resultado e' exato de qualquer forma, porque o dicionario abaixo e'
        # chaveado pelo PAR (tipo, id), nunca pelo id sozinho.
        user_id = current_user.get("id")

        alvos: list[tuple[str, int]] = []

        def _alvo(tipo: str, itens) -> None:
            for p in itens:
                if p and p.get("id"):
                    alvos.append((tipo, p["id"]))

        _alvo("vip",         result.get("vip") or [])
        _alvo("multipla",    result.get("multiplas") or [])
        _alvo("faltas",      result.get("faltas") or [])
        _alvo("goleiros",    result.get("goleiros") or [])
        _alvo("player_stats", result.get("player_stats") or [])
        _alvo("boost",        result.get("boost") or [])
        _alvo("free",        [result["dica_do_dia"]] if result.get("dica_do_dia") else [])
        _alvo("alavancagem", [result["alavancagem"]] if result.get("alavancagem") else [])

        seguidos: dict[tuple[str, int], dict] = {}
        if user_id and alvos:
            linhas = _safe_query(cur, """
                SELECT pick_type, pick_id, stake_units, actual_odd, bet_house
                FROM user_followed_picks
                WHERE user_id = %s AND pick_type = ANY(%s) AND pick_id = ANY(%s)
            """, (user_id,
                  sorted({t for t, _ in alvos}),
                  sorted({i for _, i in alvos})))
            seguidos = {(r["pick_type"], r["pick_id"]): r for r in linhas}

        def _marcar(tipo: str, itens) -> None:
            """Sem `is_followed` o card nao sabe que a aposta ja foi registrada
            e o botao "Apostar" reaparece como se nada tivesse acontecido."""
            for p in itens:
                if not p:
                    continue
                fr = seguidos.get((tipo, p.get("id")))
                p["is_followed"]      = fr is not None
                p["user_stake_units"] = float(fr["stake_units"]) if fr else None
                p["user_actual_odd"]  = float(fr["actual_odd"])  if fr and fr["actual_odd"] else None
                p["user_bet_house"]   = fr["bet_house"] if fr and fr["bet_house"] else None
                p["pick_type"] = tipo

        _marcar("vip",         result.get("vip") or [])
        _marcar("multipla",    result.get("multiplas") or [])
        _marcar("faltas",      result.get("faltas") or [])
        _marcar("goleiros",    result.get("goleiros") or [])
        _marcar("player_stats", result.get("player_stats") or [])
        _marcar("boost",        result.get("boost") or [])
        _marcar("free",        [result["dica_do_dia"]] if result.get("dica_do_dia") else [])
        _marcar("alavancagem", [result["alavancagem"]] if result.get("alavancagem") else [])

        # ── Calcula suggested_stake_units com banca real do usuário ─────────
        # Centraliza a lógica no backend; frontend apenas exibe o valor.
        if user_id:
            banca = _get_user_banca(cur, user_id)
            if banca:
                bankroll, unit_value = banca

                for p in result.get("vip") or []:
                    if not p.get("is_followed"):
                        p["suggested_stake_units"] = _compute_suggested_stake_units(
                            'vip', p.get("stake_pct"), p.get("confidence"),
                            p.get("odd"), p.get("ev"), bankroll, unit_value,
                        )

                dica = result.get("dica_do_dia")
                if dica and not dica.get("is_followed"):
                    dica["suggested_stake_units"] = _compute_suggested_stake_units(
                        'free', None, dica.get("confidence"), dica.get("odd"),
                        dica.get("ev"), bankroll, unit_value,
                    )

                for m in result.get("multiplas") or []:
                    if not m.get("is_followed"):
                        m["suggested_stake_units"] = _compute_suggested_stake_units(
                            'multipla', None, m.get("confidence"), m.get("total_odd"),
                            None, bankroll, unit_value,
                        )

                # OS MERCADOS PROPRIOS FICAVAM DE FORA (corrigido em 28/08).
                #
                # O bloco cobria vip, dica e multipla, e parou de crescer
                # enquanto os produtos cresciam: faltas, jogadores e Pick Boost
                # chegavam na tela SEM `suggested_stake_units`.
                #
                # No site isso nao aparecia como erro -- o card cai no Kelly
                # local quando o campo falta --, mas o Kelly local nao conhece
                # `stake_pct` e nao e' o mesmo numero. No APP, que nao tem
                # Kelly nenhum de proposito (pra nao existir uma segunda
                # implementacao da mesma conta), o card simplesmente nao
                # mostrava quanto apostar.
                #
                # `pick_type` decide o TETO dentro de _compute_suggested_stake_
                # units, e por isso cada um manda o seu -- nao da' pra
                # generalizar num "mercado" so'.
                for chave, tipo in (("faltas", "faltas"),
                                    ("goleiros", "goleiros"),
                                    ("player_stats", "player_stats"),
                                    ("boost", "boost")):
                    for p in result.get(chave) or []:
                        if p.get("is_followed"):
                            continue
                        p["suggested_stake_units"] = _compute_suggested_stake_units(
                            tipo, p.get("stake_pct"), p.get("confidence"),
                            p.get("odd"), p.get("ev"), bankroll, unit_value,
                        )

        return result
    finally:
        cur.close()
        conn.close()


@router.get("/vip")
def get_vip_suggestions(
    current_user: dict = Depends(require_vip),
    date_from:    Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:      Optional[str] = Query(None, description="YYYY-MM-DD"),
    market_type:  Optional[str] = Query(None, description="goals|corners|cards|result|btts"),
    resultado:    Optional[str] = Query(None, description="pending|GREEN|RED|PUSH|HALF-WIN|HALF-LOSS"),
    min_conf:     Optional[float] = Query(None, ge=0, le=1, description="0.0–1.0"),
    bet_house:    Optional[str] = Query(None),
    order_by:     str = Query("confidence", description="confidence|odd|match_date"),
    limit:        int = Query(50, ge=1, le=200),
):
    """Sugestões VIP com filtros dinâmicos."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions = []
        params = []

        # Data
        if date_from:
            conditions.append("s.match_date >= %s")
            params.append(date_from)
        else:
            conditions.append("s.match_date = CURRENT_DATE")

        if date_to:
            conditions.append("s.match_date <= %s")
            params.append(date_to)

        # Tipo de mercado
        if market_type and market_type != "all":
            conditions.append("s.market_type = %s")
            params.append(market_type)

        # Resultado
        if resultado == "pending":
            conditions.append("s.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("s.result = %s")
            params.append(resultado)

        # Confiança mínima
        if min_conf is not None:
            conditions.append("s.confidence >= %s")
            params.append(min_conf)

        # Casa de aposta
        if bet_house and bet_house != "all":
            conditions.append("s.bet_house ILIKE %s")
            params.append(f"%{bet_house}%")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        safe_order = {
            "confidence": "s.confidence DESC",
            "odd":        "s.odd DESC",
            "match_date": "s.match_date DESC, s.id DESC",
        }.get(order_by, "s.confidence DESC")

        params.append(limit)

        rows = _safe_query(cur, f"""
            SELECT
                s.id, s.fixture_id, s.match_date,
                s.home_team_name, s.away_team_name,
                s.home_team_id, s.away_team_id,
                s.market, s.line, s.odd, s.bet_house,
                s.market_type, s.confidence, s.ev, s.probability,
                s.stake_pct,
                s.reasoning, s.result, s.profit,
                s.created_at
            FROM picks_vip s
            {where}
            ORDER BY {safe_order}
            LIMIT %s
        """, params)

        picks = [dict(r) for r in rows]
        for p in picks:
            if p.get("market"):
                p["market"] = _tr(p["market"])

        # Adiciona is_followed + user_stake_units + user_actual_odd
        user_id = current_user.get("id")
        if user_id and picks:
            pick_ids = [p["id"] for p in picks if p.get("id")]
            if pick_ids:
                frows = _safe_query(cur, """
                    SELECT pick_id, stake_units, actual_odd, bet_house FROM user_followed_picks
                    WHERE user_id = %s AND pick_type = 'vip' AND pick_id = ANY(%s)
                """, (user_id, pick_ids))
                followed_map = {r["pick_id"]: r for r in frows}
                for p in picks:
                    fr = followed_map.get(p.get("id"))
                    p["is_followed"]      = fr is not None
                    p["user_stake_units"] = float(fr["stake_units"]) if fr else None
                    p["user_actual_odd"]  = float(fr["actual_odd"]) if fr and fr["actual_odd"] else None
                    p["user_bet_house"]   = fr["bet_house"] if fr and fr["bet_house"] else None
                    p["pick_type"] = "vip"

        # Calcula suggested_stake_units com banca real do usuário
        if user_id and picks:
            banca = _get_user_banca(cur, user_id)
            if banca:
                bankroll, unit_value = banca
                for p in picks:
                    if not p.get("is_followed"):
                        p["suggested_stake_units"] = _compute_suggested_stake_units(
                            'vip', p.get("stake_pct"), p.get("confidence"),
                            p.get("odd"), p.get("ev"), bankroll, unit_value,
                        )

        return picks
    finally:
        cur.close()
        conn.close()


@router.get("/vip/meta")
def get_vip_meta(current_user: dict = Depends(require_vip)):
    """Retorna valores únicos para popular os selects de filtro."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        houses = _safe_query(cur, "SELECT DISTINCT bet_house FROM picks_vip WHERE bet_house IS NOT NULL ORDER BY bet_house")
        types  = _safe_query(cur, "SELECT DISTINCT market_type FROM picks_vip WHERE market_type IS NOT NULL ORDER BY market_type")
        return {
            "bet_houses":   [r["bet_house"] for r in houses],
            "market_types": [r["market_type"] for r in types],
        }
    finally:
        cur.close()
        conn.close()


@router.get("/{suggestion_id}/detail")
def get_suggestion_detail(
    suggestion_id: int,
    pick_type: str = Query("vip"),
    current_user: dict = Depends(get_current_user),
):
    """Detalhe completo: stats dos times, últimas 5 partidas, reasoning e odds."""
    import json as _json
    conn = get_connection()
    cur = conn.cursor()
    try:
        from fastapi import HTTPException

        is_vip = is_vip_active(current_user)

        # ── MÚLTIPLA ────────────────────────────────────────────────────────
        if pick_type == "multipla":
            cur.execute("""
                SELECT id, match_date, games AS legs,
                       total_odd, COALESCE(prob_combinada, score_combo) AS confidence,
                       prob_combinada AS probability,
                       reasoning, result, profit, created_at
                FROM picks_multiplas WHERE id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Múltipla não encontrada")
            d = dict(row)
            if not is_vip:
                raise HTTPException(403, "Acesso VIP necessário para ver a análise completa")
            try:
                legs = _json.loads(d["legs"]) if isinstance(d["legs"], str) else (d["legs"] or [])
            except Exception:
                legs = []

            # Enriquece cada leg com nomes e IDs dos times via fixtures
            fixture_ids = [leg["fixture_id"] for leg in legs if leg.get("fixture_id")]
            fixture_map: dict = {}
            if fixture_ids:
                frows = _safe_query(cur, f"""
                    SELECT f.fixture_id,
                           f.home_team_id, f.away_team_id,
                           f.match_datetime,
                           {_nome_do_time("home", "f")} AS home_team,
                           {_nome_do_time("away", "f")} AS away_team
                    FROM fixtures f
                    WHERE f.fixture_id = ANY(%s)
                """, (fixture_ids,))
                for fr in frows:
                    fixture_map[fr["fixture_id"]] = fr

            enriched_legs = []
            for leg in legs:
                fid = leg.get("fixture_id")
                fi  = fixture_map.get(fid, {}) if fid else {}
                enriched_legs.append({
                    **leg,
                    "home_team":    fi.get("home_team") or leg.get("home_team") or leg.get("home"),
                    "away_team":    fi.get("away_team") or leg.get("away_team") or leg.get("away"),
                    "home_team_id": fi.get("home_team_id") or leg.get("home_team_id"),
                    "away_team_id": fi.get("away_team_id") or leg.get("away_team_id"),
                    "match_datetime": str(fi["match_datetime"]) if fi.get("match_datetime") else None,
                })

            n = len(enriched_legs)
            suggestion = {
                "id": d["id"],
                "match_date": d["match_date"],
                "home_team_name": f"Múltipla · {n} seleções",
                "away_team_name": "",
                "market": f"{n} seleções",
                "line": None,
                "odd": d["total_odd"],
                "confidence": d["confidence"],
                "reasoning": d["reasoning"],
                "result": d["result"],
                "profit": d["profit"],
                "legs": enriched_legs,
                "pick_type": "multipla",
            }
            ufp_m = _safe_query_one(cur, """
                SELECT stake_units, actual_odd FROM user_followed_picks
                WHERE user_id = %s AND pick_id = %s AND pick_type = 'multipla'
            """, (current_user["id"], suggestion_id))
            suggestion["user_stake_units"] = float(ufp_m["stake_units"]) if ufp_m else None
            suggestion["user_actual_odd"]  = float(ufp_m["actual_odd"]) if ufp_m and ufp_m["actual_odd"] else None
            if not suggestion["user_stake_units"]:
                banca_d = _get_user_banca(cur, current_user["id"])
                if banca_d:
                    bl, uv = banca_d
                    suggestion["suggested_stake_units"] = _compute_suggested_stake_units(
                        'multipla', None, d.get("confidence"), d.get("total_odd"), None, bl, uv,
                    )
            return {"suggestion": suggestion,
                    "home_recent": [], "away_recent": [], "odds": []}

        # ── ALAVANCAGEM ──────────────────────────────────────────────────────
        if pick_type == "alavancagem":
            cur.execute("""
                SELECT pa.*,
                       f1.match_datetime AS match_datetime,
                       f1.home_team_id   AS home_team_id,
                       f1.away_team_id   AS away_team_id,
                       f1.league_id      AS fix_league_id,
                       f1.season         AS fix_season
                FROM picks_alavancagem pa
                LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
                WHERE pa.id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Alavancagem não encontrada")
            d = dict(row)
            if not is_vip:
                raise HTTPException(403, "Acesso VIP necessário para ver a análise completa")
            legs = []
            if d.get("home_team_1"):
                legs.append({
                    "home": d["home_team_1"], "away": d["away_team_1"],
                    "market": d.get("market_1"), "line": d.get("line_1"),
                    "odd": d.get("odd_1"), "house": d.get("bet_house_1"),
                    "reasoning": d.get("reasoning_1"),
                })
            if d.get("home_team_2"):
                legs.append({
                    "home": d["home_team_2"], "away": d["away_team_2"],
                    "market": d.get("market_2"), "line": d.get("line_2"),
                    "odd": d.get("odd_2"), "house": d.get("bet_house_2"),
                    "reasoning": d.get("reasoning_2"),
                })
            alav_suggestion = {
                "id": d["id"],
                "fixture_id": d.get("fixture_id_1"),
                "match_date": d["match_date"],
                "match_datetime": d.get("match_datetime"),
                "home_team_name": d.get("home_team_1", "Alavancagem"),
                "away_team_name": d.get("away_team_1", ""),
                "home_team_id": d.get("home_team_id"),
                "away_team_id": d.get("away_team_id"),
                "fix_league_id": d.get("fix_league_id"),
                "fix_season": d.get("fix_season"),
                "market": d.get("market_1", "Alavancagem"),
                "line": d.get("line_1"),
                "odd": d.get("odd_combined"),
                "bet_house": d.get("bet_house_1"),
                "confidence": d.get("confidence_media"),
                "ev": float(d["ev_combined"]) if d.get("ev_combined") is not None
                      else _ev_from_reasoning(d.get("reasoning_1")),
                "reasoning": d.get("reasoning_1") or "",
                "result": d["result"],
                "profit": d["profit"],
                "legs": legs,
                "pick_type": "alavancagem",
                "tipo": d.get("tipo"),
            }
            # Busca stats e forma do jogo principal (game 1)
            alav_home_id   = alav_suggestion.get("home_team_id")
            alav_away_id   = alav_suggestion.get("away_team_id")
            alav_league_id = alav_suggestion.get("fix_league_id")
            alav_season    = alav_suggestion.get("fix_season") or 2026


            def get_alav_recent(team_id, limit=5):
                if not team_id:
                    return []
                rows = _safe_query(cur, """
                    SELECT match_date, home_team_id, away_team_id,
                           home_goals, away_goals, total_goals,
                           home_corners, away_corners, total_corners
                    FROM match_statistics
                    WHERE (home_team_id = %s OR away_team_id = %s)
                      AND status IN ('FT', 'AET', 'PEN')
                    ORDER BY match_date DESC LIMIT %s
                """, (team_id, team_id, limit))
                result = []
                for r in rows:
                    rd = dict(r)
                    is_home = rd["home_team_id"] == team_id
                    rd["is_home"]   = is_home
                    rd["gf"]        = rd["home_goals"]   if is_home else rd["away_goals"]
                    rd["ga"]        = rd["away_goals"]   if is_home else rd["home_goals"]
                    rd["corners_f"] = rd["home_corners"] if is_home else rd["away_corners"]
                    rd["corners_a"] = rd["away_corners"] if is_home else rd["home_corners"]
                    rd["resultado"] = "W" if rd["gf"] > rd["ga"] else ("D" if rd["gf"] == rd["ga"] else "L")
                    result.append(rd)
                return result

            ufp_a = _safe_query_one(cur, """
                SELECT stake_units, actual_odd FROM user_followed_picks
                WHERE user_id = %s AND pick_id = %s AND pick_type = 'alavancagem'
            """, (current_user["id"], suggestion_id))
            alav_suggestion["user_stake_units"] = float(ufp_a["stake_units"]) if ufp_a else None
            alav_suggestion["user_actual_odd"]  = float(ufp_a["actual_odd"]) if ufp_a and ufp_a["actual_odd"] else None
            return {
                "suggestion":  alav_suggestion,
                "home_recent": get_alav_recent(alav_home_id),
                "away_recent": get_alav_recent(alav_away_id),
                "odds":        [],
            }

        # ── FREE (picks_free) ────────────────────────────────────────────────
        # Mercados de modelo proprio (faltas e defesas de goleiro).
        #
        # Sem este ramo o pick caia no `else` la embaixo, que consulta
        # picks_vip: abrir a analise de um pick de faltas devolvia o pick VIP
        # de mesmo id, ou 404. Os dois mercados sao pipeline proprio e
        # precisam ler da sua tabela, igual multipla e alavancagem.
        if pick_type in ("faltas", "goleiros", "player_stats", "boost"):
            tabela = {"faltas": "picks_faltas", "goleiros": "picks_goleiros",
                      "player_stats": "picks_player_stats",
                      "boost": "picks_boost"}[pick_type]
            # O JOGADOR TAMBEM AQUI (02/09). A lista (/today) ja' devolvia
            # player_name e line_value, e o detalhe nao -- entao o mesmo pick
            # aparecia com o jogador em campo proprio no card e diluido dentro
            # da string da linha quando aberto pelo painel. Uma tela por
            # origem do dado e' exatamente a deriva que o card unico existe
            # pra evitar.
            #
            # `picks_goleiros` e' a tabela legada e nunca teve `method`: o
            # metodo dela e' fixo e mora em market_type ('saves').
            colunas_jogador = {
                "player_stats": "p.player_id, p.player_name, p.team_name, "
                                "p.line_value, p.method",
                "goleiros": "p.player_id, p.player_name, p.team_name, "
                            "p.line_value, p.market_type AS method",
            }.get(pick_type,
                  "NULL::int AS player_id, NULL::text AS player_name, "
                  "NULL::text AS team_name, NULL::numeric AS line_value, "
                  "NULL::text AS method")
            cur.execute(f"""
                SELECT p.id, p.match_date, p.home_team, p.away_team,
                       p.home_team_id, p.away_team_id,
                       p.market, p.line, p.odd, p.bet_house,
                       {colunas_jogador},
                       p.prob_real, p.edge, p.reasoning, p.result, p.profit,
                       p.fixture_id,
                       f.match_datetime, f.league_id, l.name AS league_name
                  FROM {tabela} p
             LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
             LEFT JOIN leagues  l ON l.league_id = f.league_id
                 WHERE p.id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pick nao encontrado")
            if not is_vip:
                raise HTTPException(403, "Acesso VIP necessario para ver a analise completa")

            cur.execute(
                "SELECT stake_units, actual_odd, bet_house FROM user_followed_picks "
                "WHERE user_id = %s AND pick_id = %s AND pick_type = %s",
                (current_user["id"], suggestion_id, pick_type),
            )
            follow = cur.fetchone()

            d = dict(row)
            return {
                **d,
                "home_team_name": d.get("home_team"),
                "away_team_name": d.get("away_team"),
                "pick_type": pick_type,
                # Numero puro pra tela montar "2 ou mais" sem interpretar
                # texto. Decimal do psycopg2 nao serializa sozinho.
                "line_value": (float(d["line_value"])
                               if d.get("line_value") is not None else None),
                # prob_real faz as vezes de confianca: e o numero que o modelo
                # desses dois mercados produz.
                "confidence": float(d["prob_real"]) if d.get("prob_real") is not None else None,
                "probability": float(d["prob_real"]) if d.get("prob_real") is not None else None,
                # Fracao, nao porcentagem: e a escala que picks_vip.ev usa e que
                # o front espera (SuggestionDetail e AnalysisModal fazem o x100).
                # Com o *100 daqui, um edge de 0.0914 virava "914,0%" na tela.
                "ev": float(d["edge"]) if d.get("edge") is not None else None,
                "is_followed": follow is not None,
                "user_stake_units": follow["stake_units"] if follow else None,
                "user_actual_odd": follow["actual_odd"] if follow else None,
                "user_bet_house": follow["bet_house"] if follow else None,
            }

        if pick_type == "free":
            cur.execute("""
                SELECT pf.id, pf.fixture_id, pf.match_date,
                       pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                       pf.league_id, pf.league_name, pf.market, pf.line,
                       pf.odd, pf.bet_house, pf.confidence, pf.reasoning,
                       pf.result, pf.profit,
                       COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                       COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                       f.match_datetime,
                       f.league_id AS fix_league_id, f.season AS fix_season
                FROM picks_free pf
                LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
                WHERE pf.id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Pick não encontrado")
            suggestion = dict(row)
        else:
            # ── VIP (default) ────────────────────────────────────────────────
            cur.execute("""
                SELECT s.*, f.match_datetime, f.league_id AS fix_league_id, f.season AS fix_season
                FROM picks_vip s
                LEFT JOIN fixtures f ON f.fixture_id = s.fixture_id
                WHERE s.id = %s
            """, (suggestion_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Sugestão não encontrada")
            suggestion = dict(row)
            if not is_vip:
                raise HTTPException(403, "Acesso VIP necessário para ver a análise completa")

        home_id = suggestion.get("home_team_id")
        away_id = suggestion.get("away_team_id")

        # Liga/season: vem do fixture se disponível, senão busca no match_statistics
        league_id = suggestion.get("fix_league_id")
        season    = suggestion.get("fix_season") or 2026

        if not league_id:
            ms_row = _safe_query_one(cur, """
                SELECT league_id, season FROM match_statistics
                WHERE fixture_id = %s LIMIT 1
            """, (suggestion["fixture_id"],))
            if ms_row:
                league_id = ms_row["league_id"]
                season    = ms_row["season"]

        # ── Últimas 5 partidas de cada time ─────────────────────────────────
        def get_recent(team_id, limit=5):
            rows = _safe_query(cur, """
                SELECT match_date, league_id, home_team_id, away_team_id,
                       home_goals, away_goals, total_goals,
                       home_corners, away_corners, total_corners,
                       home_yellow_cards, away_yellow_cards,
                       home_possession, away_possession, status
                FROM match_statistics
                WHERE (home_team_id = %s OR away_team_id = %s)
                  AND status IN ('FT', 'AET', 'PEN')
                ORDER BY match_date DESC
                LIMIT %s
            """, (team_id, team_id, limit))
            result = []
            for r in rows:
                d = dict(r)
                is_home = d["home_team_id"] == team_id
                d["is_home"]   = is_home
                d["gf"]        = d["home_goals"]   if is_home else d["away_goals"]
                d["ga"]        = d["away_goals"]   if is_home else d["home_goals"]
                d["corners_f"] = d["home_corners"] if is_home else d["away_corners"]
                d["corners_a"] = d["away_corners"] if is_home else d["home_corners"]
                d["resultado"] = "W" if d["gf"] > d["ga"] else ("D" if d["gf"] == d["ga"] else "L")
                result.append(d)
            return result

        home_recent = get_recent(home_id)
        away_recent = get_recent(away_id)

        # ── Odds do fixture ──────────────────────────────────────────────────
        odds_rows = _safe_query(cur, """
            SELECT DISTINCT ov.market_name, ov.value_name, ov.odd_value,
                            ov.bookmaker_name, ov.market_type, ov.side_team
            FROM odds_values ov
            WHERE ov.fixture_id = %s
            ORDER BY ov.market_type, ov.odd_value
            LIMIT 80
        """, (suggestion["fixture_id"],))

        ufp_v = _safe_query_one(cur, """
            SELECT stake_units, actual_odd FROM user_followed_picks
            WHERE user_id = %s AND pick_id = %s AND pick_type = %s
        """, (current_user["id"], suggestion_id, pick_type))
        suggestion["user_stake_units"] = float(ufp_v["stake_units"]) if ufp_v else None
        suggestion["user_actual_odd"]  = float(ufp_v["actual_odd"]) if ufp_v and ufp_v["actual_odd"] else None
        if not suggestion["user_stake_units"]:
            banca_d = _get_user_banca(cur, current_user["id"])
            if banca_d:
                bl, uv = banca_d
                pt = 'free' if pick_type == 'free' else 'vip'
                suggestion["suggested_stake_units"] = _compute_suggested_stake_units(
                    pt,
                    suggestion.get("stake_pct"),
                    suggestion.get("confidence"),
                    suggestion.get("odd"),
                    suggestion.get("ev"),
                    bl, uv,
                )
        if suggestion.get("market"):
            suggestion["market"] = _tr(suggestion["market"])

        return {
            "suggestion":  suggestion,
            "home_recent": home_recent,
            "away_recent": away_recent,
            "odds":        [dict(r) for r in odds_rows],
        }
    finally:
        cur.close()
        conn.close()


@router.get("/{fixture_id}/standings")
async def get_standings_for_fixture(
    fixture_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Classificação da liga do jogo · direto da API-Football (sem cache)."""
    from futebol_agent.api_football import get_standings

    # A CONSULTA VAI PRO THREADPOOL, E NAO E' DETALHE DE ESTILO.
    #
    # Esta rota e' `async`, entao o corpo dela roda NO EVENT LOOP. psycopg2 e'
    # bloqueante: com WEB_CONCURRENCY=1 (ver Dockerfile), o processo inteiro
    # ficava parado enquanto esta consulta ia e voltava do Supabase. Nao era so'
    # esta tela ficando lenta -- era o site todo, incluindo rotas que nem tocam
    # o banco. Medido de fora em 2026-08-20: /api/version, que so' devolve uma
    # string, chegou a 4,7s, e /public/results a 11,2s; a busca do admin passava
    # dos 15s do timeout do axios e virava "Sem conexao com o servidor" em
    # vermelho, culpando a internet do usuario por uma fila do servidor.
    #
    # Rota sincrona (`def`) nao tem esse problema: o FastAPI ja' a joga no
    # threadpool sozinho. Esta aqui precisa continuar `async` por causa do
    # `await get_standings` logo abaixo, entao quem se muda e' a parte
    # bloqueante.
    def _ler_fixture():
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(
                "SELECT league_id, home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s",
                (fixture_id,),
            )
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

    fx = await run_in_threadpool(_ler_fixture)

    if not fx:
        return {"groups": [], "home_team_id": None, "away_team_id": None}

    league_id = fx["league_id"]
    home_id   = fx["home_team_id"]
    away_id   = fx["away_team_id"]

    try:
        raw_groups = await get_standings(league_id)
    except Exception:
        return {"groups": [], "home_team_id": home_id, "away_team_id": away_id}

    def _fmt(entry: dict) -> dict:
        team  = entry.get("team", {})
        stats = entry.get("all", {})
        goals = stats.get("goals", {})
        return {
            "pos":     entry.get("rank"),
            "team_id": team.get("id"),
            "team":    team.get("name"),
            "pts":     entry.get("points"),
            "played":  stats.get("played"),
            "won":     stats.get("win"),
            "draw":    stats.get("draw"),
            "lost":    stats.get("lose"),
            "gf":      goals.get("for"),
            "ga":      goals.get("against"),
            "gd":      entry.get("goalsDiff"),
            "form":    entry.get("form", ""),
        }

    groups = []
    for group in raw_groups:
        name = group[0].get("group", "") if group else ""
        groups.append({"group": name, "teams": [_fmt(e) for e in group]})

    return {"groups": groups, "home_team_id": home_id, "away_team_id": away_id}


@router.get("/history")
def get_history(days: int = 30, current_user: dict = Depends(require_vip)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        rows = _safe_query(cur, """
            SELECT s.id, s.fixture_id, s.match_date,
                   s.home_team_name, s.away_team_name,
                   s.home_team_id, s.away_team_id,
                   s.market, s.line, s.odd, s.bet_house,
                   s.confidence, s.ev,
                   s.result, s.profit
            FROM picks_vip s
            WHERE s.match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
              AND s.result IS NOT NULL
            ORDER BY s.match_date DESC, s.id DESC
        """, (days,))
        picks = [dict(r) for r in rows]
        for p in picks:
            if p.get("market"):
                p["market"] = _tr(p["market"])
        return picks
    finally:
        cur.close()
        conn.close()


@router.get("/recent-results")
def get_recent_results(
    limit: int = Query(15, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    """Resultados recentes de todas as fontes: VIP, Free, Múltiplas, Alavancagem.
    Não expõe reasoning (nenhuma das queries abaixo seleciona essa coluna) · só
    market/odd/result/profit, o mesmo nível de dado que /api/public/results já
    mostra sem login."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        results = []

        # ── VIP (resultados visíveis para todos) ────────────────────────────
        rows = _safe_query(cur, """
            SELECT pv.id, pv.match_date,
                   pv.home_team_name, pv.away_team_name,
                   pv.home_team_id, pv.away_team_id,
                   pv.market, pv.line, pv.odd, pv.bet_house,
                   pv.confidence, pv.result, pv.profit,
                   COALESCE(ufp.stake_units, 1) AS stake
            FROM picks_vip pv
            LEFT JOIN user_followed_picks ufp
                ON ufp.pick_id = pv.id AND ufp.pick_type = 'vip' AND ufp.user_id = %s
            WHERE pv.result IS NOT NULL
            ORDER BY pv.match_date DESC, pv.id DESC
            LIMIT %s
        """, (current_user["id"], limit))
        for r in rows:
            d = dict(r)
            d["pick_type"] = "vip"
            if d.get("market"):
                d["market"] = _tr(d["market"])
            results.append(d)

        # ── FREE ─────────────────────────────────────────────────────────────
        rows = _safe_query(cur, """
            SELECT pf.id, pf.match_date,
                   pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                   COALESCE(pf.home_team_id, f.home_team_id,
                       (SELECT fx.home_team_id FROM fixtures fx
                        WHERE fx.home_team = pf.home_team AND fx.home_team_id IS NOT NULL LIMIT 1)
                   ) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id,
                       (SELECT fx.away_team_id FROM fixtures fx
                        WHERE fx.away_team = pf.away_team AND fx.away_team_id IS NOT NULL LIMIT 1)
                   ) AS away_team_id,
                   pf.market, pf.line, pf.odd, pf.bet_house,
                   pf.confidence, pf.result, pf.profit,
                   COALESCE(ufp.stake_units, 1) AS stake
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            LEFT JOIN user_followed_picks ufp
                ON ufp.pick_id = pf.id AND ufp.pick_type = 'free' AND ufp.user_id = %s
            WHERE pf.result IS NOT NULL
            ORDER BY pf.match_date DESC, pf.id DESC
            LIMIT %s
        """, (current_user["id"], limit,))
        for r in rows:
            d = dict(r)
            d["pick_type"] = "free"
            if d.get("market"):
                d["market"] = _tr(d["market"])
            results.append(d)

        # ── MÚLTIPLAS (resultados visíveis para todos) ───────────────────────
        rows = _safe_query(cur, """
            SELECT pm.id, pm.match_date,
                   pm.total_odd AS odd,
                   COALESCE(pm.prob_combinada, pm.score_combo) AS confidence,
                   pm.prob_combinada AS probability,
                   pm.result, pm.profit,
                   pm.games AS legs,
                   COALESCE(ufp.stake_units, 1) AS stake
            FROM picks_multiplas pm
            LEFT JOIN user_followed_picks ufp
                ON ufp.pick_id = pm.id AND ufp.pick_type = 'multipla' AND ufp.user_id = %s
            WHERE pm.result IS NOT NULL
            ORDER BY pm.match_date DESC, pm.id DESC
            LIMIT %s
        """, (current_user["id"], limit,))
        import json as _json
        for r in rows:
            d = dict(r)
            try:
                legs = _json.loads(d["legs"]) if isinstance(d["legs"], str) else (d["legs"] or [])
            except Exception:
                legs = []
            n = len(legs)
            first = legs[0] if legs else {}
            d["home_team_name"] = first.get("home") or first.get("home_team") or f"Múltipla · {n} seleções"
            d["away_team_name"] = first.get("away") or first.get("away_team") or ""
            d["home_team_id"]   = first.get("home_team_id")
            d["away_team_id"]   = first.get("away_team_id")
            d["market"]         = f"Múltipla · {n} seleções"
            d["line"]           = None
            d["bet_house"]      = None
            d["legs_count"]     = n
            # recalcula profit por unidade igual banca.py (ignora valor armazenado)
            result_val = d.get("result")
            odd_val = float(d.get("odd") or 1)
            if result_val == "GREEN":
                d["profit"] = round(odd_val - 1, 4)
            elif result_val == "RED":
                d["profit"] = -1.0
            elif result_val == "PUSH":
                d["profit"] = 0.0
            del d["legs"]
            d["pick_type"] = "multipla"
            results.append(d)

        # ── ALAVANCAGEM (resultados visíveis para todos) ─────────────────────
        rows = _safe_query(cur, """
            SELECT pa.id, pa.match_date,
                   pa.home_team_1 AS home_team_name,
                   pa.away_team_1 AS away_team_name,
                   COALESCE(f1.home_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.home_team_1 LIMIT 1)
                   ) AS home_team_id,
                   COALESCE(f1.away_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.away_team_1 LIMIT 1)
                   ) AS away_team_id,
                   pa.market_1 AS market, pa.line_1 AS line,
                   pa.odd_combined AS odd, pa.bet_house_1 AS bet_house,
                   pa.confidence AS confidence,
                   pa.result, pa.profit
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            WHERE pa.result IS NOT NULL
            ORDER BY pa.match_date DESC, pa.id DESC
            LIMIT %s
        """, (limit,))
        for r in rows:
            d = dict(r)
            d["pick_type"] = "alavancagem"
            results.append(d)

        # Ordena tudo por data desc, pega limit
        results.sort(key=lambda x: str(x.get("match_date") or ""), reverse=True)
        return results[:limit]
    finally:
        cur.close()
        conn.close()


@router.get("/picks-free")
def get_picks_free_history(
    current_user: dict = Depends(get_current_user),
    date_from:  Optional[str] = Query(None),
    date_to:    Optional[str] = Query(None),
    resultado:  Optional[str] = Query(None),
    limit:      int = Query(100, ge=1, le=500),
):
    """Histórico de picks gratuitos (Pick do Dia) com filtros."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions: list = []
        params: list = []
        if date_from:
            conditions.append("pf.match_date >= %s"); params.append(date_from)
        else:
            conditions.append("pf.match_date >= CURRENT_DATE - INTERVAL '30 days'")
        if date_to:
            conditions.append("pf.match_date <= %s"); params.append(date_to)
        if resultado == "pending":
            conditions.append("pf.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("pf.result = %s"); params.append(resultado)
        where = "WHERE " + " AND ".join(conditions)
        params.append(limit)
        rows = _safe_query(cur, f"""
            SELECT pf.id, pf.fixture_id, pf.match_date,
                   pf.home_team, pf.away_team,
                   pf.league_id, pf.league_name,
                   pf.market, pf.market_type, pf.line, pf.odd, pf.bet_house,
                   pf.confidence, pf.prob_real, pf.prob_real AS probability, pf.edge,
                   CASE WHEN pf.prob_real IS NOT NULL AND pf.odd IS NOT NULL
                        THEN ROUND((pf.prob_real * pf.odd - 1)::numeric, 4)
                        ELSE NULL END AS ev,
                   pf.reasoning, pf.result, pf.profit,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            {where}
            ORDER BY pf.match_date DESC
            LIMIT %s
        """, params)
        result_rows = [dict(r) for r in rows]
        banca_d = _get_user_banca(cur, current_user["id"])
        if banca_d:
            bl, uv = banca_d
            for p in result_rows:
                if not p.get("result"):
                    p["suggested_stake_units"] = _compute_suggested_stake_units(
                        'free', None, p.get("confidence"), p.get("odd"), p.get("ev"), bl, uv
                    )
        return result_rows
    finally:
        cur.close()
        conn.close()


@router.get("/multiplas")
def get_multiplas(
    current_user: dict = Depends(require_vip),
    date_from:  Optional[str] = Query(None),
    date_to:    Optional[str] = Query(None),
    resultado:  Optional[str] = Query(None),
    order_by:   str = Query("match_date"),
    limit:      int = Query(100, ge=1, le=500),
):
    """Lista de múltiplas com filtros."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions: list = []
        params: list = []
        if date_from:
            conditions.append("match_date >= %s"); params.append(date_from)
        else:
            conditions.append("match_date >= CURRENT_DATE - INTERVAL '30 days'")
        if date_to:
            conditions.append("match_date <= %s"); params.append(date_to)
        if resultado == "pending":
            conditions.append("result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("result = %s"); params.append(resultado)
        where = "WHERE " + " AND ".join(conditions)
        order_col = ("total_odd" if order_by == "odd"
                     else "COALESCE(prob_combinada, score_combo)" if order_by == "confidence"
                     else "match_date")
        params.append(limit)
        rows = _safe_query(cur, f"""
            SELECT id, match_date,
                   games AS legs,
                   total_odd, COALESCE(prob_combinada, score_combo) AS confidence,
                       prob_combinada AS probability,
                   reasoning, result, profit, created_at
            FROM picks_multiplas
            {where}
            ORDER BY {order_col} DESC, created_at DESC
            LIMIT %s
        """, params)
        enriched = _enrich_multipla_legs(cur, rows)
        banca_d = _get_user_banca(cur, current_user["id"])
        if banca_d:
            bl, uv = banca_d
            for m in enriched:
                if not m.get("result"):
                    m["suggested_stake_units"] = _compute_suggested_stake_units(
                        'multipla', None, m.get("confidence"), m.get("total_odd"), None, bl, uv
                    )
        return enriched
    finally:
        cur.close()
        conn.close()


#: (chave, tabela). A chave e' a mesma de STAKE_PADRAO e a mesma que
#: /public/results aceita em `source`, de proposito: dois nomes pro mesmo
#: recorte e' como duas telas passam a discordar sem ninguem perceber.
_FONTES_DO_PLACAR = [
    ("vip",          "picks_vip"),
    ("free",         "picks_free"),
    ("multiplas",    "picks_multiplas"),
    ("alavancagem",  "picks_alavancagem"),
    ("faltas",       "picks_faltas"),
    ("goleiros",     "picks_goleiros"),
    # Player Stats (27/08), sucessor de picks_goleiros. As duas entram:
    # goleiros parou de crescer, e o passado dela continua valendo no placar.
    ("player_stats", "picks_player_stats"),
    # Pick Boost publicado em 28/08 · entrou no placar junto com o peso 2 em
    # stake_plan.py (ate' 27/08 o peso era 0, fase 1 so' Admin).
    ("boost",        "picks_boost"),
    # Ao vivo (29/08). O produto era liquidado, notificado e seguido na banca
    # sem existir em nenhum numero publico -- a tela de Picks anunciava a
    # "Performance da IA" de um site que ignorava um dos motores dele.
    #
    # UNICA fonte cuja tabela pode nao existir: `picks_live` nasce do motor,
    # nao das migracoes do site. Por isso `_fontes` recebe o cursor e filtra.
    ("live",         "picks_live"),
]

#: Fontes cuja tabela pode faltar nesta instancia. Ver `_fontes`.
_FONTES_OPCIONAIS = {"live"}

#: Apelidos aceitos em `source`. `multipla` no singular e' o nome que
#: /public/results usa na quebra por fonte, e quem chama de la' nao tem por que
#: descobrir que aqui o plural manda.
_APELIDOS_DE_FONTE = {"multipla": "multiplas", "dica": "free", "pick_seguro": "free"}


def _fontes(source: str | None, cur=None) -> list[tuple[str, str]]:
    """As tabelas que entram no placar. `None`/`all` = todas.

    `cur` serve so' pra derrubar fonte opcional que nao existe aqui. O placar
    e' UM union: uma tabela ausente nao devolve "aquela fonte com zero", ela
    faz a consulta inteira levantar e o `_safe_query_one` responde None --
    win rate, lucro e sequencia zerados na tela por causa de um produto que
    aquele ambiente nem publica.
    """
    disponiveis = _FONTES_DO_PLACAR
    if cur is not None:
        disponiveis = [f for f in disponiveis
                       if f[0] not in _FONTES_OPCIONAIS or tabela_existe(cur, f[1])]
    if not source or source == "all":
        return disponiveis
    alvo = _APELIDOS_DE_FONTE.get(source, source)
    return [f for f in disponiveis if f[0] == alvo] or disponiveis


def _sql_do_lucro(chave: str, tabela: str) -> str:
    """`(result, profit)` de uma fonte, ja' no peso do placar.

    ALAVANCAGEM NAO TEM PESO POR LINHA (04/09). Ela e' um caminho: o lucro sai
    do caminho FECHADO, e nao da soma das pernas. Ate' aqui ela entrava como
    `profit * 0` e sumia do numero -- e como /public/results ja' passou a
    conta-la pelo caminho, as duas telas do site diziam lucros diferentes da
    mesma IA. E' exatamente a divergencia silenciosa que o topo de stake_plan.py
    avisa que aconteceria se a tabela fosse escrita duas vezes.

    LEFT JOIN e nao JOIN: a subconsulta do caminho so' conhece pick liquidado,
    e um INNER derrubaria o pick do dia que ainda nao tem resultado. Ele nao
    muda soma nenhuma (todo agregado aqui filtra `result IS NOT NULL`), mas
    some da CONTAGEM de linhas -- e contagem de linha e' o que a proxima pessoa
    usa pra conferir se a fonte esta' inteira.
    """
    if chave == "alavancagem":
        return (f"                SELECT pa.result,"
                f" COALESCE(cam.caminho_profit, 0) AS profit"
                f" FROM {tabela} pa"
                f" LEFT JOIN {alavancagem_caminho.subquery_dos_caminhos()} cam"
                f" ON cam.pick_id = pa.id")
    return (f"                SELECT result, profit * {STAKE_PADRAO[chave]} AS profit"
            f" FROM {tabela}")


@router.get("/stats/quick")
def get_quick_stats(
    source: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Win rate, lucro e sequência · de todos os pipelines ou de um só.

    `source` existe desde 28/08 porque a tela de Picks precisava, dentro do
    "O que é" de cada produto, do numero DAQUELE produto · o bloco do Free
    anunciava "Diário / 1 por dia / Grátis", tres rotulos que nunca mudam e
    nao dizem se o pick de ontem entrou ou nao. O recorte sai daqui, e nao de
    uma conta no front, pelo motivo de sempre: o peso de stake mora em
    stake_plan.py, e o numero do recorte tem que ser o mesmo numero do total,
    so' que filtrado.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Stats gerais · TODOS os seis pipelines com resultado.
        #
        # Faltas e goleiros ficavam de fora, e este e' o numero que a tela de
        # Picks estampa como "Performance da IA · Geral": o site publicava os
        # dois mercados, liquidava os dois, contava os dois na banca do usuario
        # e no historico publico -- so' a porcentagem do topo os ignorava. Ou
        # seja, o percentual anunciado nao descrevia o produto que estava sendo
        # vendido logo abaixo dele.
        #
        # Cada tabela numa sub-query com _safe_query_one por fora ja' cobre o
        # caso de ambiente sem a migracao; aqui bastou completar o UNION porque
        # as duas tabelas nascem no mesmo setup das outras.
        # O `profit` de cada tabela e' lucro com stake de 1u; o placar publico
        # anuncia o plano de stake_plan.py (4u em pick simples, 1u em bilhete).
        # O peso entra aqui pelo MESMO dicionario que /public/results usa -- com
        # a tabela escrita duas vezes, a tela de Picks e a Home passariam a
        # discordar sobre o lucro da IA sem ninguem perceber.
        fontes = _fontes(source, cur)
        uniao = "\n                UNION ALL\n".join(
            _sql_do_lucro(chave, tabela) for chave, tabela in fontes
        )
        month_row = _safe_query_one(cur, f"""
            SELECT
                COUNT(*) FILTER (WHERE result IS NOT NULL)   AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')     AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')       AS reds,
                COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) AS profit
            FROM (
{uniao}
            ) AS all_picks
            WHERE result IS NOT NULL
        """)
        stats = dict(month_row) if month_row else {"total": 0, "greens": 0, "reds": 0, "profit": 0}
        total  = stats["total"] or 0
        greens = stats["greens"] or 0
        stats["win_rate"] = round(greens / total * 100, 1) if total > 0 else 0.0

        # Sequência atual · mesma base do numero acima.
        #
        # Lia so' picks_vip, entao "5 greens seguidos" descrevia um pipeline e
        # aparecia colado num total que somava todos. Dois numeros vizinhos
        # falando de conjuntos diferentes e' pior que nao ter o segundo.
        uniao_recente = "\n                UNION ALL\n".join(
            f"                SELECT result, match_date, id FROM {tabela}"
            for _chave, tabela in fontes
        )
        recent = _safe_query(cur, f"""
            SELECT result, match_date, id FROM (
{uniao_recente}
            ) AS todos
            WHERE result IS NOT NULL
            ORDER BY match_date DESC, id DESC
            LIMIT 20
        """)
        streak = 0
        streak_type = None
        for r in recent:
            res = r["result"]
            if res in ("GREEN", "HALF-WIN"):
                outcome = "green"
            elif res in ("RED", "HALF-LOSS"):
                outcome = "red"
            else:
                continue
            if streak_type is None:
                streak_type = outcome
            if outcome == streak_type:
                streak += 1
            else:
                break

        stats["streak"]      = streak
        stats["streak_type"] = streak_type  # "green" | "red" | None
        # Ecoado: o servidor descarta fonte desconhecida e volta pro total,
        # e a tela precisa saber disso pra nao rotular de "Free" um numero
        # que e' de todo mundo.
        stats["source"] = fontes[0][0] if len(fontes) == 1 else "all"
        return stats
    finally:
        cur.close()
        conn.close()


@router.get("/latest-pick")
def get_latest_pick(current_user: dict = Depends(get_current_user)):
    """Retorna o pick mais recente · frontend usa para detectar novos picks."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        row = _safe_query_one(cur, """
            SELECT id, match_date, created_at
            FROM picks_vip
            ORDER BY id DESC
            LIMIT 1
        """)
        if not row:
            return {"id": 0, "created_at": None, "match_date": None}
        return dict(row)
    finally:
        cur.close()
        conn.close()


def _source_games_sql(source: str, date_cond: str, result_null_cond: str = "IS NOT NULL") -> str:
    """Retorna subquery normalizada para cada fonte de picks.
    result_null_cond: "IS NOT NULL" (default, exclui pendentes) ou "IS NULL" (so pendentes)."""
    if source == "free":
        # league via subquery correlacionada (nao JOIN) -- match_statistics
        # tambem tem colunas match_date/result, e {date_cond} (texto
        # compartilhado com varios outros endpoints deste arquivo) referencia
        # match_date sem qualificar a tabela; um JOIN direto tornaria essas
        # colunas ambiguas pro Postgres.
        return f"""
            SELECT pf.id, 'free' AS pick_type, pf.match_date,
                   pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                   COALESCE(pf.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(pf.away_team_id, f.away_team_id) AS away_team_id,
                   pf.market, pf.line, pf.odd, pf.bet_house,
                   pf.result, pf.profit, 1::numeric AS stake,
                   COALESCE(pf.league_id, (SELECT ms.league_id FROM match_statistics ms WHERE ms.fixture_id = pf.fixture_id)) AS league_id,
                   COALESCE(
                       pf.league_name,
                       (SELECT l.name FROM match_statistics ms LEFT JOIN leagues l ON l.league_id = ms.league_id WHERE ms.fixture_id = pf.fixture_id),
                       'Liga ' || COALESCE(pf.league_id, (SELECT ms.league_id FROM match_statistics ms WHERE ms.fixture_id = pf.fixture_id))
                   ) AS league_name
            FROM picks_free pf
            LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
            WHERE pf.result {result_null_cond} {date_cond}
        """
    if source in ("faltas", "goleiros", "player_stats", "boost"):
        # Mesma forma de picks_free (um jogo, um mercado, uma odd), então o
        # SELECT é o mesmo com a tabela trocada. Os dois mercados já contavam
        # no ROI público e no histórico de /public/results desde 01/08; só esta
        # aba não os enxergava, e um pick de faltas resolvido simplesmente não
        # existia aqui.
        #
        # `player_stats` entrou em 27/08 com a MESMA forma: é o sucessor de
        # `goleiros` como destino de prop de jogador. As duas fontes coexistem
        # porque o histórico de picks_goleiros não migrou · ela parou de
        # crescer, não de existir, e apagá-la daqui apagaria o passado do
        # produto.
        tabela = {"faltas": "picks_faltas", "goleiros": "picks_goleiros",
                  "player_stats": "picks_player_stats"}[source]
        rotulo = {"faltas": "Faltas", "goleiros": "Defesas",
                  "player_stats": "Player Stats"}[source]
        return f"""
            SELECT p.id, '{source}' AS pick_type, p.match_date,
                   p.home_team AS home_team_name, p.away_team AS away_team_name,
                   COALESCE(p.home_team_id, f.home_team_id) AS home_team_id,
                   COALESCE(p.away_team_id, f.away_team_id) AS away_team_id,
                   p.market, p.line, p.odd, p.bet_house,
                   p.result, p.profit, 1::numeric AS stake,
                   p.league_id,
                   COALESCE(
                       (SELECT l.name FROM leagues l WHERE l.league_id = p.league_id),
                       '{rotulo}'
                   ) AS league_name
            FROM {tabela} p
            LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
            WHERE p.result {result_null_cond} {date_cond}
        """
    if source == "multipla":
        return f"""
            SELECT id, 'multipla' AS pick_type, match_date,
                   CONCAT('Múltipla · ', JSONB_ARRAY_LENGTH(games::jsonb), ' sel.') AS home_team_name,
                   NULL AS away_team_name, NULL AS home_team_id, NULL AS away_team_id,
                   CONCAT('Múltipla · ', JSONB_ARRAY_LENGTH(games::jsonb), ' sel.') AS market,
                   NULL AS line, total_odd AS odd, NULL AS bet_house,
                   result,
                   CASE result
                       WHEN 'GREEN' THEN ROUND((total_odd - 1)::numeric, 4)
                       WHEN 'RED'   THEN -1.0
                       WHEN 'PUSH'  THEN 0.0
                       ELSE NULL
                   END AS profit,
                   1::numeric AS stake,
                   NULL::INTEGER AS league_id, 'Múltiplas' AS league_name
            FROM picks_multiplas
            WHERE result {result_null_cond} {date_cond}
        """
    if source == "alavancagem":
        return f"""
            SELECT pa.id, 'alavancagem' AS pick_type, pa.match_date,
                   pa.home_team_1 AS home_team_name, pa.away_team_1 AS away_team_name,
                   COALESCE(f1.home_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.home_team_1 LIMIT 1)
                   ) AS home_team_id,
                   COALESCE(f1.away_team_id,
                       (SELECT team_id FROM teams WHERE name = pa.away_team_1 LIMIT 1)
                   ) AS away_team_id,
                   pa.market_1 AS market, pa.line_1 AS line,
                   pa.odd_combined AS odd, pa.bet_house_1 AS bet_house,
                   pa.result, pa.profit, 1::numeric AS stake,
                   NULL::INTEGER AS league_id, 'Alavancagem' AS league_name
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            WHERE pa.result {result_null_cond} {date_cond}
        """
    # vip (default) -- league via subquery correlacionada, mesmo motivo do free acima
    return f"""
        SELECT id, 'vip' AS pick_type, match_date,
               home_team_name, away_team_name, home_team_id, away_team_id,
               market, line, odd, bet_house,
               result, profit, 1::numeric AS stake,
               (SELECT ms.league_id FROM match_statistics ms WHERE ms.fixture_id = picks_vip.fixture_id) AS league_id,
               COALESCE(
                   (SELECT l.name FROM match_statistics ms LEFT JOIN leagues l ON l.league_id = ms.league_id WHERE ms.fixture_id = picks_vip.fixture_id),
                   'Liga ' || (SELECT ms.league_id FROM match_statistics ms WHERE ms.fixture_id = picks_vip.fixture_id)
               ) AS league_name
        FROM picks_vip
        WHERE result {result_null_cond} {date_cond}
    """


# As fontes que a aba "Por Jogo" cobre, numa lista só.
#
# ESTA CONSTANTE EXISTE PORQUE A ABA ESTAVA VAZIA. `get_results_games` contava
# as pernas do UNION numa linha escrita à mão (`n_legs = 1 if source != "all"
# else 5`) enquanto o UNION tinha quatro. Com o filtro em "all", que é o estado
# inicial da aba, o número de parâmetros não batia com o de placeholders,
# psycopg2 levantava, `_safe_query` engolia a exceção e a tela dizia "nenhum
# pick encontrado" -- para um histórico com centenas de picks, sem erro nenhum
# em lugar nenhum.
#
# Derivar a contagem daqui é o que impede o erro de voltar: registrar um
# mercado novo passa a mexer numa lista só, e não em dois lugares que precisam
# concordar. Foi exatamente esta a lição que routers/public.py já tinha
# aprendido com faltas e goleiros (ver _SUB_BUILDERS).
# Pick Boost fica de FORA: fase 1 e' so' Admin (ver stake_plan). Entrar aqui
# o publicaria na aba "Por Jogo" sem nunca ter passado por decisao.
FONTES_POR_JOGO = ("vip", "free", "multipla", "alavancagem", "faltas",
                   "goleiros", "player_stats")


def _build_combined_sql(source: str, date_cond: str,
                        result_null_cond: str = "IS NOT NULL") -> tuple[str, int]:
    """(SQL, número de pernas). O segundo item manda no `date_params * n`."""
    if source in FONTES_POR_JOGO:
        return _source_games_sql(source, date_cond, result_null_cond), 1
    return (
        " UNION ALL ".join(
            _source_games_sql(s, date_cond, result_null_cond) for s in FONTES_POR_JOGO
        ),
        len(FONTES_POR_JOGO),
    )


@router.get("/results/games")
def get_results_games(
    current_user: Optional[dict] = Depends(get_current_user_optional),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    days:      int = Query(30, ge=1, le=3650),
    resultado: Optional[str] = Query(None),
    source:    str = Query("all"),
    offset:    int = Query(0, ge=0),
    limit:     int = Query(50, ge=1, le=200),
):
    """Picks individuais com resultado, paginados. source: all|vip|free|multipla|alavancagem

    ABERTO SEM LOGIN, mas SÓ O QUE JÁ TEM RESULTADO. Este é o histórico da IA,
    e pick encerrado não é produto: o mercado, a linha e a odd dele já valeram.
    Exigir conta pra ver o que já aconteceu só escondia a prova de quem ainda
    estava decidindo criar conta.

    O QUE CONTINUA FECHADO É O PENDENTE. `resultado=pending` inverte o filtro
    pra `result IS NULL` e devolveria os picks de HOJE com mercado, linha e odd
    -- o produto inteiro, de graça, trocando um parâmetro na URL. Sem sessão,
    esse valor é ignorado e a consulta segue só com resolvidos.

    A stake pessoal (o quanto VOCÊ apostou em cada pick) também depende de
    sessão, e simplesmente não entra quando não há usuário.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        date_cond = ""
        date_params: list = []
        if date_from:
            date_cond += " AND match_date >= %s"; date_params.append(date_from)
        else:
            date_cond += " AND match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')"; date_params.append(days)
        if date_to:
            date_cond += " AND match_date <= %s"; date_params.append(date_to)

        # "pending" filtra pelo IS NULL dentro de cada subquery (elas excluem
        # pendentes por padrao); qualquer outro valor filtra por igualdade
        # na query externa, em cima do resultado ja unido das 4 fontes.
        # Pendente exige sessão · ver docstring: sem isso a URL entregaria os
        # picks de hoje pra qualquer visitante.
        pode_ver_pendente = current_user is not None
        result_null_cond = "IS NULL" if (resultado == "pending" and pode_ver_pendente) else "IS NOT NULL"
        result_cond = ""
        result_params: list = []
        if resultado and resultado not in ("all", "pending"):
            result_cond = " AND result = %s"; result_params.append(resultado)

        inner_sql, n_legs = _build_combined_sql(source, date_cond, result_null_cond)
        combined_date_params = date_params * n_legs

        count_sql = f"SELECT COUNT(*) AS n FROM ({inner_sql}) AS c WHERE TRUE {result_cond}"
        count_row = _safe_query_one(cur, count_sql, combined_date_params + result_params)
        total = count_row["n"] if count_row else 0

        page_params = combined_date_params + result_params + [limit, offset]
        rows = _safe_query(cur, f"""
            SELECT * FROM ({inner_sql}) AS c
            WHERE TRUE {result_cond}
            ORDER BY match_date DESC, id DESC
            LIMIT %s OFFSET %s
        """, page_params)

        items = [dict(r) for r in rows]

        # Substitui stake de VIP/Free/Múltipla pelo stake pessoal do usuário.
        # Sem sessão não há stake pessoal: a lista sai com a stake do plano.
        if current_user is None:
            return {"total": total, "items": items}

        personal_types = ("vip", "free", "multipla")
        ids_by_type: dict[str, list] = {t: [] for t in personal_types}
        for x in items:
            pt = x.get("pick_type")
            if pt in ids_by_type:
                ids_by_type[pt].append(x["id"])

        stake_map: dict[tuple, float] = {}
        for pt, ids in ids_by_type.items():
            if ids:
                rows_s = _safe_query(cur, """
                    SELECT pick_id, stake_units
                    FROM user_followed_picks
                    WHERE pick_type = %s AND user_id = %s AND pick_id = ANY(%s)
                """, (pt, current_user["id"], ids))
                for r in rows_s:
                    stake_map[(pt, r["pick_id"])] = float(r["stake_units"])

        for item in items:
            key = (item.get("pick_type"), item["id"])
            if key in stake_map:
                item["stake"] = stake_map[key]

        return {"total": total, "items": items}
    finally:
        cur.close(); conn.close()


@router.get("/results/monthly")
def get_results_monthly(
    current_user: Optional[dict] = Depends(get_current_user_optional),
    source: str = Query("all"),
):
    """Resumo mensal · aberto sem login.

    Só agrega picks JÁ RESOLVIDOS (o SQL nasce com `result IS NOT NULL`), então
    não há o que esconder aqui: é o placar fechado de cada mês.
    """
    inner_sql, _ = _build_combined_sql(source, "")

    conn = get_connection()
    cur = conn.cursor()
    try:
        rows = _safe_query(cur, f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', match_date), 'YYYY-MM') AS month,
                COUNT(*)                                              AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')             AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')               AS reds,
                COUNT(*) FILTER (WHERE result = 'PUSH')              AS push,
                COUNT(*) FILTER (WHERE result = 'HALF-WIN')          AS half_wins,
                COUNT(*) FILTER (WHERE result = 'HALF-LOSS')         AS half_losses,
                COALESCE(SUM(profit), 0)                             AS profit,
                COALESCE(SUM(stake),  0)                             AS stake
            FROM ({inner_sql}) AS c
            GROUP BY DATE_TRUNC('month', match_date)
            ORDER BY DATE_TRUNC('month', match_date) DESC
        """, [])
        result = []
        for r in rows:
            d = dict(r)
            t = d["total"] or 0
            g = d["greens"] or 0
            s = float(d["stake"] or 0)
            p = float(d["profit"] or 0)
            d["win_rate"] = round(g / t * 100, 1) if t > 0 else 0.0
            d["roi"]      = round(p / s * 100, 1) if s > 0 else 0.0
            result.append(d)
        return result
    finally:
        cur.close(); conn.close()


@router.get("/alavancagem")
def get_alavancagem(
    current_user: dict = Depends(require_vip),
    date_from:    Optional[str] = Query(None),
    date_to:      Optional[str] = Query(None),
    resultado:    Optional[str] = Query(None),
    offset:       int = Query(0, ge=0),
    limit:        int = Query(50, ge=1, le=200),
):
    """Histórico de picks de alavancagem. VIP only.

    A banca da série é composta sequencialmente (reinveste no GREEN, reseta
    no RED), entao o calculo de bankroll_before/after precisa SEMPRE da serie
    inteira desde o início pra ficar correto -- so a resposta enviada ao
    frontend e paginada (offset/limit), nao a query em si.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions: list = []
        params: list = []
        if date_from:
            conditions.append("pa.match_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("pa.match_date <= %s")
            params.append(date_to)
        if resultado == "pending":
            conditions.append("pa.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("pa.result = %s"); params.append(resultado)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = _safe_query(cur, f"""
            SELECT pa.id, pa.match_date, pa.tipo,
                   pa.home_team_1, pa.away_team_1, pa.market_1, pa.line_1, pa.odd_1, pa.bet_house_1,
                   pa.confidence_1, pa.prob_real_1, pa.reasoning_1,
                   pa.home_team_2, pa.away_team_2, pa.market_2, pa.line_2, pa.odd_2, pa.bet_house_2,
                   pa.confidence_2, pa.prob_real_2, pa.reasoning_2,
                   pa.odd_combined, pa.confidence_media,
                   pa.result, pa.profit, pa.created_at,
                   {_sql_escudos_alav(2)}
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            LEFT JOIN fixtures f2 ON f2.fixture_id = pa.fixture_id_2
            {where}
            ORDER BY pa.match_date DESC
        """, params)

        # Busca bankroll inicial do usuário (default 50)
        user_id = current_user["id"]
        init_row = _safe_query_one(cur, "SELECT alav_bankroll_init FROM user_banca WHERE user_id = %s", (user_id,))
        initial = float(init_row["alav_bankroll_init"]) if init_row and init_row["alav_bankroll_init"] else 50.0

        # Calcula bankroll em ordem cronológica (ASC) e depois retorna em DESC
        picks = [dict(r) for r in rows]
        picks_asc = sorted(picks, key=lambda p: p["match_date"])
        bankroll = initial
        bankroll_map: dict[int, dict] = {}
        for p in picks_asc:
            odd = float(p["odd_combined"] or 1)
            bk_before = round(bankroll, 2)
            result = p.get("result")
            if result == "GREEN":
                bankroll = round(bankroll * odd, 2)
            elif result == "RED":
                bankroll = initial
            # PUSH / HALF-WIN / HALF-LOSS: mantém bankroll (simplificado)
            bk_after = round(bankroll, 2) if result else None
            bankroll_map[p["id"]] = {
                "bankroll_before":  bk_before,
                "bankroll_after":   bk_after,
                "potential_return": round(bk_before * odd, 2),
            }

        for p in picks:
            p.update(bankroll_map.get(p["id"], {}))

        # picks está em ordem DESC (mais recente primeiro) -- pagina por cima
        # da lista já com o bankroll calculado a partir da série completa.
        total = len(picks)
        page = picks[offset:offset + limit]
        return {"items": page, "total": total, "has_more": offset + limit < total}
    finally:
        cur.close()
        conn.close()


@router.get("/alavancagem/today")
def get_alavancagem_today(current_user: dict = Depends(require_vip)):
    """Pick de alavancagem de hoje. VIP only."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        row = _safe_query_one(cur, f"""
            SELECT pa.id, pa.match_date, pa.tipo,
                   pa.home_team_1, pa.away_team_1, pa.market_1, pa.line_1, pa.odd_1, pa.bet_house_1,
                   pa.confidence_1, pa.prob_real_1, pa.reasoning_1,
                   pa.home_team_2, pa.away_team_2, pa.market_2, pa.line_2, pa.odd_2, pa.bet_house_2,
                   pa.confidence_2, pa.prob_real_2, pa.reasoning_2,
                   pa.odd_combined, pa.confidence_media,
                   pa.result, pa.profit, pa.created_at,
                   {_sql_escudos_alav(2)}
            FROM picks_alavancagem pa
            LEFT JOIN fixtures f1 ON f1.fixture_id = pa.fixture_id_1
            LEFT JOIN fixtures f2 ON f2.fixture_id = pa.fixture_id_2
            WHERE pa.match_date = CURRENT_DATE
            LIMIT 1
        """)
        if not row:
            return None

        pick = dict(row)

        # Calcula bankroll atual percorrendo histórico anterior
        user_id = current_user["id"]
        init_row = _safe_query_one(cur, "SELECT alav_bankroll_init FROM user_banca WHERE user_id = %s", (user_id,))
        initial = float(init_row["alav_bankroll_init"]) if init_row and init_row["alav_bankroll_init"] else 50.0

        history = _safe_query(cur, """
            SELECT result, odd_combined FROM picks_alavancagem
            WHERE match_date < CURRENT_DATE AND result IS NOT NULL
            ORDER BY match_date ASC
        """)
        bankroll = initial
        for h in history:
            if h["result"] == "GREEN":
                bankroll = round(bankroll * float(h["odd_combined"] or 1), 2)
            elif h["result"] == "RED":
                bankroll = initial

        odd = float(pick["odd_combined"] or 1)
        pick["bankroll_before"]  = round(bankroll, 2)
        pick["potential_return"] = round(bankroll * odd, 2)
        pick["bankroll_after"]   = None  # ainda não tem resultado

        return pick
    finally:
        cur.close()
        conn.close()


@router.get("/liga/tendencias")
def get_liga_tendencias(
    league_id: int = Query(1, ge=1),
    limit: int = Query(500, ge=5, le=500),
    current_user: dict = Depends(require_vip),
):
    """Últimos N jogos de uma liga com tendências (gols, cartões, escanteios, faltas). VIP only."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Nome por subconsulta, nunca por JOIN em `teams` -- ver _nome_do_time.
        # Com os dois JOINs esta consulta devolvia 706 linhas pros 207 jogos
        # reais da Serie B 2026 (medido em prod, 2026-08-10): jogo repetido na
        # lista, e a media do resumo pesava mais o jogo que duplicou mais.
        rows = _safe_query(cur, f"""
            SELECT ms.fixture_id, ms.match_date, ms.referee,
                   ms.home_goals, ms.away_goals, ms.total_goals,
                   ms.total_corners, ms.total_yellow_cards, ms.total_red_cards,
                   ms.home_shots_on, ms.away_shots_on,
                   ms.home_fouls, ms.away_fouls,
                   ms.home_goalkeeper_saves, ms.away_goalkeeper_saves,
                   ms.home_team_id, ms.away_team_id,
                   {_nome_do_time("home")} AS home_team,
                   {_nome_do_time("away")} AS away_team
            FROM match_statistics ms
            WHERE ms.league_id = %s
              AND ms.status IN ('FT', 'AET', 'PEN')
            ORDER BY ms.match_date DESC
            LIMIT %s
        """, (league_id, limit))

        games = []
        for r in rows:
            g = dict(r)
            g["total_fouls"]    = (g.get("home_fouls") or 0) + (g.get("away_fouls") or 0)
            g["total_shots_on"] = (g.get("home_shots_on") or 0) + (g.get("away_shots_on") or 0)
            # Defesas do goleiro: soma dos dois lados. None nos dois vira None,
            # nao zero -- "sem dado" e "ninguem defendeu" sao coisas diferentes,
            # e a media abaixo pula o jogo em vez de puxa-la pra baixo.
            defesas = [g.get("home_goalkeeper_saves"), g.get("away_goalkeeper_saves")]
            g["total_saves"] = (sum(v for v in defesas if v is not None)
                                if any(v is not None for v in defesas) else None)
            games.append(g)

        if not games:
            return {"games": [], "summary": None}

        n = len(games)
        btts   = sum(1 for g in games if (g["home_goals"] or 0) > 0 and (g["away_goals"] or 0) > 0)
        over25 = sum(1 for g in games if (g["total_goals"] or 0) >= 3)
        com_defesa = [g["total_saves"] for g in games if g["total_saves"] is not None]
        summary = {
            # Media so' sobre os jogos que TEM o contador. Defesa e' o dado com
            # mais buraco na API (aparece em 0.86% dos jogos segundo a medicao
            # do pipeline de goleiros), entao dividir pelo total de jogos daria
            # uma media perto de zero que nao descreve nada.
            "avg_saves": round(sum(com_defesa) / len(com_defesa), 2) if com_defesa else None,
            "jogos_com_defesa": len(com_defesa),
            "total_games":      n,
            "avg_goals":        round(sum(float(g["total_goals"] or 0)        for g in games) / n, 2),
            "avg_corners":      round(sum(float(g["total_corners"] or 0)      for g in games) / n, 2),
            "avg_yellow_cards": round(sum(float(g["total_yellow_cards"] or 0) for g in games) / n, 2),
            "avg_red_cards":    round(sum(float(g["total_red_cards"] or 0)    for g in games) / n, 2),
            "avg_fouls":        round(sum(float(g["total_fouls"])             for g in games) / n, 2),
            "avg_shots_on":     round(sum(float(g["total_shots_on"])          for g in games) / n, 2),
            "btts_pct":         round(btts  / n * 100, 1),
            "over25_pct":       round(over25 / n * 100, 1),
        }
        return {"games": games, "summary": summary}
    finally:
        cur.close()
        conn.close()


@router.get("/liga/arbitros")
def get_liga_arbitros(
    league_id: int = Query(1, ge=1),
    min_jogos: int = Query(2, ge=1, le=20),
    current_user: dict = Depends(require_vip),
):
    """Media de cartao por arbitro NESTA liga, amarelo e vermelho separados.

    Separados de proposito: o motor pontua vermelho como 2 (ver _cards_points),
    entao um arbitro de 3.0 amarelos e 0.6 vermelhos produz o mesmo "peso" de um
    de 4.2 amarelos sem vermelho nenhum -- e os dois dao jogos bem diferentes. A
    coluna de pontos aparece junto porque e' a que o motor usa; as duas cruas
    ficam do lado pra a leitura nao depender da formula.

    Agrega de match_statistics por (referee, league_id) e nao de referee_stats,
    que e' por temporada e mistura competicoes: o mesmo arbitro apita Serie A e
    estadual com media diferente, e quem escolhe pick de cartao numa liga quer
    o numero DELE NAQUELA liga. VIP only, igual ao resto da tela."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        rows = _safe_query(cur, """
            SELECT ms.referee,
                   COUNT(*)                                          AS jogos,
                   ROUND(AVG(COALESCE(ms.total_yellow_cards, 0)), 2)  AS avg_yellow,
                   ROUND(AVG(COALESCE(ms.total_red_cards, 0)), 2)     AS avg_red,
                   ROUND(AVG(COALESCE(ms.total_fouls,
                        COALESCE(ms.home_fouls,0) + COALESCE(ms.away_fouls,0))), 1) AS avg_fouls
              FROM match_statistics ms
             WHERE ms.league_id = %s
               AND ms.status IN ('FT','AET','PEN')
               AND ms.referee IS NOT NULL AND ms.referee <> ''
               AND ms.total_yellow_cards IS NOT NULL
          GROUP BY ms.referee
            HAVING COUNT(*) >= %s
          ORDER BY (AVG(COALESCE(ms.total_yellow_cards,0))
                    + 2 * AVG(COALESCE(ms.total_red_cards,0))) DESC
        """, (league_id, min_jogos))

        arbitros = []
        for r in rows:
            d = dict(r)
            amarelo = float(d["avg_yellow"] or 0)
            vermelho = float(d["avg_red"] or 0)
            # Mesma convencao de stats_model._cards_points: vermelho vale 2.
            d["avg_card_points"] = round(amarelo + 2 * vermelho, 2)
            arbitros.append(d)
        return {"arbitros": arbitros, "min_jogos": min_jogos}
    finally:
        cur.close()
        conn.close()


@router.get("/liga/ranking")
def get_liga_ranking(
    league_id: int = Query(1, ge=1),
    context: str = Query("all"),
    current_user: dict = Depends(require_vip),
):
    """Rankings por time numa liga: gols, escanteios, cartões, faltas, finalizações. VIP only."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Nome por subconsulta, nunca por JOIN em `teams` -- ver _nome_do_time.
        # O JOIN duplicava a partida uma vez por liga em que o time esta
        # cadastrado: 384 linhas pros 207 jogos da Serie B 2026 (medido em prod,
        # 2026-08-10). As MEDIAS sobreviviam (soma e contagem inflavam junto),
        # mas o "jogos" de cada time no ranking mostrava quase o dobro.
        _HOME = f"""
            SELECT ms.home_team_id AS team_id,
                   {_nome_do_time("home")} AS team_name,
                   ms.home_goals          AS goals,
                   ms.home_corners        AS corners,
                   ms.home_yellow_cards   AS yellow_cards,
                   ms.home_red_cards      AS red_cards,
                   ms.home_fouls          AS fouls,
                   ms.home_shots_on       AS shots_on
            FROM match_statistics ms
            WHERE ms.league_id = %s AND ms.status IN ('FT', 'AET', 'PEN')
        """
        _AWAY = f"""
            SELECT ms.away_team_id AS team_id,
                   {_nome_do_time("away")} AS team_name,
                   ms.away_goals          AS goals,
                   ms.away_corners        AS corners,
                   ms.away_yellow_cards   AS yellow_cards,
                   ms.away_red_cards      AS red_cards,
                   ms.away_fouls          AS fouls,
                   ms.away_shots_on       AS shots_on
            FROM match_statistics ms
            WHERE ms.league_id = %s AND ms.status IN ('FT', 'AET', 'PEN')
        """
        if context == "home":
            raw = _safe_query(cur, _HOME, (league_id,))
        elif context == "away":
            raw = _safe_query(cur, _AWAY, (league_id,))
        else:
            raw = _safe_query(cur, f"{_HOME} UNION ALL {_AWAY}", (league_id, league_id))

        from collections import defaultdict
        acc: dict = defaultdict(lambda: {
            "team_id": None, "team_name": "", "games": 0,
            "goals": 0.0, "corners": 0.0, "yellow_cards": 0.0,
            "red_cards": 0.0, "fouls": 0.0, "shots_on": 0.0,
        })
        for row in raw:
            tid = row.get("team_id")
            if tid is None:
                continue
            a = acc[tid]
            a["team_id"]   = tid
            a["team_name"] = row.get("team_name") or a["team_name"]
            a["games"]    += 1
            for col in ("goals", "corners", "yellow_cards", "red_cards", "fouls", "shots_on"):
                a[col] += float(row.get(col) or 0)

        result = []
        for a in acc.values():
            n = a["games"]
            if n == 0:
                continue
            result.append({
                "team_id":      a["team_id"],
                "team_name":    a["team_name"],
                "games":        n,
                "avg_goals":    round(a["goals"]        / n, 2),
                "avg_corners":  round(a["corners"]      / n, 2),
                "avg_yellows":  round(a["yellow_cards"] / n, 2),
                "avg_reds":     round(a["red_cards"]    / n, 2),
                "avg_fouls":    round(a["fouls"]        / n, 2),
                "avg_shots_on": round(a["shots_on"]     / n, 2),
            })
        return result
    finally:
        cur.close()
        conn.close()


@router.get("/results")
def get_results(
    current_user: dict = Depends(get_current_user),
    days:      int = Query(30, ge=1, le=3650),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    source:    str = Query("all"),
):
    conn = get_connection()
    cur = conn.cursor()
    try:
        date_cond = ""
        params_q: list = []
        if date_from:
            date_cond += " AND match_date >= %s"; params_q.append(date_from)
        if date_to:
            date_cond += " AND match_date <= %s"; params_q.append(date_to)
        if not date_from:
            date_cond += " AND match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')"; params_q.append(days)

        # Contagem de pernas derivada do builder · aqui a lista dizia 4 e o
        # UNION tinha o mesmo problema de get_results_games.
        inner_sql, n_legs = _build_combined_sql(source, date_cond)
        combined_params = params_q * n_legs

        row = _safe_query_one(cur, f"""
            SELECT
                COUNT(*)                                            AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')           AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')             AS reds,
                COUNT(*) FILTER (WHERE result = 'PUSH')            AS push,
                COUNT(*) FILTER (WHERE result = 'HALF-WIN')        AS half_wins,
                COUNT(*) FILTER (WHERE result = 'HALF-LOSS')       AS half_losses,
                COALESCE(SUM(profit), 0)                           AS profit_total,
                COALESCE(SUM(stake),  0)                           AS stake_total,
                MIN(match_date)                                     AS desde
            FROM ({inner_sql}) AS c
        """, combined_params)
        stats = dict(row) if row else {}

        rows = _safe_query(cur, f"""
            SELECT match_date,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE result = 'GREEN')     AS greens,
                   COUNT(*) FILTER (WHERE result = 'RED')       AS reds,
                   COUNT(*) FILTER (WHERE result = 'PUSH')      AS push,
                   COUNT(*) FILTER (WHERE result = 'HALF-WIN')  AS half_wins,
                   COUNT(*) FILTER (WHERE result = 'HALF-LOSS') AS half_losses,
                   COALESCE(SUM(profit), 0)                 AS profit
            FROM ({inner_sql}) AS c
            GROUP BY match_date
            ORDER BY match_date DESC
        """, combined_params)
        stats["by_day"] = [dict(r) for r in rows]

        # Por liga · agrupa por league_id (nao league_name, que pode estar
        # desatualizado pra um mesmo league_id) e usa pick_type como fallback
        # quando league_id e NULL (Multipla/Alavancagem), senao as duas
        # colapsariam juntas por serem ambas league_id NULL. Mesmo padrao
        # ja usado em /public/results.
        league_rows = _safe_query(cur, f"""
            SELECT
                COALESCE(league_id::text, pick_type) AS group_key,
                MAX(league_id)   AS league_id,
                MAX(league_name) AS league_name,
                COUNT(*)                                  AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')  AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')    AS reds,
                COALESCE(SUM(profit), 0)                  AS profit,
                COALESCE(SUM(stake),  0)                  AS stake_total
            FROM ({inner_sql}) AS c
            GROUP BY group_key
            ORDER BY total DESC
        """, combined_params)
        stats["by_league"] = [{k: v for k, v in dict(r).items() if k != "group_key"} for r in league_rows]

        return stats
    finally:
        cur.close()
        conn.close()


# ─── Faltas e Defesas de goleiro ────────────────────────────────────────────
# Dois mercados com pipeline proprio (engine_pipelines/faltas_pipeline.py e
# goleiros_pipeline.py, 2026-08-01), em tabelas separadas de picks_vip/free.
# Sao VIP, como alavancagem: entram no pacote pago, nao no slot gratuito
# diario (que segue sendo um pick so, a Dica do Dia).
#
# _safe_query em vez de cur.execute direto e' proposital: instancia que ainda
# nao rodou a migracao das tabelas novas responde lista vazia em vez de 500
# (o mesmo motivo pelo qual o resto deste modulo usa o helper).

def _paginar(rows: list, offset: int, limit: int) -> dict:
    return {"total": len(rows), "items": [dict(r) for r in rows[offset:offset + limit]]}


@router.get("/faltas")
def get_faltas(
    current_user: dict = Depends(require_vip),
    date_from:    Optional[str] = Query(None),
    date_to:      Optional[str] = Query(None),
    resultado:    Optional[str] = Query(None),
    offset:       int = Query(0, ge=0),
    limit:        int = Query(50, ge=1, le=200),
):
    """Historico de picks de faltas (Over 22.5 no total do jogo). VIP only."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions, params = [], []
        if date_from:
            conditions.append("pf.match_date >= %s"); params.append(date_from)
        if date_to:
            conditions.append("pf.match_date <= %s"); params.append(date_to)
        if resultado == "pending":
            conditions.append("pf.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("pf.result = %s"); params.append(resultado)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        rows = _safe_query(cur, f"""
            SELECT pf.id, pf.fixture_id, pf.match_date,
                   pf.home_team, pf.away_team, pf.home_team_id, pf.away_team_id,
                   pf.league_id, pf.market, pf.market_type, pf.line, pf.odd,
                   pf.bet_house, pf.confidence, pf.prob_real, pf.prob_real AS probability, pf.edge,
                   pf.reasoning, pf.stake_pct, pf.stake_units,
                   pf.result, pf.profit, pf.created_at
            FROM picks_faltas pf
            {where}
            ORDER BY pf.match_date DESC, pf.edge DESC
        """, params)
        return _paginar(rows, offset, limit)
    finally:
        cur.close()
        conn.close()


@router.get("/goleiros")
def get_goleiros(
    current_user: dict = Depends(require_vip),
    date_from:    Optional[str] = Query(None),
    date_to:      Optional[str] = Query(None),
    resultado:    Optional[str] = Query(None),
    offset:       int = Query(0, ge=0),
    limit:        int = Query(50, ge=1, le=200),
):
    """Historico de picks de defesas de goleiro. VIP only.

    E' prop de JOGADOR: cada linha traz player_name/team_name e a linha no
    formato "N ou mais defesas". Nao existe versao por time desse mercado.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions, params = [], []
        if date_from:
            conditions.append("pg.match_date >= %s"); params.append(date_from)
        if date_to:
            conditions.append("pg.match_date <= %s"); params.append(date_to)
        if resultado == "pending":
            conditions.append("pg.result IS NULL")
        elif resultado and resultado != "all":
            conditions.append("pg.result = %s"); params.append(resultado)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        rows = _safe_query(cur, f"""
            SELECT pg.id, pg.fixture_id, pg.match_date,
                   pg.home_team, pg.away_team, pg.home_team_id, pg.away_team_id,
                   pg.league_id, pg.player_id, pg.player_name,
                   pg.team_id, pg.team_name,
                   pg.market, pg.market_type, pg.line, pg.line_value, pg.odd,
                   pg.bet_house, pg.confidence, pg.prob_real, pg.edge,
                   pg.reasoning, pg.stake_pct, pg.stake_units,
                   pg.result, pg.profit, pg.created_at
            FROM picks_goleiros pg
            {where}
            ORDER BY pg.match_date DESC, pg.edge DESC
        """, params)
        return _paginar(rows, offset, limit)
    finally:
        cur.close()
        conn.close()


# Tabela e nome das colunas de time por tipo de pick. Faltas e goleiros tem
# tabela propria (pipeline proprio), free/vip usam nomes de coluna diferentes
# pro mesmo dado -- e' o mesmo mapa que get_suggestion_detail resolve em
# ramos separados, aqui condensado porque so' precisamos de 5 campos.
_PICK_FONTE = {
    "vip":      ("picks_vip",      "home_team_name", "away_team_name"),
    "free":     ("picks_free",     "home_team",      "away_team"),
    "faltas":   ("picks_faltas",   "home_team",      "away_team"),
    "goleiros": ("picks_goleiros", "home_team",      "away_team"),
    # Player Stats (27/08) -- a tabela que substitui picks_goleiros como
    # destino de prop de jogador. picks_goleiros continua aqui porque o
    # historico dela nao migrou: ela parou de CRESCER, nao de existir.
    "player_stats": ("picks_player_stats", "home_team", "away_team"),
    # Pick Boost e ao vivo (29/08). Faltavam aqui, entao a aba de serie
    # respondia "tipo sem serie" pros dois -- o card mostrava a amostra que
    # decidiu em todos os outros produtos e ficava mudo justamente nos dois
    # mais novos. picks_live segue a familia de nomes de picks_vip.
    "boost":        ("picks_boost", "home_team", "away_team"),
    "live":         ("picks_live",  "home_team_name", "away_team_name"),
}


def _pernas_de_pick_simples(cur, tabela: str, col_casa: str, col_fora: str,
                            suggestion_id: int) -> list:
    """A unica perna de um pick de mercado unico (vip/free/faltas/goleiros)."""
    # O arbitro sai da fixture e, se ela nao existir mais, de match_statistics
    # (registro permanente, sem FK -- mesmo motivo pelo qual routers/public.py
    # le liga de la'). Sem ele o mercado de cartoes perde a serie de quem apita.
    # `player_id` so existe em picks_goleiros. Vem como NULL nas outras
    # tabelas pra que _series_da_perna possa decidir a fonte da serie com um
    # `if` so, em vez de um ramo por tipo de pick.
    # `stat_column` diz qual contador de player_match_stats liquida o pick.
    # picks_goleiros nao tem a coluna (nasceu so' pra defesas), entao ela e'
    # sintetizada como 'saves' -- que e' literalmente o unico valor que aquela
    # tabela sempre teve. Assim `_serie_do_jogador` fica com UM caminho, e nao
    # com um ramo por tabela.
    if tabela == "picks_goleiros":
        coluna_jogador = ("p.player_id, p.player_name, "
                          "'saves'::text AS stat_column")
    elif tabela == "picks_player_stats":
        coluna_jogador = "p.player_id, p.player_name, p.stat_column"
    else:
        coluna_jogador = ("NULL::int AS player_id, NULL::text AS player_name, "
                          "NULL::text AS stat_column")
    cur.execute(f"""
        SELECT p.fixture_id, p.market, p.line, p.market_type,
               {coluna_jogador},
               COALESCE(p.home_team_id, f.home_team_id) AS home_team_id,
               COALESCE(p.away_team_id, f.away_team_id) AS away_team_id,
               p.{col_casa} AS home_team, p.{col_fora} AS away_team,
               COALESCE(f.league_id, ms.league_id) AS league_id,
               COALESCE(f.season, ms.season)       AS season,
               COALESCE(f.referee, ms.referee)     AS referee
          FROM {tabela} p
     LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
     LEFT JOIN match_statistics ms ON ms.fixture_id = p.fixture_id
         WHERE p.id = %s
    """, (suggestion_id,))
    row = cur.fetchone()
    return [dict(row)] if row else []


def _pernas_de_multipla(cur, suggestion_id: int) -> list:
    """Pernas de uma multipla, do JSONB `games`.

    Liga/temporada e ids de time saem da fixture, nao do JSON: o bilhete guarda
    o que era verdade no dia da geracao, e a serie precisa do mesmo recorte de
    competicao que o motor usou (ver a docstring de get_market_form).
    """
    cur.execute("SELECT games FROM picks_multiplas WHERE id = %s", (suggestion_id,))
    row = cur.fetchone()
    if not row or not row["games"]:
        return []
    games = row["games"]
    if isinstance(games, str):
        games = json.loads(games)

    pernas = []
    for g in games:
        fixture_id = g.get("fixture_id")
        pernas.append({
            "fixture_id": fixture_id,
            "market": g.get("market"),
            "line": g.get("line"),
            "market_type": g.get("market_type"),
            "home_team": g.get("home_team"),
            "away_team": g.get("away_team"),
            "home_team_id": g.get("home_team_id"),
            "away_team_id": g.get("away_team_id"),
            **_fixture_meta(cur, fixture_id, g.get("home_team_id"), g.get("away_team_id")),
        })
    return pernas


def _pernas_de_alavancagem(cur, suggestion_id: int) -> list:
    """Pernas de uma alavancagem -- ate' 3, em colunas numeradas."""
    cur.execute("""
        SELECT fixture_id_1, market_1, line_1, market_type_1, home_team_1, away_team_1,
               fixture_id_2, market_2, line_2, market_type_2, home_team_2, away_team_2,
               fixture_id_3, market_3, line_3, market_type_3, home_team_3, away_team_3
          FROM picks_alavancagem WHERE id = %s
    """, (suggestion_id,))
    row = cur.fetchone()
    if not row:
        return []
    row = dict(row)

    pernas = []
    for i in (1, 2, 3):
        if not row.get(f"market_{i}"):
            continue
        fixture_id = row.get(f"fixture_id_{i}")
        pernas.append({
            "fixture_id": fixture_id,
            "market": row.get(f"market_{i}"),
            "line": row.get(f"line_{i}"),
            "market_type": row.get(f"market_type_{i}"),
            "home_team": row.get(f"home_team_{i}"),
            "away_team": row.get(f"away_team_{i}"),
            **_fixture_meta(cur, fixture_id),
        })
    return pernas


def _fixture_meta(cur, fixture_id, home_team_id=None, away_team_id=None) -> dict:
    """league_id/season/ids de time da fixture da perna.

    picks_alavancagem guarda so' o NOME dos times, e a multipla guarda ids que
    podem ter vindo vazios de um pick antigo -- os dois precisam da fixture pra
    fechar a identidade do jogo. Sem fixture, o que faltar fica None e a perna
    simplesmente nao desenha serie (melhor que serie do time errado)."""
    vazio = {"league_id": None, "season": None, "referee": None}
    if not fixture_id:
        return vazio
    # Duas buscas por chave primaria em vez de um join: `fixtures` e' fila
    # operacional e a linha pode ter saido, `match_statistics` e' o registro
    # permanente (mesma razao de routers/public.py ler liga de la').
    for tabela in ("fixtures", "match_statistics"):
        cur.execute(f"""
            SELECT home_team_id, away_team_id, league_id, season, referee
              FROM {tabela} WHERE fixture_id = %s
        """, (fixture_id,))
        f = cur.fetchone()
        if f:
            break
    if not f:
        return vazio
    f = dict(f)
    return {
        "league_id": f.get("league_id"),
        "season": f.get("season"),
        "referee": f.get("referee"),
        "home_team_id": home_team_id or f.get("home_team_id"),
        "away_team_id": away_team_id or f.get("away_team_id"),
    }


# Colunas que market_form.folha_do_jogo sabe traduzir pra folha da API, mais o
# que a serie precisa pra identificar o jogo. Uma lista so' pras duas consultas
# (time e arbitro): se elas divergirem, uma das duas series perde um contador em
# silencio -- e o sintoma seria "sem dado" em barra que tem dado.
# ESTA LISTA E O `_ADAPTADOR` DE market_form.py SAO O MESMO CONTRATO, EM DOIS
# LUGARES. `folha_do_jogo` so' copia as chaves que o adaptador conhece, e so'
# consegue copiar o que ESTA CONSULTA trouxe. Faltar em qualquer um dos dois
# produz o mesmo sintoma, e ele e' silencioso: `_stat_side` devolve None pra todo
# jogo, nenhuma barra resolve, e "Como esse mercado vem se comportando" some da
# tela sem erro nenhum no log.
#
# Foi o que aconteceu com CHUTES (2026-08-17, pick free Internacional x Remo,
# "Total Shots Over 26.5"): `Total Shots` e `Offsides` tinham sido adicionados ao
# _ADAPTADOR justamente pra fechar esse buraco, mas as colunas nunca entraram
# aqui. A correcao ficou pela metade e o sintoma continuou identico.
#
# O motor NAO sofria do mesmo: ele le por MatchStatsService, com a sua propria
# lista de colunas, e por isso calculava taxa de 60.4% em 15 jogos pro mesmo
# mercado enquanto o card nao achava um unico jogo. Card e pick contando
# historias diferentes sobre o mesmo numero e' pior que nao mostrar serie.
#
# Ao registrar familia nova: coluna AQUI + entrada no _ADAPTADOR. As duas.
_COLUNAS_DA_SERIE = """
        ms.fixture_id, ms.match_date, ms.home_goals, ms.away_goals,
        ms.home_team_id, ms.away_team_id,
        ms.home_corners, ms.away_corners,
        ms.home_yellow_cards, ms.away_yellow_cards,
        ms.home_red_cards, ms.away_red_cards,
        ms.home_fouls, ms.away_fouls,
        ms.home_shots_on, ms.away_shots_on,
        ms.home_total_shots, ms.away_total_shots,
        ms.home_offsides, ms.away_offsides,
        ms.home_goalkeeper_saves, ms.away_goalkeeper_saves
"""


def _nome_do_time(lado: str, alias: str = "ms") -> str:
    """SQL do nome de um lado da partida, por SUBCONSULTA e nunca por JOIN.

    `teams` tem ate' 3 linhas pro mesmo team_id (uma por liga em que o time
    aparece). Um LEFT JOIN em teams multiplica a partida por esse numero, e com
    os dois lados o fator vira 2x2, 2x3... A serie do card saiu errada em
    producao por isso (pick VIP #1581, Goias x Londrina, 2026-08-10): o jogo do
    Goias contra o Sport apareceu 4 vezes nas 5 barras, e a media do Londrina
    fora virou 14.4 (dois jogos repetidos) quando os 5 jogos reais dao 11.4.

    Subconsulta escalar com LIMIT 1 devolve uma linha por partida por
    construcao, seja qual for o estado da tabela de times.

    `alias` e' a tabela que dirige a consulta -- `ms` (match_statistics) na
    maioria, `f` quando quem dirige e' a propria fixtures."""
    return f"""COALESCE(
        (SELECT f2.{lado}_team FROM fixtures f2 WHERE f2.fixture_id = {alias}.fixture_id LIMIT 1),
        (SELECT t.name FROM teams t WHERE t.team_id = {alias}.{lado}_team_id LIMIT 1)
    )"""


def _jogos_do_time(cur, team_id: int, mando: str, league_id, season,
                   excluir_fixture, limit: int) -> list:
    """Ultimos `limit` jogos do time NO MANDO pedido, com o nome do adversario.

    O filtro de mando e' a regra inteira desta consulta. Se o Goias joga em casa
    na partida do pick, o que responde a pergunta e' o Goias EM CASA -- os jogos
    dele como visitante medem outra coisa (+27% de diferenca em escanteios na
    Serie A 2026) e diluem a media que o card mostra. Mesma correcao de
    2026-08-08 no motor, agora tambem no que o usuario le.

    Mesma liga/temporada que o motor leu (MatchStatsService.get_all_matches_full)
    -- serie e pick contando historias diferentes sobre o mesmo numero e' pior
    que nao mostrar serie nenhuma. Sem fixture na tabela (pick antigo) o filtro
    sai e a serie fica um pouco mais larga.

    COPA E SELECAO LEEM TODAS AS COMPETICOES (corrigido 2026-08-27). O motor
    nao usa o mesmo recorte pra toda competicao: em copa de clube e em selecao
    ele le o historico do time em TODAS as competicoes
    (competition_profile.uses_all_competitions_history), porque a propria
    competicao nao acumula jogo suficiente -- travar nela reprova a partida
    inteira em silencio.

    Esta funcao filtrava por liga SEMPRE. O resultado, em jogo de copa, era a
    tela mostrando uma amostra que o motor nunca olhou -- as vezes duas ou tres
    barras onde a decisao usou quinze, as vezes nenhuma. E' o mesmo defeito de
    08/08 (card e motor contando historias diferentes), so' que na outra ponta:
    la' a serie era LARGA demais, aqui era estreita demais.

    A regra passa a ser derivada da MESMA funcao que o motor consulta, e nao de
    uma lista de ligas repetida aqui."""
    todas_competicoes = bool(
        _competicao is not None and league_id
        and _competicao.uses_all_competitions_history(league_id))

    filtro_liga, params_liga = "", []
    if league_id and season and not todas_competicoes:
        filtro_liga = "AND ms.league_id = %s AND ms.season = %s"
        params_liga = [league_id, season]

    coluna_mando = "ms.home_team_id" if mando == "home" else "ms.away_team_id"
    adversario = _nome_do_time("away" if mando == "home" else "home")

    cur.execute(f"""
        SELECT {_COLUNAS_DA_SERIE}, {adversario} AS opponent
          FROM match_statistics ms
         WHERE {coluna_mando} = %s
           AND ms.status IN ('FT','AET','PEN')
           AND ms.fixture_id <> COALESCE(%s, -1)
           {filtro_liga}
      ORDER BY ms.match_date DESC
         LIMIT %s
    """, (team_id, excluir_fixture, *params_liga, limit))
    return [dict(r) for r in cur.fetchall()]


def _jogos_do_arbitro(cur, referee: str, season, excluir_fixture, limit: int) -> list:
    """Ultimos jogos apitados pelo arbitro, com os dois times no rotulo.

    SEM filtro de liga, de proposito: arbitro nao pertence a competicao, apita
    estadual, serie A e copa na mesma temporada, e a media de cartoes dele e' a
    mesma pessoa nas tres. E' o mesmo recorte que o motor ja' usa
    (RefereeStatsService.get_stats agrega por arbitro + temporada, sem liga) --
    filtrar aqui faria o card mostrar uma amostra que o motor nunca olhou."""
    filtro_season, params_season = "", []
    if season:
        filtro_season = "AND ms.season = %s"
        params_season = [season]

    cur.execute(f"""
        SELECT {_COLUNAS_DA_SERIE},
               {_nome_do_time("home")} || ' x ' || {_nome_do_time("away")} AS opponent
          FROM match_statistics ms
         WHERE ms.referee = %s
           AND ms.status IN ('FT','AET','PEN')
           AND ms.fixture_id <> COALESCE(%s, -1)
           {filtro_season}
      ORDER BY ms.match_date DESC
         LIMIT %s
    """, (referee, excluir_fixture, *params_season, limit))
    return [dict(r) for r in cur.fetchall()]


#: Contadores de `player_match_stats` que a serie de jogador sabe ler, e o
#: rotulo de cada um. Lista fechada porque o nome da coluna entra em SQL por
#: f-string -- vir do banco (`picks_player_stats.stat_column`) nao e' desculpa
#: pra confiar nele. Espelha services/player_stats_engine/methods.py: metodo
#: novo la' precisa de uma linha aqui, e ate' la' a serie some em vez de
#: mostrar numero errado.
_CONTADOR_DO_JOGADOR = {
    "saves":           "Defesas",
    "shots_on":        "Chutes no alvo",
    "shots_total":     "Chutes",
    "fouls_committed": "Faltas cometidas",
    "tackles_total":   "Desarmes",
    "passes_total":    "Passes",
}


def _serie_do_jogador(cur, perna: dict, limit: int) -> dict | None:
    """Serie de um prop de JOGADOR, no contador que o proprio pick nomeia.

    POR QUE NAO DA' PRA REUSAR A SERIE DE TIME AQUI
    ----------------------------------------------
    "Defesas do goleiro Warleson · 2 ou mais" e' uma linha sobre UMA pessoa, e
    a folha de match_statistics guarda o total do TIME (os dois goleiros, se
    houve substituicao). Medido contra os jogos reais: a serie de time devolvia
    media 5.17 defesas onde a linha do pick era 1.5, e pintava 6 de 6 verdes.
    Numero errado numa tela que existe pra ser conferida e' pior que tela sem
    numero -- e era exatamente pra la que o card ia se a serie de time
    respondesse por este mercado.

    A fonte certa ja esta no banco: `player_match_stats.saves`, a mesma que a
    liquidacao do pick usa (routers/live.py, bloco DEFESAS DE GOLEIRO). Serie e
    resultado passam a ler a mesma coluna, entao o grafico nao pode contradizer
    o GREEN/RED do proprio pick.

    Nao ha chamada de API aqui: a coleta ja gravou essas linhas.
    """
    player_id = perna.get("player_id")
    if not player_id:
        return None

    # GENERALIZADO EM 2026-08-27. Ate' aqui a consulta lia `saves` escrito na
    # mao, porque defesas era o unico prop que existia. Com o Player Stats a
    # coluna vem do PROPRIO pick (`stat_column`), entao chutes, faltas e
    # desarmes ganham a serie sem um ramo novo -- e um metodo que a lista
    # branca ainda nao conhece devolve None em vez de quebrar a consulta.
    coluna = perna.get("stat_column") or "saves"
    if coluna not in _CONTADOR_DO_JOGADOR:
        return None

    cur.execute(f"""
        SELECT fixture_id, match_date, {coluna} AS valor, team_name
          FROM player_match_stats
         WHERE player_id = %s
           AND {coluna} IS NOT NULL
           AND (%s IS NULL OR fixture_id <> %s)
         ORDER BY match_date DESC
         LIMIT %s
    """, (player_id, perna.get("fixture_id"), perna.get("fixture_id"), limit))
    jogos = [dict(r) for r in cur.fetchall()]
    if not jogos:
        return None

    # A linha sai do mesmo parser que grada o pick (settlement.parse_line), nao
    # de um regex local. "2 ou mais defesas" vira over 1.5 la dentro, e e' esse
    # numero que precisa atravessar o grafico.
    parsed = settlement.parse_line(perna.get("line"))
    linha, op = parsed["value"], (parsed["op"] or "over")
    if linha is None:
        return None

    itens = []
    for j in jogos:
        valor = float(j["valor"])
        resultado, _factor = settlement.settle_over_under(valor, linha, op)
        itens.append({
            "fixture_id": j["fixture_id"],
            "match_date": j["match_date"].isoformat() if hasattr(j["match_date"], "isoformat") else j["match_date"],
            "value": valor,
            "result": resultado,
            # Prop de jogador nao tem "mando" que mude a leitura do contador ·
            # sao as defesas dele, jogue onde jogar.
            "is_home": None,
            "opponent": None,
        })

    # `op` entra porque frase_da_serie conjuga a partir dele ("passou de" vs
    # "ficou abaixo de"). Sem ele a frase volta None e a serie fica muda.
    serie = {"label": _CONTADOR_DO_JOGADOR[coluna], "line": linha, "op": op,
             "matches": itens, **market_form.resumo(itens)}
    if not serie["resolved"]:
        return None
    # "goleiro Fulano" e nao so' o nome: frase_da_serie prefixa "O ", e "O
    # Lucas Arcanjo" soa errado onde "O goleiro Lucas Arcanjo" soa certo.
    # "goleiro Fulano" so' vale pro metodo de defesas -- frase_da_serie
    # prefixa "O ", e "O Lucas Arcanjo" soa errado onde "O goleiro Lucas
    # Arcanjo" soa certo. Nos outros contadores o cargo nao e' relevante (nem
    # sempre correto), entao entra so' o nome.
    nome = perna.get("player_name") or "o jogador"
    sujeito = f"goleiro {nome}" if coluna == "saves" else nome
    serie["frase"] = market_form.frase_da_serie(sujeito, serie)

    # MESMO FORMATO da perna de time (`teams` com uma serie dentro). O card nao
    # ganha um ramo novo pra prop de jogador: o que muda e' de onde o numero
    # veio, nao como ele e' desenhado.
    return {
        "fixture_id": perna.get("fixture_id"),
        "market": perna.get("market"),
        "line": perna.get("line"),
        "home_team": perna.get("home_team"),
        "away_team": perna.get("away_team"),
        "label": serie["label"],
        "line_value": serie["line"],
        "op": op,
        "escopo": "jogador",
        "teams": [{
            "team_id": None,
            "team": nome,
            "side": None,
            "amostra_curta": len(itens) < limit,
            "amostra_pedida": limit,
            **serie,
        }],
        # Arbitro nao entra: ele nao e' causa de defesa de goleiro.
        "referee": None,
    }


def _series_da_perna(cur, perna: dict, limit: int) -> dict | None:
    """Uma serie por TIME dentro de uma perna, ou None se nao houver o que ver.

    Quem entra depende do escopo do mercado: "Escanteios Casa Mais/Menos" fala
    de um time so', entao a serie do adversario seria outro numero na mesma
    tela; "Escanteios Mais/Menos" fala do confronto, e ai os dois entram, cada
    um com a propria fileira de barras.

    O lado de cada alvo e' o mando dele NESTA partida, e e' tambem o filtro dos
    jogos que entram na serie -- mandante so' com jogos em casa, visitante so'
    com jogos fora. Ver _jogos_do_time.
    """
    # Prop de jogador antes de qualquer coisa: a serie dele nao sai da folha
    # do time, e deixar cair no caminho de baixo mostraria o numero errado.
    if perna.get("player_id"):
        return _serie_do_jogador(cur, perna, limit)

    escopo = market_form.escopo_do_mercado(perna.get("market"))
    alvos = []
    if escopo == "home":
        alvos = [("home", perna.get("home_team_id"), perna.get("home_team"))]
    elif escopo == "away":
        alvos = [("away", perna.get("away_team_id"), perna.get("away_team"))]
    else:
        alvos = [
            ("home", perna.get("home_team_id"), perna.get("home_team")),
            ("away", perna.get("away_team_id"), perna.get("away_team")),
        ]
    if not all(team_id for _lado, team_id, _nome in alvos):
        return None

    series = []
    for lado, team_id, nome in alvos:
        jogos = _jogos_do_time(cur, team_id, lado, perna.get("league_id"),
                               perna.get("season"), perna.get("fixture_id"), limit)
        if not jogos:
            continue
        serie = market_form.serie_do_mercado(
            jogos, perna.get("market"), perna.get("market_type"), perna.get("line"),
            _stat_for_market, team_id=team_id,
        )
        # Sem nenhum jogo resolvido a serie nao diz nada -- resultado, placar
        # exato e defesas de goleiro caem aqui (nao ha contador por jogo em
        # match_statistics pra eles). Melhor a secao sumir do que desenhar uma
        # fileira de barras cinza.
        #
        # BTTS saiu desta lista em 2026-08-08: o contador dele e' o placar do
        # time que menos marcou, ver market_form.py.
        if not serie["resolved"]:
            continue
        series.append({
            "team_id": team_id,
            "team": nome,
            # Mando NESTE jogo, que e' tambem o mando de todos os jogos da
            # serie -- o card usa pra dizer "ultimos N em casa"/"fora".
            "side": lado,
            # Menos jogos do que a serie pediu. Filtrar por mando (2026-08-10)
            # tornou isso comum no comeco de temporada: um time tem ~7 jogos em
            # casa numa fase inteira, e no comeco tem 2. A barra existe, mas
            # dizer "ultimos 5" quando sao 2 e' o tipo de silencio que faz o
            # numero parecer mais solido do que e'. Regra no servidor pra a tela
            # nao precisar saber quantos jogos foram pedidos.
            "amostra_curta": len(jogos) < limit,
            "amostra_pedida": limit,
            # Frase de fato, no formato que o apostador reconhece das casas.
            # Vem do MESMO `serie` que desenha as barras, entao numero e texto
            # nao tem como divergir -- e ela conta os jogos em que a linha
            # bateu mesmo quando isso contraria o pick. Ver market_form.
            "frase": market_form.frase_da_serie(nome, serie, lado),
            **serie,
        })

    if not series:
        return None

    return {
        "fixture_id": perna.get("fixture_id"),
        "market": perna.get("market"),
        "line": perna.get("line"),
        "home_team": perna.get("home_team"),
        "away_team": perna.get("away_team"),
        "label": series[0]["label"],
        "line_value": series[0]["line"],
        "op": series[0]["op"],
        "escopo": escopo,
        "teams": series,
        "referee": _serie_do_arbitro(cur, perna, escopo, limit),
    }


def _serie_do_arbitro(cur, perna: dict, escopo: str, limit: int) -> dict | None:
    """Serie do ARBITRO, so' em mercado de cartoes de total.

    Cartao e' o unico contador em que quem apita responde por parte do numero --
    o motor ja' trata isso como fato (referee_model.cards_market_eligible chega a
    VETAR o mercado quando o arbitro nao tem amostra), mas o card mostrava a
    conta sem essa variavel. Duas equipes disciplinadas com um arbitro rigoroso
    dao um jogo de 6 cartoes, e nenhuma das duas series de time explicava isso.

    Fora de cartoes nao entra: em escanteios ou gols o arbitro nao e' causa, e
    uma fileira de barras ali sugeriria uma relacao que nao existe.

    Escopo de time tambem fica de fora: a linha de "Cartoes Casa" e' de um time
    (~2.5) e o contador do arbitro e' do jogo inteiro (~4.8) -- as barras
    ficariam todas de um lado da regua, dizendo o oposto do que parece.
    """
    referee = perna.get("referee")
    if not referee:
        return None
    if not market_form.e_mercado_de_cartoes(perna.get("market"), perna.get("market_type")):
        return None
    # Mercado de UM time ("Cartoes Visitante") tambem ganha o arbitro, mas como
    # CONTEXTO, nao como serie graduada. A linha do pick e de um time (~2.5) e o
    # contador do arbitro e do jogo inteiro (~4.8): pintar as barras contra essa
    # linha poria todas do mesmo lado da regua e diria o oposto do que parece.
    # Antes disso a secao simplesmente sumia, e o usuario perguntou por que a
    # multipla nao mostrava o arbitro que o VIP mostrava -- a resposta era que
    # nem VIP mostrava, quando o mercado era de time. Some a comparacao, fica a
    # informacao: quantos cartoes este arbitro da por jogo.
    so_contexto = escopo != "total"

    jogos = _jogos_do_arbitro(cur, referee, perna.get("season"),
                              perna.get("fixture_id"), limit)
    if not jogos:
        return None
    serie = market_form.serie_do_mercado(
        jogos, perna.get("market"), perna.get("market_type"), perna.get("line"),
        _stat_for_market,
    )
    if not serie["resolved"]:
        return None
    if so_contexto:
        # Sem linha nao ha regua, e sem regua o front nao pinta GREEN/RED · o
        # resultado de cada jogo sai junto pra nao sobrar cor sem criterio.
        serie["line"] = None
        for m in serie["matches"]:
            m["result"] = None
        serie["hit_rate"] = None
        serie["greens"] = 0
    return {
        "name": referee,
        "amostra_curta": len(jogos) < limit,
        "amostra_pedida": limit,
        "contexto": so_contexto,
        **serie,
    }


@router.get("/{suggestion_id}/market-form")
def get_market_form(
    suggestion_id: int,
    pick_type: str = Query("vip"),
    # 10, e nao 5 (2026-08-23). O recorte por MANDO continua -- pick do
    # Flamengo fora traz so' os jogos dele fora --, o que dobrou foi a
    # profundidade. Cinco jogos de um mando so' e' amostra curta demais pra
    # sustentar a frase e a media que o card mostra; dez ja se defende. Quem
    # tiver menos mostra o que tem, e `amostra_curta` avisa na tela.
    limit: int = Query(10, ge=3, le=20),
    current_user: dict = Depends(get_current_user),
):
    """Ultimos jogos de CADA time, NO MANDO DO JOGO, medidos pelo MERCADO do pick.

    Nao e' a forma do time (V/E/D): e' o contador que a aposta observa, jogo a
    jogo, contra a linha do pick -- verde no que teria pago, vermelho no que
    nao. Alimenta o bloco "Como esse mercado vem se comportando" dentro do
    "Entenda esta analise".

    A conta nao mora aqui: market_form.py monta a serie reusando
    _stat_for_market (dispatch de familia, com as duas armadilhas de producao
    ja resolvidas) e services/settlement.py (meia-linha asiatica, PUSH em linha
    cheia). Ver a docstring de market_form pro porque.

    UMA SERIE POR TIME, NO MANDO DO JOGO (2026-08-10). Antes o mercado de total
    devolvia UMA lista com os jogos dos dois times ordenados por data. Ninguem
    conseguia ler de quem era cada barra, e a media juntava mandos diferentes.
    Agora cada time tem a propria serie, e ela so' traz os jogos NO MANDO que
    aquele time vai jogar: mandante com jogos em casa, visitante com jogos fora.

    O preco disso e' amostra menor (um time tem ~7 jogos em casa numa fase de
    campeonato, nao 15) e e' aceito de proposito -- e' o mesmo trade da correcao
    de 2026-08-08 no motor: amostra grande que responde a outra pergunta nao e'
    amostra melhor. Ver _jogos_do_time.

    NOTA sobre mercado de TOTAL: aqui o card ficou mais estrito que o motor, que
    para totais ainda le os jogos dos dois times em qualquer mando
    (stats_model.pool_and_field). A divergencia e' conhecida e o proximo passo
    seria medir se vale alinhar o motor -- filtrar la' corta o pool de ~30 pra
    ~14 jogos, e num contador de PARTIDA (nao de time) o vies de mando e' bem
    menor que os +27% que motivaram o filtro nos mercados de um time so'.

    MULTIPLA E ALAVANCAGEM ENTRARAM JUNTO. Continuam sem UMA serie que descreva
    o bilhete -- isso nao existe, sao mercados diferentes -- mas cada PERNA tem
    a sua, que e' a versao honesta de "igual aos outros pipelines" (mesma
    decisao que a regra de mercado perna a perna ja' seguia no modal).

    A SERIE TEM QUE OLHAR O MESMO QUE O MOTOR OLHOU (corrigido 2026-08-08).
    Duas divergencias reais, achadas comparando os picks de 08/08 com o banco:

    1. MANDO. "Escanteios Visitante Mais/Menos" e' sobre quem joga fora, mas a
       consulta pegava os jogos dos DOIS times e `_stat_for_market` lia o lado
       "fora" de cada um deles, fosse de quem fosse. No pick #1573 (Botafogo x
       Fluminense) 5 das 8 barras contavam outro time -- Vasco, Bahia, Botafogo,
       Vitoria e Santos -- e a media exibida (3.00) nao era do Fluminense
       (5.20 fora de casa). Hoje sao duas travas: _jogos_do_time so' traz jogos
       do mando certo, e market_form.perspectiva_do_time poe o time no lado que
       o mercado nomeia antes de `_stat_for_market` ler a folha.

    2. COMPETICAO. O motor le historico da MESMA liga/temporada da fixture
       (MatchStatsService.get_all_matches_full); a serie lia qualquer
       competicao. No pick #1572 (Coritiba x Chapecoense) dois dos oito jogos
       eram de Copa do Brasil, com 14 e 13 escanteios, e o motor nunca os viu.
       Card e pick contando historias diferentes sobre o mesmo numero e' pior
       que nao mostrar serie nenhuma.
    """
    # Paywall: a serie do mercado devolve `market` e `line` da perna · o
    # conteudo que se paga. So' `free` e' publico; todo o resto exige plano
    # ativo, igual ao /detail. Sem esta trava, um free pegava o id do pick VIP
    # no teaser de /today (result["bloqueados"]) e lia mercado+linha aqui.
    if pick_type != "free" and not is_vip_active(current_user):
        raise HTTPException(403, "Acesso VIP necessário para ver a análise completa")

    conn = get_connection()
    cur = conn.cursor()
    try:
        if pick_type == "multipla":
            pernas = _pernas_de_multipla(cur, suggestion_id)
        elif pick_type == "alavancagem":
            pernas = _pernas_de_alavancagem(cur, suggestion_id)
        else:
            fonte = _PICK_FONTE.get(pick_type)
            if not fonte:
                return {"available": False, "reason": "tipo sem serie"}
            pernas = _pernas_de_pick_simples(cur, *fonte, suggestion_id)
            if not pernas:
                raise HTTPException(404, "Pick nao encontrado")

        legs = [s for s in (_series_da_perna(cur, p, limit) for p in pernas) if s]
        if not legs:
            return {"available": False, "reason": "sem serie por jogo"}
        return {"available": True, "legs": legs}
    finally:
        cur.close()
        conn.close()

#: Onde mora o `engine_debug` de cada tipo de pick. Lista fechada: `pick_type`
#: vem da query string e o nome da tabela entra em SQL por f-string.
_TABELA_ENGINE_DEBUG = {
    "vip":          "picks_vip",
    "free":         "picks_free",
    "faltas":       "picks_faltas",
    "goleiros":     "picks_goleiros",
    "player_stats": "picks_player_stats",
    "boost":        "picks_boost",
}

#: Teto de jogos exibidos. O motor grava ate' 10 por time (pedido do usuario em
#: 27/08); o corte aqui e' a segunda trava, pra um pick gravado por uma versao
#: futura mais generosa nao despejar trinta linhas num modal de celular.
_AMOSTRA_MAX_EXIBIDA = 10


@router.get("/{suggestion_id}/amostra")
def get_amostra(
    suggestion_id: int,
    pick_type: str = Query("vip"),
    current_user: dict = Depends(get_current_user),
):
    """Os jogos que o motor REALMENTE leu para decidir este pick.

    POR QUE ISTO NAO E' A MESMA COISA QUE /market-form
    -------------------------------------------------
    `market-form` reconsulta o banco e monta uma serie pelo contador do
    mercado. E' util (mostra GREEN/RED barra a barra), mas e' uma SEGUNDA
    leitura: ela pode divergir do que decidiu, e ja' divergiu duas vezes em
    producao -- por mando em 08/08, e por competicao em jogo de copa, onde o
    motor le todas as competicoes e a consulta lia so' a liga.

    Este endpoint nao consulta historico nenhum. Ele devolve o retrato que o
    proprio motor gravou em `engine_debug.amostra` no instante da escolha
    (services/engine_audit/amostra.py). Por construcao nao tem como divergir:
    e' o mesmo objeto que entrou na conta.

    Vem junto o CONTEXTO DO CONFRONTO, que o motor ja' calculava e que nunca
    chegava a lugar nenhum: se e' classico (excesso de cartao medido no
    confronto direto), se e' jogo de volta de mata-mata, o placar da ida e o
    agregado. Era a outra metade do pedido -- entender o JOGO, nao so' a media.

    Pick anterior a 27/08 nao tem amostra gravada. Responde
    `available: false` com motivo, e a tela nao mostra a secao · melhor que
    inventar uma amostra reconsultada que talvez nao seja a que decidiu.
    """
    tabela = _TABELA_ENGINE_DEBUG.get(pick_type)
    if not tabela:
        return {"available": False, "reason": "tipo de pick sem amostra"}

    # Paywall: a amostra e' a analise interna que decidiu o pick pago. So'
    # `free` e' publico; o resto segue a mesma regra do /detail e do
    # /market-form. Ver o comentario la'.
    if pick_type != "free" and not is_vip_active(current_user):
        raise HTTPException(403, "Acesso VIP necessário para ver a análise completa")

    conn = get_connection()
    cur = conn.cursor()
    try:
        # Pick de jogador leva TRES colunas a mais. A amostra dele e' uma fileira
        # de numeros, e numero solto nao se le: "3 2 1 4" so' vira informacao ao
        # lado da linha que precisava ser batida. O nome do mercado e o do
        # jogador vem junto pela mesma razao -- a amostra passa a dizer de QUEM
        # e de QUE mercado ela e', em vez de depender do card que ficou atras
        # do modal.
        # `picks_goleiros` e' a tabela legada e nunca teve coluna `method` -- o
        # metodo dela e' fixo e mora em `market_type` ('saves').
        extras = {"picks_player_stats": ", method, line_value, player_name",
                  "picks_goleiros": ", market_type AS method, line_value, player_name",
                  }.get(tabela, "")
        cur.execute(f"SELECT engine_debug{extras} FROM {tabela} WHERE id = %s",
                    (suggestion_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Pick nao encontrado")
        contexto_jogador = {
            "metodo": row.get("method"),
            "linha": float(row["line_value"]) if row.get("line_value") is not None else None,
            "jogador": row.get("player_name"),
        } if extras else {}

        debug = row["engine_debug"] or {}
        if isinstance(debug, str):
            try:
                debug = json.loads(debug)
            except Exception:
                debug = {}
        amostra = (debug or {}).get("amostra")
        if not amostra:
            return {"available": False,
                    "reason": "pick anterior ao registro de amostra"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logging.getLogger(__name__).warning("[AMOSTRA] %s#%s: %s", tabela, suggestion_id, e)
        return {"available": False, "reason": "nao foi possivel ler a amostra"}
    finally:
        cur.close()
        conn.close()

    # Prop de JOGADOR guarda outra forma (uma lista de valores por atuacao, nao
    # dois times). Devolvida como esta': quem desenha decide, e achatar as duas
    # num formato so' produziria campos vazios dos dois lados.
    if "valores" in amostra and "mandante" not in amostra:
        return {"available": True, "tipo": "jogador",
                "amostra": {**amostra, **contexto_jogador,
                            "valores": (amostra.get("valores") or [])[:_AMOSTRA_MAX_EXIBIDA]}}

    for lado in ("mandante", "visitante"):
        bloco = amostra.get(lado) or {}
        if bloco.get("jogos"):
            bloco["jogos"] = bloco["jogos"][:_AMOSTRA_MAX_EXIBIDA]
    return {"available": True, "tipo": "time", "amostra": amostra}



# ─── A análise inteira, numa requisição ──────────────────────────────────────
#
# O "Entenda esta análise" abria e ia se montando: a forma do mercado chegava
# de uma requisição, a amostra do motor de outra, cada uma com o próprio
# esqueleto, cada uma terminando na hora dela. Em conexão de celular isso é o
# modal pulando duas vezes na cara de quem abriu · e o pior momento pra tela
# tremer é justamente o de ler número.
#
# Uma chamada, uma espera. O front busca isto ANTES de abrir (no toque do
# botão) e guarda em cache, então na maior parte das vezes o modal abre com
# tudo pronto e não pisca nada.
#
# NÃO CALCULA NADA NOVO: chama os dois handlers que já existem e junta as
# respostas. Reimplementar aqui criaria uma segunda fonte pra mesma pergunta,
# que é como as duas telas de amostra divergiram em produção.
#
# Falha de um lado não derruba o outro: quem tem forma de mercado mas não tem
# amostra gravada (pick anterior a 27/08) continua vendo a metade que existe.
@router.get("/{suggestion_id}/analise")
def get_analise_completa(
    suggestion_id: int,
    pick_type: str = Query("vip"),
    current_user: dict = Depends(get_current_user),
):
    """Forma do mercado + amostra do motor, juntas."""
    def _tentar(fn, rotulo: str):
        try:
            return fn()
        except HTTPException:
            # Paywall e "não encontrado" são respostas legítimas dos dois
            # handlers e precisam chegar inteiras ao chamador.
            raise
        except Exception:
            logger.warning("[ANALISE] %s de %s#%s falhou", rotulo, pick_type,
                           suggestion_id, exc_info=True)
            return {"available": False}

    return {
        "market_form": _tentar(
            # `limit` explícito: chamada direta em Python não passa pelo
            # FastAPI, então o default do parâmetro seria o objeto `Query(10)`
            # em vez do número 10 · ele iria inteiro pro `LIMIT %s`.
            lambda: get_market_form(suggestion_id, pick_type=pick_type, limit=10,
                                    current_user=current_user),
            "forma do mercado"),
        "amostra": _tentar(
            lambda: get_amostra(suggestion_id, pick_type=pick_type,
                                current_user=current_user),
            "amostra"),
    }
