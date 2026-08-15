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
 * Lucro em unidades, sempre com sinal. `+42,7u` · `−1,00u`.
 *
 * TODO numero publico de unidade sai daqui, e a premissa e' sempre a mesma:
 * STAKE FIXA DE 1u POR PICK. E' o que a coluna `profit` das seis tabelas de
 * picks guarda (settlement.py: GREEN -> odd-1, HALF-WIN -> (odd-1)/2, PUSH -> 0,
 * HALF-LOSS -> -0.5, RED -> -1), entao somar `profit` ja da' o resultado em
 * unidades sem recalcular nada no cliente.
 *
 * Isso NAO e' a stake sugerida da Banca, que varia de 1u a 10u por confianca
 * (stakeUtils.ts). Quem mostra este numero tem que dizer "stake fixa de 1u" na
 * tela, senao o usuario compara com a banca dele e o site parece estar mentindo.
 *
 * Total com 1 casa; media por pick com 2, porque media e' numero pequeno e 1
 * casa achata tudo em `+0,2u`. Sufixo `u` minusculo colado, igual a Banca ja usa.
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
