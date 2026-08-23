"""Coleta a estatistica de quem ja' apitou · puxada por VISITA, nao por relogio.

O QUE FALTAVA

`match_statistics` so' enchia quando alguem clicava "Atualizar Jogos" no /admin.
Enquanto isso o motor decide em cima dela: baseline de liga, media de time,
media do arbitro, confronto direto. Jogo encerrado sem estatistica e' uma
partida que aconteceu e o motor nao viu -- e o unico sintoma e' a media ficar
velha, que nao parece defeito de nada.

POR QUE NAO E' UM AGENDADOR

Porque agendador foi removido deste backend em 2026-08-01, depois de a cota da
API estourar, e a decisao vale. Este modulo copia a forma que a resolucao de
picks ja' usa desde 2026-08-09 (routers/live.py::maybe_resolve_pending): a
varredura acontece quando alguem VISITA o site, com freios em ordem de custo.
Site parado nao gasta nada.

OS FREIOS, do mais barato pro mais caro:

  1. AMBIENTE. So' producao. A chave da API-Football e' uma conta so' pros tres
     ambientes: uma janela aberta no dev consumiria a cota do site real.
  2. RELOGIO. Uma passada a cada `STATS_SWEEP_INTERVAL_SECONDS` (padrao 600s),
     e uma por vez -- duas visitas simultaneas nao viram duas coletas.
  3. BANCO. Existe jogo encerrado sem estatistica na janela? E' uma consulta,
     zero API, e na maior parte do dia a resposta e' nao.
  4. So' entao a API.
"""
import logging
import os
import threading
import time
from datetime import date, timedelta

from database import get_connection

logger = logging.getLogger(__name__)

_INTERVALO = int(os.getenv("STATS_SWEEP_INTERVAL_SECONDS", "600"))

#: Janela de dias que a varredura enxerga. Jogo mais velho que isso nao volta
#: sozinho: se a estatistica nao apareceu em tres dias, ela nao vai aparecer, e
#: reconsultar viraria custo fixo e permanente. O botao do /admin continua
#: varrendo sem janela.
_JANELA_DIAS = int(os.getenv("STATS_SWEEP_MAX_AGE_DAYS", "3"))

#: Teto de partidas por passada. O trabalho e' 1 requisicao por jogo; sem teto,
#: uma rodada inteira de sabado viraria 40 chamadas numa visita so'.
_TETO_POR_PASSADA = int(os.getenv("STATS_SWEEP_MAX_FIXTURES", "15"))

_lock = threading.Lock()
_estado: dict = {"ultima": 0.0, "rodando": False, "ultimo_resultado": None}

_FINALIZADOS = ("FT", "AET", "PEN")


def _habilitada() -> bool:
    """Igual ao gate da varredura de picks · ver `_varredura_habilitada`.

    `STATS_SWEEP=off` desliga na mao em qualquer ambiente, sem deploy, se a
    cota apertar.
    """
    if os.getenv("STATS_SWEEP", "on").strip().lower() in ("off", "0", "false", "no"):
        return False
    from runtime_env import is_production, side_effects_enabled
    return is_production() and side_effects_enabled()


def _ha_jogo_sem_estatistica() -> bool:
    """Freio de banco: so' banco, zero API.

    Falso positivo e' inofensivo -- a varredura roda e nao acha nada. Por isso
    a consulta prefere errar pra esse lado.
    """
    desde = date.today() - timedelta(days=_JANELA_DIAS)
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(f"""
                SELECT 1
                  FROM fixtures f
             LEFT JOIN match_statistics ms ON ms.fixture_id = f.fixture_id
                 WHERE f.status IN %s
                   AND f.match_datetime >= %s
                   AND ms.fixture_id IS NULL
                 LIMIT 1
            """, (_FINALIZADOS, desde))
            return cur.fetchone() is not None
        finally:
            cur.close()
    except Exception as e:
        logger.warning("[STATS-SWEEP] freio de banco falhou: %s", e)
        return False
    finally:
        if conn is not None:
            conn.close()


def _coletar() -> dict:
    """Estatistica das partidas pendentes e recalculo das medias de time.

    Reusa os servicos do motor em vez de reimplementar a coleta: sao os MESMOS
    que o botao do /admin dispara, entao nao existe um segundo jeito de gravar
    `match_statistics` que possa divergir do primeiro.
    """
    import sys
    from settlement_bridge import _pipeline_dir  # ja' resolve PIPELINE_SRC_PATH

    caminho = _pipeline_dir()
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

    from collectors.match_statistics_sync_service import MatchStatisticsSyncService
    from services.team_stats_aggregator_service import TeamStatsAggregatorService

    resumo = {"partidas": 0, "times": 0}

    servico = MatchStatisticsSyncService()
    saida = servico.sync_pending_fixtures()
    if isinstance(saida, dict):
        resumo["partidas"] = saida.get("processados") or saida.get("total") or 0

    # As medias TEM que ser recalculadas junto. Gravar a partida e nao
    # atualizar `team_statistics` deixa o motor lendo a media de ontem sobre um
    # historico de hoje -- o pior dos dois mundos, porque parece atualizado.
    TeamStatsAggregatorService().update_recent_teams_statistics(days=_JANELA_DIAS)
    resumo["times"] = -1  # o servico nao devolve contagem; -1 = "rodou"
    return resumo


def _passada() -> None:
    try:
        resumo = _coletar()
        _estado["ultimo_resultado"] = resumo
        logger.info("[STATS-SWEEP] %s", resumo)
    except Exception as e:
        _estado["ultimo_resultado"] = {"erro": str(e)[:200]}
        logger.error("[STATS-SWEEP] falhou: %s", e, exc_info=True)
    finally:
        with _lock:
            _estado["rodando"] = False


def maybe_sync_finished_stats() -> None:
    """Chamada de dentro de rotas de leitura. NUNCA bloqueia quem chamou.

    A coleta vai pra thread de fundo: ela faz uma requisicao por partida, e o
    visitante que por acaso disparou a varredura nao pode esperar por isso.
    """
    if not _habilitada():
        return

    agora = time.time()
    with _lock:
        if _estado["rodando"] or agora - _estado["ultima"] < _INTERVALO:
            return
        _estado["ultima"] = agora
        _estado["rodando"] = True

    try:
        if not _ha_jogo_sem_estatistica():
            with _lock:
                _estado["rodando"] = False
            return
    except Exception:
        with _lock:
            _estado["rodando"] = False
        raise

    threading.Thread(target=_passada, name="stats-sweep", daemon=True).start()


def estado_da_varredura() -> dict:
    """Retrato pro /admin. So' leitura."""
    return {
        "habilitada": _habilitada(),
        "intervalo_s": _INTERVALO,
        "janela_dias": _JANELA_DIAS,
        "rodando": _estado["rodando"],
        "ultima_passada_ha_s": (round(time.time() - _estado["ultima"])
                                if _estado["ultima"] else None),
        "ultimo_resultado": _estado["ultimo_resultado"],
    }
