import { useMemo, useState } from 'react'
import { cn } from '../lib/cn'

/*
 * Mapa de calor de atividade por dia.
 *
 * Cada quadrado é um dia; a cor é o APROVEITAMENTO (greens sobre total), não o
 * volume. Volume viraria um mapa que só diz "teve muito jogo na rodada", que a
 * agenda já conta melhor.
 *
 * A escala é discreta em 4 degraus em vez de gradiente contínuo: em quadrado de
 * 11px o olho não distingue 60% de 63%, e degrau nomeado dá legenda honesta.
 * Dia sem pick fica com a cor da superfície, distinto de "0% de acerto".
 */

interface DayData {
  match_date: string
  total: number
  greens: number
}

const DOW = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S']

/** Degrau de cor por faixa de win rate. */
function tone(wr: number | null): string {
  if (wr === null) return 'bg-surface-2'
  if (wr >= 70) return 'bg-accent'
  if (wr >= 55) return 'bg-accent/60'
  if (wr >= 40) return 'bg-accent/30'
  return 'bg-red-500/40'
}

export default function ActivityHeatmap({
  data,
  weeks = 13,
  className,
}: {
  data: DayData[]
  /** Quantas semanas mostrar, contando pra trás a partir de hoje. */
  weeks?: number
  className?: string
}) {
  const [hover, setHover] = useState<string | null>(null)

  const { cells, byDate } = useMemo(() => {
    const byDate = new Map(data.map(d => [d.match_date, d]))

    // Fecha a grade no sábado da semana atual pra última coluna ficar cheia.
    const today = new Date()
    const end = new Date(today)
    end.setDate(end.getDate() + (6 - end.getDay()))

    const start = new Date(end)
    start.setDate(start.getDate() - (weeks * 7 - 1))

    const cells: Array<{ iso: string; wr: number | null; total: number; greens: number }> = []
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const iso = d.toLocaleDateString('en-CA')
      const rec = byDate.get(iso)
      cells.push({
        iso,
        wr: rec && rec.total > 0 ? Math.round((rec.greens / rec.total) * 100) : null,
        total: rec?.total ?? 0,
        greens: rec?.greens ?? 0,
      })
    }
    return { cells, byDate }
  }, [data, weeks])

  // Agrupa em colunas de 7 (uma coluna = uma semana, domingo no topo).
  const columns = useMemo(() => {
    const out: (typeof cells)[] = []
    for (let i = 0; i < cells.length; i += 7) out.push(cells.slice(i, i + 7))
    return out
  }, [cells])

  const hovered = hover ? byDate.get(hover) : null

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex gap-2">
        {/* Rótulos dos dias da semana */}
        <div className="flex flex-col gap-[3px] shrink-0 pt-[2px]">
          {DOW.map((d, i) => (
            <span
              key={i}
              className="h-[11px] w-3 text-[8px] leading-[11px] text-ink-4 text-center"
              aria-hidden="true"
            >
              {i % 2 === 1 ? d : ''}
            </span>
          ))}
        </div>

        <div className="flex gap-[3px] overflow-x-auto scrollbar-none pb-1">
          {columns.map((col, ci) => (
            <div key={ci} className="flex flex-col gap-[3px] shrink-0">
              {col.map(cell => (
                <div
                  key={cell.iso}
                  onMouseEnter={() => setHover(cell.iso)}
                  onMouseLeave={() => setHover(null)}
                  title={cell.total > 0
                    ? `${new Date(cell.iso + 'T12:00:00').toLocaleDateString('pt-BR')}: ${cell.greens}/${cell.total} (${cell.wr}%)`
                    : `${new Date(cell.iso + 'T12:00:00').toLocaleDateString('pt-BR')}: sem pick`}
                  className={cn(
                    'w-[11px] h-[11px] rounded-[2px] transition-transform duration-1',
                    tone(cell.wr),
                    hover === cell.iso && 'ring-1 ring-ink-2 scale-125',
                  )}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        {/* Legenda */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-ink-4">menos</span>
          {['bg-red-500/40', 'bg-accent/30', 'bg-accent/60', 'bg-accent'].map(c => (
            <span key={c} className={cn('w-[11px] h-[11px] rounded-[2px]', c)} />
          ))}
          <span className="text-[10px] text-ink-4">mais</span>
          <span className="text-[10px] text-ink-4 ml-2">aproveitamento no dia</span>
        </div>

        {/* Leitura do dia sob o cursor. Altura fixa pra grade não pular. */}
        <div className="text-[11px] text-ink-3 h-4">
          {hovered && hovered.total > 0 && (
            <>
              {new Date(hovered.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })}
              {': '}
              <span className="font-mono text-ink-1">{hovered.greens}/{hovered.total}</span>
              {' greens'}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
