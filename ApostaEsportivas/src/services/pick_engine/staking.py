"""Calculo de stake · Kelly fracionado.

Vivia como @staticmethod dentro de ai/ai_suggestions_service.py, e era a
unica coisa que prendia os pipelines de producao (engine_pipelines/vip,
dica e multipla) no modulo de IA legado: eles importavam um arquivo de 1000
linhas, que instancia client Anthropic no __init__, so pra usar esta funcao
pura. Extraido pra ca em 2026-07-29 pra permitir aposentar ai/.

Matematica identica a de antes, sem nenhuma mudanca de comportamento.

Espelha website/backend/routers/suggestions.py::_compute_suggested_stake_units
e o frontend (stakeUtils.ts). Sao tres copias da mesma formula em runtimes
diferentes -- mexeu numa, tem que mexer nas tres.

Retorna (stake_pct, stake_units_ref). stake_units_ref assume a convencao
1u = 1% de banca que o site usa como base antes de converter pro valor de
unidade real do usuario.

pick_type:
  'vip'      -> tiers por confidence+EV: >=80%+EV>10% ate 5%/10u,
                >=72%+EV>5% ate 4%/7u, demais ate 3%/5u. Kelly 1/2.
  'free'     -> teto fixo 2%/6u. Kelly 1/2.
  'multipla' -> teto fixo 2.5%/3u. Kelly 1/4. Unico tipo que NAO usa EV
                (o pipeline passa confidence=score_combo, que ja resume a
                forca do combo).
"""


def calculate_stake(confidence: float, odd: float, ev: float = 0.0,
                    stat_strong: bool = False, pick_type: str = "vip") -> tuple[float, int]:
    if stat_strong or (ev <= 0 and pick_type != "multipla"):
        return 0.01, 1

    b = float(odd) - 1.0
    p = float(confidence)
    q = 1.0 - p

    if b <= 0 or p <= 0 or p >= 1:
        return 0.01, 1

    kelly = (b * p - q) / b
    if kelly <= 0:
        return 0.01, 1

    if pick_type == "vip":
        if confidence >= 0.80 and ev > 0.10:
            cap, max_units = 0.05, 10
        elif confidence >= 0.72 and ev > 0.05:
            cap, max_units = 0.04, 7
        else:
            cap, max_units = 0.03, 5
        stake_pct = round(max(0.01, min(cap, kelly * 0.50)), 4)
    else:
        cap, kelly_frac, max_units = {
            "free":     (0.02, 0.50, 6),
            "multipla": (0.025, 0.25, 3),
        }.get(pick_type, (0.03, 0.50, 5))
        stake_pct = round(max(0.005, min(cap, kelly * kelly_frac)), 4)

    ref_units = max(1, min(max_units, round(stake_pct / 0.01)))

    return stake_pct, ref_units
