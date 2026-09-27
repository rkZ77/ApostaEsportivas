import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import api from '../services/api'
import { Spinner } from './ui'

/*
 * Os REDs do período, cada um com as duas leituras que respondem "por que
 * perdeu": a do MOTOR (probabilidade anunciada, o que ele deixou de lado) e a
 * do CAMPO (por quanto perdeu, se estourou no 1º tempo, expulsão, time
 * poupado). A rota /admin/motor/reds existia sem tela nenhuma.
 */

interface Leitura {
  mercado?: string | null
  linha?: string | null
  categoria: string
  rotulo: string
  fatos: string[]
}

interface Red {
  tabela: string
  produto: string
  pick_id: number
  dia: string
  odd: number | null
  profit: number | null
  home_team: string | null
  away_team: string | null
  probabilidade_anunciada: number | null
  melhor_do_jogo: { market_type?: string; line?: string } | null
  leitura: Leitura | null
}

const COR: Record<string, string> = {
  evento_atipico: 'text-amber-400',
  estourou_cedo:  'text-orange-400',
  time_poupado:   'text-amber-400',
  por_pouco:      'text-ink-2',
  leitura_errada: 'text-red-400',
  sem_folha:      'text-ink-3',
  saiu_cedo:      'text-amber-400',
  veio_do_banco:  'text-amber-400',
}

function dataBr(dia: string): string {
  const [a, m, d] = (dia || '').slice(0, 10).split('-')
  return a ? `${d}/${m}` : ''
}

function pct(p: number | null): string {
  if (p === null || p === undefined) return ''
  const v = p <= 1 ? p * 100 : p
  return `${v.toFixed(0).replace('.', ',')}%`
}

export default function AdminReds() {
  const [reds, setReds] = useState<Red[]>([])
  const [dias, setDias] = useState(7)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')

  const buscar = useCallback(async () => {
    setCarregando(true)
    setErro('')
    try {
      const { data } = await api.get('/admin/motor/reds', { params: { dias } })
      setReds(Array.isArray(data?.reds) ? data.reds : [])
      if (data && data.disponivel === false) setErro('Nenhuma decisão registrada ainda.')
    } catch {
      setErro('Não foi possível carregar os REDs agora.')
      setReds([])
    } finally {
      setCarregando(false)
    }
  }, [dias])

  useEffect(() => { buscar() }, [buscar])

  const porCategoria = reds.reduce<Record<string, number>>((acc, r) => {
    const k = r.leitura?.rotulo
    if (k) acc[k] = (acc[k] || 0) + 1
    return acc
  }, {})

  return (
    <section className="rounded-md border border-line bg-surface-1 p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm sm:text-base font-semibold text-ink-1">
          <AlertTriangle size={16} className="text-red-400" aria-hidden />
          REDs: por que perdeu
        </h2>
        <div className="flex items-center gap-2">
          <select
            value={dias}
            onChange={e => setDias(Number(e.target.value))}
            className="rounded-md border border-line bg-surface-0 px-2 py-1 text-xs text-ink-1"
            aria-label="Período"
          >
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </select>
          <button onClick={buscar} className="p-1 text-ink-3 hover:text-ink-1" aria-label="Atualizar">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {Object.keys(porCategoria).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(porCategoria).map(([rotulo, n]) => (
            <span key={rotulo} className="rounded-full border border-line px-2 py-0.5 text-xs text-ink-2">
              {rotulo}: {n}
            </span>
          ))}
        </div>
      )}

      {carregando ? (
        <div className="py-6 flex justify-center"><Spinner /></div>
      ) : erro ? (
        <p className="mt-3 text-sm text-ink-3">{erro}</p>
      ) : reds.length === 0 ? (
        <p className="mt-3 text-sm text-ink-3">Nenhum RED no período.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {reds.map(r => {
            const mercado = r.leitura?.mercado
              ? `${r.leitura.mercado}${r.leitura.linha ? ` ${r.leitura.linha}` : ''}`
              : [r.melhor_do_jogo?.market_type, r.melhor_do_jogo?.line].filter(Boolean).join(' ')
            return (
              <li key={`${r.tabela}-${r.pick_id}`} className="py-3 text-xs sm:text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-semibold text-ink-1">
                    {r.home_team && r.away_team ? `${r.home_team} x ${r.away_team}` : r.produto}
                  </span>
                  <span className="text-ink-3">{r.produto}, {dataBr(r.dia)}</span>
                </div>
                <div className="mt-0.5 text-ink-2">
                  {mercado}
                  {r.odd ? ` @${Number(r.odd).toFixed(2).replace('.', ',')}` : ''}
                  {r.probabilidade_anunciada !== null ? ` (anunciado ${pct(r.probabilidade_anunciada)})` : ''}
                </div>
                {r.leitura && (
                  <div className="mt-1">
                    <span className={`font-semibold ${COR[r.leitura.categoria] || 'text-ink-2'}`}>
                      {r.leitura.rotulo}
                    </span>
                    {r.leitura.fatos.length > 0 && (
                      <span className="text-ink-3"> {r.leitura.fatos.join(' ')}</span>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
