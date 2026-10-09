/* O bilhete que o próprio usuário montou no Raio-X, aberto (07/10/2026).
 *
 * Meus Picks e a Banca abriam todo lançamento no SuggestionDetail, que lê
 * /suggestions/{id}: para o bilhete pessoal essa rota não existe e o modal
 * mostrava "Erro ao carregar dados". Aqui ele lê a rota dele
 * (/banca/bilhete-pessoal/{id}), que liquida antes de responder, então quem
 * abre depois do jogo já vê o GREEN ou o RED.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { m as motion } from 'framer-motion'
import { X, User, Check, Minus } from 'lucide-react'
import api from '../../services/api'
import { backdropFade, dialogScale } from '../../lib/motion'
import { getResultStyle } from '../../utils/resultStyle'
import { fmtBRL } from '../../utils/format'
import { TeamLogo } from '../TeamLogo'

interface Perna {
  fixture_id: number; home: string; away: string
  home_team_id?: number; away_team_id?: number
  tipo: 'time' | 'jogador'; descricao: string; odd?: number
  resultado?: 'GREEN' | 'RED' | 'VOID' | null
  /** Número da estatística, ou o placar ("2-1") no resultado final / chance dupla. */
  valor?: number | string | null; motivo?: string
  status_jogo?: string | null; inicio?: string | null
}

interface Bilhete {
  id: number; pernas: Perna[]; result: string | null; observacao: string | null
  odd: number; stake_units: number | null; casa: string | null
  lucro_unidades: number | null; lucro_reais: number | null; criado_em: string | null
}

const AO_VIVO = new Set(['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'])

function situacao(p: Perna): string {
  if (p.status_jogo && AO_VIVO.has(p.status_jogo)) return 'Ao vivo'
  if (p.status_jogo && ['FT', 'AET', 'PEN'].includes(p.status_jogo)) return 'Encerrado · conferindo'
  if (p.inicio) {
    const d = new Date(p.inicio)
    return `${d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} ${d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`
  }
  return 'Aguardando'
}

function SeloDaPerna({ r }: { r: Perna['resultado'] }) {
  if (r === 'GREEN') return <span className="w-6 h-6 rounded-full bg-green-500/15 text-green-400 flex items-center justify-center"><Check className="w-3.5 h-3.5" strokeWidth={3} /></span>
  if (r === 'RED') return <span className="w-6 h-6 rounded-full bg-red-500/15 text-red-400 flex items-center justify-center"><X className="w-3.5 h-3.5" strokeWidth={3} /></span>
  if (r === 'VOID') return <span className="w-6 h-6 rounded-full bg-surface-3 text-ink-3 flex items-center justify-center"><Minus className="w-3.5 h-3.5" strokeWidth={3} /></span>
  return <span className="w-6 h-6 rounded-full border border-dashed border-line-strong" />
}

export default function DetalheDoBilhetePessoal({ id, onClose }: { id: number; onClose: () => void }) {
  const [b, setB] = useState<Bilhete | null>(null)
  const [erro, setErro] = useState(false)

  useEffect(() => {
    let vivo = true
    api.get(`/banca/bilhete-pessoal/${id}`)
      .then(r => { if (vivo) setB(r.data) })
      .catch(() => { if (vivo) setErro(true) })
    return () => { vivo = false }
  }, [id])

  const rs = getResultStyle(b?.result === 'PUSH' ? 'PUSH' : b?.result)
  const conferidas = b ? b.pernas.filter(p => p.resultado).length : 0

  return createPortal(
    <motion.div variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center bg-black/70 backdrop-blur-sm sm:p-4"
      onClick={onClose}>
      <motion.div variants={dialogScale}
        className="w-full max-h-[92dvh] sm:max-w-lg bg-surface-0 border border-line rounded-t-xl sm:rounded-lg flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()} role="dialog" aria-label="Meu bilhete">
        <div className="shrink-0 flex items-center justify-between px-5 py-4 border-b border-line">
          <div>
            <p className="text-[10px] font-black uppercase tracking-wide text-ink-3">Meu bilhete</p>
            <p className="text-sm text-ink-2 mt-0.5">
              {b ? `${b.pernas.length} ${b.pernas.length === 1 ? 'seleção' : 'seleções'} · odd ${b.odd.toFixed(2)}` : 'Carregando…'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {rs && <span className={`text-xs font-black px-2 py-1 rounded border ${rs.bg} ${rs.border} ${rs.text}`}>{rs.label}</span>}
            <button onClick={onClose} aria-label="Fechar"
              className="w-9 h-9 flex items-center justify-center rounded-lg text-ink-2 hover:text-ink-1 bg-surface-2 border border-line-strong">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {erro ? (
            <p className="text-sm text-ink-3 text-center py-10">Não foi possível abrir este bilhete agora. Tente de novo em instantes.</p>
          ) : !b ? (
            <div className="space-y-2 animate-pulse">
              {[1, 2, 3].map(i => <div key={i} className="h-16 rounded-lg bg-surface-2" />)}
            </div>
          ) : (
            <>
              {/* Progresso da conferência */}
              {!b.result && (
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-ink-3">Seleções conferidas</span>
                    <span className="font-mono text-ink-1 tabular-nums">{conferidas}/{b.pernas.length}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
                    <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${(conferidas / b.pernas.length) * 100}%` }} />
                  </div>
                </div>
              )}

              <ul className="space-y-2">
                {b.pernas.map((p, i) => (
                  <li key={i} className={`rounded-lg border p-3 flex items-start gap-3 ${
                    p.resultado === 'GREEN' ? 'border-green-500/25 bg-green-500/5'
                      : p.resultado === 'RED' ? 'border-red-500/25 bg-red-500/5'
                      : 'border-line bg-surface-1'}`}>
                    <SeloDaPerna r={p.resultado} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-ink-1 flex items-center gap-1">
                        {p.tipo === 'jogador' && <User className="w-3.5 h-3.5 text-ink-3 shrink-0" />}
                        <span className="truncate">{p.descricao}</span>
                      </p>
                      <div className="flex items-center gap-1.5 mt-1 text-xs text-ink-3 min-w-0">
                        <TeamLogo id={p.home_team_id} name={p.home} size={12} />
                        <span className="truncate">{p.home} x {p.away}</span>
                        <TeamLogo id={p.away_team_id} name={p.away} size={12} />
                      </div>
                      <p className="text-[11px] text-ink-4 mt-1">
                        {p.resultado
                          ? p.resultado === 'VOID'
                            ? `Anulada${p.motivo ? `: ${p.motivo}` : ''}`
                            : p.valor != null ? `Saiu ${p.valor}` : 'Conferida'
                          : situacao(p)}
                      </p>
                    </div>
                    {p.odd != null && <span className="font-mono text-xs text-ink-2 tabular-nums shrink-0">{p.odd.toFixed(2)}</span>}
                  </li>
                ))}
              </ul>

              <dl className="rounded-lg border border-line bg-surface-1 divide-y divide-line text-sm">
                {b.stake_units != null && (
                  <div className="flex justify-between px-4 py-2.5"><dt className="text-ink-3">Stake</dt><dd className="font-mono text-ink-1">{b.stake_units}u</dd></div>
                )}
                <div className="flex justify-between px-4 py-2.5"><dt className="text-ink-3">Odd</dt><dd className="font-mono text-ink-1">{b.odd.toFixed(2)}</dd></div>
                {b.casa && (
                  <div className="flex justify-between px-4 py-2.5"><dt className="text-ink-3">Casa</dt><dd className="text-ink-1">{b.casa}</dd></div>
                )}
                {b.lucro_unidades != null && (
                  <div className="flex justify-between px-4 py-2.5">
                    <dt className="text-ink-3">Resultado</dt>
                    <dd className={`font-mono font-black ${b.lucro_unidades > 0 ? 'text-green-400' : b.lucro_unidades < 0 ? 'text-red-400' : 'text-ink-2'}`}>
                      {b.lucro_unidades > 0 ? '+' : ''}{b.lucro_unidades.toFixed(2)}u
                      {b.lucro_reais != null && <span className="text-ink-3 font-normal ml-1.5">({fmtBRL(b.lucro_reais)})</span>}
                    </dd>
                  </div>
                )}
              </dl>

              {b.observacao && <p className="text-xs text-ink-3 leading-relaxed">{b.observacao}</p>}
              <p className="text-[11px] text-ink-4 leading-relaxed">
                Montado por você no Raio-X. O site confere cada seleção com a estatística oficial do jogo e fecha o bilhete sozinho. Não é pick da IA e não entra no placar público.
              </p>
            </>
          )}
        </div>
      </motion.div>
    </motion.div>,
    document.body,
  )
}
