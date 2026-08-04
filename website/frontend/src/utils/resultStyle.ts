export type PickResult = 'GREEN' | 'RED' | 'PUSH' | 'HALF-WIN' | 'HALF-LOSS'

/* Sem campo `emoji`: o resultado é comunicado pela cor e pelo rótulo. O glifo
   que existia aqui duplicava o próprio rótulo em ½ WIN ("½ WIN ½") e ia contra
   a regra de não usar emoji na interface. */
export interface ResultStyle {
  bg: string
  border: string
  text: string
  label: string
  /** Cor sólida (hex) usada em contextos fora do Tailwind, ex: desenho em <canvas>. */
  hex: string
}

export const RESULT_STYLE: Record<PickResult, ResultStyle> = {
  GREEN:      { bg: 'bg-green-500/15',  border: 'border-green-500/40',  text: 'text-green-400',  label: 'GREEN', hex: '#4ade80' },
  RED:        { bg: 'bg-red-500/15',    border: 'border-red-500/40',    text: 'text-red-400',    label: 'RED', hex: '#f87171' },
  PUSH:       { bg: 'bg-surface-3/40',   border: 'border-line-strong',      text: 'text-ink-2',   label: 'PUSH', hex: '#d4d4d8' },
  'HALF-WIN': { bg: 'bg-teal-500/15',   border: 'border-teal-500/40',   text: 'text-teal-400',   label: '½ WIN', hex: '#2dd4bf' },
  'HALF-LOSS':{ bg: 'bg-orange-500/15', border: 'border-orange-500/40', text: 'text-orange-400', label: '½ LOSS', hex: '#fb923c' },
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
  faltas: 'Faltas',
  goleiros: 'Defesas',
}

export const PICK_TYPE_HEX: Record<string, string> = {
  vip: '#facc15',
  free: '#4ade80',
  multipla: '#60a5fa',
  multiplas: '#60a5fa',
  alavancagem: '#fb923c',
  faltas: '#c084fc',
  goleiros: '#38bdf8',
}

/**
 * Borda do card de pick por tipo, na mesma convenção de cor do badge acima.
 * Existe pra que os 6 tipos de card (VIP, free, múltipla, alavancagem, faltas,
 * defesas) usem a casca `.pick-card` e se diferenciem só pela cor da borda,
 * em vez de cada um trazer a sua própria casca.
 */
export const PICK_TYPE_BORDER: Record<string, string> = {
  vip:         'border-green-500/20 hover:border-green-500/40',
  free:        'border-green-500/20 hover:border-green-500/40',
  multipla:    'border-blue-400/20 hover:border-blue-400/40',
  multiplas:   'border-blue-400/20 hover:border-blue-400/40',
  alavancagem: 'border-orange-400/20 hover:border-orange-400/40',
  faltas:      'border-purple-400/20 hover:border-purple-400/40',
  goleiros:    'border-sky-400/20 hover:border-sky-400/40',
}

/** Classes Tailwind pro badge de tipo de pick (VIP/Free/Múltipla/Alavancagem). */
export const PICK_TYPE_CLS: Record<string, string> = {
  vip:         'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  free:        'text-green-400 bg-green-500/10 border-green-500/20',
  multipla:    'text-blue-400 bg-blue-400/10 border-blue-400/20',
  multiplas:   'text-blue-400 bg-blue-400/10 border-blue-400/20',
  alavancagem: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
  // Mesmas cores da aba Mercados na pagina de picks (roxo/azul-claro), pra
  // um pick de faltas ser reconhecido pela cor em qualquer tela.
  faltas:      'text-purple-400 bg-purple-400/10 border-purple-400/20',
  goleiros:    'text-sky-400 bg-sky-400/10 border-sky-400/20',
}
