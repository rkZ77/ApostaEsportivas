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

/** Explicação curta do que cada resultado significa, pra quem não conhece os termos. */
export const RESULT_EXPLAIN: Record<PickResult, string> = {
  GREEN:      'A aposta bateu: o que foi previsto aconteceu. Você ganha o valor apostado multiplicado pela odd.',
  RED:        'A aposta não bateu: o que foi previsto não aconteceu. Você perde o valor apostado.',
  PUSH:       'Empate técnico: a linha bateu exatamente no número apostado. O valor apostado é devolvido, sem ganho nem perda.',
  'HALF-WIN': 'Meio ganho: a linha era fracionada (ex: 2.75 gols), a aposta foi dividida em duas partes e uma delas ganhou. Você recebe metade do lucro da odd.',
  'HALF-LOSS':'Meia perda: a linha era fracionada (ex: 2.75 gols), a aposta foi dividida em duas partes e uma delas perdeu. Você perde metade do valor apostado.',
}

export function explainResult(result?: string | null): string {
  if (!result) return ''
  return RESULT_EXPLAIN[result as PickResult] ?? ''
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

/** Classes Tailwind pro badge de tipo de pick (VIP/Free/Múltipla/Alavancagem). */
export const PICK_TYPE_CLS: Record<string, string> = {
  vip:         'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  free:        'text-green-400 bg-green-500/10 border-green-500/20',
  multipla:    'text-blue-400 bg-blue-400/10 border-blue-400/20',
  multiplas:   'text-blue-400 bg-blue-400/10 border-blue-400/20',
  alavancagem: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
}
