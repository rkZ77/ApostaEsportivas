export function fmtBRL(value: number): string {
  return 'R$ ' + Math.abs(value).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function fmtSigned(value: number): string {
  return (value >= 0 ? '+' : '−') + fmtBRL(value)
}

export function winRate(greens: number, total: number): number | null {
  if (!total) return null
  return Math.round((greens / total) * 100)
}

/**
 * Legenda do plano de stake, usada enquanto `/public/results` não respondeu.
 * A resposta traz `stake_label` montado em backend/stake_plan.py, que é a
 * fonte da verdade · isto aqui é só o texto de partida.
 */
export const STAKE_LABEL_PADRAO = 'VIP 4u · free e mercados 3u · múltipla 1u'

/**
 * Lucro em unidades, sempre com sinal. `+42,7u` · `−1,00u`.
 *
 * Todo número público de unidade sai daqui. A base de cálculo é a coluna
 * `profit` das seis tabelas de picks, que guarda o lucro de UMA unidade
 * (settlement.py: GREEN -> odd-1, HALF-WIN -> (odd-1)/2, PUSH -> 0, HALF-LOSS
 * -> -0.5, RED -> -1); o peso do plano de stake (backend/stake_plan.py) já vem
 * multiplicado do backend, então aqui é só formatar.
 *
 * Isso NÃO é a stake sugerida da Banca, que varia por confiança
 * (stakeUtils.ts). Quem mostra este número tem que exibir STAKE_LABEL_PADRAO
 * junto, senão o usuário compara com a banca dele, os números não batem e o
 * site parece estar mentindo.
 *
 * Total com 1 casa; média por pick com 2, porque média é número pequeno e 1
 * casa achata tudo em `+0,2u`. Sufixo `u` minúsculo colado, igual à Banca.
 */
export function fmtUnits(value: number, decimals = 1): string {
  const abs = Math.abs(value).toLocaleString('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return `${value < 0 ? '−' : '+'}${abs}u`
}

// Final da Copa 2026: 19/07. Depois disso, mensagens da Copa (home + banners
// dentro do app) trocam pra algo evergreen (Brasileirão/Premier League seguem).

export function maskPhone(value: string): string {
  const d = value.replace(/\D/g, '').slice(0, 11)
  if (d.length <= 2)  return d.length ? `(${d}` : ''
  if (d.length <= 6)  return `(${d.slice(0,2)}) ${d.slice(2)}`
  if (d.length <= 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`
  return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`
}


/** Probabilidade 0-1 do banco em 0-100 pro card de compartilhar.
 *
 * `probability` e `confidence` sao campos DIFERENTES e confidence vive acima
 * (0,816 contra 0,755 no mesmo pick, medido em picks_vip), entao quem chama
 * passa probability primeiro e so' cai em confidence quando ela nao existe --
 * picks VIP antigos e multiplas nao tem a coluna. Devolve null em vez de 0
 * quando nao ha nada: 0% seria uma afirmacao, e ausencia nao e' zero.
 */
export function pctProb(v: unknown): number | null {
  const n = Number(v)
  if (!isFinite(n) || n <= 0) return null
  return n <= 1 ? n * 100 : n
}
