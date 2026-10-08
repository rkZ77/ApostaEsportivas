import { useCallback, useEffect, useState } from 'react'
import { CalendarClock, ChevronDown, Play } from 'lucide-react'
import api from '../services/api'
import { Panel, PanelHead } from './ui'

/*
 * O que roda sozinho (08/10/2026, pedido do usuário).
 *
 * O agendador voltou com as travas que faltaram em 01/08: só no ambiente de
 * produção do Railway, teto de cota da API e uma execução por dia. Esta caixa
 * responde "rodou hoje?" sem precisar abrir log, e mostra a última saída de
 * cada medição do motor, que antes só existia rodando script no terminal.
 */

interface Execucao {
  origem?: string; iniciado_em?: string; terminado_em?: string | null
  status?: string; detalhe?: string | null
}
interface Tarefa { nome: string; rotulo: string; inicio: string; gasta_api: boolean; hoje: Execucao | null }
interface Medicao { nome: string; rotulo: string; dia?: string; saida?: string; ok?: boolean; criado_em?: string }
interface Estado { ligado: boolean; teto_cota: number; tarefas: Tarefa[]; medicoes: Medicao[] }

const COR: Record<string, string> = {
  ok: 'text-green-400 bg-green-500/10 border-green-500/25',
  rodando: 'text-blue-300 bg-blue-500/10 border-blue-500/25',
  erro: 'text-red-400 bg-red-500/10 border-red-500/25',
  pulada: 'text-yellow-300 bg-yellow-500/10 border-yellow-500/25',
}

const hora = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''

/** A linha de veredito de cada script ("=== Leitura ===" e o que vem depois). */
export function leituraDaMedicao(saida?: string): string | null {
  if (!saida) return null
  const i = saida.lastIndexOf('=== Leitura ===')
  if (i < 0) return null
  return saida.slice(i + '=== Leitura ==='.length).trim().split('\n').map(l => l.trim()).filter(Boolean).join(' ')
}

export default function AdminAgendador() {
  const [estado, setEstado] = useState<Estado | null>(null)
  const [erro, setErro] = useState(false)
  const [aberta, setAberta] = useState<string | null>(null)
  const [rodando, setRodando] = useState(false)

  const carregar = useCallback(() => {
    api.get('/admin/agendador').then(r => { setEstado(r.data); setErro(false) }).catch(() => setErro(true))
  }, [])
  useEffect(() => { carregar() }, [carregar])

  const medirAgora = async () => {
    setRodando(true)
    try {
      await api.post('/admin/agendador/medicoes')
      setTimeout(() => { carregar(); setRodando(false) }, 20_000)
    } catch {
      setRodando(false)
    }
  }

  if (erro) return null
  return (
    <Panel>
      <PanelHead
        label="O que roda sozinho"
        meta={estado ? (estado.ligado ? `ligado · teto de cota ${Math.round(estado.teto_cota * 100)}%` : 'desligado neste ambiente') : ''}
      />
      {!estado ? (
        <div className="p-4 text-xs text-ink-4">Carregando…</div>
      ) : (
        <>
          {!estado.ligado && (
            <p className="px-4 pt-3 text-[11px] text-ink-3 leading-relaxed">
              Só liga no ambiente de produção do Railway. Aqui os horários abaixo são o plano, não o que aconteceu.
              Para desligar em produção sem deploy: variável <code className="text-ink-2">AGENDADOR=off</code>.
            </p>
          )}
          <ul className="divide-y divide-line">
            {estado.tarefas.map(t => {
              const st = t.hoje?.status
              return (
                <li key={t.nome} className="px-4 py-2.5 flex items-center gap-3">
                  <CalendarClock className="w-4 h-4 text-ink-4 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-ink-1 truncate">{t.rotulo}</p>
                    <p className="text-[10px] text-ink-4 truncate">
                      {t.inicio}{t.gasta_api ? ' · gasta API' : ' · só banco'}
                      {t.hoje?.origem === 'manual' && ' · rodado no botão'}
                      {t.hoje?.detalhe && ` · ${t.hoje.detalhe}`}
                    </p>
                  </div>
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded border shrink-0 ${st ? COR[st] ?? COR.rodando : 'text-ink-4 border-line'}`}>
                    {st ? `${st}${t.hoje?.terminado_em ? ` ${hora(t.hoje.terminado_em)}` : ''}` : 'hoje ainda não'}
                  </span>
                </li>
              )
            })}
          </ul>

          <div className="px-4 py-3 border-t border-line flex items-center justify-between gap-3">
            <p className="text-xs font-semibold text-ink-2">Medições do motor</p>
            <button onClick={medirAgora} disabled={rodando}
              className="flex items-center gap-1.5 text-xs font-bold text-accent-ink bg-accent/10 border border-accent/40 rounded-md px-3 py-1.5 disabled:opacity-50">
              <Play className="w-3.5 h-3.5" /> {rodando ? 'Rodando…' : 'Rodar agora'}
            </button>
          </div>
          <ul className="divide-y divide-line border-t border-line">
            {estado.medicoes.map(m => {
              const leitura = leituraDaMedicao(m.saida)
              const alerta = !!leitura && /desligar|perde|pior|n[aã]o ligar/i.test(leitura)
              return (
                <li key={m.nome}>
                  <button onClick={() => setAberta(a => (a === m.nome ? null : m.nome))}
                    className="w-full px-4 py-2.5 flex items-center gap-3 text-left hover:bg-surface-2/40">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-ink-1">{m.rotulo}</p>
                      <p className={`text-[10px] leading-relaxed ${alerta ? 'text-red-400 font-semibold' : 'text-ink-3'}`}>
                        {m.saida == null ? 'ainda não rodou' : leitura ?? (m.ok ? 'sem veredito no texto' : 'falhou, abra para ver')}
                      </p>
                    </div>
                    {m.dia && <span className="text-[10px] text-ink-4 shrink-0">{m.dia}</span>}
                    <ChevronDown className={`w-4 h-4 text-ink-4 shrink-0 transition-transform ${aberta === m.nome ? 'rotate-180' : ''}`} />
                  </button>
                  {aberta === m.nome && m.saida && (
                    <pre className="mx-4 mb-3 p-3 rounded-md bg-surface-0 border border-line text-[10px] leading-snug text-ink-2 overflow-x-auto max-h-96">
                      {m.saida}
                    </pre>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </Panel>
  )
}
