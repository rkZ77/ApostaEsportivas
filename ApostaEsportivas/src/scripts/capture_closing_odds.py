"""Fase 1.5 do plano de implementacao (2026-07-25): captura a odd de
FECHAMENTO (ultima cotacao disponivel antes do jogo comecar) do mesmo
mercado/linha de cada pick ja salvo -- pre-requisito pra calcular Closing
Line Value (CLV, Fase 2.8) depois. Grava em `closing_odds`, tabela
append-only criada por essa razao especifica -- `odds_values` e' upsert
(sobrescreve por bookmaker+mercado a cada coleta) e perderia o valor
histórico do fechamento se fosse reaproveitada aqui.

So' captura pra fixtures cujo jogo comeca dentro de _LOOKAHEAD_MINUTES (ou
ja comecou ha pouco, _GRACE_MINUTES) e que ainda nao tem uma linha
capturada -- roda com seguranca em intervalos curtos (ex.: a cada 15min)
sem duplicar. Precisa ser agendado externamente perto do horario dos jogos
(mesmo padrao operacional dos outros comandos de main.py) -- este script
so' cobre a logica de captura em si.

Uso:
    python -m scripts.capture_closing_odds
"""
import sys

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from utils.db_utils import get_connection

_LOOKAHEAD_MINUTES = 60
_GRACE_MINUTES = 30

# As quatro tabelas de pick que guardam market_id -- sem ele nao da' pra
# saber contra qual mercado comparar o fechamento. picks_multiplas e
# picks_alavancagem nao guardam e por isso ficam de fora.
_PICK_SOURCES = (
    ("picks_vip", "fixture_id, market_id, market_type, line"),
    ("picks_free", "fixture_id, market_id, market_type, line"),
    ("picks_faltas", "fixture_id, market_id, market_type, line"),
    ("picks_goleiros", "fixture_id, market_id, market_type, line"),
)


def _picks_needing_capture(cur) -> list[dict]:
    """Picks com jogo comecando em breve (ou ja comecado ha pouco) e sem
    linha em closing_odds ainda pra esse (fixture_id, market_id)."""
    union_sql = " UNION ALL ".join(f"SELECT {cols} FROM {table}" for table, cols in _PICK_SOURCES)
    cur.execute(f"""
        SELECT DISTINCT picks.fixture_id, picks.market_id, picks.market_type, picks.line,
               f.match_datetime
        FROM ({union_sql}) picks
        JOIN fixtures f ON f.fixture_id = picks.fixture_id
        WHERE picks.market_id IS NOT NULL
          AND f.match_datetime <= NOW() + INTERVAL '{_LOOKAHEAD_MINUTES} minutes'
          AND f.match_datetime >= NOW() - INTERVAL '{_GRACE_MINUTES} minutes'
          AND NOT EXISTS (
              SELECT 1 FROM closing_odds co
              WHERE co.fixture_id = picks.fixture_id
                AND co.market_id = picks.market_id
                AND co.line = picks.line
          )
    """)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _direction_prefix(line_label: str) -> str:
    """'Under 5.5' -> 'under', 'Home +0.25' -> 'home' -- primeira palavra
    do value_label salvo no pick, pra casar contra odds_values.value_name
    sem precisar reimplementar o parser completo de parse_line()."""
    return (line_label or "").strip().split(" ")[0].strip().lower()


def _line_number(line_label: str):
    """'Over 4.5' -> '4.5'. None quando a linha nao tem numero ('Yes', 'Home')
    -- nesses mercados line_value costuma ser NULL e nao ha o que casar."""
    for pedaco in (line_label or "").replace(",", ".").split():
        try:
            return f"{float(pedaco):g}"
        except ValueError:
            continue
    return None


def _best_closing_odd(cur, fixture_id: int, market_id: int, direction: str,
                      line_label: str):
    """Melhor odd corrente pra a MESMA linha do MESMO mercado.

    A versao anterior agrupava por (value_name, line_value) e ordenava por
    `best_odd DESC LIMIT 1` -- ou seja, entre todas as linhas daquela direcao
    ela escolhia a de MAIOR odd, que num "Over" e' sempre a linha mais
    distante. Um pick de "Over 4.5" gravava como fechamento a odd do "Over
    9.5". Mesmo defeito de direcao unica que o fallback de
    picks_ledger_sync_service._closing_odd_for tinha: o numero saia sempre pro
    lado que faz o motor parecer pior do que e'.
    """
    alvo = _line_number(line_label)
    cur.execute("""
        SELECT value_name, line_value, MAX(odd_value) AS best_odd,
               COUNT(DISTINCT bookmaker_id) AS n_books
        FROM odds_values
        WHERE fixture_id = %s AND market_id = %s AND LOWER(value_name) LIKE %s
        GROUP BY value_name, line_value
    """, (fixture_id, market_id, f"{direction}%"))
    candidatos = cur.fetchall()
    if not candidatos:
        return None

    if alvo is not None:
        candidatos = [c for c in candidatos
                      if _line_number(c[1]) == alvo or _line_number(c[0]) == alvo]
        if not candidatos:
            return None
    elif len(candidatos) > 1:
        # Sem numero na linha (mercado categorico) e mais de um valor casando o
        # prefixo: nao da' pra saber qual e' o certo. Devolver o de maior odd
        # seria repetir o defeito.
        return None

    melhor = max(candidatos, key=lambda c: c[2])
    return {"value_name": melhor[0], "line_value": melhor[1],
            "odd": melhor[2], "n_books": melhor[3]}


def capture():
    conn = get_connection()
    cur = conn.cursor()

    pending = _picks_needing_capture(cur)
    print(f"[CLOSING_ODDS] {len(pending)} pick(s) pendente(s) de captura.")

    captured = 0
    for p in pending:
        direction = _direction_prefix(p["line"])
        best = (_best_closing_odd(cur, p["fixture_id"], p["market_id"], direction, p["line"])
                if direction else None)
        if not best:
            print(f"[CLOSING_ODDS] fixture={p['fixture_id']} market={p['market_id']}: sem odd atual encontrada, pulando.")
            continue

        cur.execute("""
            INSERT INTO closing_odds (fixture_id, market_id, market_type, line, closing_odd, bookmaker)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            p["fixture_id"], p["market_id"], p["market_type"], p["line"],
            best["odd"], f"best_of_{best['n_books']}",
        ))
        conn.commit()
        captured += 1
        print(f"[CLOSING_ODDS] fixture={p['fixture_id']} market={p['market_id']} "
              f"({p['market_type']} {p['line']}): odd de fechamento {best['odd']} ({best['n_books']} casas).")

    cur.close()
    conn.close()
    print(f"[CLOSING_ODDS] {captured} linha(s) capturada(s).")


if __name__ == "__main__":
    capture()
