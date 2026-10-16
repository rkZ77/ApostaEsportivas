import { useEffect, useState } from 'react'
import { HelpCircle } from 'lucide-react'
import api from '../services/api'
import { SpinnerBlock } from './ui'

/*
 * POR QUE ESTA LIGA NÃO TEVE PICK (14/10/2026, pedido do usuário: "o motor
 * não gerou pick do Championship, estava sem odd ou o quê?").
 *
 * Escolhe a liga e o dia e vê, jogo a jogo, o que cada motor fez · ver
 * /admin/motor/por-que. O caso que nenhuma outra tela mostrava é o jogo SEM
 * ODD: os pipelines só leem jogo com odd, então ele nem entra no log de
 * decisões e parecia que o motor tinha ignorado a liga.
 */

interface Liga { league_id: number; name: string; ativa: boolean }
interface PorPipeline { pipeline: string; rotulo: string; status: string; explicacao: string }
interface Jogo {
  fixture_id: number; home_team: string; away_team: string; quando: string | null; status: string | null
  odds: number; mercados_com_odd: number; resumo: string; pipelines: PorPipeline[]
}

const hojeBR = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'America/Sao_Paulo' })

export default function AdminPorQue() {
  const [ligas, setLigas] = useState<Liga[]>([])
  const [liga, setLiga] = useState<number | ''>('')
  const [dia, setDia] = useState(hojeBR())
  const [carregando, setCarregando] = useState(false)
  const [res, setRes] = useState<{ jogos: Jogo[]; aviso: string | null } | null>(null)
  const [erro, setErro] = useState(false)

  useEffect(() => {
    api.get('/admin/motor/por-que').then(r => setLigas(r.data.ligas ?? [])).catch(() => setErro(true))
  }, [])

  useEffect(() => {
    if (liga === '') { setRes(null); return }
    setCarregando(true)
    setErro(false)
    api.get('/admin/motor/por-que', { params: { liga, data: dia } })
      .then(r => setRes({ jogos: r.data.jogos ?? [], aviso: r.data.aviso ?? null }))
      .catch(() => setErro(true))
      .finally(() => setCarregando(false))
  }, [liga, dia])

  const campo = 'bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[36px] focus:border-ink-4 focus:outline-none'

  return (
    <div className="card p-4 space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-bold text-ink-1">
        <HelpCircle className="w-4 h-4" /> Por que não saiu pick?
      </h3>
      <p className="text-xs text-ink-3">
        Escolha a liga e o dia: cada jogo mostra se tinha odd e o que cada motor fez com ele.
      </p>
      <div className="flex flex-wrap gap-2">
        <select value={liga} onChange={e => setLiga(e.target.value ? Number(e.target.value) : '')}
          className={`${campo} flex-1 min-w-[180px]`} aria-label="Liga">
          <option value="">Escolha a liga</option>
          {ligas.map(l => (
            <option key={l.league_id} value={l.league_id}>{l.name}{l.ativa ? '' : ' (desativada)'}</option>
          ))}
        </select>
        <input type="date" value={dia} onChange={e => setDia(e.target.value)} className={campo} aria-label="Dia" />
      </div>

      {erro && <p className="text-xs text-ink-3">Não deu para carregar agora.</p>}
      {carregando && <SpinnerBlock />}
      {!carregando && res && (
        res.jogos.length === 0 ? (
          <p className="text-sm text-ink-2">{res.aviso ?? 'Nenhum jogo.'}</p>
        ) : (
          <div className="divide-y divide-line/60 border border-line rounded-lg overflow-hidden">
            {res.jogos.map(j => (
              <div key={j.fixture_id} className="p-3 space-y-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-bold text-ink-1">{j.home_team} x {j.away_team}</span>
                  <span className="text-[11px] text-ink-3 tabular-nums">
                    {(j.quando ?? '').slice(11, 16)} · {j.odds ? `${j.odds} odds em ${j.mercados_com_odd} mercados` : 'sem odd'}
                  </span>
                </div>
                <p className={`text-xs ${j.odds ? 'text-ink-2' : 'text-amber-400'}`}>{j.resumo}</p>
                {j.pipelines.length > 0 && (
                  <ul className="space-y-0.5">
                    {j.pipelines.map(p => (
                      <li key={p.pipeline} className="text-[11px] text-ink-3">
                        <b className="text-ink-2">{p.rotulo}</b> · {p.explicacao}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}
