import { useEffect, useState } from 'react'
import api from '../services/api'

/*
 * Quanto a Leitura da IA do Raio-X está gastando (12/10/2026, pedido do
 * usuário: "nada muito gastar com IA"). Uma linha por dia: leituras geradas,
 * jogos que o filtro de amostra barrou (custo zero), falhas, tokens e o custo
 * estimado pelo preço do modelo. A fatura de verdade é a do console da
 * Anthropic; isto é para acompanhar a tendência sem sair do painel.
 */

interface Dia {
  dia: string; geradas: number; sem_amostra: number; falhas: number
  tokens_in: number; tokens_out: number; custo_usd: number
}
interface Uso { dias: Dia[]; modelo: string; teto_dia: number; ligado: boolean }

const usd = (v: number) => `US$ ${v.toFixed(v < 1 ? 4 : 2)}`

export default function AdminLeiturasIA() {
  const [uso, setUso] = useState<Uso | null>(null)
  const [erro, setErro] = useState(false)

  useEffect(() => {
    api.get('/admin/leituras-ia').then(r => setUso(r.data)).catch(() => setErro(true))
  }, [])

  if (erro) return <p className="text-xs text-ink-3">Não deu para ler o uso da Leitura da IA.</p>
  if (!uso) return <p className="text-xs text-ink-4">Carregando…</p>

  const total = uso.dias.reduce((s, d) => s + d.custo_usd, 0)
  const geradas = uso.dias.reduce((s, d) => s + d.geradas, 0)

  return (
    <div className="card p-4 space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          ['Situação', uso.ligado ? 'Ligada' : 'Desligada'],
          ['Teto por dia', String(uso.teto_dia)],
          ['Leituras (14 dias)', String(geradas)],
          ['Custo (14 dias)', usd(total)],
        ].map(([rotulo, valor]) => (
          <div key={rotulo} className="rounded bg-surface-1 px-3 py-2">
            <p className="text-[10px] text-ink-4">{rotulo}</p>
            <p className="text-lg font-bold text-ink-1">{valor}</p>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-ink-4">Modelo {uso.modelo}. Uma leitura por jogo por dia, gerada quando alguém abre a aba.</p>

      {uso.dias.length === 0 ? (
        <p className="text-xs text-ink-3">Nenhuma leitura gerada ainda.</p>
      ) : (
        <div className="overflow-x-auto -mx-4 px-4">
          <table className="w-full text-xs tabular-nums">
            <thead>
              <tr className="text-ink-4 text-left">
                <th className="py-1.5 pr-3 font-semibold">Dia</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Geradas</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Sem amostra</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Falhas</th>
                <th className="py-1.5 pr-3 font-semibold text-right">Tokens</th>
                <th className="py-1.5 font-semibold text-right">Custo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {uso.dias.map(d => (
                <tr key={d.dia} className="text-ink-2">
                  <td className="py-1.5 pr-3">{d.dia.split('-').reverse().slice(0, 2).join('/')}</td>
                  <td className="py-1.5 pr-3 text-right font-bold text-ink-1">{d.geradas}</td>
                  <td className="py-1.5 pr-3 text-right">{d.sem_amostra}</td>
                  <td className="py-1.5 pr-3 text-right">{d.falhas}</td>
                  <td className="py-1.5 pr-3 text-right">{((d.tokens_in + d.tokens_out) / 1000).toFixed(1)}k</td>
                  <td className="py-1.5 text-right">{usd(d.custo_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
