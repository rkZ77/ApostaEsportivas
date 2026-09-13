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

/* A CASCA DO CARD QUE DEU GREEN (2026-09-12, pedido do usuario).
 *
 * Pick liquidado em GREEN sai com a borda verde e um fio de fundo, no lugar da
 * borda da cor do PRODUTO. Antes ele era identico ao pendente e a unica
 * diferenca era um selo de 10px no canto -- numa grade de quatro colunas
 * ninguem le' selo, le' bloco de cor, e o acerto e' o melhor argumento que o
 * produto tem.
 *
 * Enquanto o pick esta' aberto a borda continua sendo a do produto, que e' o
 * que separa VIP de Boost numa lista misturada; depois de liquidado esse
 * trabalho ja' foi feito.
 *
 * So' o GREEN. Dar o mesmo tratamento ao RED transformaria a tela num painel
 * onde a derrota grita igual, e o pedido era destacar o acerto.
 */
/* BORDA, E NENHUM FUNDO (2026-09-12, ajuste do usuario). A casca chegou a ter
   um `bg-green-500/[0.03]` junto, e o tinte competia com o fundo esverdeado
   das PERNAS do bilhete: no card de alavancagem e de boost as duas camadas de
   verde empilhavam e a perna deixava de se destacar dentro do card. O padrao
   passa a ser o daqueles dois cards, que ja' estavam certos: fundo normal,
   verde so' no contorno. */
export const CASCA_GREEN =
  'border-green-500/50 shadow-[0_0_0_1px_rgb(34_197_94/0.18)]'

/* A CAIXA DO JOGO DENTRO DO CARD (2026-09-12, pedido do usuario).
 *
 * A perna da multipla ja' nascia numa caixa que muda de cor com o resultado
 * dela, e o pick SIMPLES nao tinha caixa nenhuma: os dois produtos apareciam
 * um embaixo do outro na aba Hoje, o bilhete com as selecoes verdes e o VIP
 * com o jogo solto no fundo do card. Mesma ideia, dois desenhos.
 *
 * Aqui o pick simples passa a usar a caixa da perna, com os mesmos tres
 * estados. O RED existe para a caixa (ao contrario da CASCA, que so' destaca o
 * GREEN): dentro do card ela e' leitura de conferencia, nao vitrine, e deixar
 * o RED cinza faria parecer pendente.
 */
export function caixaDoPick(result?: string | null): string {
  if (result === 'GREEN' || result === 'HALF-WIN') return 'border-green-500/20 bg-green-500/5'
  if (result === 'RED' || result === 'HALF-LOSS')  return 'border-red-500/20 bg-red-500/5'
  return 'border-line bg-surface-1/60'
}

/** Borda do card: a do GREEN quando ele deu green, a do produto no resto. */
export function cascaDoPick(result: string | null | undefined, bordaDoProduto: string): string {
  return result === 'GREEN' ? CASCA_GREEN : bordaDoProduto
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
  bingo: 'Bingo',
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
  /* Rosa · o Bingo é a outra cartela e vive ao lado da múltipla numa lista
     misturada, então precisa se distinguir DELA antes de qualquer outra coisa.
     Repetir o azul faria os dois bilhetes parecerem o mesmo produto. */
  bingo: '#fb7185',
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
  bingo:       'border-rose-400/20 hover:border-rose-400/40',
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
  bingo:       'text-rose-400 bg-rose-400/10 border-rose-400/20',
  alavancagem: 'text-orange-400 bg-orange-400/10 border-orange-400/20',
  // Mesmas cores da aba Mercados na pagina de picks (roxo/azul-claro), pra
  // um pick de faltas ser reconhecido pela cor em qualquer tela.
  faltas:      'text-purple-400 bg-purple-400/10 border-purple-400/20',
  goleiros:    'text-sky-400 bg-sky-400/10 border-sky-400/20',
  player_stats:'text-amber-400 bg-amber-400/10 border-amber-400/20',
  boost:       'text-cyan-400 bg-cyan-400/10 border-cyan-400/20',
  live:        'text-accent-ink bg-accent/10 border-accent/25',
}
