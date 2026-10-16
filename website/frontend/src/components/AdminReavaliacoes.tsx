import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react'
import api from '../services/api'
import { Panel, PanelHead } from './ui'

/*
 * Reavaliação perto do apito (08/10/2026).
 *
 * O motor reavalia os picks de VIP e Free no fechamento (~30 min antes do
 * apito, e de novo quando a escalação oficial sai): odd de agora, desfalque
 * que surgiu depois da previsão e titular fora do XI. Ele só GRAVA o alerta,
 * não cancela o pick. É aqui que dá pra ver e decidir antes do jogo.
 */

export interface Reavaliacao {
  pick_table: string; pick_id: number; fixture_id: number; reavaliado_em: string
  home_team?: string; away_team?: string; market?: string; line?: string; result?: string | null
  odd_publicada?: number | string | null; odd_agora?: number | string | null
  prob_publicada?: number | string | null; prob_reavaliada?: number | string | null
  ev_publicado?: number | string | null; ev_reavaliado?: number | string | null
  novos_ausentes?: Record<string, number[]> | null; fracao_perdida?: number | string | null
  alerta?: string | null; detalhe?: { xi_oficial?: boolean } | null
}

const num = (v: unknown): number | null => (v == null || v === '' ? null : Number(v))
const pct = (v: unknown) => { const n = num(v); return n == null ? '–' : `${(n * 100).toFixed(1)}%` }
const sinal = (v: unknown) => { const n = num(v); return n == null ? '–' : `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)}%` }

/** A linha de números de uma reavaliação, do jeito que o operador lê. */
export function resumoDaReavaliacao(r: Reavaliacao): string {
  const partes: string[] = []
  const antes = num(r.odd_publicada), agora = num(r.odd_agora)
  partes.push(agora == null ? 'linha sem cotação agora'
    : `odd ${antes ?? '–'} → ${agora}`)
  if (num(r.prob_reavaliada) != null && num(r.prob_reavaliada) !== num(r.prob_publicada)) {
    partes.push(`prob ${pct(r.prob_publicada)} → ${pct(r.prob_reavaliada)}`)
  }
  if (num(r.ev_reavaliado) != null) partes.push(`EV ${sinal(r.ev_publicado)} → ${sinal(r.ev_reavaliado)}`)
  const novos = Object.values(r.novos_ausentes ?? {}).reduce((s, l) => s + (l?.length ?? 0), 0)
  if (novos) partes.push(`${novos} ausente(s) novo(s)${num(r.fracao_perdida) ? ` · ${pct(r.fracao_perdida)} da produção` : ''}`)
  partes.push(r.detalhe?.xi_oficial ? 'com XI oficial' : 'antes do XI oficial')
  return partes.join(' · ')
}

export default function AdminReavaliacoes() {
  const [linhas, setLinhas] = useState<Reavaliacao[] | null>(null)
  const [erro, setErro] = useState(false)

  const carregar = useCallback(() => {
    api.get('/admin/reavaliacoes').then(r => { setLinhas(r.data.reavaliacoes ?? []); setErro(false) })
      .catch(() => setErro(true))
  }, [])
  useEffect(() => { carregar() }, [carregar])

  if (erro) return null
  const alertas = (linhas ?? []).filter(l => l.alerta).length
  return (
    <Panel>
      <PanelHead
        label="Reavaliação perto do apito"
        meta={linhas == null ? '' : `${linhas.length} pick(s) hoje · ${alertas} com alerta`}
      />
      <div className="px-4 pt-3 flex items-start justify-between gap-3">
        <p className="text-[11px] text-ink-3 leading-relaxed">
          VIP e Free conferidos no fechamento: odd de agora, desfalque novo e titular fora do XI.
          O motor só avisa, não cancela o pick.
        </p>
        <button onClick={carregar} className="shrink-0 text-ink-4 hover:text-ink-2" aria-label="Atualizar">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>
      {linhas == null ? (
        <div className="p-4 text-xs text-ink-4">Carregando…</div>
      ) : linhas.length === 0 ? (
        <div className="p-4 text-xs text-ink-4">Nenhum pick reavaliado hoje ainda. Roda junto do fechamento.</div>
      ) : (
        <ul className="divide-y divide-line mt-2">
          {linhas.map(r => (
            <li key={`${r.pick_table}-${r.pick_id}`} className="px-4 py-2.5 flex items-start gap-3">
              {r.alerta
                ? <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                : <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />}
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-ink-1 truncate">
                  {r.pick_table === 'picks_free' ? 'Free' : 'VIP'} · {r.home_team} x {r.away_team} · {r.market} {r.line}
                </p>
                {r.alerta && <p className="text-[11px] text-red-400 font-semibold">{r.alerta}</p>}
                <p className="text-[10px] text-ink-3 leading-relaxed">{resumoDaReavaliacao(r)}</p>
              </div>
              {r.result && <span className="text-[10px] text-ink-4 shrink-0">{r.result}</span>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
