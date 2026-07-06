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

export function maskPhone(value: string): string {
  const d = value.replace(/\D/g, '').slice(0, 11)
  if (d.length <= 2)  return d.length ? `(${d}` : ''
  if (d.length <= 6)  return `(${d.slice(0,2)}) ${d.slice(2)}`
  if (d.length <= 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`
  return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`
}
