import { useEffect, useState } from 'react'
import { Activity } from 'lucide-react'
import api from '../services/api'
import { Skeleton } from './ui'

/*
 * Como esse mercado vem se comportando.
 *
 * Uma barra por jogo recente dos dois times, medida pelo contador que a aposta
 * observa (escanteios, cartões, faltas, chutes no alvo), com a linha do pick
 * atravessando o gráfico. Verde onde teria pago, vermelho onde não.
 *
 * É a diferença entre "a IA acha que dá Over 9.5" e "nos últimos 8 jogos deu
 * 11, 8, 12, 10...". O número de probabilidade pede confiança; isto mostra o
 * que aconteceu.
 *
 * Quem decide a cor NÃO é este arquivo. O servidor devolve cada jogo já
 * liquidado pelo mesmo módulo que grada o pick de verdade (settlement), então
 * meia-linha asiática e PUSH em linha cheia chegam aqui resolvidos. Um
 * `valor > linha` daqui pareceria inofensivo e pintaria de verde jogo que não
 * pagou.
 *
 * Jogo sem estatística publicada aparece como barra vazia e fica fora da taxa.
 * Some é o que não pode: "não sei" virando zero foi o que gravou RED num pick
 * que era GREEN em 05/08.
 */

interface FormMatch {
  fixture_id: number
  match_date: string | null
  /** null = a fonte não publicou o contador desse jogo. */
  value: number | null
  result: 'GREEN' | 'RED' | 'PUSH' | null
}

interface MarketFormData {
  available: boolean
  label?: string
  line?: number | null
  op?: 'over' | 'under' | null
  matches?: FormMatch[]
  resolved?: number
  greens?: number
  hit_rate?: number | null
  average?: number | null
}

const COR: Record<string, string> = {
  GREEN: 'bg-accent',
  RED:   'bg-red-400',
  PUSH:  'bg-ink-4',
}

export default function MarketForm({
  pickId,
  pickType,
}: {
  pickId: number
  pickType: string
}) {
  const [data, setData] = useState<MarketFormData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let vivo = true
    api.get(`/suggestions/${pickId}/market-form`, { params: { pick_type: pickType } })
      .then(r => { if (vivo) setData(r.data) })
      .catch(() => { if (vivo) setData({ available: false }) })
      .finally(() => { if (vivo) setLoading(false) })
    return () => { vivo = false }
  }, [pickId, pickType])

  if (loading) return <Skeleton className="h-[132px]" />
  if (!data?.available || !data.matches?.length) return null

  const { matches, line, label, hit_rate, average, greens, resolved } = data
  const valores = matches.map(m => m.value).filter((v): v is number => v != null)
  if (!valores.length) return null

  // O topo acomoda a maior barra E a linha, senão a linha do pick sai do
  // quadro justo quando ela é o que mais importa ver.
  const teto = Math.max(...valores, line ?? 0) * 1.15 || 1
  const alturaLinha = line != null ? (line / teto) * 100 : null
  const taxa = hit_rate != null ? Math.round(hit_rate * 100) : null

  return (
    <div className="bg-surface-0 border border-line rounded-lg p-4">
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 min-w-0">
          <Activity className="w-3.5 h-3.5 text-ink-4 shrink-0" />
          <span className="panel-label truncate">Como esse mercado vem se comportando</span>
        </div>
        {taxa != null && (
          <span className={`font-mono text-sm font-bold tabular-nums shrink-0 ${taxa >= 60 ? 'text-accent' : taxa >= 40 ? 'text-ink-2' : 'text-red-400'}`}>
            {taxa}%
          </span>
        )}
      </div>

      <p className="text-[11px] text-ink-4 mb-4">
        {label} nos últimos {matches.length} jogos dos dois times
        {average != null && <> · média {average}</>}
        {taxa != null && <> · bateu em {greens} de {resolved}</>}
      </p>

      <div className="relative h-24 flex items-end gap-1">
        {/* Linha do pick, atravessando. É a régua contra a qual as barras são
            lidas, então fica por cima delas e não atrás. */}
        {alturaLinha != null && alturaLinha < 100 && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 border-t border-dashed border-ink-3/70 z-10"
            style={{ bottom: `${alturaLinha}%` }}
          >
            <span className="absolute right-0 -top-4 font-mono text-[9px] text-ink-3 bg-surface-0 px-1">
              {line}
            </span>
          </div>
        )}

        {matches.slice().reverse().map(m => {
          const altura = m.value != null ? Math.max((m.value / teto) * 100, 4) : 100
          const titulo = m.value == null
            ? `${m.match_date ?? ''} · sem estatística publicada`
            : `${m.match_date ?? ''} · ${m.value}`
          return (
            <div key={m.fixture_id} className="flex-1 h-full flex items-end" title={titulo}>
              <div
                className={`w-full rounded-sm transition-[height] ${
                  m.value == null
                    ? 'border border-dashed border-line-strong bg-transparent'
                    : COR[m.result ?? ''] ?? 'bg-ink-4'
                }`}
                style={{ height: `${altura}%` }}
              />
            </div>
          )
        })}
      </div>

      <div className="flex items-center gap-3 mt-3 pt-2.5 border-t border-line/60 flex-wrap">
        {[
          ['bg-accent', 'bateu'],
          ['bg-red-400', 'não bateu'],
          ['bg-ink-4', 'devolveu'],
        ].map(([cls, txt]) => (
          <span key={txt} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-sm ${cls}`} />
            <span className="text-[10px] text-ink-4">{txt}</span>
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-sm border border-dashed border-line-strong" />
          <span className="text-[10px] text-ink-4">sem dado</span>
        </span>
      </div>
    </div>
  )
}
