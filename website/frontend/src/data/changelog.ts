export interface ChangelogEntry {
  /** Identifica a versão pro usuário já ter visto · não precisa bater com o
   * timestamp de deploy do servidor, só precisa ser único e crescente. */
  id: string
  date: string
  items: string[]
}

// Adicionar só quando tiver melhoria real pro usuário (não é todo deploy que
// entra aqui) · mais recente por último, o card mostra sempre o último item.
export const CHANGELOG: ChangelogEntry[] = [
  {
    id: '2026-07-20',
    date: '20 de julho',
    items: [
      'Nova página pra sacar da banca, com histórico completo de saques',
      'Configuração da banca agora trava 1x por mês, pra manter o histórico de risco confiável',
      'Sugestão de unidades por pick corrigida: usa a banca certa depois do fechamento mensal',
    ],
  },
  {
    id: '2026-07-22',
    date: '22 de julho',
    items: [
      'Corrigido: picks com Handicap Asiático (gols, escanteios ou cartões) que ficavam travados em "Pendente" mesmo com o jogo já encerrado',
      'Resultados da IA: nova aba "Por Liga" e paginação nos picks recentes',
      'Motor de picks mais rigoroso: cartões agora considera o histórico do árbitro e o clima do jogo, escanteios passa a usar posse de bola e chutes reais',
    ],
  },
]
