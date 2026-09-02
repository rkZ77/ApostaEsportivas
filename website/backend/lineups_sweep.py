"""A ESCALAÇÃO do pick de jogador, puxada por VISITA.

O QUE ISTO RESOLVE
------------------
Pick de jogador é sobre uma pessoa, e ninguém perguntava se essa pessoa ia
entrar em campo. Um titular poupado no meio da semana produzia um pick que só
podia dar RED: a linha é "2 ou mais chutes no alvo" e quem não joga faz zero.
Pior que perder, o card seguia anunciando a aposta como se ela estivesse de pé
até o apito final.

A informação existe e é barata: `/fixtures/lineups` publica a escalação oficial
de 20 a 40 minutos antes do apito. Uma requisição por partida, uma vez.

O QUE A VARREDURA FAZ COM ELA
-----------------------------
Três estados, e os três aparecem no card:

  · escalação ainda não publicada  -> o card avisa que ainda não saiu;
  · jogador no XI inicial          -> o card confirma que ele começa;
  · jogador FORA do XI inicial     -> o pick é ANULADO (PUSH) e o card fica no
    lugar dizendo isso.

ANULAR, E NÃO DEIXAR PERDER. É o que a casa faz: mercado de jogador que não
entra em campo é anulado e a entrada volta. Marcar RED puniria o apostador por
uma decisão do técnico, que não é o que o pick previu -- o pick previu o que
ELE faria jogando. E some com a evidência: uma sequência de REDs "do motor" que
na verdade é escalação, e ninguém investigaria a diferença.

O CARD FICA. Sumir com ele no dia seguinte ao "cadê o pick do Pedro" é pior que
mostrar o pick anulado: quem seguiu a aposta precisa entender por que a casa
devolveu a entrada dele.

POR QUE NÃO É UM AGENDADOR
--------------------------
Porque agendador foi removido deste backend em 2026-08-01, depois de a cota da
API estourar, e a decisão vale. Este módulo copia a forma de stats_sweep.py e
de routers/live.py::maybe_resolve_pending: a varredura acontece quando alguém
VISITA o site, com freios em ordem de custo. Site parado não gasta nada.

OS FREIOS, do mais barato pro mais caro:

  1. AMBIENTE. Só produção, pelo mesmo motivo dos outros dois: a chave da
     API-Football é uma conta só pros três ambientes.
  2. RELÓGIO. Uma passada a cada `LINEUP_SWEEP_INTERVAL_SECONDS` (padrão 300s),
     e uma por vez.
  3. BANCO. Existe pick de jogador pendente cujo jogo começa dentro da janela e
     cuja partida ainda não tem escalação oficial gravada? Uma consulta, zero
     API, e na maior parte do dia a resposta é não.
  4. Só então a API, com teto por passada.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import requests

import api_quota
from database import get_connection

logger = logging.getLogger(__name__)

API_BASE = "https://v3.football.api-sports.io"

_INTERVALO = int(os.getenv("LINEUP_SWEEP_INTERVAL_SECONDS", "300"))

#: Quanto antes do apito a varredura começa a perguntar. O provedor publica de
#: 20 a 40 minutos antes; 120 dá folga para o jogo que sai cedo sem transformar
#: a pergunta num custo que se repete a tarde inteira.
_ANTES_MIN = int(os.getenv("LINEUP_SWEEP_ANTES_MINUTOS", "120"))

#: E até quando ela insiste. Depois do apito a escalação já saiu; se não saiu
#: em três horas, não vai sair, e continuar perguntando vira custo fixo.
_DEPOIS_MIN = int(os.getenv("LINEUP_SWEEP_DEPOIS_MINUTOS", "180"))

#: Teto de partidas por passada. O trabalho é uma requisição por jogo.
_TETO = int(os.getenv("LINEUP_SWEEP_MAX_FIXTURES", "10"))

#: Depois de tantas tentativas sem escalação publicada, a partida sai da fila.
#: Existe liga que o provedor simplesmente não cobre com lineup, e sem este
#: corte ela seria reconsultada a cada passada até o fim da janela.
_MAX_TENTATIVAS = int(os.getenv("LINEUP_SWEEP_MAX_TENTATIVAS", "12"))

MOTIVO_FORA = "jogador não começou entre os titulares"

_lock = threading.Lock()
_estado: dict = {"ultima": 0.0, "rodando": False, "ultimo_resultado": None}


def _habilitada() -> bool:
    """Mesmo gate das outras duas varreduras. Ver stats_sweep._habilitada."""
    if os.getenv("LINEUP_SWEEP", "on").strip().lower() in ("off", "0", "false", "no"):
        return False
    from runtime_env import is_production, side_effects_enabled
    return is_production() and side_effects_enabled()


def _headers() -> dict:
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


#: A fila. Partida com pick de jogador pendente, dentro da janela do apito, sem
#: escalação oficial gravada e que ainda não desistiu de tentar.
#:
#: `match_datetime` é horário de Brasília sem fuso (ver a nota do projeto sobre
#: fusos), então a comparação é com NOW() já convertido para o mesmo fuso -- e
#: nunca com `match_date`, que é DATE pura e não tem hora nenhuma.
_SQL_FILA = """
    SELECT DISTINCT pp.fixture_id, f.match_datetime
      FROM picks_player_stats pp
      JOIN fixtures f ON f.fixture_id = pp.fixture_id
 LEFT JOIN fixture_lineups fl ON fl.fixture_id = pp.fixture_id
     WHERE pp.result IS NULL
       AND pp.fixture_id IS NOT NULL
       AND COALESCE(fl.oficial, FALSE) = FALSE
       AND COALESCE(fl.tentativas, 0) < %s
       AND f.match_datetime BETWEEN
             (NOW() AT TIME ZONE 'America/Sao_Paulo') - (%s * INTERVAL '1 minute')
         AND (NOW() AT TIME ZONE 'America/Sao_Paulo') + (%s * INTERVAL '1 minute')
     ORDER BY f.match_datetime
     LIMIT %s
"""


def _fila(cur, limite: int = _TETO) -> list[int]:
    cur.execute(_SQL_FILA, (_MAX_TENTATIVAS, _DEPOIS_MIN, _ANTES_MIN, limite))
    return [r["fixture_id"] for r in cur.fetchall()]


def _ha_partida_na_fila() -> bool:
    """Freio de banco: só banco, zero API."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            return bool(_fila(cur, limite=1))
        finally:
            cur.close()
    except Exception as e:
        logger.warning("[LINEUP-SWEEP] freio de banco falhou: %s", e)
        return False
    finally:
        if conn is not None:
            conn.close()


def _ids_da_escalacao(times: list) -> tuple[list, list]:
    """(titulares, reservas) em player_id, somando os dois times.

    O provedor devolve uma entrada por time, cada uma com `startXI` e
    `substitutes`. Jogador sem id acontece (base, nome não resolvido) e é
    descartado: sem id não dá para casar com o pick, e adivinhar por nome é
    exatamente o tipo de casamento que já falhou por acento neste projeto.
    """
    titulares, reservas = [], []
    for time_ in times or []:
        for chave, destino in (("startXI", titulares), ("substitutes", reservas)):
            for item in time_.get(chave) or []:
                pid = ((item or {}).get("player") or {}).get("id")
                if pid is not None:
                    destino.append(int(pid))
    return titulares, reservas


def _buscar(fixture_id: int) -> tuple[list, list] | None:
    """A escalação de uma partida. `None` quando ainda não foi publicada.

    Nunca levanta: falha de rede não pode derrubar a varredura inteira, e a
    partida volta na próxima passada.
    """
    try:
        r = requests.get(f"{API_BASE}/fixtures/lineups", headers=_headers(),
                         params={"fixture": fixture_id}, timeout=12)
        api_quota.registrar(r.headers, origem="lineups")
        if r.status_code != 200:
            logger.warning("[LINEUP-SWEEP] fixture %s: HTTP %s", fixture_id, r.status_code)
            return None
        resposta = (r.json() or {}).get("response") or []
        if not resposta:
            return None
        titulares, reservas = _ids_da_escalacao(resposta)
        # Escalação sem nenhum titular não é escalação: o provedor devolve o
        # bloco com formação e lista vazia enquanto o clube não confirma.
        # Gravar isso como oficial anularia todos os picks da partida.
        if not titulares:
            return None
        return titulares, reservas
    except Exception as e:
        logger.warning("[LINEUP-SWEEP] fixture %s falhou: %s", fixture_id, e)
        return None


def _registrar_tentativa(cur, fixture_id: int) -> None:
    cur.execute("""
        INSERT INTO fixture_lineups (fixture_id, tentativas, atualizado_em)
             VALUES (%s, 1, NOW())
        ON CONFLICT (fixture_id) DO UPDATE
                SET tentativas = fixture_lineups.tentativas + 1,
                    atualizado_em = NOW()
    """, (fixture_id,))


def _gravar(cur, fixture_id: int, titulares: list, reservas: list) -> None:
    cur.execute("""
        INSERT INTO fixture_lineups
                    (fixture_id, oficial, titulares, reservas, tentativas, atualizado_em)
             VALUES (%s, TRUE, %s, %s, 1, NOW())
        ON CONFLICT (fixture_id) DO UPDATE
                SET oficial = TRUE,
                    titulares = EXCLUDED.titulares,
                    reservas = EXCLUDED.reservas,
                    tentativas = fixture_lineups.tentativas + 1,
                    atualizado_em = NOW()
    """, (fixture_id, titulares, reservas))


def _anular_fora_do_xi(cur, fixture_id: int, titulares: list) -> int:
    """Anula os picks pendentes de quem não começa. Devolve quantos.

    `profit = 0` porque PUSH devolve a entrada: nem ganho nem perda. É o mesmo
    tratamento da anulação por falta de estatística (routers/live.py), e é o
    que faz a aposta seguida sair do saldo sem contar como erro do motor -- o
    /admin não conta PUSH no denominador de acerto.

    A APOSTA SEGUIDA PRECISA SABER. Quem seguiu o pick tem uma linha em
    `user_followed_picks`, e ela é liquidada por `_sync_followed_result` --
    o mesmo ponto único por onde todo resultado do site passa, e que também
    alimenta o sino. Gravar só na tabela do pick deixaria a aposta do usuário
    pendente para sempre, com a banca dele segurando uma entrada que a casa já
    devolveu.
    """
    cur.execute("""
        UPDATE picks_player_stats
           SET result = 'PUSH', profit = 0, void_reason = %s
         WHERE fixture_id = %s
           AND result IS NULL
           AND (player_id IS NULL OR NOT (player_id = ANY(%s)))
     RETURNING id
    """, (MOTIVO_FORA, fixture_id, titulares))
    ids = [r["id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

    if ids:
        # Import local: `routers.live` puxa meio backend, e este módulo é
        # carregado de dentro de uma rota de leitura.
        from routers.live import _sync_followed_result
        for pick_id in ids:
            try:
                _sync_followed_result(pick_id, "player_stats", "PUSH", cur)
            except Exception:
                logger.error("[LINEUP-SWEEP] sync do pick %s falhou",
                             pick_id, exc_info=True)
    return len(ids)


def _passada() -> None:
    resumo = {"consultadas": 0, "publicadas": 0, "anulados": 0}
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            fixtures = _fila(cur)
        finally:
            cur.close()

        for fixture_id in fixtures:
            resumo["consultadas"] += 1
            escalacao = _buscar(fixture_id)
            cur = conn.cursor()
            try:
                if escalacao is None:
                    # Ainda não saiu. Só conta a tentativa, para a partida que
                    # o provedor nunca vai cobrir sair da fila sozinha.
                    _registrar_tentativa(cur, fixture_id)
                else:
                    titulares, reservas = escalacao
                    _gravar(cur, fixture_id, titulares, reservas)
                    anulados = _anular_fora_do_xi(cur, fixture_id, titulares)
                    resumo["publicadas"] += 1
                    resumo["anulados"] += anulados
                    if anulados:
                        logger.warning(
                            "[LINEUP-SWEEP] fixture %s: %s pick(s) anulado(s), %s",
                            fixture_id, anulados, MOTIVO_FORA)
                conn.commit()
            except Exception:
                conn.rollback()
                logger.error("[LINEUP-SWEEP] gravação da fixture %s falhou",
                             fixture_id, exc_info=True)
            finally:
                cur.close()

        _estado["ultimo_resultado"] = resumo
        logger.info("[LINEUP-SWEEP] %s", resumo)
    except Exception as e:
        _estado["ultimo_resultado"] = {"erro": str(e)[:200]}
        logger.error("[LINEUP-SWEEP] falhou: %s", e, exc_info=True)
    finally:
        if conn is not None:
            conn.close()
        with _lock:
            _estado["rodando"] = False


def maybe_check_lineups() -> None:
    """Chamada de dentro de rotas de leitura. NUNCA bloqueia quem chamou."""
    if not _habilitada():
        return

    agora = time.time()
    with _lock:
        if _estado["rodando"] or agora - _estado["ultima"] < _INTERVALO:
            return
        _estado["ultima"] = agora
        _estado["rodando"] = True

    try:
        if not _ha_partida_na_fila():
            with _lock:
                _estado["rodando"] = False
            return
    except Exception:
        with _lock:
            _estado["rodando"] = False
        raise

    threading.Thread(target=_passada, name="lineup-sweep", daemon=True).start()


def estado_da_varredura() -> dict:
    """Retrato pro /admin. Só leitura."""
    return {
        "habilitada": _habilitada(),
        "intervalo_s": _INTERVALO,
        "janela_antes_min": _ANTES_MIN,
        "janela_depois_min": _DEPOIS_MIN,
        "rodando": _estado["rodando"],
        "ultima_passada_ha_s": (round(time.time() - _estado["ultima"])
                                if _estado["ultima"] else None),
        "ultimo_resultado": _estado["ultimo_resultado"],
    }
