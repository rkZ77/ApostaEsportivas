import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle, XCircle, Clock, ShieldCheck } from 'lucide-react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import PageShell from '../components/PageShell'
import { useAuth } from '../context/AuthContext'
import { usePlans, fmtPlanPrice } from '../hooks/usePlans'
import api from '../services/api'
import { WA_SUPPORT } from '../lib/support'
import { iniciouCheckout } from '../lib/analytics'
import ProvaPublica from '../components/ProvaPublica'
import { MODULOS_VIP, SEM_RENOVACAO_AUTOMATICA } from '../lib/oferta'

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
      // O `_ga` viaja junto pro backend disparar o purchase pelo servidor: o
      // MercadoPago leva o usuário pra fora e quem paga por PIX costuma não
      // voltar pro /checkout/sucesso, então evento de compra no navegador
      // perderia boa parte da receita. Ver backend/analytics.py.
      const gaCookie = document.cookie.split('; ').find(c => c.startsWith('_ga='))?.slice(4) ?? ''
      // begin_checkout é o último passo que o navegador consegue medir: daqui
      // o usuário sai pro MercadoPago e só o servidor vê o resto.
      const plano = plans.find(p => p.id === selectedPlan)
      if (plano) iniciouCheckout(plano)
      const { data } = await api.post('/payments/create', { plan: selectedPlan, ga_cookie: gaCookie })
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
        {/*
          A PROVA VEM ANTES DA LISTA.

          Esta é a última tela antes de pagar e era a única do funil sem um
          número sequer: a Home mostra o histórico, a página de Resultados
          mostra o histórico, e aqui, com o dedo no botão, não havia nada.
          Os números saem de /public/results, os mesmos das outras duas telas.
        */}
        <ProvaPublica compacta />

        {/* Benefícios */}
        <div className="card p-5">
          <h2 className="text-ink-1 font-bold mb-4">O que você ganha no VIP</h2>
          {/*
            A LISTA ERA ESCRITA À MÃO AQUI, e subvendia o produto na pior hora
            possível. Eram seis frases genéricas · "Análise de probabilidades",
            "Suporte ao Agente de IA" · que não citavam múltipla, alavancagem,
            ao vivo, Pick Boost, estatística de jogador, faltas nem defesas.
            Sete módulos que a assinatura abre e que a tela de pagar não
            mencionava, enquanto a vitrine da Home listava todos.

            Agora as duas leem de lib/oferta. `MODULOS_VIP` é o que a assinatura
            destrava, então esta lista é exatamente o que está sendo comprado.
          */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {MODULOS_VIP.map(({ Icon, titulo }) => (
              <div key={titulo} className="flex items-center gap-2 text-sm text-ink-2">
                <Icon className="w-4 h-4 text-accent-ink shrink-0" aria-hidden="true" />
                {titulo}
              </div>
            ))}
          </div>
          <p className="text-ink-4 text-xs mt-4 pt-3 border-t border-line">
            Mais a gestão de banca, a agenda de jogos e o histórico completo, que a conta
            já tem.
          </p>
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
                {/*
                  OS DOIS SELOS NUMA LINHA SÓ.

                  Eram dois `absolute` independentes, um preso em `left-3` e o
                  outro em `right-3`. No trimestral, que é o único plano que
                  carrega os dois, eles se encontravam no meio: numa tela de
                  390px o resultado era "Popu" com "Economize 17%" impresso por
                  cima · e isso na tela em que a pessoa escolhe quanto vai
                  pagar.

                  Numa linha flex com `justify-between` eles dividem a largura
                  em vez de disputá-la, e o `truncate` garante que o encontro,
                  se voltar a acontecer, corte o texto em vez de empilhar.
                */}
                {(plan.id === POPULAR_PLAN || plan.save_pct > 0) && (
                  <span className="absolute -top-2.5 inset-x-2 flex items-center justify-between gap-1 pointer-events-none">
                    {plan.id === POPULAR_PLAN ? (
                      <span className="font-mono text-[10px] bg-green-600 text-white px-1.5 py-0.5 rounded-sm font-semibold truncate">
                        Popular
                      </span>
                    ) : <span />}
                    {plan.save_pct > 0 && (
                      <span className="font-mono text-[10px] bg-yellow-500 text-on-fill px-1.5 py-0.5 rounded-sm font-semibold shrink-0">
                        {/* Sozinho no topo do card cabe a palavra inteira.
                            Dividindo a linha com o "Popular", num card de 168px,
                            não cabe · e "Economize" cortado no meio não vende
                            nada. O número é a informação; o verbo é enfeite. */}
                        {plan.id === POPULAR_PLAN ? `−${plan.save_pct}%` : `Economize ${plan.save_pct}%`}
                      </span>
                    )}
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
            <span className="font-mono text-accent-ink font-bold text-lg">
              {fmtPlanPrice(selected.price)}
            </span>
          </div>
          {/* "Vai cobrar sozinho no mês que vem?" é a objeção mais comum de
              quem assina qualquer coisa aqui, e a resposta é favorável ao
              produto: o backend cria uma `preference` do MercadoPago, que cobra
              uma vez só · não existe `preapproval`, não existe recorrência. O
              texto vem de lib/oferta pra sair junto caso isso mude. */}
          <p className="flex items-start gap-2 text-xs text-ink-2 pt-1">
            <ShieldCheck className="w-4 h-4 text-accent-ink shrink-0 mt-px" aria-hidden="true" />
            <span>{SEM_RENOVACAO_AUTOMATICA}</span>
          </p>
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
