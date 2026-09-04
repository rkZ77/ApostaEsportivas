"""Fase 1.3/1.4 do plano de implementacao (2026-07-25): Brier Score,
Log-Loss e reliability diagram sobre o historico real de picks resolvidos.

Roda so-leitura contra DB_ENV (dev ou prod, conforme variavel de ambiente
ja setada) -- nunca escreve nada. Reaproveita
services.ai_performance_service.AIPerformanceService.get_calibration_rows()
(mesma fonte que services/pick_engine/calibration.py ja usa), por mercado
e no agregado geral, comparando o periodo anterior aos fixes de cartao
vermelho/push (antes de 2026-07-25) contra o periodo posterior -- validacao
esperada: metricas devem melhorar (cair) no periodo pos-fix.

Uso:
    python -m scripts.compute_calibration_metrics [dias]
"""
import sys
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])

from services.ai_performance_service import AIPerformanceService
from services.pick_engine import metrics

_FIX_CUTOFF = datetime(2026, 7, 25, tzinfo=timezone.utc)


def _report(label: str, rows: list[dict]) -> None:
    brier = metrics.brier_score(rows)
    ll = metrics.log_loss(rows)
    curve = metrics.reliability_curve(rows)
    ece = metrics.expected_calibration_error(curve)

    print(f"\n=== {label} ===")
    if brier is None:
        print("  sem amostra binaria (GREEN/RED) suficiente")
        return
    print(f"  n={brier['n']}  Brier={brier['score']}  LogLoss={ll['score']}  ECE={ece}")
    for b in curve:
        lo, hi = b["bucket_range"]
        print(
            f"    [{lo:.2f}-{hi:.2f}) conf_media={b['mean_confidence']:.3f} "
            f"hit_real={b['hit_rate_real']:.3f} n={b['n']}"
        )


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    rows = AIPerformanceService().get_calibration_rows(days=days)
    print(f"{len(rows)} picks resolvidos nos ultimos {days} dias")

    def _after_cutoff(r):
        ca = r.get("created_at")
        if ca is None:
            return True
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        return ca >= _FIX_CUTOFF

    pre_fix = [r for r in rows if not _after_cutoff(r)]
    pos_fix = [r for r in rows if _after_cutoff(r)]

    _report("GERAL (todo o periodo)", rows)
    _report(f"PRE-FIX (antes de {_FIX_CUTOFF.date()})", pre_fix)
    _report(f"POS-FIX (a partir de {_FIX_CUTOFF.date()})", pos_fix)

    by_market = defaultdict(list)
    for r in rows:
        by_market[r.get("market_type") or "unknown"].append(r)
    for mt, mrows in sorted(by_market.items(), key=lambda kv: -len(kv[1])):
        _report(f"MERCADO: {mt}", mrows)


if __name__ == "__main__":
    main()
