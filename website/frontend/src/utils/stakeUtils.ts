/**
 * Calcula lucro/prejuízo em unidades para um pick resolvido.
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
 * Caps máximos de stake por tipo de pick (% da banca).
 * Lógica espelhada no backend (_compute_suggested_stake_units).
 *   VIP      → 5%  banca  | Kelly ½
 *   Free     → 2%  banca  | Kelly ½
 *   Múltipla → 2.5% banca | Kelly ¼
 */
export const STAKE_CAPS = {
  vip:      { maxPct: 0.05, kellyFrac: 0.50 },
  free:     { maxPct: 0.02, kellyFrac: 0.50 },
  multipla: { maxPct: 0.025, kellyFrac: 0.25 },
} as const

/**
 * Calcula stake para picks VIP usando stake_pct do backend.
 * Preferir sempre usar suggested_stake_units vindo da API.
 *
 * Caps por nível de confiança (backend):
 *   conf ≥ 80% e EV > 10% → max 5%
 *   conf ≥ 72% e EV > 5%  → max 4%
 *   demais positivos       → max 3%
 *   EV ≤ 0                 → 1u (stat-strong)
 */
export function calcVipStake(
  prob: number,
  odd: number,
  ev: number,
  bankroll: number,
  unitValue: number,
  stakePctFromBackend?: number | null,
): StakeSuggestion | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null

  // EV negativo: stake mínimo (espelha lógica do backend)
  if (ev <= 0 && (stakePctFromBackend == null || stakePctFromBackend <= 0)) {
    return { units: 1, amountR: unitValue, kellyPct: Math.round(unitValue / bankroll * 1000) / 10 }
  }

  let stakePct: number

  if (stakePctFromBackend != null && stakePctFromBackend > 0) {
    stakePct = Math.min(stakePctFromBackend, STAKE_CAPS.vip.maxPct)
  } else {
    const b = odd - 1
    const q = 1 - prob
    if (b <= 0 || prob <= 0 || prob >= 1) return null
    const kelly = (b * prob - q) / b
    if (kelly <= 0) return null
    const cap = prob >= 0.80 && ev > 0.10 ? 0.05
              : prob >= 0.72 && ev > 0.05 ? 0.04
              : 0.03
    stakePct = Math.max(0.01, Math.min(cap, kelly * STAKE_CAPS.vip.kellyFrac))
  }

  const stakeAmount = stakePct * bankroll
  const units = Math.max(1, Math.round(stakeAmount / unitValue))
  return { units, amountR: units * unitValue, kellyPct: Math.round(stakePct * 1000) / 10 }
}

/**
 * Calcula stake para picks Free (dica do dia): Kelly ½, max 2% da banca.
 */
export function calcFreeStake(
  prob: number,
  odd: number,
  ev: number,
  bankroll: number,
  unitValue: number,
): StakeSuggestion | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null
  if (ev <= 0) {
    return { units: 1, amountR: unitValue, kellyPct: Math.round(unitValue / bankroll * 1000) / 10 }
  }
  const b = odd - 1
  const q = 1 - prob
  if (b <= 0 || prob <= 0 || prob >= 1) return null
  const kelly = (b * prob - q) / b
  if (kelly <= 0) return null
  const stakePct = Math.max(0.005, Math.min(STAKE_CAPS.free.maxPct, kelly * STAKE_CAPS.free.kellyFrac))
  const units = Math.max(1, Math.round(stakePct * bankroll / unitValue))
  return { units, amountR: units * unitValue, kellyPct: Math.round(stakePct * 1000) / 10 }
}

/**
 * Calcula stake para picks Múltipla: Kelly ¼, max 2.5% da banca.
 */
export function calcMultiplaStake(
  prob: number,
  odd: number,
  bankroll: number,
  unitValue: number,
): StakeSuggestion | null {
  if (!bankroll || !unitValue || unitValue <= 0) return null
  const b = odd - 1
  const q = 1 - prob
  if (b <= 0 || prob <= 0 || prob >= 1) return null
  const kelly = (b * prob - q) / b
  if (kelly <= 0) return null
  const stakePct = Math.max(0.005, Math.min(STAKE_CAPS.multipla.maxPct, kelly * STAKE_CAPS.multipla.kellyFrac))
  const units = Math.max(1, Math.round(stakePct * bankroll / unitValue))
  return { units, amountR: units * unitValue, kellyPct: Math.round(stakePct * 1000) / 10 }
}

/**
 * Calculadora Kelly genérica (usada para exibição/comparação manual).
 * Para picks do site, prefira as funções específicas por tipo.
 */
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
