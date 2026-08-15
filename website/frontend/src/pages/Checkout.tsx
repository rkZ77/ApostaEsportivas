import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle, XCircle, Check, Clock } from 'lucide-react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import PageShell from '../components/PageShell'
import { useAuth } from '../context/AuthContext'
import { usePlans, fmtPlanPrice } from '../hooks/usePlans'
import api from '../services/api'
import { WA_SUPPORT } from '../lib/support'

/* O plano em destaque é escolha de venda, não vem do backend: o resto (preço,
   período, desconto) vem de usePlans. */
const POPULAR_PLAN = 'trimestral'

function SuccessPage() {
  const navigate = useNavigate()
  const { refreshUser } = useAuth()
  const [estado, setEstado] = useState<'ativando' | 'ativo' | 'sem_confirmacao'>('ativando')

  /* Não espera o webhook de braços cruzados: pergunta ao MercadoPago pelo
     /payments/confirm, que ativa o VIP na hora se o pagamento estiver
     aprovado. Foi exatamente o que faltou em 07/08/2026, quando o webhook
     começou a rejeitar as notificações e quem pagou continuou free sem
     ninguém perceber. */
  useEffect(() => {
    let tentativas = 0
    const MAX = 12
    let cancelado = false

    const virouVip = (plano?: string) => plano === 'vip' || plano === 'admin'

    const verificar = async () => {
      if (cancelado) return
      try {
        // A cada três voltas, cobra a confirmação do MercadoPago de novo:
        // boleto e Pix podem levar alguns segundos para aprovar.
        if (tentativas % 3 === 0) {
          await api.post('/payments/confirm').catch(() => {})
        }
        // Busca o plano direto da API para evitar stale closure
        const { data } = await api.get('/auth/me')
        await refreshUser()
        if (virouVip(data.plan)) {
          setEstado('ativo')
          return
        }
      } catch { /* ignora */ }
      tentativas++
      if (tentativas >= MAX) { setEstado('sem_confirmacao'); return }
      setTimeout(verificar, 2000)
    }

    verificar()
    return () => { cancelado = true }
  }, [])

  const confirmado = estado === 'ativo'

  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center px-4">
      <div className="text-center space-y-4 max-w-sm">
        <motion.div
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 400, damping: 20 }}
          className={`w-20 h-20 rounded-full flex items-center justify-center mx-auto border
            ${estado === 'sem_confirmacao'
              ? 'bg-yellow-500/10 border-yellow-500/30'
              : 'bg-green-500/10 border-green-500/30'}`}
        >
          {estado === 'sem_confirmacao'
            ? <Clock className="w-9 h-9 text-yellow-400" />
            : <CheckCircle className="w-10 h-10 text-green-400" />}
        </motion.div>

        {estado === 'sem_confirmacao' ? (
          <>
            <h1 className="text-2xl font-bold text-ink-1">Pagamento recebido</h1>
            <p className="text-ink-2">
              Ainda não conseguimos confirmar a liberação do seu acesso. Se já foi debitado,
              fale com o suporte que a gente ativa na hora.
            </p>
            <div className="flex flex-col gap-2 pt-1">
              <a href={WA_SUPPORT} target="_blank" rel="noopener noreferrer"
                 className="btn-primary px-8 py-3">Falar com o suporte</a>
              <button onClick={() => navigate('/picks')} className="btn-ghost px-8 py-3">
                Voltar aos Picks
              </button>
            </div>
          </>
        ) : (
          <>
            <h1 className="text-2xl font-bold text-ink-1">Pagamento aprovado!</h1>
            <p className="text-ink-2">
              {confirmado ? 'Seu plano VIP foi ativado. Bem-vindo!' : 'Estamos liberando seu acesso.'}
            </p>
            {confirmado
              ? <button onClick={() => navigate('/picks')} className="btn-primary px-8 py-3">Ver Picks VIP</button>
              : <p className="text-ink-4 text-sm animate-pulse">Ativando seu acesso VIP…</p>
            }
          </>
        )}
      </div>
    </div>
  )
}

function FailurePage() {
  const navigate = useNavigate()
  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center px-4">
      <div className="text-center space-y-4">
        <motion.div
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 400, damping: 20 }}
          className="w-20 h-20 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center mx-auto"
        >
          <XCircle className="w-10 h-10 text-red-400" />
        </motion.div>
        <h1 className="text-2xl font-bold text-ink-1">Pagamento recusado</h1>
        <p className="text-ink-2">Houve um problema com o pagamento. Tente novamente.</p>
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
      // Pergunta ao MercadoPago antes de olhar o plano: se o Pix já compensou,
      // o acesso é liberado neste clique, sem depender do webhook.
      await api.post('/payments/confirm').catch(() => {})
      const { data } = await api.get('/auth/me')
      await refreshUser()
      if (data.plan === 'vip' || data.plan === 'admin') setActivated(true)
    } catch { /* ignora */ } finally {
      setChecking(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center px-4">
      <div className="text-center space-y-4">
        <motion.div
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 400, damping: 20 }}
          className="w-20 h-20 rounded-full bg-yellow-500/10 border border-yellow-500/30 flex items-center justify-center mx-auto"
        >
          <Clock className="w-9 h-9 text-yellow-400" />
        </motion.div>
        <h1 className="text-2xl font-bold text-ink-1">Pagamento em análise</h1>
        <p className="text-ink-2">Seu pagamento está sendo processado.</p>
        <div className="bg-surface-1 border border-line rounded-md px-4 py-3 text-left space-y-1 max-w-xs mx-auto">
          <p className="text-ink-2 text-xs font-semibold">Previsão de ativação:</p>
          <p className="text-ink-3 text-xs">Pix: até 5 minutos</p>
          <p className="text-ink-3 text-xs">Boleto: até 3 dias úteis após compensação</p>
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
  const { plans } = usePlans()
  const [selectedPlan, setSelectedPlan] = useState<string>(POPULAR_PLAN)
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

  const selected = plans.find(p => p.id === selectedPlan) ?? plans[0]

  return (
    <PageShell
      title="Assinar VIP"
      description="Acesso completo a todos os picks da IA, múltiplas, alavancagem e gestão de banca."
      noindex
      width="narrow"
      bar={{ back: true, title: 'Assinar VIP', sub: 'Acesso completo a todos os picks' }}
      mainClassName="space-y-6"
    >
        {/* Benefícios */}
        <div className="card p-5">
          <h2 className="text-ink-1 font-bold mb-4">O que você ganha no VIP</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              'Todos os picks do dia',
              'Análise de probabilidades',
              'Gestão de banca inteligente',
              'Histórico completo de resultados',
              'Suporte ao Agente de IA',
              'Notificações de novos picks',
            ].map(benefit => (
              <div key={benefit} className="flex items-center gap-2 text-sm text-ink-2">
                <Check className="w-4 h-4 text-green-500 shrink-0" />
                {benefit}
              </div>
            ))}
          </div>
        </div>

        {/* Seletor de plano */}
        <div>
          <h2 className="text-ink-1 font-bold mb-3">Escolha o período</h2>
          <div className="grid grid-cols-2 gap-3">
            {plans.map(plan => (
              <motion.button
                key={plan.id}
                whileTap={{ scale: 0.97 }}
                animate={{ scale: selectedPlan === plan.id ? 1.02 : 1 }}
                transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                onClick={() => setSelectedPlan(plan.id)}
                className={`relative text-left p-4 rounded-md border-2 transition-colors
                  ${selectedPlan === plan.id
                    ? 'border-green-500 bg-green-500/5'
                    : 'border-line bg-surface-1 hover:border-line-strong'}`}
              >
                {plan.id === POPULAR_PLAN && (
                  <span className="absolute -top-2.5 left-3 font-mono text-xs bg-green-600 text-ink-1 px-2 py-0.5 rounded-sm font-semibold">
                    Popular
                  </span>
                )}
                {plan.save_pct > 0 && (
                  <span className="absolute -top-2.5 right-3 font-mono text-xs bg-yellow-500 text-black px-2 py-0.5 rounded-sm font-semibold">
                    Economize {plan.save_pct}%
                  </span>
                )}
                <div className="text-ink-1 font-bold text-sm">{plan.label}</div>
                <div className="text-ink-3 text-xs mt-0.5">{plan.period}</div>
                <div className="mt-2">
                  <span className="font-mono text-ink-1 font-bold text-xl">
                    {fmtPlanPrice(plan.price)}
                  </span>
                </div>
                <div className="font-mono text-ink-3 text-xs mt-0.5">
                  {fmtPlanPrice(plan.price_per_month)}/mês
                </div>
              </motion.button>
            ))}
          </div>
        </div>

        {/* Resumo */}
        <div className="card p-5 space-y-3">
          <h2 className="text-ink-1 font-bold">Resumo do pedido</h2>
          <div className="flex justify-between text-sm">
            <span className="text-ink-2">Plano Picks: {selected.label}</span>
            <span className="font-mono text-ink-1 font-semibold">
              {fmtPlanPrice(selected.price)}
            </span>
          </div>
          <div className="flex justify-between text-sm pt-2 border-t border-line">
            <span className="text-ink-1 font-bold">Total</span>
            <span className="font-mono text-accent font-bold text-lg">
              {fmtPlanPrice(selected.price)}
            </span>
          </div>
          <p className="text-ink-4 text-xs">
            Pagamento processado com segurança via MercadoPago. Aceita cartão, Pix e boleto.
          </p>
        </div>

        {/* Aviso sobre tempo de ativação por método */}
        <div className="bg-surface-1 border border-line rounded-md p-4 space-y-2">
          <p className="text-ink-2 text-xs font-bold mb-1">Tempo de ativação por método</p>
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
            <span className="text-ink-2 font-semibold">Cartão de crédito:</span>
            <span className="text-ink-2">ativação imediata após aprovação</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
            <span className="text-ink-2 font-semibold">Pix:</span>
            <span className="text-ink-2">ativação em até 5 minutos após pagamento</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-yellow-500 shrink-0" />
            <span className="text-ink-2 font-semibold">Boleto:</span>
            <span className="text-ink-2">ativação em até 3 dias úteis após compensação</span>
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

        <p className="text-ink-4 text-xs text-center">
          Ao pagar, você concorda com os{' '}
          <Link to="/termos" className="underline hover:text-ink-2 transition-colors">termos de uso</Link>
          {' '}e a{' '}
          <Link to="/privacidade" className="underline hover:text-ink-2 transition-colors">política de privacidade</Link>.
        </p>
    </PageShell>
  )
}
