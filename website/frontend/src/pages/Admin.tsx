import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'

interface User {
  id: number
  name: string
  email: string
  plan: string
  subscription_type: string | null
  active: boolean
  expires_at: string | null
  created_at: string
}

const SUBSCRIPTION_TYPES = [
  { value: '',           label: '—'          },
  { value: 'mensal',     label: 'Mensal'     },
  { value: 'trimestral', label: 'Trimestral' },
  { value: 'semestral',  label: 'Semestral'  },
  { value: 'anual',      label: 'Anual'      },
]

const PLAN_FILTER = ['todos', 'free', 'vip', 'admin'] as const
type PlanFilter = typeof PLAN_FILTER[number]

export default function Admin() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const [users, setUsers] = useState<User[]>([])
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [search, setSearch] = useState('')
  const [planFilter, setPlanFilter] = useState<PlanFilter>('todos')
  const [newUser, setNewUser] = useState({ name: '', email: '', password: '', plan: 'free' })

  useEffect(() => {
    if (!isAdmin) { navigate('/picks'); return }
    Promise.all([api.get('/admin/users'), api.get('/admin/stats')])
      .then(([u, s]) => { setUsers(u.data); setStats(s.data) })
      .finally(() => setLoading(false))
  }, [isAdmin])

  const setPlan = async (id: number, plan: string) => {
    await api.put(`/admin/users/${id}`, { plan })
    setUsers(u => u.map(x => x.id === id ? { ...x, plan } : x))
  }

  const setSubscriptionType = async (id: number, subscription_type: string) => {
    await api.put(`/admin/users/${id}`, { subscription_type: subscription_type || null })
    setUsers(u => u.map(x => x.id === id ? { ...x, subscription_type: subscription_type || null } : x))
  }

  const setExpiresAt = async (id: number, expires_at: string) => {
    await api.put(`/admin/users/${id}`, { expires_at: expires_at || null })
    setUsers(u => u.map(x => x.id === id ? { ...x, expires_at: expires_at || null } : x))
  }

  const toggleActive = async (id: number, active: boolean) => {
    await api.put(`/admin/users/${id}`, { active: !active })
    setUsers(u => u.map(x => x.id === id ? { ...x, active: !active } : x))
  }

  const deleteUser = async (id: number, name: string) => {
    if (!window.confirm(`Deletar usuário "${name}"? Esta ação é irreversível.`)) return
    try {
      await api.delete(`/admin/users/${id}`)
      setUsers(u => u.filter(x => x.id !== id))
      if (stats) setStats((s: any) => ({ ...s, total: s.total - 1 }))
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Erro ao deletar usuário')
    }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const { data } = await api.post('/admin/users', newUser)
      setUsers(u => [data, ...u])
      setNewUser({ name: '', email: '', password: '', plan: 'free' })
      setCreating(false)
    } catch (err: any) { alert(err.response?.data?.detail || 'Erro') }
  }

  const filtered = users.filter(u => {
    const q = search.toLowerCase()
    const matchSearch = !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    const matchPlan = planFilter === 'todos' || u.plan === planFilter
    return matchSearch && matchPlan
  })

  if (loading) return (
    <><Navbar /><div className="min-h-screen flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
    </div></>
  )

  return (
    <div className="min-h-screen bg-black">
      <Navbar />
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
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

      <main className="max-w-6xl mx-auto px-4 py-8">
        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-4 gap-4 mb-8">
            {[
              { label: 'Total',  value: stats.total,  color: 'text-white' },
              { label: 'VIP',    value: stats.vip,    color: 'text-yellow-400' },
              { label: 'Free',   value: stats.free,   color: 'text-zinc-400' },
              { label: 'Ativos', value: stats.ativos, color: 'text-green-500' },
            ].map(({ label, value, color }) => (
              <div key={label} className="stat-card text-center">
                <div className={`text-4xl font-black ${color}`}>{value}</div>
                <div className="text-xs text-zinc-500 uppercase tracking-wider">{label}</div>
              </div>
            ))}
          </div>
        )}

        {/* Criar usuário */}
        {creating && (
          <form onSubmit={handleCreate} className="card p-5 mb-6 grid grid-cols-1 md:grid-cols-5 gap-3">
            <input className="input" placeholder="Nome" value={newUser.name} onChange={e => setNewUser(v => ({ ...v, name: e.target.value }))} required />
            <input className="input" placeholder="Email" type="email" value={newUser.email} onChange={e => setNewUser(v => ({ ...v, email: e.target.value }))} required />
            <input className="input" placeholder="Senha" type="password" value={newUser.password} onChange={e => setNewUser(v => ({ ...v, password: e.target.value }))} required />
            <select className="input" value={newUser.plan} onChange={e => setNewUser(v => ({ ...v, plan: e.target.value }))}>
              <option value="free">Free</option>
              <option value="vip">VIP</option>
              <option value="admin">Admin</option>
            </select>
            <button type="submit" className="btn-primary">Criar</button>
          </form>
        )}

        {/* Busca + filtro por plano */}
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <input
            className="input flex-1 text-sm"
            placeholder="Buscar por nome ou email..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <div className="flex gap-1">
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

        {/* Tabela */}
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800">
                  {['Usuário', 'Email', 'Plano', 'Tipo', 'Validade VIP', 'Status', 'Cadastro', 'Ações'].map(h => (
                    <th key={h} className="text-left text-zinc-500 font-medium px-4 py-3 uppercase text-xs tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(u => (
                  <tr key={u.id} className="border-b border-zinc-800/50 hover:bg-zinc-900/50 transition-colors">
                    <td className="px-4 py-3 text-white font-semibold whitespace-nowrap">{u.name}</td>
                    <td className="px-4 py-3 text-zinc-400 text-xs">{u.email}</td>
                    <td className="px-4 py-3">
                      <span className={u.plan === 'vip' ? 'badge-vip' : u.plan === 'admin' ? 'badge-admin' : 'badge-free'}>
                        {u.plan.toUpperCase()}
                      </span>
                    </td>
                    {/* Tipo de plano */}
                    <td className="px-4 py-3">
                      <select
                        value={u.subscription_type ?? ''}
                        onChange={e => setSubscriptionType(u.id, e.target.value)}
                        className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-xs text-zinc-300 focus:outline-none focus:border-green-500"
                      >
                        {SUBSCRIPTION_TYPES.map(t => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <input
                        type="date"
                        value={u.expires_at ? u.expires_at.slice(0, 10) : ''}
                        onChange={e => setExpiresAt(u.id, e.target.value)}
                        className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-xs text-zinc-300 focus:outline-none focus:border-green-500 w-36"
                        title="Data de expiração VIP"
                      />
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
                        <button
                          onClick={() => deleteUser(u.id, u.name)}
                          className="text-xs px-2 py-1 rounded-lg border border-zinc-800 text-zinc-600 hover:border-red-800 hover:text-red-500 transition-colors"
                          title="Deletar usuário"
                        >
                          ×
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-zinc-600 text-sm">
                      Nenhum usuário encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  )
}
