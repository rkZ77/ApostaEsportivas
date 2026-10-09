"""Coleta de FECHAMENTO: o retrato da cotacao perto do apito, so' dos jogos
que ja' tem pick. E' o que faz o CLV medir alguma coisa.

POR QUE EXISTE (2026-10-02)
---------------------------
O produto vende pick de valor (EV+). O unico jeito de saber, com o volume que
temos, se o motor encontra valor de verdade e' o CLV: a odd que publicamos
contra a odd que o mercado fechou. O resultado (GREEN/RED) precisa de mil
apostas pra separar vantagem de sorte; o CLV, de algumas dezenas.

Ate' aqui o "fechamento" era o ultimo retrato de `odds_snapshots` antes do
apito, e retrato so' existia quando alguem rodava `odds` -- de manha, antes
de gerar os picks. Fechamento = a propria odd do pick, CLV ~ 0 por
construcao. (Somava-se a isso o fuso errado do minuto do retrato, ver
odds_collector_service.MINUTOS_ATE_O_APITO_SQL.)

O QUE FAZ
---------
Uma rodada: acha os jogos de HOJE com pick em qualquer produto que comecam
nos proximos `JANELA_MINUTOS` e ainda nao tem retrato dentro dessa janela;
pede a cotacao de cada um (uma requisicao por casa ativa) e grava SO' o
retrato -- `odds_values`, que os motores leem, nao e' tocada.

`loop`: repete a rodada a cada `INTERVALO_MINUTOS` ate' nao sobrar jogo com
pick por comecar (ou `TETO_HORAS`). Nada roda agendado neste projeto, entao o
uso pensado e' um clique no /admin depois do "Rodar Tudo".

    python capturar_fechamento.py          uma rodada
    python capturar_fechamento.py loop     ate' o ultimo jogo com pick comecar
"""
import sys
import time

from utils.db_utils import get_connection
from utils.data_br import HOJE_BR, AGORA_BR as _AGORA_BR
from utils.api_client import ApiQuotaEsgotada
from services import api_quota
from collectors.odds_collector_service import OddsCollectorService

#: Quao perto do apito o retrato precisa ser pra valer como fechamento. Tem
#: que caber dentro de `picks_ledger_sync_service.FECHAMENTO_MAX_MINUTOS`.
JANELA_MINUTOS = 30
INTERVALO_MINUTOS = 10
TETO_HORAS = 16

#: Onde cada tabela de pick guarda o jogo. Uma consulta por tabela, cada uma
#: isolada: ambiente que nunca rodou um motor nao tem a tabela dele.
_FIXTURES_COM_PICK = (
    *(f"SELECT fixture_id FROM {t} WHERE match_date = {HOJE_BR}"
      for t in ("picks_vip", "picks_free", "picks_faltas", "picks_goleiros",
                "picks_player_stats", "picks_boost")),
    *(f"""SELECT (g->>'fixture_id')::bigint FROM {t},
                 jsonb_array_elements(games::jsonb) g
           WHERE match_date = {HOJE_BR}"""
      for t in ("picks_multiplas", "picks_bingo")),
    *(f"SELECT fixture_id_{i} FROM picks_alavancagem WHERE match_date = {HOJE_BR}"
      for i in (1, 2, 3)),
)


def fixtures_com_pick_hoje(cur) -> set:
    ids = set()
    for sql in _FIXTURES_COM_PICK:
        cur.execute("SAVEPOINT tabela_de_pick")
        try:
            cur.execute(sql)
            ids.update(r[0] for r in cur.fetchall() if r[0])
            cur.execute("RELEASE SAVEPOINT tabela_de_pick")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT tabela_de_pick")
    return ids


def _pendentes(cur, ids: set) -> tuple[list, int]:
    """(jogos pra coletar agora, jogos com pick que ainda vao comecar)."""
    if not ids:
        return [], 0
    cur.execute(f"""
        SELECT f.fixture_id,
               EXTRACT(EPOCH FROM (f.match_datetime - {_AGORA_BR})) / 60 AS minutos,
               EXISTS (SELECT 1 FROM odds_snapshots s
                        WHERE s.fixture_id = f.fixture_id
                          AND s.minutes_to_kickoff BETWEEN 0 AND %s) AS ja_tem
          FROM fixtures f
         WHERE f.fixture_id = ANY(%s)
           AND f.status IN ('NS', 'TBD')
           AND f.match_datetime > {_AGORA_BR}
    """, (JANELA_MINUTOS, list(ids)))
    linhas = cur.fetchall()
    agora = [fid for fid, minutos, ja_tem in linhas
             if minutos <= JANELA_MINUTOS and not ja_tem]
    return agora, len(linhas)


def rodada(coletor: OddsCollectorService) -> int:
    """Uma passada. Devolve quantos jogos com pick ainda vao comecar."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        ids = fixtures_com_pick_hoje(cur)
        agora, por_comecar = _pendentes(cur, ids)
    finally:
        cur.close()
        conn.close()

    print(f"[FECHAMENTO] {len(ids)} jogo(s) com pick hoje · {por_comecar} por comecar · "
          f"{len(agora)} dentro de {JANELA_MINUTOS} min do apito sem retrato.")
    casas = len(coletor.casas)
    for fixture_id in agora:
        if not api_quota.pode_gastar(casas):
            print(f"[FECHAMENTO] Cota do dia quase no fim "
                  f"(restam {api_quota.restante_conhecido()}). Parando: o CLV desses "
                  f"jogos fica sem fechamento, que e' o certo -- nao inventa.")
            break
        try:
            data = coletor.fetch_odds_by_fixture(fixture_id)
        except ApiQuotaEsgotada:
            print("[FECHAMENTO] A API recusou por cota esgotada.")
            break
        if not data or not data.get("bookmakers"):
            print(f"[FECHAMENTO] fixture {fixture_id}: sem cotacao na API.")
            continue
        n = coletor.save_snapshot_only(fixture_id, data["bookmakers"])
        print(f"[FECHAMENTO] fixture {fixture_id}: {n} cotacao(oes) no retrato.")
        _reavaliar(fixture_id)
    # Segunda passada: a escalacao oficial saiu depois da primeira reavaliacao.
    for fixture_id in _esperando_escalacao(ids):
        print(f"[FECHAMENTO] fixture {fixture_id}: escalacao oficial saiu, reavaliando.")
        _reavaliar(fixture_id)
    return por_comecar


def _esperando_escalacao(ids: set) -> list:
    try:
        from services.pick_engine import reavaliacao
        conn = get_connection()
        cur = conn.cursor()
        try:
            return reavaliacao.esperando_escalacao(cur, ids)
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"[FECHAMENTO] fila de reavaliacao com escalacao falhou: {e}")
        return []


def _reavaliar(fixture_id: int) -> None:
    """Reavaliacao dos picks do jogo com o retrato que acabou de sair (ver
    pick_engine/reavaliacao.py). Nunca derruba o fechamento: o CLV e' o
    trabalho principal desta passada."""
    try:
        from services.pick_engine import reavaliacao
        conn = get_connection()
        cur = conn.cursor()
        try:
            r = reavaliacao.reavaliar_fixture(cur, fixture_id)
            if r:
                alertas = sum(1 for x in r if x.get("alerta"))
                print(f"[FECHAMENTO] fixture {fixture_id}: {len(r)} pick(s) reavaliado(s), "
                      f"{alertas} com alerta.")
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"[FECHAMENTO] reavaliacao do fixture {fixture_id} falhou: {e}")


def run(loop: bool = False) -> None:
    coletor = OddsCollectorService()
    fim = time.monotonic() + TETO_HORAS * 3600
    while True:
        por_comecar = rodada(coletor)
        if not loop:
            return
        if por_comecar == 0:
            print("[FECHAMENTO] Nenhum jogo com pick por comecar hoje. Fim.")
            return
        if time.monotonic() >= fim:
            print(f"[FECHAMENTO] Teto de {TETO_HORAS}h atingido. Fim.")
            return
        time.sleep(INTERVALO_MINUTOS * 60)


if __name__ == "__main__":
    run(loop="loop" in [a.lower() for a in sys.argv[1:]])
