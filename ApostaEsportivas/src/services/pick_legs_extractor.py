"""Extrai pernas individuais das 4 tabelas de picks (picks_vip/picks_free
sao 1 linha = 1 perna; picks_multiplas/picks_alavancagem tem 2-3 pernas
por linha, em formatos diferentes -- JSON array vs colunas _1/_2/_3).
Usado por scripts/backtest_pick_engine.py e services/picks_ledger_sync_service.py
-- extraido pra um lugar so em vez de duplicar a logica de achatamento."""
import json


#: Tabelas que seguem a nomenclatura de picks_vip (home_team_name,
#: probability, ev). picks_free, picks_faltas e picks_goleiros usam a outra
#: (home_team, prob_real, edge) -- o desalinhamento historico entre as duas
#: familias de nome, que picks_live NAO repete de proposito.
_TABELAS_ESTILO_VIP = ("picks_vip", "picks_live")


def fetch_vip_free_legs(cur, table: str) -> list:
    """cur precisa ser RealDictCursor. Uma linha = uma perna.

    picks_vip e picks_live guardam nome do time em home_team_name/
    away_team_name; picks_free, picks_faltas e picks_goleiros guardam em
    home_team/away_team -- colunas diferentes."""
    estilo_vip = table in _TABELAS_ESTILO_VIP
    team_cols = ("home_team_name AS home_team, away_team_name AS away_team"
                 if estilo_vip else "home_team, away_team")
    # market_id e' o que identifica QUAL mercado da casa de apostas a perna
    # aponta. Sem ele, casar a perna contra `odds_snapshots` so' pelo rotulo da
    # linha pega um mercado qualquer -- ver o defeito documentado em
    # picks_ledger_sync_service._closing_odd_for. picks_live nao tem a coluna,
    # entao a selecao e' condicional.
    market_id_col = ("market_id" if _tem_coluna(cur, table, "market_id")
                     else "NULL::int AS market_id")
    cur.execute(f"""
        SELECT id, fixture_id, match_date, home_team_id, away_team_id,
               {market_id_col},
               {team_cols}, market, market_type, line, odd, bet_house,
               confidence, {"probability" if estilo_vip else "prob_real AS probability"},
               {"ev" if estilo_vip else "edge AS ev"},
               reasoning, stake_pct, stake_units, result, profit, created_at,
               engine_debug -> 'ai_review' AS ai_review
        FROM {table}
        WHERE fixture_id IS NOT NULL
    """)
    legs = []
    for row in cur.fetchall():
        d = dict(row)
        d["source_table"] = table
        d["source_id"] = d.pop("id")
        # leg_number=1 (nao None) -- NULL nao e deduplicado por UNIQUE
        # constraint no Postgres (NULL != NULL), quebraria idempotencia
        # do upsert em picks_ledger.
        d["leg_number"] = 1
        legs.append(d)
    return legs


def fetch_multiplas_legs(cur) -> list:
    """cur precisa ser RealDictCursor."""
    cur.execute("SELECT id, games, match_date, created_at FROM picks_multiplas")
    legs = []
    for row in cur.fetchall():
        games_raw = row["games"]
        games = games_raw if isinstance(games_raw, list) else json.loads(games_raw)
        for i, g in enumerate(games, start=1):
            if not g.get("fixture_id"):
                continue
            legs.append({
                "source_table": "picks_multiplas", "source_id": row["id"], "leg_number": i,
                "fixture_id": g["fixture_id"], "match_date": row["match_date"],
                "home_team_id": g.get("home_team_id"), "away_team_id": g.get("away_team_id"),
                "home_team": g.get("home_team"), "away_team": g.get("away_team"),
                "market": g.get("market", ""), "market_type": g.get("market_type"),
                # So' existe nas multiplas geradas a partir de 2026-08-20; nas
                # anteriores fica None e a perna nao recebe CLV.
                "market_id": g.get("market_id"),
                "line": g.get("line", ""), "odd": g.get("odd"), "bet_house": g.get("bet_house"),
                "confidence": g.get("confidence"), "probability": g.get("prob_real"),
                "ev": None, "reasoning": None, "stake_pct": None, "stake_units": None,
                "result": g.get("result"), "profit": None, "created_at": row["created_at"],
                # A multipla e' revisada como bilhete unico, entao toda perna
                # carrega o mesmo parecer -- ver multipla_pipeline._save_multipla.
                "ai_review": g.get("ai_review"),
            })
    return legs


def _tem_coluna(cur, tabela: str, coluna: str) -> bool:
    """Coluna nova em tabela que ja' existe em PROD so' aparece depois que o
    pipeline correspondente rodou o ALTER. Ate' la', selecionar a coluna
    derrubaria a extracao inteira -- e o ledger e' lido por todo o site."""
    cur.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s LIMIT 1
    """, (tabela, coluna))
    return cur.fetchone() is not None


def fetch_alavancagem_legs(cur) -> list:
    """cur precisa ser RealDictCursor."""
    tem_review = _tem_coluna(cur, "picks_alavancagem", "ai_review")
    cur.execute(f"""
        SELECT {'ai_review' if tem_review else 'NULL::jsonb AS ai_review'},
               id, match_date, created_at,
               fixture_id_1, home_team_1, away_team_1, market_1, market_type_1, line_1, odd_1,
               bet_house_1, confidence_1, prob_real_1, reasoning_1,
               fixture_id_2, home_team_2, away_team_2, market_2, market_type_2, line_2, odd_2,
               bet_house_2, confidence_2, prob_real_2, reasoning_2,
               fixture_id_3, home_team_3, away_team_3, market_3, market_type_3, line_3, odd_3,
               bet_house_3, confidence_3, prob_real_3, reasoning_3
        FROM picks_alavancagem
    """)
    legs = []
    for row in cur.fetchall():
        for i in (1, 2, 3):
            fid = row[f"fixture_id_{i}"]
            if not fid:
                continue
            legs.append({
                "source_table": "picks_alavancagem", "source_id": row["id"], "leg_number": i,
                "fixture_id": fid, "match_date": row["match_date"],
                "home_team_id": None, "away_team_id": None,
                "home_team": row[f"home_team_{i}"], "away_team": row[f"away_team_{i}"],
                "market": row[f"market_{i}"] or "", "market_type": row[f"market_type_{i}"],
                # picks_alavancagem nao guarda market_id em nenhuma das 3
                # pernas -- sem ele nao ha como saber contra qual mercado
                # comparar o fechamento, e o CLV fica NULL (que e' o certo).
                "market_id": None,
                "line": row[f"line_{i}"] or "", "odd": row[f"odd_{i}"], "bet_house": row[f"bet_house_{i}"],
                "confidence": row[f"confidence_{i}"], "probability": row[f"prob_real_{i}"],
                "ev": None, "reasoning": row[f"reasoning_{i}"], "stake_pct": None, "stake_units": None,
                "result": None, "profit": None, "created_at": row["created_at"],
                # Um parecer por bilhete, replicado nas 2-3 pernas (a coluna
                # ai_review e' do bilhete inteiro, nao da perna).
                "ai_review": row["ai_review"],
            })
    return legs


def fetch_all_legs(cur) -> list:
    """Todas as pernas de todas as tabelas de picks, achatadas.
    cur precisa ser RealDictCursor."""
    legs = []
    legs += fetch_vip_free_legs(cur, "picks_vip")
    legs += fetch_vip_free_legs(cur, "picks_free")
    # picks_faltas e picks_goleiros usam exatamente as mesmas colunas de
    # picks_free (home_team/away_team, prob_real, edge), entao reusam o mesmo
    # extractor -- os condicionais la' dentro so' distinguem picks_vip.
    # try/except porque instancia sem a migracao das tabelas novas nao pode
    # deixar de sincronizar o ledger inteiro.
    #
    # picks_live entra na MESMA lista protegida (2026-08-11): a tabela so'
    # existe onde o motor Live rodou, e em producao ela nao existe -- o
    # except aqui e' o que garante que a sincronizacao do ledger do pre-jogo
    # continua funcionando identica onde o Live nao foi implantado.
    for tabela in ("picks_faltas", "picks_goleiros", "picks_live"):
        try:
            legs += fetch_vip_free_legs(cur, tabela)
        except Exception:
            cur.connection.rollback()
    legs += fetch_multiplas_legs(cur)
    legs += fetch_alavancagem_legs(cur)
    return legs


def fixture_context(cur, fixture_id: int):
    """home_team_id/away_team_id/league_id/season direto de match_statistics
    (fonte unica de verdade -- ignora o que estiver denormalizado nas
    tabelas de picks, que pode faltar pra multiplas/alavancagem).
    cur pode ser cursor comum (posicional) ou RealDictCursor."""
    cur.execute("""
        SELECT home_team_id, away_team_id, league_id, season
        FROM match_statistics WHERE fixture_id = %s LIMIT 1
    """, (fixture_id,))
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {"home_team_id": row[0], "away_team_id": row[1], "league_id": row[2], "season": row[3]}
