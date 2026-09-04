"""Liga as decisões já gravadas aos picks que elas geraram · uma vez só.

POR QUE ESTE SCRIPT EXISTE
--------------------------
`engine_decisions` guarda, desde 07/08, tudo que o motor viu em cada partida:
os mercados candidatos, os scores parciais, o contexto e o motivo de cada
descarte. O que faltava era o elo com o RESULTADO -- a linha não dizia qual
pick ela produziu, e sem isso a aba de Auditoria só respondia "o que o motor
viu no dia 12", que é uma pergunta de arqueologia.

A pergunta que se faz de verdade é a inversa: PEGUEI UM RED, POR QUE O MOTOR
ESCOLHEU ISSO. Ela só tem resposta com `pick_table` + `pick_id` preenchidos.
O motor passou a gravar esse elo em 2026-08-28 (decision_log.registrar_selecao);
este script preenche o que já estava no banco -- três semanas de decisão, ~2.500
linhas, das quais 58 são RED dos últimos 30 dias.

POR QUE É SEGURO CASAR POR PARTIDA AQUI
---------------------------------------
Casar decisão com pick por (fixture_id, match_date) sozinho seria errado: o
mesmo jogo pode virar pick no VIP, na Free e na múltipla no mesmo dia, e as
três decisões são diferentes. O que torna o casamento exato é a coluna
`pipeline`, que já está gravada em toda linha: cada pipeline alimenta UMA
tabela de pick, então (pipeline, fixture, dia) identifica a decisão sem
ambiguidade. `method` entra no Player Stats, que é o único produto com mais de
um pick por partida (um por método).

Idempotente: só escreve onde `pick_table IS NULL`. Rodar de novo não muda nada.

    DB_ENV=prod python scripts/vincular_decisao_ao_pick.py          # relatório
    DB_ENV=prod python scripts/vincular_decisao_ao_pick.py gravar   # aplica
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

#: pipeline -> tabela de pick, para os produtos de UMA partida por pick.
#: `picks_goleiros` continua aqui porque tem pendência histórica a explicar --
#: parou de crescer, não de existir.
UMA_PARTIDA = {
    "VIP_ENGINE":         "picks_vip",
    "DICA_ENGINE":        "picks_free",
    "FALTAS_ENGINE":      "picks_faltas",
    "GOLEIROS_ENGINE":    "picks_goleiros",
    "PICK_BOOST_ENGINE":  "picks_boost",
    "LIVE_ENGINE":        "picks_live",
}

#: O Player Stats tem um pick por MÉTODO na mesma partida (saves, shots_on,
#: fouls...), então o casamento precisa do método além da partida.
POR_METODO = {"PLAYER_STATS_ENGINE": "picks_player_stats"}


def _ligar_uma_partida(cur, pipeline: str, tabela: str, gravar: bool) -> int:
    sql = f"""
        UPDATE engine_decisions d
           SET pick_table = %s,
               pick_id    = p.id,
               status     = 'selecionado'
          FROM {tabela} p
         WHERE d.pipeline   = %s
           AND d.pick_table IS NULL
           AND d.fixture_id = p.fixture_id
           AND d.match_date = p.match_date
    """
    return _executar(cur, sql, (tabela, pipeline), gravar)


def _ligar_por_metodo(cur, pipeline: str, tabela: str, gravar: bool) -> int:
    sql = f"""
        UPDATE engine_decisions d
           SET pick_table = %s,
               pick_id    = p.id,
               status     = 'selecionado'
          FROM {tabela} p
         WHERE d.pipeline   = %s
           AND d.pick_table IS NULL
           AND d.fixture_id = p.fixture_id
           AND d.match_date = p.match_date
           AND d.method     = p.method
    """
    return _executar(cur, sql, (tabela, pipeline), gravar)


def _ligar_alavancagem(cur, gravar: bool) -> int:
    """Até três pernas em colunas separadas · todas apontam pro mesmo bilhete."""
    sql = """
        UPDATE engine_decisions d
           SET pick_table = 'picks_alavancagem',
               pick_id    = p.id,
               status     = 'selecionado'
          FROM picks_alavancagem p
         WHERE d.pipeline   = 'ALAVANCAGEM_ENGINE'
           AND d.pick_table IS NULL
           AND d.match_date = p.match_date
           AND d.fixture_id IN (p.fixture_id_1, p.fixture_id_2, p.fixture_id_3)
    """
    return _executar(cur, sql, (), gravar)


def _ligar_multipla(cur, gravar: bool) -> int:
    """As pernas moram no JSON `games` · abre e casa fixture a fixture."""
    sql = """
        UPDATE engine_decisions d
           SET pick_table = 'picks_multiplas',
               pick_id    = p.id,
               status     = 'selecionado'
          FROM picks_multiplas p
         WHERE d.pipeline   = 'MULTIPLA_ENGINE'
           AND d.pick_table IS NULL
           AND d.match_date = p.match_date
           AND d.fixture_id IN (
                 SELECT (leg->>'fixture_id')::int
                   FROM jsonb_array_elements(p.games) leg
                  WHERE leg->>'fixture_id' IS NOT NULL
               )
    """
    return _executar(cur, sql, (), gravar)


def _executar(cur, sql: str, params: tuple, gravar: bool) -> int:
    """Conta antes de escrever · o modo relatório roda o mesmo UPDATE e volta
    atrás, que é o único jeito de o número do ensaio ser o número real."""
    cur.execute(sql, params)
    return cur.rowcount


def main() -> int:
    gravar = "gravar" in [a.lower() for a in sys.argv[1:]]
    conn = get_connection()
    cur = conn.cursor()
    total = 0
    try:
        for pipeline, tabela in UMA_PARTIDA.items():
            n = _ligar_uma_partida(cur, pipeline, tabela, gravar)
            total += n
            print(f"  {pipeline:<22} -> {tabela:<20} {n:>5} decisão(ões)")
        for pipeline, tabela in POR_METODO.items():
            n = _ligar_por_metodo(cur, pipeline, tabela, gravar)
            total += n
            print(f"  {pipeline:<22} -> {tabela:<20} {n:>5} decisão(ões)")
        n = _ligar_alavancagem(cur, gravar)
        total += n
        print(f"  {'ALAVANCAGEM_ENGINE':<22} -> {'picks_alavancagem':<20} {n:>5} decisão(ões)")
        n = _ligar_multipla(cur, gravar)
        total += n
        print(f"  {'MULTIPLA_ENGINE':<22} -> {'picks_multiplas':<20} {n:>5} decisão(ões)")

        if gravar:
            conn.commit()
            print(f"\n{total} decisão(ões) ligadas ao pick.")
        else:
            conn.rollback()
            print(f"\nENSAIO · {total} decisão(ões) seriam ligadas. "
                  f"Rode com `gravar` para aplicar.")
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
