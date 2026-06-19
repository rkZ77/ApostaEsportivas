import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

interface User {
  id: number
  name: string
  email: string
  phone?: string | null
  plan: string
  subscription_type: string | null
  active: boolean
  expires_at: string | null
  created_at: string
  bankroll_current: number | null
  unit_value: number | null
}

interface Stats {
  total: number
  vip: number
  trial: number
  free: number
  ativos: number
  vip_expirando: number
  picks_hoje: {
    vip_picks: number
    alavancagem: number
    dica: number
    multiplas: number
  }
}

const SUBSCRIPTION_TYPES = [
  { value: '',           label: ''          },
  { value: 'mensal',     label: 'Mensal'     },
  { value: 'trimestral', label: 'Trimestral' },
  { value: 'semestral',  label: 'Semestral'  },
  { value: 'anual',      label: 'Anual'      },
]

const PLAN_FILTER = ['todos', 'free', 'trial', 'vip', 'admin'] as const
type PlanFilter = typeof PLAN_FILTER[number]

const planBadge = (plan: string) => {
  if (plan === 'vip')   return 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/30'
  if (plan === 'trial') return 'bg-amber-400/10 text-amber-400 border border-amber-400/30'
  if (plan === 'admin') return 'bg-purple-500/10 text-purple-400 border border-purple-500/30'
  return 'bg-zinc-800 text-zinc-400 border border-zinc-700'
}

const expiryWarning = (expires_at: string | null) => {
  if (!expires_at) return null
  const days = Math.ceil((new Date(expires_at).getTime() - Date.now()) / 86400000)
  if (days < 0)  return <span className="text-xs text-red-400 font-semibold">Expirado</span>
  if (days <= 7) return <span className="text-xs text-orange-400 font-semibold">{days}d</span>
  return null
}

export default function Admin() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const [users, setUsers]     = useState<User[]>([])
  const [stats, setStats]     = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [search, setSearch]   = useState('')
  const [planFilter, setPlanFilter] = useState<PlanFilter>('todos')
  const [newUser, setNewUser] = useState({ name: '', email: '', password: '', plan: 'free' })
  const [runningCmd, setRunningCmd] = useState<string | null>(null)
  const [pipelineStatus, setPipelineStatus] = useState<Record<string, { status: string; started_at: string | null; finished_at: string | null; error: string | null; log: string | null }>>({})
  const [expandedLog, setExpandedLog] = useState<string | null>(null)
  const [payments, setPayments] = useState<any[]>([])
  const [paymentsLoading, setPaymentsLoading] = useState(false)
  const [paymentsPage, setPaymentsPage] = useState(0)
  const [usersPage, setUsersPage] = useState(0)
  const [pickSearch, setPickSearch] = useState('')
  const [pickDateFrom, setPickDateFrom] = useState('')
  const [pickDateTo, setPickDateTo] = useState('')
  const [pickTypeFilter, setPickTypeFilter] = useState('')
  const [pickResults, setPickResults] = useState<any[]>([])
  const [pickSearching, setPickSearching] = useState(false)
  const [settingResult, setSettingResult] = useState<number | null>(null)
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)
  const USERS_PER_PAGE = 15
  const PAYMENTS_PER_PAGE = 10

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 3000)
  }

  const PIPELINE_ACTIONS = [
    { command: 'atualizar_jogos',      label: 'Atualizar Jogos'      },
    { command: 'capturar_odds',        label: 'Capturar Odds'        },
    { command: 'gerar_vip',            label: 'Gerar VIP'            },
    { command: 'gerar_free',           label: 'Gerar Free'           },
    { command: 'gerar_multipla',       label: 'Gerar Múltipla'       },
    { command: 'gerar_alavancagem',    label: 'Gerar Alavancagem'    },
    { command: 'atualizar_resultados', label: 'Atualizar Resultados' },
  ] as const

  useEffect(() => {
    const poll = () => api.get('/admin/pipeline-status').then(r => setPipelineStatus(r.data)).catch(() => {})
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  const runPipeline = async (command: string) => {
    setRunningCmd(command)
    try {
      await api.post('/admin/run-pipeline', { command })
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'Erro ao iniciar pipeline', false)
    } finally {
      setRunningCmd(null)
    }
  }

  const reload = () => {
    setLoading(true)
    api.get('/admin/users')
      .then(u => setUsers(u.data))
      .catch(() => setUsers([]))
      .finally(() => setLoading(false))
    api.get('/admin/stats')
      .then(s => setStats(s.data))
      .catch(() => {})
  }

  useEffect(() => {
    if (!isAdmin) { navigate('/picks'); return }
    reload()
    setPaymentsLoading(true)
    api.get('/admin/payments').then(r => setPayments(r.data)).catch(() => {}).finally(() => setPaymentsLoading(false))
  }, [isAdmin])

  const setPlan = async (id: number, plan: string) => {
    try {
      await api.put(`/admin/users/${id}`, { plan })
      setUsers(u => u.map(x => x.id === id ? { ...x, plan } : x))
      showToast('Plano atualizado')
    } catch { showToast('Erro ao atualizar plano', false) }
  }

  const setSubscriptionType = async (id: number, subscription_type: string) => {
    try {
      await api.put(`/admin/users/${id}`, { subscription_type: subscription_type || null })
      setUsers(u => u.map(x => x.id === id ? { ...x, subscription_type: subscription_type || null } : x))
      showToast('Tipo salvo')
    } catch { showToast('Erro ao salvar tipo', false) }
  }

  const setExpiresAt = async (id: number, expires_at: string) => {
    try {
      await api.put(`/admin/users/${id}`, { expires_at: expires_at || null })
      setUsers(u => u.map(x => x.id === id ? { ...x, expires_at: expires_at || null } : x))
      showToast(expires_at ? 'Validade salva' : 'Validade removida')
    } catch { showToast('Erro ao salvar validade', false) }
  }

  const toggleActive = async (id: number, active: boolean) => {
    try {
      await api.put(`/admin/users/${id}`, { active: !active })
      setUsers(u => u.map(x => x.id === id ? { ...x, active: !active } : x))
      showToast(active ? 'Usuário desativado' : 'Usuário ativado')
    } catch { showToast('Erro ao alterar status', false) }
  }

  const deleteUser = async (id: number, name: string) => {
    if (!window.confirm(`Desativar usuário "${name}"?`)) return
    try {
      await api.delete(`/admin/users/${id}`)
      setUsers(u => u.map(x => x.id === id ? { ...x, active: false } : x))
      showToast('Usuário desativado')
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'Erro ao desativar usuário', false)
    }
  }

  const searchPicks = async () => {
    setPickSearching(true)
    try {
      const params: Record<string, string> = {}
      if (pickSearch)     params.q         = pickSearch
      if (pickDateFrom)   params.date_from = pickDateFrom
      if (pickDateTo)     params.date_to   = pickDateTo
      if (pickTypeFilter) params.pick_type = pickTypeFilter
      const r = await api.get('/admin/picks/search', { params })
      setPickResults(r.data)
    } catch { showToast('Erro ao buscar picks', false) }
    finally { setPickSearching(false) }
  }

  const setPickResult = async (pick: any, result: string) => {
    setSettingResult(pick.id)
    try {
      await api.post('/admin/picks/set-result', {
        pick_type: pick.pick_type,
        pick_id: pick.id,
        result: result === 'pending' ? null : result,
      })
      setPickResults(prev => prev.map(p =>
        p.id === pick.id && p.pick_type === pick.pick_type
          ? { ...p, result: result === 'pending' ? null : result }
          : p
      ))
      showToast(`Resultado alterado para ${result === 'pending' ? 'Pendente' : result}`)
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'Erro ao alterar resultado', false)
    } finally { setSettingResult(null) }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const { data } = await api.post('/admin/users', newUser)
      setUsers(u => [data, ...u])
      setNewUser({ name: '', email: '', password: '', plan: 'free' })
      setCreating(false)
      showToast('Usuário criado')
      reload()
    } catch (err: any) { showToast(err.response?.data?.detail || 'Erro ao criar usuário', false) }
  }

  const filtered = users.filter(u => {
    const q = search.toLowerCase()
    const matchSearch = !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    const matchPlan = planFilter === 'todos' || u.plan === planFilter
    return matchSearch && matchPlan
  })
  const usersTotalPages = Math.ceil(filtered.length / USERS_PER_PAGE)
  const usersPageSafe = Math.min(usersPage, Math.max(0, usersTotalPages - 1))
  const filteredPage = filtered.slice(usersPageSafe * USERS_PER_PAGE, (usersPageSafe + 1) * USERS_PER_PAGE)

  const paymentsTotalPages = Math.ceil(payments.length / PAYMENTS_PER_PAGE)
  const paymentsPageSafe = Math.min(paymentsPage, Math.max(0, paymentsTotalPages - 1))
  const paymentsPage_ = payments.slice(paymentsPageSafe * PAYMENTS_PER_PAGE, (paymentsPageSafe + 1) * PAYMENTS_PER_PAGE)

  if (loading) return (
    <><Navbar /><div className="min-h-screen flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
    </div></>
  )

  return (
    <div className="min-h-screen bg-black flex flex-col">
      {toast && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-[9999] px-5 py-3 rounded-xl shadow-lg text-sm font-semibold whitespace-nowrap transition-all ${toast.ok ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}>
          {toast.msg}
        </div>
      )}
      <Navbar />

      {/* Header */}
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/picks')} className="text-zinc-500 hover:text-white transition-colors text-lg leading-none">←</button>
            <div>
              <h1 className="text-xl font-black text-white">Painel Admin</h1>
              <p className="text-zinc-500 text-sm">Gerenciar usuários e planos</p>
            </div>
          </div>
          <button onClick={() => setCreating(v => !v)} className="btn-primary text-sm px-4 py-2">
            + Novo usuário
          </button>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-4 py-6 flex-1 w-full">

        {/* Pipeline */}
        <div className="card p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Pipeline</h2>
            {(() => {
              const s = pipelineStatus['tudo']
              const isTudoRunning = runningCmd === 'tudo' || s?.status === 'running'
              return (
                <div className="flex flex-col items-end gap-1">
                  <button
                    onClick={() => runPipeline('tudo')}
                    disabled={runningCmd !== null || isTudoRunning}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-green-500/15 border border-green-500/30 text-green-400 hover:bg-green-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed font-semibold"
                  >
                    {isTudoRunning
                      ? <><span className="w-3 h-3 border border-green-500/50 border-t-green-400 rounded-full animate-spin" /> Rodando tudo...</>
                      : '▶ Rodar Tudo (jogos → odds → picks)'}
                  </button>
                  {s && (
                    <span
                      className={`text-[10px] cursor-pointer underline ${s.status === 'error' ? 'text-red-500' : s.status === 'ok' ? 'text-zinc-500' : 'text-zinc-600'}`}
                      onClick={() => setExpandedLog(expandedLog === 'tudo' ? null : 'tudo')}
                    >
                      {s.status === 'running' ? `rodando: ${(s as any).log || '...'}` : `${s.status} ${s.finished_at}`}
                    </span>
                  )}
                  {expandedLog === 'tudo' && (s?.error || s?.log) && (
                    <pre className={`text-[10px] bg-zinc-900 rounded p-2 max-w-sm whitespace-pre-wrap break-all ${s.status === 'error' ? 'text-red-400' : 'text-zinc-400'}`}>
                      {s.error || s.log}
                    </pre>
                  )}
                </div>
              )
            })()}
          </div>
          <div className="flex flex-wrap gap-2">
            {PIPELINE_ACTIONS.map(({ command, label }) => {
              const s = pipelineStatus[command]
              const isRunning = runningCmd === command || s?.status === 'running'
              const dot = !s ? null
                : s.status === 'running' ? <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
                : s.status === 'ok'      ? <span className="w-2 h-2 rounded-full bg-green-500" />
                :                          <span className="w-2 h-2 rounded-full bg-red-500" />
              return (
                <div key={command} className="flex flex-col items-start gap-1">
                  <button
                    onClick={() => runPipeline(command)}
                    disabled={runningCmd !== null || isRunning}
                    className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {isRunning && <span className="w-3 h-3 border border-zinc-500 border-t-white rounded-full animate-spin" />}
                    {dot && !isRunning && dot}
                    {label}
                  </button>
                  {s && (
                    <span
                      className={`text-[10px] pl-1 cursor-pointer underline ${s.status === 'error' ? 'text-red-500' : s.status === 'ok' ? 'text-zinc-500' : 'text-zinc-600'}`}
                      onClick={() => setExpandedLog(expandedLog === command ? null : command)}
                    >
                      {s.status === 'running' ? `rodando desde ${s.started_at}` : `${s.status} ${s.finished_at}`}
                    </span>
                  )}
                  {expandedLog === command && (s?.error || s?.log) && (
                    <pre className={`text-[10px] bg-zinc-900 rounded p-2 max-w-xs whitespace-pre-wrap break-all mt-1 ${s.status === 'error' ? 'text-red-400' : 'text-zinc-400'}`}>
                      {s.error || s.log}
                    </pre>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Stats — usuários */}
        {stats && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
              {[
                { label: 'Total',         value: stats.total,         color: 'text-white' },
                { label: 'VIP',           value: stats.vip,           color: 'text-yellow-400' },
                { label: 'Trial',         value: stats.trial,         color: 'text-blue-400' },
                { label: 'Free',          value: stats.free,          color: 'text-zinc-400' },
                { label: 'Ativos',        value: stats.ativos,        color: 'text-green-500' },
                { label: 'VIP expirando', value: stats.vip_expirando, color: stats.vip_expirando > 0 ? 'text-orange-400' : 'text-zinc-600' },
              ].map(({ label, value, color }) => (
                <div key={label} className="stat-card text-center py-3">
                  <div className={`text-3xl font-black ${color}`}>{value}</div>
                  <div className="text-xs text-zinc-500 uppercase tracking-wider mt-1">{label}</div>
                </div>
              ))}
            </div>

            {/* Picks de hoje */}
            <div className="card p-4 mb-6">
              <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Picks de hoje</h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: 'VIP',         value: stats.picks_hoje.vip_picks,   target: '' },
                  { label: 'Alavancagem', value: stats.picks_hoje.alavancagem, target: 1   },
                  { label: 'Dica do Dia', value: stats.picks_hoje.dica,        target: 1   },
                  { label: 'Múltiplas',   value: stats.picks_hoje.multiplas,   target: 1   },
                ].map(({ label, value, target }) => {
                  const ok = target === '' ? value > 0 : value >= (target as number)
                  return (
                    <div key={label} className="flex items-center gap-3 bg-zinc-900 rounded-xl px-4 py-3">
                      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-green-500' : 'bg-zinc-700'}`} />
                      <div>
                        <div className="text-white font-bold text-lg leading-none">{value}</div>
                        <div className="text-zinc-500 text-xs mt-0.5">{label}</div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}

        {/* Pagamentos */}
        <div className="card overflow-hidden mb-6">
          <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between gap-3 flex-wrap">
            <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Pagamentos</h2>
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-600">{payments.length} registro(s)</span>
              <button
                onClick={async () => {
                  const id = prompt('ID do pagamento MercadoPago:')
                  if (!id) return
                  try {
                    const r = await api.post('/admin/sync-payment', { mp_payment_id: id })
                    showToast(`VIP ativado: ${r.data.user.name} · ${r.data.plan}`)
                    api.get('/admin/payments').then(r2 => setPayments(r2.data)).catch(() => {})
                  } catch (e: any) {
                    showToast('Erro: ' + (e.response?.data?.detail || e.message), false)
                  }
                }}
                className="px-2 py-1 text-xs rounded border border-zinc-700 text-zinc-400 hover:text-white hover:border-green-600 transition-colors"
              >
                + Reprocessar pagamento
              </button>
            </div>
          </div>
          {paymentsLoading ? (
            <div className="p-6 flex justify-center"><div className="w-5 h-5 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" /></div>
          ) : payments.length === 0 ? (
            <p className="text-center text-zinc-600 text-sm py-6">Nenhum pagamento registrado.</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800">
                      {['Data', 'Usuário', 'Plano', 'Valor', 'Método', 'Status', 'Expira'].map(h => (
                        <th key={h} className="text-left text-zinc-500 font-medium px-4 py-2 uppercase tracking-wider whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {paymentsPage_.map((p, i) => (
                      <tr key={i} className="border-b border-zinc-800/40 hover:bg-zinc-900/40">
                        <td className="px-4 py-2 text-zinc-500 whitespace-nowrap">{new Date(p.created_at).toLocaleDateString('pt-BR')}</td>
                        <td className="px-4 py-2">
                          <div className="text-white font-medium">{p.user_name}</div>
                          <div className="text-zinc-600">{p.user_email}</div>
                        </td>
                        <td className="px-4 py-2 capitalize text-zinc-300">{p.plan_key}</td>
                        <td className="px-4 py-2 text-green-400 font-semibold">R${Number(p.amount).toFixed(2)}</td>
                        <td className="px-4 py-2 text-zinc-400">{p.payment_method ?? ''}</td>
                        <td className="px-4 py-2">
                          <span className={`px-2 py-0.5 rounded font-medium ${p.status === 'approved' ? 'bg-green-500/10 text-green-400' : 'bg-zinc-800 text-zinc-500'}`}>
                            {p.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-zinc-500 whitespace-nowrap">{p.expires_at ? new Date(p.expires_at).toLocaleDateString('pt-BR') : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {paymentsTotalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-zinc-800">
                  <span className="text-xs text-zinc-600">Página {paymentsPageSafe + 1} de {paymentsTotalPages}</span>
                  <div className="flex gap-2">
                    <button onClick={() => setPaymentsPage(p => Math.max(0, p - 1))} disabled={paymentsPageSafe === 0} className="px-3 py-1 text-xs rounded border border-zinc-700 text-zinc-400 hover:text-white disabled:opacity-30">← Ant</button>
                    <button onClick={() => setPaymentsPage(p => Math.min(paymentsTotalPages - 1, p + 1))} disabled={paymentsPageSafe === paymentsTotalPages - 1} className="px-3 py-1 text-xs rounded border border-zinc-700 text-zinc-400 hover:text-white disabled:opacity-30">Próx →</button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Corrigir resultado de pick */}
        <div className="card p-4 mb-6">
          <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Corrigir Resultado de Pick</h2>
          {/* Atalhos rápidos de data */}
          {(() => {
            const brt = (daysAgo = 0) => {
              const d = new Date(new Date().toLocaleString('en-CA', { timeZone: 'America/Sao_Paulo' }))
              d.setDate(d.getDate() - daysAgo)
              return d.toISOString().slice(0, 10)
            }
            const shortcuts = [
              { label: 'Hoje',          from: brt(0),  to: brt(0)  },
              { label: 'Ontem',         from: brt(1),  to: brt(1)  },
              { label: '3 dias',        from: brt(3),  to: brt(0)  },
              { label: 'Semana passada',from: brt(7),  to: brt(0)  },
              { label: '15 dias',       from: brt(15), to: brt(0)  },
            ]
            return (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {shortcuts.map(s => (
                  <button key={s.label}
                    onClick={() => { setPickDateFrom(s.from); setPickDateTo(s.to) }}
                    className={`text-[11px] px-2.5 py-1 rounded-lg border transition-colors touch-manipulation ${pickDateFrom === s.from && pickDateTo === s.to ? 'border-green-500/50 bg-green-500/10 text-green-400' : 'border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200'}`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )
          })()}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">Time</label>
              <input
                className="input text-sm"
                placeholder="Ex: Brasil, Flamengo..."
                value={pickSearch}
                onChange={e => setPickSearch(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchPicks()}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">Tipo</label>
              <select className="input text-sm" value={pickTypeFilter} onChange={e => setPickTypeFilter(e.target.value)}>
                <option value="">Todos</option>
                <option value="vip">VIP</option>
                <option value="free">Free</option>
                <option value="multipla">Múltipla</option>
                <option value="alavancagem">Alavancagem</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">Data de</label>
              <input type="date" className="input text-sm" value={pickDateFrom} onChange={e => setPickDateFrom(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">Data até</label>
              <input type="date" className="input text-sm" value={pickDateTo} onChange={e => setPickDateTo(e.target.value)} />
            </div>
          </div>
          <button onClick={searchPicks} disabled={pickSearching}
            className="w-full btn-primary text-sm py-3 disabled:opacity-40 touch-manipulation mb-3">
            {pickSearching ? 'Buscando...' : 'Buscar Picks'}
          </button>

          {pickResults.length > 0 && (
            <div className="space-y-2 mt-2">
              {pickResults.map((p) => {
                const resultCls: Record<string, string> = {
                  GREEN: 'text-green-400 bg-green-400/10 border-green-500/30',
                  RED: 'text-red-400 bg-red-400/10 border-red-500/30',
                  PUSH: 'text-zinc-400 bg-zinc-700/40 border-zinc-600/30',
                  'HALF-WIN': 'text-teal-400 bg-teal-400/10 border-teal-500/30',
                  'HALF-LOSS': 'text-orange-400 bg-orange-400/10 border-orange-500/30',
                }
                const typeCls: Record<string, string> = {
                  vip: 'text-yellow-400 bg-yellow-400/10', free: 'text-green-400 bg-green-400/10',
                  multipla: 'text-blue-400 bg-blue-400/10', alavancagem: 'text-orange-400 bg-orange-400/10',
                }
                const resCls = p.result ? (resultCls[p.result] ?? 'text-zinc-400 bg-zinc-700/40 border-zinc-600/30') : 'text-zinc-600 bg-zinc-900 border-zinc-800'
                return (
                  <div key={`${p.pick_type}-${p.id}`} className="bg-zinc-900 border border-zinc-800 rounded-xl p-3 flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap min-w-0">
                        <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded ${typeCls[p.pick_type] ?? 'text-zinc-400 bg-zinc-700/40'}`}>{p.pick_type}</span>
                        <span className="text-xs font-semibold text-white truncate">{p.home_team}{p.away_team ? ` vs ${p.away_team}` : ''}</span>
                      </div>
                      <span className="text-[10px] text-zinc-500 shrink-0">{p.match_date ? new Date(p.match_date).toLocaleDateString('pt-BR') : ''}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-black px-2 py-1 rounded border ${resCls}`}>{p.result ?? 'Pendente'}</span>
                      <span className="text-zinc-600 text-xs">·</span>
                      <span className="text-xs text-zinc-500 truncate">{p.market} {p.line}</span>
                    </div>
                    <select
                      disabled={settingResult === p.id}
                      value=""
                      onChange={e => { if (e.target.value) setPickResult(p, e.target.value) }}
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-sm text-zinc-300 focus:outline-none focus:border-green-500 disabled:opacity-40 touch-manipulation"
                    >
                      <option value="">Alterar resultado...</option>
                      <option value="GREEN">GREEN</option>
                      <option value="RED">RED</option>
                      <option value="PUSH">PUSH</option>
                      <option value="HALF-WIN">HALF-WIN</option>
                      <option value="HALF-LOSS">HALF-LOSS</option>
                      <option value="pending">Pendente (limpar)</option>
                    </select>
                  </div>
                )
              })}
            </div>
          )}
          {pickResults.length === 0 && !pickSearching && (pickSearch || pickDateFrom) && (
            <p className="text-zinc-600 text-xs text-center py-4">Nenhum pick encontrado.</p>
          )}
        </div>

        {/* Criar usuário */}
        {creating && (
          <form onSubmit={handleCreate} className="card p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <input className="input" placeholder="Nome" value={newUser.name} onChange={e => setNewUser(v => ({ ...v, name: e.target.value }))} required />
            <input className="input" placeholder="Email" type="email" value={newUser.email} onChange={e => setNewUser(v => ({ ...v, email: e.target.value }))} required />
            <input className="input" placeholder="Senha (min 10 chars, maiúscula, número)" type="password" value={newUser.password} onChange={e => setNewUser(v => ({ ...v, password: e.target.value }))} required />
            <select className="input" value={newUser.plan} onChange={e => setNewUser(v => ({ ...v, plan: e.target.value }))}>
              <option value="free">Free</option>
              <option value="trial">Trial</option>
              <option value="vip">VIP</option>
              <option value="admin">Admin</option>
            </select>
            <div className="flex gap-2">
              <button type="submit" className="btn-primary flex-1">Criar</button>
              <button type="button" onClick={() => setCreating(false)} className="px-3 py-2 rounded-lg border border-zinc-700 text-zinc-400 hover:text-white text-sm transition-colors">✕</button>
            </div>
          </form>
        )}

        {/* Busca + filtro */}
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <input
            className="input flex-1 text-sm"
            placeholder="Buscar por nome ou email..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <div className="flex gap-1 flex-wrap">
            {PLAN_FILTER.map(p => (
              <button
                key={p}
                onClick={() => setPlanFilter(p)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-colors border ${
                  planFilter === p
                    ? 'bg-green-500 border-green-500 text-black'
                    : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'
                }`}
              >
                {p === 'todos' ? 'Todos' : p.toUpperCase()}
              </button>
            ))}
          </div>
          <span className="text-zinc-600 text-xs self-center whitespace-nowrap">{filtered.length} usuário(s)</span>
        </div>

        {/* Tabela — desktop */}
        <div className="card overflow-hidden hidden md:block">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800">
                  {['Usuário', 'WhatsApp', 'Plano', 'Tipo / Validade', 'Banca', 'Status', 'Cadastro', 'Ações'].map(h => (
                    <th key={h} className="text-left text-zinc-500 font-medium px-4 py-3 uppercase text-xs tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredPage.map(u => (
                  <tr key={u.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-white">{u.name}</div>
                      <div className="text-zinc-500 text-xs">{u.email}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-400 whitespace-nowrap">
                      {u.phone
                        ? <span className="text-green-400">{u.phone}</span>
                        : <span className="text-zinc-700">sem número</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-1 rounded-lg font-semibold ${planBadge(u.plan)}`}>
                        {u.plan.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <select
                          value={u.subscription_type ?? ''}
                          onChange={e => setSubscriptionType(u.id, e.target.value)}
                          className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-xs text-zinc-300 focus:outline-none focus:border-green-500"
                        >
                          {SUBSCRIPTION_TYPES.map(t => (
                            <option key={t.value} value={t.value}>{t.label}</option>
                          ))}
                        </select>
                        <div className="flex items-center gap-1">
                          <input
                            type="date"
                            value={u.expires_at ? u.expires_at.slice(0, 10) : ''}
                            onChange={e => setExpiresAt(u.id, e.target.value)}
                            className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-xs text-zinc-300 focus:outline-none focus:border-green-500 w-32"
                          />
                          {expiryWarning(u.expires_at)}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-400">
                      {u.bankroll_current != null
                        ? <><div className="text-white font-semibold">R${u.bankroll_current.toFixed(0)}</div><div className="text-zinc-600">{u.unit_value != null ? `U R$${u.unit_value.toFixed(0)}` : ''}</div></>
                        : null}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-1 rounded-lg font-medium ${u.active ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                        {u.active ? 'Ativo' : 'Inativo'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-zinc-500 text-xs whitespace-nowrap">
                      {new Date(u.created_at).toLocaleDateString('pt-BR')}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2 items-center">
                        <select
                          value={u.plan}
                          onChange={e => setPlan(u.id, e.target.value)}
                          className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none"
                        >
                          <option value="free">Free</option>
                          <option value="trial">Trial</option>
                          <option value="vip">VIP</option>
                          <option value="admin">Admin</option>
                        </select>
                        <button
                          onClick={() => toggleActive(u.id, u.active)}
                          className={`text-xs px-2 py-1 rounded-lg border transition-colors whitespace-nowrap ${
                            u.active
                              ? 'border-red-700 text-red-400 hover:bg-red-900/20'
                              : 'border-green-700 text-green-400 hover:bg-green-900/20'
                          }`}
                        >
                          {u.active ? 'Desativar' : 'Ativar'}
                        </button>
                        {u.active && (
                          <button
                            onClick={() => deleteUser(u.id, u.name)}
                            className="text-xs px-2 py-1 rounded-lg border border-zinc-800 text-zinc-600 hover:border-red-800 hover:text-red-500 transition-colors"
                            title="Desativar usuário"
                          >✕</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {filteredPage.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-zinc-600 text-sm">
                      Nenhum usuário encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {usersTotalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-zinc-800">
                <span className="text-xs text-zinc-600">Página {usersPageSafe + 1} de {usersTotalPages} · {filtered.length} usuário(s)</span>
                <div className="flex gap-2">
                  <button onClick={() => setUsersPage(p => Math.max(0, p - 1))} disabled={usersPageSafe === 0} className="px-3 py-1 text-xs rounded border border-zinc-700 text-zinc-400 hover:text-white disabled:opacity-30">← Ant</button>
                  <button onClick={() => setUsersPage(p => Math.min(usersTotalPages - 1, p + 1))} disabled={usersPageSafe === usersTotalPages - 1} className="px-3 py-1 text-xs rounded border border-zinc-700 text-zinc-400 hover:text-white disabled:opacity-30">Próx →</button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Cards — mobile */}
        <div className="flex flex-col gap-3 md:hidden">
          {filtered.length === 0 && (
            <p className="text-center text-zinc-600 text-sm py-8">Nenhum usuário encontrado.</p>
          )}
          {filteredPage.map(u => (
            <div key={u.id} className="card p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="font-semibold text-white">{u.name}</div>
                  <div className="text-zinc-500 text-xs mt-0.5">{u.email}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-1 rounded-lg font-semibold ${planBadge(u.plan)}`}>
                    {u.plan.toUpperCase()}
                  </span>
                  <span className={`text-xs px-2 py-1 rounded-lg font-medium ${u.active ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                    {u.active ? 'Ativo' : 'Inativo'}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs text-zinc-500 mb-3">
                <div>Tipo: <span className="text-zinc-300">{u.subscription_type ?? ''}</span></div>
                <div className="flex items-center gap-1">
                  Expira: <span className="text-zinc-300">{u.expires_at ? u.expires_at.slice(0, 10) : ''}</span>
                  {expiryWarning(u.expires_at)}
                </div>
                <div>Banca: <span className="text-zinc-300">{u.bankroll_current != null ? `R$${u.bankroll_current.toFixed(0)}` : ''}</span></div>
                <div>Cadastro: <span className="text-zinc-300">{new Date(u.created_at).toLocaleDateString('pt-BR')}</span></div>
              </div>

              <div className="flex gap-2 flex-wrap">
                <select
                  value={u.plan}
                  onChange={e => setPlan(u.id, e.target.value)}
                  className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none flex-1"
                >
                  <option value="free">Free</option>
                  <option value="trial">Trial</option>
                  <option value="vip">VIP</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  onClick={() => toggleActive(u.id, u.active)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                    u.active ? 'border-red-700 text-red-400' : 'border-green-700 text-green-400'
                  }`}
                >
                  {u.active ? 'Desativar' : 'Ativar'}
                </button>
              </div>
            </div>
          ))}
        </div>

      </main>
      <Footer />
    </div>
  )
}
