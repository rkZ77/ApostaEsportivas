import json
import psycopg2.extras
from utils.db_utils import get_connection


class AIPerformanceService:
    """
    Consulta o histórico de resultados das sugestões da IA e retorna
    um resumo compacto para calibração do confidence nas próximas análises.
    """

    def get_summary(self, days: int = 60) -> dict | None:
        """
        Retorna resumo de desempenho por mercado dos últimos N dias.
        Retorna None se não houver dados suficientes (< 5 resultados).
        """
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # ── Desempenho por market_type (picks_vip) ──────────────────
        cur.execute("""
            SELECT
                COALESCE(market_type, 'unknown') AS market_type,
                COUNT(*) AS total,
                ROUND(AVG(
                    CASE
                        WHEN result = 'GREEN'     THEN 1.0
                        WHEN result = 'RED'       THEN 0.0
                    END
                )::numeric, 3) AS hit_rate,
                ROUND(AVG(confidence)::numeric, 3) AS avg_conf
            FROM picks_vip
            WHERE result IN ('GREEN', 'RED')
              AND created_at >= NOW() - INTERVAL '%s days'
            GROUP BY market_type
            ORDER BY total DESC;
        """, (days,))

        rows = cur.fetchall()

        total_geral = sum(r["total"] for r in rows)
        if total_geral < 5:
            cur.close()
            conn.close()
            return None

        por_mercado = {}
        weighted_hit = 0.0
        for r in rows:
            mt = r["market_type"]
            hit = float(r["hit_rate"] or 0)
            conf = float(r["avg_conf"] or 0)
            gap = round(conf - hit, 3)
            por_mercado[mt] = {
                "n":   int(r["total"]),
                "hit": hit,
                "conf": conf,
                "gap": gap,   # positivo = IA foi superconfiante
            }
            weighted_hit += hit * int(r["total"])

        hit_geral = round(weighted_hit / total_geral, 3) if total_geral else None

        # ── Tendência: últimos 10 resultados ─────────────────────────────
        cur.execute("""
            SELECT ROUND(AVG(
                CASE WHEN result = 'GREEN' THEN 1.0 WHEN result = 'RED' THEN 0.0 END
            )::numeric, 3) AS hit_10
            FROM (
                SELECT result FROM picks_vip
                WHERE result IN ('GREEN', 'RED')
                ORDER BY created_at DESC
                LIMIT 10
            ) t;
        """)
        row10 = cur.fetchone()
        hit_recente = float(row10["hit_10"]) if row10 and row10["hit_10"] is not None else None

        # ── Desempenho das múltiplas ──────────────────────────────────────
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN result = 'GREEN' THEN 1 ELSE 0 END) AS green
            FROM picks_multiplas
            WHERE result IN ('GREEN', 'RED')
              AND created_at >= NOW() - INTERVAL '%s days';
        """, (days,))
        mp = cur.fetchone()
        multiplas = None
        if mp and int(mp["total"]) > 0:
            n = int(mp["total"])
            g = int(mp["green"])
            multiplas = {"n": n, "hit": round(g / n, 3)}

        cur.close()
        conn.close()

        return {
            "periodo_dias": days,
            "total_analisadas": total_geral,
            "hit_geral": hit_geral,
            "hit_recente_10": hit_recente,
            "por_mercado": por_mercado,
            "multiplas": multiplas,
        }

    def get_calibration_rows(self, days: int = 60) -> list[dict]:
        """Linhas cruas de picks_vip+picks_free resolvidos nos últimos N dias --
        market_type, confidence declarado, o retrato salvo no momento da escolha
        (engine_debug, ver services/pick_engine/homologation.py::build_score_breakdown_section)
        e cartões vermelhos do jogo (sinal de evento atípico). Sem agregação
        nem classificação aqui de propósito -- isso acontece em Python via
        services/pick_engine/red_analysis.py + calibration.py (mais legível
        que embutir a lógica de classify_miss em SQL, e reaproveita a mesma
        função testável que decide se um RED conta contra a calibração).

        picks_vip não tem league_id direto (fixtures é só fila operacional,
        o registro permanente é match_statistics -- mesmo padrão já usado em
        website/backend/routers/public.py::_sub_vip); picks_free já grava
        league_id direto (engine_pipelines/dica_pipeline.py), com fallback
        pro join só pra picks antigos que não tinham essa coluna ainda."""
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                pv.market_type, pv.result, pv.confidence, pv.engine_debug,
                ms.league_id AS league_id,
                COALESCE(ms.home_red_cards, 0) + COALESCE(ms.away_red_cards, 0) AS red_cards
            FROM picks_vip pv
            LEFT JOIN match_statistics ms ON ms.fixture_id = pv.fixture_id
            WHERE pv.result IN ('GREEN', 'RED')
              AND pv.created_at >= NOW() - INTERVAL '%s days'

            UNION ALL

            SELECT
                pf.market_type, pf.result, pf.confidence, pf.engine_debug,
                COALESCE(pf.league_id, ms.league_id) AS league_id,
                COALESCE(ms.home_red_cards, 0) + COALESCE(ms.away_red_cards, 0) AS red_cards
            FROM picks_free pf
            LEFT JOIN match_statistics ms ON ms.fixture_id = pf.fixture_id
            WHERE pf.result IN ('GREEN', 'RED')
              AND pf.created_at >= NOW() - INTERVAL '%s days'
        """, (days, days))

        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]

    def format_for_prompt(self, days: int = 60) -> str:
        """
        Retorna string compacta pronta para injetar no prompt.
        Retorna string informando ausência de dados se não houver histórico.
        """
        data = self.get_summary(days)
        if not data:
            return '{"status": "sem historico suficiente · menos de 5 resultados registrados"}'
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def get_team_picks(self, teams: list[str], limit: int = 15) -> list[dict]:
        """Últimos picks de qualquer pipeline envolvendo os times informados.
        Pesquisa picks_vip, picks_free e picks_alavancagem.
        """
        if not teams:
            return []
        teams_arr = list({t.strip() for t in teams if t})

        conn = get_connection()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                (
                  SELECT 'VIP' AS pipeline, match_date,
                         home_team_name AS home, away_team_name AS away,
                         market, COALESCE(line,'') AS line,
                         odd::text AS odd, confidence, result,
                         LEFT(reasoning, 120) AS reasoning,
                         created_at
                  FROM picks_vip
                  WHERE home_team_name = ANY(%s) OR away_team_name = ANY(%s)
                )
                UNION ALL
                (
                  SELECT 'Free' AS pipeline, match_date,
                         home_team AS home, away_team AS away,
                         market, COALESCE(line,'') AS line,
                         odd::text AS odd, confidence, result,
                         LEFT(reasoning, 120) AS reasoning,
                         created_at
                  FROM picks_free
                  WHERE home_team = ANY(%s) OR away_team = ANY(%s)
                )
                UNION ALL
                (
                  SELECT 'Alavancagem' AS pipeline, match_date,
                         home_team_1 AS home, away_team_1 AS away,
                         market_1 AS market, COALESCE(line_1,'') AS line,
                         odd_1::text AS odd, confidence_1 AS confidence,
                         result,
                         LEFT(reasoning_1, 120) AS reasoning,
                         created_at
                  FROM picks_alavancagem
                  WHERE home_team_1 = ANY(%s) OR away_team_1 = ANY(%s)
                     OR home_team_2 = ANY(%s) OR away_team_2 = ANY(%s)
                )
                ORDER BY created_at DESC
                LIMIT %s
            """, (
                teams_arr, teams_arr,
                teams_arr, teams_arr,
                teams_arr, teams_arr, teams_arr, teams_arr,
                limit,
            ))
            rows = cur.fetchall()
        finally:
            cur.close()
            conn.close()

        result = []
        for r in rows:
            result.append({
                "pipeline":   r["pipeline"],
                "data":       str(r["match_date"]),
                "jogo":       f"{r['home']} vs {r['away']}",
                "mercado":    r["market"] + (f" {r['line']}" if r["line"] else ""),
                "odd":        r["odd"],
                "confidence": float(r["confidence"]) if r["confidence"] else None,
                "resultado":  r["result"] or "pendente",
                "reasoning":  r["reasoning"] or "",
            })
        return result

    def get_team_picks_str(self, teams: list[str], limit: int = 15) -> str:
        """Retorna JSON compacto dos últimos picks por time, pronto para o prompt."""
        picks = self.get_team_picks(teams, limit)
        if not picks:
            return '{"status": "sem picks anteriores para estes times"}'
        return json.dumps(picks, ensure_ascii=False, separators=(",", ":"))
