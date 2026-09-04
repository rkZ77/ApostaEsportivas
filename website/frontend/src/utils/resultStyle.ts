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

/**
 * Degradê de fundo do card conforme o resultado (ver `.pick-card--*` em
 * index.css). Vale pra TODOS os cards de pick · o selo do canto some da tela
 * ao rolar no celular, o fundo não.
 *
 * PUSH fica de fora: anulado não é acerto nem erro, e pintar o card de
 * qualquer cor tomaria partido. A caixa "Pick anulado" já explica ali dentro.
 */
export function pickCardResultBg(result?: string | null): string {
  switch (result) {
    case 'GREEN':      return 'pick-card--green'
    case 'RED':        return 'pick-card--red'
    case 'HALF-WIN':   return 'pick-card--half-win'
    case 'HALF-LOSS':  return 'pick-card--half-loss'
    default:           return ''
  }
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
  /* Player Stats · o rótulo é "Jogador" e não o método ("Chutes no alvo").
     Este mapa nomeia o PRODUTO, que é o que o selo do card mostra ao lado do
     VIP e do Free; o método aparece no próprio card, no lugar do mercado. */
  player_stats: 'Jogador',
  boost: 'Boost',
  live: 'Ao Vivo',
}

export const PICK_TYPE_HEX: Record<string, string> = {
  vip: '#facc15',
  free: '#4ade80',
  multipla: '#60a5fa',
  multiplas: '#60a5fa',
  alavancagem: '#fb923c',
  faltas: '#c084fc',
  goleiros: '#38bdf8',
  /* Âmbar, e não o azul-claro de goleiros: Player Stats ABSORVEU defesas como
     um método, mas cobre chutes, faltas, desarmes e passes também · repetir a
     cor faria o produto novo parecer o antigo com outro nome. */
  player_stats: '#fbbf24',
  /* Ciano · o Boost é combinado e precisa se distinguir do âmbar do
     Player Stats e do verde do VIP numa lista misturada. */
  boost: '#22d3ee',
  /* VERDE DA MARCA (#00CC00), e não o vermelho de "ao vivo" (29/08, decisão
     do usuário). O vermelho vinha do badge pulsante da barra de abas, mas
     dentro do card ele disputava leitura com o vermelho de RED: numa lista
     misturada, um card inteiro contornado de vermelho parece pick perdido
     antes de qualquer um ler o selo de resultado.

     É o verde da marca, e não o #4ade80 do Free: os dois convivem na mesma
     tela e precisam continuar distinguíveis. */
  live: '#00CC00',
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
  player_stats:'border-amber-400/20 hover:border-amber-400/40',
  boost:       'border-cyan-400/20 hover:border-cyan-400/40',
  live:        'border-accent/25 hover:border-accent/50',
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
  player_stats:'text-amber-400 bg-amber-400/10 border-amber-400/20',
  boost:       'text-cyan-400 bg-cyan-400/10 border-cyan-400/20',
  live:        'text-accent-ink bg-accent/10 border-accent/25',
}
