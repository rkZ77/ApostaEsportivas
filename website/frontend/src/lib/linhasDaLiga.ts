/*
 * LINHAS DA LIGA (15/10/2026, aba Ligas).
 *
 * Em quantos jogos da amostra cada linha bateu · a mesma "taxa por linha" do
 * Raio-X, só que da liga inteira. Conta sobre os jogos que a tela já tem
 * (/suggestions/liga/tendencias), sem rota nova nem cota.
 *
 * Jogo sem o dado (escanteio ou cartão nulo) fica FORA da conta daquela linha,
 * em vez de contar como "não bateu": sem dado não é zero.
 */

export interface JogoDaLiga {
  home_goals: number | null
  away_goals: number | null
  total_goals?: number | null
  total_corners: number | null
  total_yellow_cards: number | null
}

export interface Linha {
  rotulo: string
  bateu: number
  total: number
  /** 0-100, inteiro. null quando nenhum jogo tem o dado. */
  pct: number | null
}

export interface GrupoDeLinhas { titulo: string; linhas: Linha[] }

function gols(j: JogoDaLiga): number | null {
  if (j.home_goals == null || j.away_goals == null) return null
  return j.home_goals + j.away_goals
}

function contar(jogos: JogoDaLiga[], valor: (j: JogoDaLiga) => number | null, passou: (v: number) => boolean, rotulo: string): Linha {
  let bateu = 0, total = 0
  for (const j of jogos) {
    const v = valor(j)
    if (v == null) continue
    total++
    if (passou(v)) bateu++
  }
  return { rotulo, bateu, total, pct: total ? Math.round((bateu / total) * 100) : null }
}

const virgula = (n: number) => String(n).replace('.', ',')

export function linhasDaLiga(jogos: JogoDaLiga[]): GrupoDeLinhas[] {
  const acima = (l: number) => (v: number) => v > l
  return [
    {
      titulo: 'Gols',
      linhas: [
        ...[0.5, 1.5, 2.5, 3.5].map(l => contar(jogos, gols, acima(l), `Mais de ${virgula(l)}`)),
        contar(jogos, j => (j.home_goals == null || j.away_goals == null) ? null : (j.home_goals > 0 && j.away_goals > 0 ? 1 : 0),
               v => v === 1, 'Ambas marcam'),
      ],
    },
    {
      titulo: 'Escanteios',
      linhas: [8.5, 9.5, 10.5].map(l => contar(jogos, j => j.total_corners, acima(l), `Mais de ${virgula(l)}`)),
    },
    {
      titulo: 'Cartões amarelos',
      linhas: [3.5, 4.5].map(l => contar(jogos, j => j.total_yellow_cards, acima(l), `Mais de ${virgula(l)}`)),
    },
  ]
}

/** Quantos jogos terminaram com 0, 1, 2, 3, 4 e 5+ gols. */
export function distribuicaoDeGols(jogos: JogoDaLiga[]): { rotulo: string; jogos: number }[] {
  const caixas = [0, 0, 0, 0, 0, 0]
  for (const j of jogos) {
    const g = gols(j)
    if (g == null) continue
    caixas[Math.min(g, 5)]++
  }
  return caixas.map((n, i) => ({ rotulo: i === 5 ? '5+' : String(i), jogos: n }))
}
