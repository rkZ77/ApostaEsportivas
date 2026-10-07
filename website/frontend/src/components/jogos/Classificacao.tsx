import { useEffect, useMemo, useState } from 'react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { EmptyState, ErrorState, Skeleton } from '../ui'
import { TeamLogo } from '../TeamLogo'

/*
 * Classificação da liga do jogo (2026-10-07, pedido do usuário: "saber
 * posição e tal").
 *
 * Os dois times do jogo vêm destacados, e o seletor Geral / Casa / Fora
 * refaz a tabela só com os jogos de mandante ou de visitante: é o recorte que
 * importa pra aposta (o mandante forte em casa que é fraco fora não aparece
 * na tabela geral). A faixa da esquerda pinta a zona: verde Libertadores ou
 * Champions, azul Sul-Americana ou Europa, vermelho rebaixamento.
 *
 * Celular primeiro: cinco colunas curtas (#, time, J, SG, Pts) e a forma em
 * bolinhas só a partir do tablet.
 */

interface Linha {
  group_name: string | null
  team_id: number
  team_name: string
  rank: number
  points: number
  goals_diff: number
  form: string | null
  description: string | null
  played: number; win: number; draw: number; lose: number
  goals_for: number; goals_against: number
  home_played: number; home_win: number; home_draw: number; home_lose: number
  home_goals_for: number; home_goals_against: number
  away_played: number; away_win: number; away_draw: number; away_lose: number
  away_goals_for: number; away_goals_against: number
}

type Recorte = 'geral' | 'casa' | 'fora'

/** A zona da tabela pela descrição do provedor (em inglês). */
export function zonaDaLinha(descricao: string | null): 'titulo' | 'continental' | 'rebaixamento' | null {
  const d = (descricao ?? '').toLowerCase()
  if (!d) return null
  if (d.includes('relegation')) return 'rebaixamento'
  // As vagas secundárias ANTES: o provedor escreve "Promotion - ..." em todas,
  // e testar "promotion" primeiro pintava a Sul-Americana como Libertadores.
  if (d.includes('sudamericana') || d.includes('europa') || d.includes('conference') || d.includes('play')) return 'continental'
  if (d.includes('libertadores') || d.includes('champions league') || d.includes('promotion')) return 'titulo'
  return null
}

const COR_ZONA = { titulo: 'bg-green-500', continental: 'bg-blue-500', rebaixamento: 'bg-red-500' }

/** A linha refeita só com os jogos de casa ou de fora, e a tabela reordenada. */
export function recortar(linhas: Linha[], recorte: Recorte) {
  if (recorte === 'geral') {
    return linhas.map(l => ({ l, rank: l.rank, j: l.played, sg: l.goals_diff, pts: l.points }))
  }
  const p = recorte === 'casa' ? 'home' : 'away'
  const refeitas = linhas.map(l => {
    const v = l[`${p}_win` as keyof Linha] as number, e = l[`${p}_draw` as keyof Linha] as number
    const gp = l[`${p}_goals_for` as keyof Linha] as number, gc = l[`${p}_goals_against` as keyof Linha] as number
    return { l, rank: 0, j: l[`${p}_played` as keyof Linha] as number, sg: gp - gc, pts: v * 3 + e, gp }
  })
  refeitas.sort((a, b) => b.pts - a.pts || b.sg - a.sg || b.gp - a.gp)
  refeitas.forEach((r, i) => { r.rank = i + 1 })
  return refeitas
}

export default function Classificacao({ fixtureId, leagueId, homeId, awayId }: {
  fixtureId: number; leagueId: number | null; homeId: number; awayId: number
}) {
  const [linhas, setLinhas] = useState<Linha[] | null>(null)
  const [erro, setErro] = useState(false)
  const [recorte, setRecorte] = useState<Recorte>('geral')

  const carregar = () => {
    setErro(false)
    api.get(`/fixtures/${fixtureId}/classificacao`, { params: { league: leagueId ?? undefined } })
      .then(r => setLinhas(r.data.linhas ?? []))
      .catch(() => setErro(true))
  }
  useEffect(carregar, [fixtureId])

  /* Liga de grupos: mostra só o(s) grupo(s) dos dois times do jogo. */
  const grupos = useMemo(() => {
    const todas = linhas ?? []
    const nomes = [...new Set(todas.map(l => l.group_name ?? ''))]
    const doJogo = nomes.filter(g => todas.some(l => (l.group_name ?? '') === g && (l.team_id === homeId || l.team_id === awayId)))
    return (doJogo.length ? doJogo : nomes).map(g => ({ nome: g, linhas: todas.filter(l => (l.group_name ?? '') === g) }))
  }, [linhas, homeId, awayId])

  if (erro) return <div className="card"><ErrorState title="Não deu pra carregar a tabela" onRetry={carregar} /></div>
  if (!linhas) return <div className="space-y-2"><Skeleton className="h-10 w-full" /><Skeleton className="h-[420px] w-full" /></div>
  if (!linhas.length) {
    return <div className="card"><EmptyState title="Sem tabela dessa liga ainda"
      description="A classificação entra quando a coleta da rodada roda." compact /></div>
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 rounded-lg border border-line p-0.5 bg-surface-1">
        {([['geral', 'Geral'], ['casa', 'Em casa'], ['fora', 'Fora']] as [Recorte, string][]).map(([k, r]) => (
          <button key={k} onClick={() => setRecorte(k)} aria-pressed={recorte === k}
            className={cn('h-10 rounded-md text-sm font-bold transition-colors', recorte === k ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
            {r}
          </button>
        ))}
      </div>

      {grupos.map(g => (
        <div key={g.nome} className="card overflow-hidden">
          {g.nome && grupos.length > 1 && (
            <div className="px-3 py-2 border-b border-line text-xs font-bold text-ink-2">{g.nome}</div>
          )}
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="text-[11px] text-ink-3 border-b border-line">
                <th className="w-9 py-2 font-semibold">#</th>
                <th className="text-left font-semibold">Time</th>
                <th className="w-9 font-semibold">J</th>
                <th className="w-11 font-semibold">SG</th>
                <th className="w-11 font-semibold text-ink-1">Pts</th>
                <th className="hidden sm:table-cell w-28 font-semibold">Forma</th>
              </tr>
            </thead>
            <tbody>
              {recortar(g.linhas, recorte).map(({ l, rank, j, sg, pts }) => {
                const doJogo = l.team_id === homeId || l.team_id === awayId
                const zona = recorte === 'geral' ? zonaDaLinha(l.description) : null
                return (
                  <tr key={l.team_id}
                    className={cn('border-b border-line/50 last:border-0', doJogo && 'bg-accent/10')}>
                    <td className="relative text-center py-2 text-ink-2 font-semibold">
                      {zona && <span className={cn('absolute left-0 top-1 bottom-1 w-1 rounded-r', COR_ZONA[zona])} />}
                      {rank}
                    </td>
                    <td className="min-w-0">
                      <div className="flex items-center gap-2 min-w-0 pr-2">
                        <TeamLogo id={l.team_id} name={l.team_name} size={18} />
                        <span className={cn('truncate', doJogo ? 'font-black text-ink-1' : 'text-ink-1')}>{l.team_name}</span>
                      </div>
                    </td>
                    <td className="text-center text-ink-3">{j}</td>
                    <td className={cn('text-center', sg > 0 ? 'text-accent-ink' : sg < 0 ? 'text-red-400' : 'text-ink-3')}>
                      {sg > 0 ? `+${sg}` : sg}
                    </td>
                    <td className="text-center font-black text-ink-1">{pts}</td>
                    <td className="hidden sm:table-cell">
                      <div className="flex gap-0.5 justify-center">
                        {(l.form ?? '').slice(-5).split('').map((c, i) => (
                          <span key={i} className={cn('w-4 h-4 rounded-sm text-[9px] font-black grid place-items-center',
                            c === 'W' ? 'bg-green-500 text-on-fill' : c === 'L' ? 'bg-red-500 text-on-fill' : 'bg-surface-3 text-ink-2')}>
                            {c === 'W' ? 'V' : c === 'L' ? 'D' : 'E'}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}

      {recorte === 'geral' && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-[11px] text-ink-3">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-green-500" />Libertadores / Champions / acesso</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-blue-500" />Sul-Americana / Europa / playoff</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-red-500" />Rebaixamento</span>
        </div>
      )}
    </div>
  )
}
