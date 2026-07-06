export type PickResult = 'GREEN' | 'RED' | 'PUSH' | 'HALF-WIN' | 'HALF-LOSS'

export interface ResultStyle {
  bg: string
  border: string
  text: string
  label: string
  emoji: string
  /** Cor sólida (hex) usada em contextos fora do Tailwind, ex: desenho em <canvas>. */
  hex: string
}

export const RESULT_STYLE: Record<PickResult, ResultStyle> = {
  GREEN:      { bg: 'bg-green-500/15',  border: 'border-green-500/40',  text: 'text-green-400',  label: 'GREEN',  emoji: '✓', hex: '#4ade80' },
  RED:        { bg: 'bg-red-500/15',    border: 'border-red-500/40',    text: 'text-red-400',    label: 'RED',    emoji: '✗', hex: '#f87171' },
  PUSH:       { bg: 'bg-zinc-700/40',   border: 'border-zinc-600',      text: 'text-zinc-300',   label: 'PUSH',   emoji: '↔', hex: '#d4d4d8' },
  'HALF-WIN': { bg: 'bg-teal-500/15',   border: 'border-teal-500/40',   text: 'text-teal-400',   label: '½ WIN',  emoji: '½', hex: '#2dd4bf' },
  'HALF-LOSS':{ bg: 'bg-orange-500/15', border: 'border-orange-500/40', text: 'text-orange-400', label: '½ LOSS', emoji: '½', hex: '#fb923c' },
}

export function getResultStyle(result?: string | null): ResultStyle | null {
  if (!result) return null
  return RESULT_STYLE[result as PickResult] ?? null
}

export const PICK_TYPE_LABEL: Record<string, string> = {
  vip: 'VIP',
  free: 'Free',
  multipla: 'Múltipla',
  multiplas: 'Múltipla',
  alavancagem: 'Alavancagem',
}

export const PICK_TYPE_HEX: Record<string, string> = {
  vip: '#facc15',
  free: '#4ade80',
  multipla: '#60a5fa',
  multiplas: '#60a5fa',
  alavancagem: '#fb923c',
}
