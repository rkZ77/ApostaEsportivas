/**
 * Calcula lucro/prejuízo em unidades para um pick resolvido.
 * Usa a odd real do usuário (user_actual_odd) se disponível, senão a odd do pick.
 * Usa stake_units reais do usuário (userUnits) se disponível, senão Kelly/sugestão.
 */
export function calcProfitUnits(
  result: string,
  pickOdd: number,
  units: number,
  userActualOdd?: number | null,
): number {
  const odd = userActualOdd ?? pickOdd
  switch (result) {
    case 'GREEN':     return (odd - 1) * units
    case 'RED':       return -units
    case 'PUSH':      return 0
    case 'HALF-WIN':  return ((odd - 1) * units) / 2
    case 'HALF-LOSS': return -units / 2
    default:          return 0
  }
}

export interface StakeSuggestion {
  units: number
  amountR: number
  kellyPct: number
}

/**
 * Calcula stake sugerido usando Kelly fracionado.
 * Kelly = (b*p - q) / b  onde b = odd-1, p = prob_real (Poisson), q = 1-p
 * Passar prob_real quando disponível; fallback para confidence quando não há Poisson.
 * kellyFraction: 0.5 para picks simples (½ Kelly), 0.25 para múltiplas (¼ Kelly).
 * Resultado arredondado para o 1u mais próximo, entre 1u e maxUnits.
 */
/**
 * Calcula stake para picks VIP/Free espelhando o cap do backend:
 *   conf ≥ 80% e EV > 10% → até 5% da banca (5u por R$10 unit em R$1k banca)
 *   conf ≥ 72% e EV > 5%  → até 4% da banca
 *   demais positivos       → até 3% da banca
 * Usa stake_pct do backend quando disponível (mais preciso).
 */
export function calcVipStake(
  prob: number,
  odd: number,
  ev: number,
  bankroll: number,
  unitValue: number,
  stakePctFromBackend?: number | null,
): { units: number; amountR: number; kellyPct: number } | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null

  let stakePct: number

  if (stakePctFromBackend != null && stakePctFromBackend > 0) {
    stakePct = stakePctFromBackend
  } else {
    const b = odd - 1
    const q = 1 - prob
    if (b <= 0 || prob <= 0 || prob >= 1) return null
    const kelly = (b * prob - q) / b
    if (kelly <= 0) return null
    const cap = prob >= 0.80 && ev > 0.10 ? 0.05
              : prob >= 0.72 && ev > 0.05 ? 0.04
              : 0.03
    stakePct = Math.max(0.01, Math.min(cap, kelly * 0.5))
  }

  const units = Math.max(1, Math.min(5, Math.round((stakePct * bankroll) / unitValue)))
  return { units, amountR: units * unitValue, kellyPct: Math.round(stakePct * 1000) / 10 }
}

export function suggestStake(
  probReal: number,
  odd: number,
  bankroll: number,
  unitValue: number,
  maxUnits: number = 10,
  kellyFraction: number = 0.5,
): StakeSuggestion | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null

  const b = odd - 1
  const p = probReal
  const q = 1 - p

  if (b <= 0 || p <= 0 || p >= 1) return null

  const kelly = (b * p - q) / b
  if (kelly <= 0) return null

  const fracKelly = kelly * kellyFraction
  const stakeR    = bankroll * fracKelly

  let units = stakeR / unitValue
  units = Math.max(1, Math.min(maxUnits, units))
  units = Math.round(units)

  return {
    units,
    amountR:  Math.round(units * unitValue * 100) / 100,
    kellyPct: Math.round(fracKelly * 100 * 10) / 10,
  }
}
