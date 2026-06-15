export interface StakeSuggestion {
  units: number
  amountR: number
  kellyPct: number
}

/**
 * Calcula stake sugerido usando ½ Kelly Criterion.
 * Kelly = (b*p - q) / b  onde b = odd-1, p = confiança, q = 1-p
 * Usa metade do Kelly para reduzir risco de ruína.
 * Resultado arredondado para o 1u mais próximo, entre 1u e maxUnits.
 * Para múltiplas: maxUnits = 7. Para picks simples: maxUnits = 10.
 */
export function suggestStake(
  confidence: number,
  odd: number,
  bankroll: number,
  unitValue: number,
  maxUnits: number = 10,
): StakeSuggestion | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null

  const b = odd - 1
  const p = confidence
  const q = 1 - p

  if (b <= 0 || p <= 0 || p >= 1) return null

  const kelly = (b * p - q) / b
  if (kelly <= 0) return null

  const halfKelly = kelly / 2
  const stakeR    = bankroll * halfKelly

  let units = stakeR / unitValue
  units = Math.max(1, Math.min(maxUnits, units))
  units = Math.round(units)

  return {
    units,
    amountR:  Math.round(units * unitValue * 100) / 100,
    kellyPct: Math.round(halfKelly * 100 * 10) / 10,
  }
}
