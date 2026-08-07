/*
 * Escala de largura de página, num arquivo só.
 *
 * Mora aqui, e não dentro do PageShell, porque a Navbar também precisa dela:
 * o PageShell importa a Navbar, então a Navbar importar de volta do PageShell
 * fecharia um ciclo. Um módulo sem componente dentro quebra o ciclo e deixa
 * claro que isto é vocabulário, não casca.
 *
 * A escala não é uma régua contínua de tamanhos: é uma decisão sobre o QUE
 * está dentro da página.
 *
 * Texto que se lê tem largura ideal, e ela é curta. A faixa confortável fica
 * entre 45 e 75 caracteres por linha (Bringhurst, Tschichold, e depois
 * rastreamento ocular). O problema de linha longa não é ler a linha, é achar
 * o começo da próxima · o olho perde a volta e relê a mesma. Para quem tem
 * dislexia ou baixa visão isso deixa de ser desconforto e vira barreira.
 *
 * Grade, tabela e gráfico não têm "próxima linha" para achar. O que eles
 * querem é caber mais coluna, e prender isso numa faixa central desperdiça
 * metade do monitor · foi exatamente a queixa que o GitHub levou anos
 * ouvindo de quem revisava código em tela 4K.
 *
 * Por isso a escala vai de 42rem a "sem teto", e as duas pontas respondem a
 * perguntas diferentes.
 */

export const PAGE_WIDTH = {
  /**
   * Sem teto, como aplicativo: Picks, Banca, Meus Picks, Estatísticas, Jogos,
   * Resultados, Admin. O padding cresce com a tela para o conteúdo não
   * encostar na borda do monitor, que é o que separa "ocupa a tela" de
   * "vazou".
   */
  full: 'max-w-none px-4 sm:px-6 lg:px-8',
  /** Grade de poucos cards (planos) e painel de conta. */
  wide: 'max-w-6xl px-4',
  default: 'max-w-5xl px-4',
  /** Teto de leitura. Não subir daqui sem mexer no tamanho da fonte junto. */
  prose: 'max-w-3xl px-4',
  /** Formulário e conversa, onde foco vale mais que espaço. */
  narrow: 'max-w-2xl px-4',
} as const

export type PageWidth = keyof typeof PAGE_WIDTH
