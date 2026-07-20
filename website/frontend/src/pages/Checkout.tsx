import { useState, useEffect } from 'react'
import { CheckCircle, XCircle, Check, Clock } from 'lucide-react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'
import BackButton from '../components/BackButton'

interface Plan {
  id: string
  label: string
  price: number
  period: string
  pricePerMonth: number
  savings?: string
  popular?: boolean
}

const PLANS: Plan[] = [
  { id: 'mensal',     label: 'Mensal',     price: 39.90,  period: '1 mês',    pricePerMonth: 39.90 },
  { id: 'trimestral', label: 'Trimestral', price: 99.90,  period: '3 meses',  pricePerMonth: 33.30, savings: 'Economize 17%', popular: true },
  { id: 'semestral',  label: 'Semestral',  price: 199.90, period: '6 meses',  pricePerMonth: 33.32, savings: 'Economize 17%' },
  { id: 'anual',      label: 'Anual',      price: 359.90, period: '12 meses', pricePerMonth: 29.99, savings: 'Economize 25%' },
]

function SuccessPage() {
  const navigate = useNavigate()
  const { refreshUser } = useAuth()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let attempts = 0
    const MAX = 15
    let cancelled = false

    const poll = async () => {
      if (cancelled) return
      try {
        // Busca o plano direto da API para evitar stale closure
        const { data } = await api.get('/auth/me')
        await refreshUser()
        if (data.plan === 'vip' || data.plan === 'admin') {
          setReady(true)
          return
        }
      } catch { /* ignora */ }
      attempts++
      if (attempts >= MAX) { setReady(true); return }
      setTimeout(poll, 2000)
    }

    // Primeira tentativa após 2s (tempo mínimo para webhook chegar)
    const t = setTimeout(poll, 2000)
    return () => { cancelled = true; clearTimeout(t) }
  }, [])

  return (
    <div className="min-h-screen bg-black flex items-center justify-center px-4">
      <div className="text-center space-y-4">
        <div className="w-20 h-20 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mx-auto">
          <CheckCircle className="w-10 h-10 text-green-400" />
        </div>
        <h1 className="text-2xl font-black text-white">Pagamento aprovado!</h1>
        <p className="text-zinc-400">Seu plano VIP foi ativado. Bem-vindo!</p>
        {!ready
          ? <p className="text-zinc-600 text-sm animate-pulse">Ativando seu acesso VIP…</p>
          : <button onClick={() => navigate('/picks')} className="btn-primary px-8 py-3">Ver Picks VIP</button>
        }
      </div>
    </div>
  )
}

function FailurePage() {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen bg-black flex items-center justify-center px-4">
      <div className="text-center space-y-4">
        <div className="w-20 h-20 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center mx-auto">
          <XCircle className="w-10 h-10 text-red-400" />
        </div>
        <h1 className="text-2xl font-black text-white">Pagamento recusado</h1>
        <p className="text-zinc-400">Houve um problema com o pagamento. Tente novamente.</p>
        <button onClick={() => navigate('/checkout')} className="btn-primary px-8 py-3">
          Tentar novamente
        </button>
      </div>
    </div>
  )
}

function PendingPage() {
  const navigate = useNavigate()
  const { refreshUser } = useAuth()
  const [checking, setChecking] = useState(false)
  const [activated, setActivated] = useState(false)

  const checkPayment = async () => {
    setChecking(true)
    try {
      const { data } = await api.get('/auth/me')
      await refreshUser()
      if (data.plan === 'vip' || data.plan === 'admin') setActivated(true)
    } catch { /* ignora */ } finally {
      setChecking(false)
    }
  }

  return (
    <div className="min-h-screen bg-black flex items-center justify-center px-4">
      <div className="text-center space-y-4">
        <div className="w-20 h-20 rounded-full bg-yellow-500/10 border border-yellow-500/30 flex items-center justify-center mx-auto">
          <Clock className="w-9 h-9 text-yellow-400" />
        </div>
        <h1 className="text-2xl font-black text-white">Pagamento em análise</h1>
        <p className="text-zinc-400">Seu pagamento está sendo processado.</p>
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-left space-y-1 max-w-xs mx-auto">
          <p className="text-zinc-300 text-xs font-semibold">Previsão de ativação:</p>
          <p className="text-zinc-500 text-xs">Pix: até 5 minutos</p>
          <p className="text-zinc-500 text-xs">Boleto: até 3 dias úteis após compensação</p>
        </div>
        {activated
          ? <button onClick={() => navigate('/picks')} className="btn-primary px-8 py-3">Ver Picks VIP</button>
          : (
            <div className="flex flex-col gap-2">
              <button onClick={checkPayment} disabled={checking}
                className="btn-primary px-8 py-3 disabled:opacity-60">
                {checking ? 'Verificando…' : 'Verificar pagamento'}
              </button>
              <button onClick={() => navigate('/picks')} className="btn-ghost px-8 py-3">
                Voltar aos Picks
              </button>
            </div>
          )
        }
      </div>
    </div>
  )
}

export default function Checkout() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [selectedPlan, setSelectedPlan] = useState<string>('trimestral')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Sub-páginas de retorno do MercadoPago
  if (location.pathname === '/checkout/sucesso') return <SuccessPage />
  if (location.pathname === '/checkout/falha')   return <FailurePage />
  if (location.pathname === '/checkout/pendente') return <PendingPage />

  const handleCheckout = async () => {
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/payments/create', { plan: selectedPlan })
      window.location.href = data.init_point
    } catch (err: any) {
      setError(err.response?.data?.detail ?? 'Erro ao iniciar pagamento. Tente novamente.')
    } finally {
      setLoading(false)
    }
  }

  const selected = PLANS.find(p => p.id === selectedPlan)!

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      {/* Header */}
      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-2xl mx-auto px-4 py-4 flex items-center gap-3">
          <BackButton />
          <div>
            <h1 className="text-base font-black text-white">Assinar VIP</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Acesso completo a todos os picks</p>
          </div>
        </div>
      </div>

      <main className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        {/* Benefícios */}
        <div className="card p-5">
          <h2 className="text-white font-bold mb-4">O que você ganha no VIP</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              'Todos os picks do dia',
              'Análise de probabilidades',
              'Gestão de banca inteligente',
              'Histórico completo de resultados',
              'Suporte ao Agente de IA',
              'Notificações de novos picks',
            ].map(benefit => (
              <div key={benefit} className="flex items-center gap-2 text-sm text-zinc-300">
                <Check className="w-4 h-4 text-green-500 shrink-0" />
                {benefit}
              </div>
            ))}
          </div>
        </div>

        {/* Seletor de plano */}
        <div>
          <h2 className="text-white font-bold mb-3">Escolha o período</h2>
          <div className="grid grid-cols-2 gap-3">
            {PLANS.map(plan => (
              <button
                key={plan.id}
                onClick={() => setSelectedPlan(plan.id)}
                className={`relative text-left p-4 rounded-xl border-2 transition-all
                  ${selectedPlan === plan.id
                    ? 'border-green-500 bg-green-500/5'
                    : 'border-zinc-800 bg-zinc-900 hover:border-zinc-600'}`}
              >
                {plan.popular && (
                  <span className="absolute -top-2.5 left-3 text-xs bg-green-600 text-white px-2 py-0.5 rounded-full font-semibold">
                    Popular
                  </span>
                )}
                {plan.savings && (
                  <span className="absolute -top-2.5 right-3 text-xs bg-yellow-500 text-black px-2 py-0.5 rounded-full font-semibold">
                    {plan.savings}
                  </span>
                )}
                <div className="text-white font-bold text-sm">{plan.label}</div>
                <div className="text-zinc-500 text-xs mt-0.5">{plan.period}</div>
                <div className="mt-2">
                  <span className="text-white font-black text-xl">
                    R$ {plan.price.toFixed(2).replace('.', ',')}
                  </span>
                </div>
                <div className="text-zinc-500 text-xs mt-0.5">
                  R$ {plan.pricePerMonth.toFixed(2).replace('.', ',')}/mês
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Resumo */}
        <div className="card p-5 space-y-3">
          <h2 className="text-white font-bold">Resumo do pedido</h2>
          <div className="flex justify-between text-sm">
            <span className="text-zinc-400">Plano Picks: {selected.label}</span>
            <span className="text-white font-semibold">
              R$ {selected.price.toFixed(2).replace('.', ',')}
            </span>
          </div>
          <div className="flex justify-between text-sm pt-2 border-t border-zinc-800">
            <span className="text-white font-bold">Total</span>
            <span className="text-green-400 font-black text-lg">
              R$ {selected.price.toFixed(2).replace('.', ',')}
            </span>
          </div>
          <p className="text-zinc-600 text-xs">
            Pagamento processado com segurança via MercadoPago. Aceita cartão, Pix e boleto.
          </p>
        </div>

        {/* Aviso sobre tempo de ativação por método */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-2">
          <p className="text-zinc-400 text-xs font-bold uppercase mb-1">Tempo de ativação por método</p>
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
            <span className="text-zinc-300 font-semibold">Cartão de crédito:</span>
            <span className="text-zinc-400">ativação imediata após aprovação</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
            <span className="text-zinc-300 font-semibold">Pix:</span>
            <span className="text-zinc-400">ativação em até 5 minutos após pagamento</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-yellow-500 shrink-0" />
            <span className="text-zinc-300 font-semibold">Boleto:</span>
            <span className="text-zinc-400">ativação em até 3 dias úteis após compensação</span>
          </div>
        </div>

        {error && <p className="text-red-400 text-sm text-center">{error}</p>}

        <button
          onClick={handleCheckout}
          disabled={loading}
          className="btn-primary w-full py-4 text-base font-bold"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              Aguarde...
            </span>
          ) : (
            `Pagar R$ ${selected.price.toFixed(2).replace('.', ',')} via MercadoPago`
          )}
        </button>

        <p className="text-zinc-600 text-xs text-center">
          Ao pagar, você concorda com os{' '}
          <Link to="/termos" className="underline hover:text-zinc-400 transition-colors">termos de uso</Link>
          {' '}e a{' '}
          <Link to="/privacidade" className="underline hover:text-zinc-400 transition-colors">política de privacidade</Link>.
        </p>
      </main>
    </div>
  )
}
