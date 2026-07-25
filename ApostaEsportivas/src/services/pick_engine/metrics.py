"""Metricas de calibracao probabilistica (Fase 1.3/1.4 do plano de
implementacao, 2026-07-25): Brier Score, Log-Loss e curva de
confiabilidade (reliability diagram) sobre o historico real de picks
resolvidos. Primeira infraestrutura de medicao formal de calibracao do
motor -- ate aqui so existia o gap simples (confidence media - hit rate)
em calibration.py, que e 1 numero por (mercado, liga), sem granularidade
de faixa de probabilidade. Serve tambem de gate objetivo pra aceitar ou
rejeitar qualquer mudanca futura em config.py/pesos (ver Fase 1.7)."""
import math

_EPS = 1e-9  # evita log(0) no log-loss


def _binary_outcome(result: str | None) -> int | None:
    """GREEN=1, RED=0. Qualquer outro (PUSH, HALF-WIN, HALF-LOSS, None)
    fica de fora -- Brier/log-loss so fazem sentido pra desfecho binario;
    PUSH nao e nem acerto nem erro da probabilidade declarada."""
    if result == "GREEN":
        return 1
    if result == "RED":
        return 0
    return None


def brier_score(picks: list[dict]) -> dict | None:
    """Media de (confidence - outcome)^2 -- 0=perfeito, 0.25=chute
    aleatorio numa moeda justa, 1=sempre errado com certeza total.
    None se nao houver nenhum par (confidence, resultado binario) valido."""
    pairs = []
    for p in picks:
        outcome = _binary_outcome(p.get("result"))
        conf = p.get("confidence")
        if outcome is None or conf is None:
            continue
        pairs.append((float(conf), outcome))
    if not pairs:
        return None
    score = sum((c - o) ** 2 for c, o in pairs) / len(pairs)
    return {"score": round(score, 4), "n": len(pairs)}


def log_loss(picks: list[dict]) -> dict | None:
    """Penaliza mais pesado erros extremos (confidence 90% que da RED
    custa muito mais que 55% que da RED) -- bom complemento ao Brier,
    mais sensivel a excesso de confianca especificamente."""
    pairs = []
    for p in picks:
        outcome = _binary_outcome(p.get("result"))
        conf = p.get("confidence")
        if outcome is None or conf is None:
            continue
        c = min(max(float(conf), _EPS), 1 - _EPS)
        pairs.append((c, outcome))
    if not pairs:
        return None
    total = sum(-(o * math.log(c) + (1 - o) * math.log(1 - c)) for c, o in pairs)
    return {"score": round(total / len(pairs), 4), "n": len(pairs)}


def reliability_curve(picks: list[dict], n_buckets: int = 8) -> list[dict]:
    """Agrupa picks em buckets de confidence declarada (0-1 dividido em
    n_buckets fatias iguais) e compara a media do bucket contra o hit
    rate real dentro dele -- reliability diagram classico. Bucket vazio
    fica de fora da lista (nao inventa ponto sem dado)."""
    edges = [i / n_buckets for i in range(n_buckets + 1)]
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_buckets)]
    for p in picks:
        outcome = _binary_outcome(p.get("result"))
        conf = p.get("confidence")
        if outcome is None or conf is None:
            continue
        c = float(conf)
        idx = min(int(c * n_buckets), n_buckets - 1)
        buckets[idx].append((c, outcome))

    curve = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        confs = [c for c, _ in bucket]
        outcomes = [o for _, o in bucket]
        curve.append({
            "bucket_range": (round(edges[i], 2), round(edges[i + 1], 2)),
            "mean_confidence": round(sum(confs) / len(confs), 4),
            "hit_rate_real": round(sum(outcomes) / len(outcomes), 4),
            "n": len(bucket),
        })
    return curve


def expected_calibration_error(curve: list[dict]) -> float | None:
    """ECE: media do |confidence - hit_rate_real| de cada bucket, ponderada
    pelo tamanho do bucket -- resume o reliability diagram inteiro num
    numero so (0=perfeitamente calibrado). None se a curva vier vazia."""
    if not curve:
        return None
    n = sum(b["n"] for b in curve)
    if n == 0:
        return None
    weighted = sum(b["n"] * abs(b["mean_confidence"] - b["hit_rate_real"]) for b in curve)
    return round(weighted / n, 4)
