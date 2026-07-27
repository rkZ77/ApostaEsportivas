import { useEffect, useState, useCallback } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import Navbar from '../components/Navbar'
import BackButton from '../components/BackButton'
import api from '../services/api'
import { fmtBRL } from '../utils/format'
import NumberTicker from '../components/ui/NumberTicker'

export default function BancaSaque() {
  const [current, setCurrent]         = useState(0)
  const [withdrawals, setWithdrawals] = useState<any[]>([])
  const [loading, setLoading]         = useState(true)

  const [amount, setAmount] = useState('')
  const [err,    setErr]    = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    Promise.all([
      api.get('/banca/summary'),
      api.get('/banca/withdrawals', { params: { limit: 100 } }),
    ])
      .then(([s, w]) => {
        setCurrent(s.data.bankroll_current ?? 0)
        setWithdrawals(w.data ?? [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const amountNum = parseFloat(amount.replace(',', '.')) || 0
  const newBanca  = current - amountNum

  const handleSave = async () => {
    setErr('')
    if (!amountNum || amountNum <= 0) { setErr('Informe um valor maior que zero.'); return }
    if (amountNum > current) { setErr('Você não pode sacar mais do que tem na banca.'); return }
    setSaving(true)
    try {
      const { data } = await api.post('/banca/withdraw', { amount: amountNum })
      setCurrent(data.bankroll_start)
      setAmount('')
      load()
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-2xl mx-auto px-4 py-4 flex items-center gap-3">
          <BackButton to="/banca" />
          <div>
            <h1 className="text-base font-black text-white">Sacar da banca</h1>
            <p className="text-zinc-500 text-xs">O valor sai da sua banca e fica registrado no histórico</p>
          </div>
        </div>
      </div>

      <main className="max-w-2xl mx-auto px-4 py-6">
        {loading ? (
          <div className="card p-16 flex items-center justify-center">
            <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-6">
            <div className="card p-5">
              <p className="text-xs text-zinc-500 uppercase font-semibold mb-1">Banca atual</p>
              <NumberTicker value={current} formatter={fmtBRL} className="font-mono text-3xl font-black text-white" />
            </div>

            <div className="card p-5">
              <label className="text-xs text-zinc-500 block mb-1.5">Quanto você quer sacar? (R$)</label>
              <input
                type="number" min="0.01" step="0.01" value={amount}
                onChange={e => setAmount(e.target.value)}
                className="input w-full" placeholder="Ex: 500" autoFocus
              />

              <AnimatePresence>
              {amountNum > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div className="mt-3 bg-zinc-800/50 rounded-lg px-3 py-2.5 text-xs flex items-center justify-between">
                    <span className="text-zinc-400">Banca depois do saque</span>
                    <NumberTicker value={newBanca} formatter={fmtBRL} className={`font-black ${newBanca < 0 ? 'text-red-400' : 'text-white'}`} />
                  </div>
                </motion.div>
              )}
              </AnimatePresence>

              {err && <p className="text-red-400 text-xs mt-3">{err}</p>}

              <button
                onClick={handleSave}
                disabled={saving || !amountNum || amountNum > current}
                className="btn-primary w-full py-2.5 text-sm mt-4 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {saving ? 'Salvando...' : 'Confirmar saque'}
              </button>
            </div>

            <div className="card overflow-hidden">
              <div className="px-5 py-3 border-b border-zinc-800">
                <span className="text-xs font-bold text-zinc-500 uppercase">Histórico de saques</span>
              </div>
              {withdrawals.length === 0 ? (
                <p className="text-zinc-600 text-sm px-5 py-8 text-center">Nenhum saque ainda</p>
              ) : (
                <div className="divide-y divide-zinc-800/60">
                  {withdrawals.map(w => (
                    <div key={w.id} className="flex items-center gap-3 px-5 py-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-bold text-white">− {fmtBRL(w.amount)}</p>
                        <p className="text-[11px] text-zinc-500 mt-0.5">
                          {new Date(w.created_at).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                        </p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-[10px] text-zinc-600">de {fmtBRL(w.bankroll_before)} pra {fmtBRL(w.bankroll_after)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
