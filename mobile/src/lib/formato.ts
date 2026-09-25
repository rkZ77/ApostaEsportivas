/**
 * Formatação de texto e número para as telas.
 *
 * REGRA DE FUSO (a mesma do site, e o motivo de não haver `new Date` aqui):
 * `match_datetime` vem do banco como horário de Brasília SEM fuso declarado,
 * e `match_date` é um DATE puro. Jogar qualquer um dos dois em `new Date` faz
 * o aparelho aplicar o fuso local por cima e deslocar o horário do jogo --
 * num celular configurado fora do Brasil o pick apareceria na hora errada.
 * Por isso a hora é lida por fatia de string, que é exatamente o que o valor
 * já significa.
 */
import type { Resultado } from '../api/types'
import { cores } from '../theme/tokens'

/** "2026-08-11T21:30:00" -> "21:30". Sem conversão de fuso, de propósito. */
export function horaDoJogo(matchDatetime?: string | null): string {
  if (!matchDatetime || matchDatetime.length < 16) return ''
  return matchDatetime.slice(11, 16)
}

/** "2026-08-11" -> "11/08". */
export function diaCurto(matchDate?: string | null): string {
  if (!matchDate || matchDate.length < 10) return ''
  return `${matchDate.slice(8, 10)}/${matchDate.slice(5, 7)}`
}

/** Data de hoje em Brasília, no formato YYYY-MM-DD, sem depender do fuso do aparelho. */
export function hojeEmBrasilia(): string {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return fmt.format(new Date())
}

export function ehHoje(matchDate?: string | null): boolean {
  return Boolean(matchDate) && matchDate!.slice(0, 10) === hojeEmBrasilia()
}

/** Odd sempre com duas casas · 1.8 vira "1.80". */
export function odd(valor?: number | null): string {
  if (valor == null) return '—'
  return valor.toFixed(2)
}

/** Confiança chega 0–100 ou 0–1 conforme a tabela · normaliza para inteiro em %. */
export function confianca(valor?: number | null): string {
  if (valor == null) return '—'
  const pct = valor <= 1 ? valor * 100 : valor
  return `${Math.round(pct)}%`
}

/** EV chega como fração (0.0734) · vira "+7.3%". */
export function ev(valor?: number | null): string {
  if (valor == null) return '—'
  const pct = Math.abs(valor) <= 1 ? valor * 100 : valor
  const sinal = pct > 0 ? '+' : ''
  return `${sinal}${pct.toFixed(1)}%`
}

/*
 * NÚMEROS · as mesmas regras de website/frontend/src/utils/format.ts.
 *
 * Valor (banca, stake) sai sem sinal; resultado (lucro/prejuízo) sai sempre
 * com sinal. Era uma função só para os dois, e a banca aparecia "+R$ 1184,50"
 * como se fosse lucro, e o lucro potencial "++R$ 21,60". Separado, não tem
 * como errar. Milhar com ponto e decimal com vírgula; odd continua com ponto,
 * como nas casas e no site.
 *
 * Feito à mão em vez de `toLocaleString('pt-BR')` porque o suporte a Intl
 * varia entre motores JS e a tela não pode depender disso.
 */
function numeroBR(valor: number, casas: number): string {
  const [inteiro, decimal] = Math.abs(valor).toFixed(casas).split('.')
  const comMilhar = inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return decimal ? `${comMilhar},${decimal}` : comMilhar
}

/** Valor em reais, sem sinal · `R$ 1.184,50`. Espelho de `fmtBRL`. */
export function reais(valor?: number | null): string {
  if (valor == null) return '—'
  return `R$ ${numeroBR(valor, 2)}`
}

/** Resultado em reais, sempre com sinal · `+R$ 21,60` / `−R$ 30,00`. Espelho de `fmtSigned`. */
export function reaisComSinal(valor?: number | null): string {
  if (valor == null) return '—'
  return `${valor >= 0 ? '+' : '−'}${reais(valor)}`
}

/** Porcentagem que o backend já calculou · `63,9%`. */
export function pct(valor?: number | null, casas = 1): string {
  if (valor == null) return '—'
  return `${valor < 0 ? '−' : ''}${numeroBR(valor, casas)}%`
}

/** Quantidade de unidades · `1,5u`, `2u`. */
export function unidades(valor?: number | null): string {
  if (valor == null) return '—'
  const n = Number(valor)
  return `${numeroBR(n, n % 1 === 0 ? 0 : 1)}u`
}

/** Unidades de resultado, sempre com sinal · `+1,08u`. Espelho de `fmtUnits`. */
export function unidadesComSinal(valor?: number | null, casas = 2): string {
  if (valor == null) return '—'
  return `${valor < 0 ? '−' : '+'}${numeroBR(valor, casas)}u`
}

/** Nome do time · picks_vip usa *_name, picks_free usa home_team/away_team. */
export function timeCasa(p: { home_team_name?: string | null; home_team?: string | null }): string {
  return p.home_team_name ?? p.home_team ?? 'Casa'
}

export function timeFora(p: { away_team_name?: string | null; away_team?: string | null }): string {
  return p.away_team_name ?? p.away_team ?? 'Visitante'
}

/** Mercado + linha na forma que o usuário lê no site. */
export function mercadoCompleto(market?: string | null, line?: string | null): string {
  if (!market) return '—'
  return line ? `${market} ${line}` : market
}

/* Rótulo e cor de resultado · mesma semântica de utils/resultStyle.ts no site. */
const RESULTADOS: Record<string, { rotulo: string; cor: string }> = {
  GREEN: { rotulo: 'Green', cor: cores.green },
  RED: { rotulo: 'Red', cor: cores.red },
  PUSH: { rotulo: 'Anulado', cor: cores.ink3 },
  VOID: { rotulo: 'Anulado', cor: cores.ink3 },
  'HALF-WIN': { rotulo: 'Meio green', cor: cores.green },
  'HALF-LOSS': { rotulo: 'Meio red', cor: cores.red },
}

export function estiloDoResultado(resultado: Resultado): { rotulo: string; cor: string } {
  if (!resultado) return { rotulo: 'Em aberto', cor: cores.amber }
  return RESULTADOS[resultado] ?? { rotulo: resultado, cor: cores.ink3 }
}

/** URL do escudo · mesma fonte de imagem que o site já usa. */
export function escudo(teamId?: number | null): string | null {
  if (!teamId) return null
  return `https://media.api-sports.io/football/teams/${teamId}.png`
}
