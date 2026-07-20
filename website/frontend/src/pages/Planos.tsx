import { useNavigate } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import { Lightbulb, Crown, User } from 'lucide-react'
import { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import api from '../services/api'
import BackButton from '../components/BackButton'

const PLAN_DAYS: Record<string, number> = {
  trial: 2, mensal: 30, trimestral: 90, semestral: 180, anual: 365,
}
const PLAN_LABEL: Record<string, string> = {
  mensal: 'Mensal', trimestral: 'Trimestral', semestral: 'Semestral', anual: 'Anual',
}
const PLAN_PRICE: Record<string, number> = {
  mensal: 39.90, trimestral: 99.90, semestral: 199.90, anual: 359.90,
}
const METHOD_LABEL: Record<string, string> = {
  credit_card: 'Cartão de crédito', debit_card: 'Cartão de débito',
  pix: 'Pix', ticket: 'Boleto', account_money: 'Saldo MP',
}

interface ReferralData {
  referral_code: string; referral_link: string
  total_indicated: number; total_converted: number; days_earned: number
}

export default function Planos() {
  const navigate = useNavigate()
  const { user, isVip, isAdmin, daysUntilExpiry, updateUser } = useAuth()

  const [meData, setMeData]               = useState<any>(null)
  const [trialUsed, setTrialUsed]         = useState<boolean | null>(null)
  const [activating, setActivating]       = useState(false)
  const [activateError, setActivateError] = useState('')
  const [activated, setActivated]         = useState(false)
  const [payments, setPayments]           = useState<any[]>([])
  const [referral, setReferral]           = useState<ReferralData | null>(null)
  const [referralCopied, setReferralCopied] = useState(false)

  const isTrial = user?.plan === 'trial'

  // Countdown ao vivo
  const [countdown, setCountdown] = useState('')
  useEffect(() => {
    if (!user?.expires_at || (!isVip && !isTrial)) { setCountdown(''); return }
    const tick = () => {
      const diff = new Date(user.expires_at!).getTime() - Date.now()
      if (diff <= 0) { setCountdown('Expirado'); return }
      const d = Math.floor(diff / 86400000)
      const h = Math.floor((diff % 86400000) / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setCountdown(`${d}d ${h}h ${m.toString().padStart(2,'0')}m ${s.toString().padStart(2,'0')}s`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [user?.expires_at, isVip, isTrial])

  useEffect(() => {
    if (!user) return
    api.get('/auth/me').then(r => {
      setMeData(r.data)
      setTrialUsed(r.data.trial_used ?? false)
    }).catch(() => setTrialUsed(true))
    api.get('/payments/history').then(r => setPayments(r.data)).catch(() => {})
    api.get('/auth/referral').then(r => setReferral(r.data)).catch(() => {})
  }, [user])

  const handleActivateTrial = async () => {
    setActivating(true); setActivateError('')
    try {
      const { data } = await api.post('/auth/activate-trial')
      updateUser({ plan: 'trial', expires_at: data.expires_at })
      setActivated(true); setTrialUsed(true)
    } catch (e: any) {
      setActivateError(e?.response?.data?.detail ?? 'Erro ao ativar trial.')
    } finally { setActivating(false) }
  }

  const copyReferral = () => {
    if (!referral) return
    navigator.clipboard.writeText(referral.referral_link).then(() => {
      setReferralCopied(true)
      setTimeout(() => setReferralCopied(false), 2000)
    })
  }

  const isEligibleForTrial = user && user.plan === 'free' && trialUsed === false

  // Cálculos do plano atual
  const subType      = meData?.subscription_type as string | null
  const totalDays    = isTrial ? 2 : (subType ? (PLAN_DAYS[subType] ?? 30) : 30)
  const remaining    = daysUntilExpiry ?? 0
  const pct          = Math.max(0, Math.min(100, daysUntilExpiry !== null ? (remaining / totalDays) * 100 : 100))
  const urgent       = remaining <= (isTrial ? 1 : 5)
  const expiryDate   = user?.expires_at
    ? new Date(user.expires_at).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' })
    : null
  const startDate    = user?.expires_at && daysUntilExpiry !== null
    ? new Date(Date.now() - (totalDays - remaining) * 86400000).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' })
    : null
  const memberSince  = meData?.created_at
    ? new Date(meData.created_at).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' })
    : null

  // Total gasto em pagamentos aprovados
  const totalSpent = payments.reduce((acc, p) => acc + Number(p.amount), 0)

  // Sugestão de upgrade (só para mensal)
  const upgradeOptions = subType === 'mensal' ? [
    { key: 'trimestral', label: 'Trimestral', price: 99.90, perMonth: 33.30, savePct: 17, saveAmt: (39.90 * 3 - 99.90).toFixed(2) },
    { key: 'anual',      label: 'Anual',      price: 359.90, perMonth: 29.99, savePct: 25, saveAmt: (39.90 * 12 - 359.90).toFixed(2) },
  ] : []

  const color = isTrial ? 'green' : 'yellow'

  return (
    <>
    <Helmet>
      <title>Planos · Pick IA | VIP e Free para Apostas Esportivas</title>
      <meta name="description" content="Escolha seu plano Pick IA. Free com picks diários ou VIP com análise completa, múltiplas, alavancagem e gestão de banca para Brasileirão e as principais ligas europeias." />
      <link rel="canonical" href="https://pickia.com.br/planos" />
    </Helmet>
    <div className="min-h-screen bg-black">
      <Navbar />

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center gap-3">
          <BackButton />
          <div>
            <h1 className="text-base font-black text-white">Meu Plano</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Status e detalhes do seu acesso</p>
          </div>
        </div>
      </div>

      <main className="max-w-3xl mx-auto px-4 py-8 space-y-6">

        {activated && (
          <div className="bg-green-500/10 border border-green-500/40 rounded-2xl p-6 text-center">
            <div className="w-14 h-14 bg-green-500/20 border border-green-500/30 rounded-full flex items-center justify-center mx-auto mb-3">
              <svg className="w-7 h-7 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-white font-black text-xl mb-1">Teste VIP ativado!</h2>
            <p className="text-zinc-400 text-sm mb-4">Você tem 2 dias de acesso completo. Aproveite!</p>
            <button onClick={() => navigate('/picks')}
              className="bg-green-500 hover:bg-green-400 text-black font-black px-8 py-3 rounded-xl text-sm transition-colors">
              Ver Picks
            </button>
          </div>
        )}

        {user && !activated && (isVip || isTrial) && (
          <div className={`relative bg-zinc-900 border ${urgent ? 'border-red-500/40' : `border-${color}-500/20`} rounded-2xl p-6 overflow-hidden`}>
            <div className={`absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-${color}-500/60 to-transparent`} />

            {/* Cabeçalho */}
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                {/* Status atual + badge urgente */}
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-zinc-500 text-xs">Status atual:</span>
                  <span className={`text-xs font-black ${isTrial ? 'text-amber-400' : urgent ? 'text-red-400' : 'text-yellow-400'}`}>
                    {isTrial ? 'TRIAL' : subType ? `VIP ${PLAN_LABEL[subType]}` : 'VIP'}
                  </span>
                  {urgent && (
                    <span className="text-[10px] bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-0.5 rounded-full font-bold uppercase animate-pulse">
                      Expirando
                    </span>
                  )}
                </div>

                {/* Countdown */}
                {countdown && (
                  <p className="text-zinc-400 text-xs mb-2">
                    Expira em <span className={`font-bold tabular-nums ${urgent ? 'text-red-400' : 'text-white'}`}>{countdown}</span>
                  </p>
                )}

                <p className={`font-black text-3xl ${urgent ? 'text-red-400' : 'text-white'}`}>
                  {daysUntilExpiry === null ? 'Ativo' : remaining <= 0 ? 'Expirado' : `${remaining} dia${remaining === 1 ? '' : 's'}`}
                  {remaining > 0 && daysUntilExpiry !== null && <span className="text-zinc-500 font-normal text-sm ml-1">restantes</span>}
                </p>
              </div>
              <button onClick={() => navigate('/checkout')}
                className="shrink-0 bg-yellow-400 hover:bg-yellow-300 text-black font-black text-xs px-4 py-2.5 rounded-xl transition-colors">
                {isTrial ? 'Assinar VIP' : 'Renovar'}
              </button>
            </div>

            {/* Barra de progresso */}
            {daysUntilExpiry !== null && (
              <div className="space-y-1.5 mb-5">
                <div className="flex justify-between text-[10px] text-zinc-500">
                  <span>Progresso do plano</span>
                  <span>{remaining} / {totalDays} dias</span>
                </div>
                <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${urgent ? 'bg-red-500' : isTrial ? 'bg-green-500' : 'bg-yellow-400'}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            )}

            {/* Datas */}
            <div className="grid grid-cols-2 gap-3 mb-5">
              {startDate && (
                <div className="bg-zinc-800/60 rounded-xl p-3">
                  <p className="text-[10px] text-zinc-500 uppercase mb-0.5">Início</p>
                  <p className="text-white text-xs font-semibold">{startDate}</p>
                </div>
              )}
              {expiryDate && (
                <div className="bg-zinc-800/60 rounded-xl p-3">
                  <p className="text-[10px] text-zinc-500 uppercase mb-0.5">{remaining <= 0 ? 'Expirou' : 'Expira'}</p>
                  <p className={`text-xs font-semibold ${urgent ? 'text-red-400' : 'text-white'}`}>{expiryDate}</p>
                </div>
              )}
              {memberSince && (
                <div className="bg-zinc-800/60 rounded-xl p-3">
                  <p className="text-[10px] text-zinc-500 uppercase mb-0.5">Membro desde</p>
                  <p className="text-white text-xs font-semibold">{memberSince}</p>
                </div>
              )}
              {totalSpent > 0 && (
                <div className="bg-zinc-800/60 rounded-xl p-3">
                  <p className="text-[10px] text-zinc-500 uppercase mb-0.5">Total investido</p>
                  <p className="text-green-400 text-xs font-black">R$ {totalSpent.toFixed(2).replace('.', ',')}</p>
                </div>
              )}
            </div>

            {/* Features incluídas */}
            <div className="grid grid-cols-2 gap-2">
              {['Picks VIP (10–20/dia)', 'Múltiplas por IA', 'Alavancagem de risco calculado', 'Agente IA de futebol', 'Histórico com ROI', 'Análise detalhada'].map(f => (
                <div key={f} className="flex items-center gap-1.5 text-xs text-zinc-400">
                  <svg className="w-3.5 h-3.5 text-green-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                  {f}
                </div>
              ))}
            </div>
          </div>
        )}

        {user && !activated && !isVip && !isAdmin && !isTrial && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex items-center gap-4">
            <div className="w-10 h-10 bg-zinc-800 rounded-full flex items-center justify-center shrink-0 text-zinc-500 font-black text-sm">F</div>
            <div className="flex-1">
              <p className="text-white font-bold text-sm">Plano Free</p>
              <p className="text-zinc-500 text-xs mt-0.5">1 pick gratuito por dia · sem expiração</p>
              {memberSince && <p className="text-zinc-700 text-xs mt-0.5">Membro desde {memberSince}</p>}
            </div>
            <button onClick={() => navigate('/checkout')}
              className="shrink-0 bg-yellow-400 hover:bg-yellow-300 text-black font-black text-xs px-4 py-2 rounded-xl transition-colors">
              Upgrade VIP
            </button>
          </div>
        )}

        {isAdmin && (
          <div className="bg-purple-400/10 border border-purple-400/20 rounded-2xl p-5">
            <p className="text-purple-400 font-black text-sm">Conta Admin. Acesso irrestrito e permanente.</p>
            {memberSince && <p className="text-purple-400/50 text-xs mt-1">Membro desde {memberSince}</p>}
          </div>
        )}

        {isEligibleForTrial && !activated && (
          <div className="relative bg-zinc-900 border border-green-500/50 rounded-2xl p-6 overflow-hidden">
            <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-green-500 to-transparent" />
            <div className="absolute top-4 right-4">
              <span className="bg-green-500 text-black text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Sem cartão</span>
            </div>
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 bg-green-500/10 border border-green-500/30 rounded-xl flex items-center justify-center shrink-0 mt-0.5">
                <svg className="w-6 h-6 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v13m0-13V6a2 2 0 112 2h-2zm0 0V5.5A2.5 2.5 0 109.5 8H12zm-7 4h14M5 12a2 2 0 110-4h14a2 2 0 110 4M5 12v7a2 2 0 002 2h10a2 2 0 002-2v-7" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-sm text-green-500 font-bold mb-1">Disponível para você</p>
                <h2 className="text-xl font-black text-white mb-1">2 dias de VIP grátis</h2>
                <p className="text-zinc-400 text-sm mb-4">Acesse todos os picks VIP, Múltiplas, Alavancagem e Agente IA. Sem cartão, sem compromisso.</p>
                <ul className="space-y-1.5 mb-5">
                  {['Picks VIP completos (10–20/dia)', 'Múltiplas e Alavancagem', 'Agente IA de futebol', 'Histórico completo com ROI'].map(f => (
                    <li key={f} className="flex items-center gap-2 text-sm text-zinc-300">
                      <svg className="w-4 h-4 text-green-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                      {f}
                    </li>
                  ))}
                </ul>
                {activateError && <p className="text-red-400 text-xs mb-3">{activateError}</p>}
                <button onClick={handleActivateTrial} disabled={activating}
                  className="bg-green-500 hover:bg-green-400 disabled:opacity-60 text-black font-black px-7 py-3 rounded-xl text-sm transition-colors flex items-center gap-2">
                  {activating
                    ? <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Ativando...</>
                    : 'Ativar 2 dias VIP gratuito'}
                </button>
              </div>
            </div>
          </div>
        )}

        {upgradeOptions.length > 0 && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
            <p className="text-xs text-zinc-500 font-black uppercase mb-1 flex items-center gap-1"><Lightbulb className="w-3.5 h-3.5" /> Você pode economizar</p>
            <p className="text-white text-sm mb-4">
              No plano <span className="text-yellow-400 font-bold">Mensal</span> você paga R$ 39,90/mês.
              Veja quanto economizaria mudando:
            </p>
            <div className="grid grid-cols-2 gap-3">
              {upgradeOptions.map(opt => (
                <button key={opt.key} onClick={() => navigate('/checkout')}
                  className="relative p-4 rounded-xl border border-zinc-700 hover:border-yellow-400/50 hover:bg-yellow-400/5 transition-all text-left group">
                  <p className="text-white font-black text-sm group-hover:text-yellow-400 transition-colors">{opt.label}</p>
                  <p className="text-zinc-500 text-xs mt-0.5">R$ {opt.perMonth.toFixed(2).replace('.', ',')}/mês</p>
                  <p className="text-green-400 text-xs font-bold mt-2">Economize R$ {opt.saveAmt.replace('.', ',')} ↓{opt.savePct}%</p>
                </button>
              ))}
            </div>
          </div>
        )}

        {referral && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-4">
            <div>
              <h3 className="text-sm font-black text-white">Indicações</h3>
              <p className="text-zinc-500 text-xs mt-0.5">
                +1 dia VIP por cadastro · +2 dias VIP se assinar o plano
              </p>
            </div>

            {/* Recompensas */}
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="bg-zinc-800/60 border border-zinc-700/50 rounded-xl p-3 flex items-center gap-2">
                <User className="w-5 h-5 text-zinc-400 shrink-0" />
                <div>
                  <p className="text-white font-black">+1 dia</p>
                  <p className="text-zinc-500">por cadastro</p>
                </div>
              </div>
              <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-xl p-3 flex items-center gap-2">
                <Crown className="w-5 h-5 text-yellow-400 shrink-0" />
                <div>
                  <p className="text-yellow-400 font-black">+2 dias</p>
                  <p className="text-zinc-500">se assinar VIP</p>
                </div>
              </div>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Cadastros',   value: referral.total_indicated, color: 'text-white' },
                { label: 'Assinantes',  value: referral.total_converted,  color: 'text-green-400' },
                { label: 'Dias ganhos', value: referral.days_earned,      color: 'text-yellow-400' },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-zinc-800/60 rounded-xl p-3 text-center">
                  <p className={`text-2xl font-black ${color}`}>{value}</p>
                  <p className="text-zinc-500 text-xs mt-0.5">{label}</p>
                </div>
              ))}
            </div>

            {/* Breakdown */}
            {referral.total_indicated > 0 && (
              <div className="bg-zinc-800/40 rounded-xl px-4 py-3 space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-zinc-500">{referral.total_indicated} cadastro{referral.total_indicated !== 1 ? 's' : ''} × 1 dia</span>
                  <span className="text-white font-bold">+{referral.total_indicated} dia{referral.total_indicated !== 1 ? 's' : ''}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">{referral.total_converted} assinante{referral.total_converted !== 1 ? 's' : ''} × 2 dias</span>
                  <span className="text-yellow-400 font-bold">+{referral.total_converted * 2} dia{referral.total_converted * 2 !== 1 ? 's' : ''}</span>
                </div>
                <div className="flex justify-between border-t border-zinc-700 pt-1.5 mt-1">
                  <span className="text-zinc-400 font-semibold">Total</span>
                  <span className="text-yellow-400 font-black">{referral.days_earned} dias VIP</span>
                </div>
              </div>
            )}

            {/* Link */}
            <div>
              <p className="text-xs text-zinc-500 mb-1.5">Seu link de indicação</p>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-xs text-zinc-300 font-mono truncate select-all">
                  {referral.referral_link}
                </div>
                <button onClick={copyReferral}
                  className={`shrink-0 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                    referralCopied ? 'bg-green-500/20 text-green-400' : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
                  }`}>
                  {referralCopied ? 'Copiado!' : 'Copiar'}
                </button>
              </div>
              <p className="text-zinc-600 text-xs mt-1">Código: <span className="text-zinc-400 font-mono font-bold">{referral.referral_code}</span></p>
            </div>

            {referral.total_indicated === 0 && (
              <p className="text-zinc-600 text-xs text-center">
                Compartilhe seu link: cada amigo que se cadastrar te dá +1 dia, e +2 se assinar o VIP!
              </p>
            )}
          </div>
        )}

        {payments.length > 0 && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            <h3 className="text-sm font-black text-white uppercase mb-4">Histórico de pagamentos</h3>
            <div className="space-y-0">
              {payments.map(p => {
                const date = p.created_at
                  ? new Date(p.created_at).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' })
                  : ''
                return (
                  <div key={p.id} className="flex items-center justify-between py-3 border-b border-zinc-800 last:border-0">
                    <div>
                      <p className="text-white text-sm font-semibold">
                        Plano Picks: {PLAN_LABEL[p.plan] ?? p.plan}
                      </p>
                      <p className="text-zinc-500 text-xs mt-0.5">
                        {date} · {METHOD_LABEL[p.payment_method] ?? p.payment_method}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-green-400 font-black text-sm">
                        R$ {Number(p.amount).toFixed(2).replace('.', ',')}
                      </p>
                      <span className="text-[10px] bg-green-500/10 text-green-400 border border-green-500/20 px-1.5 py-0.5 rounded font-bold uppercase">
                        Aprovado
                      </span>
                    </div>
                  </div>
                )
              })}
              {totalSpent > 0 && (
                <div className="flex items-center justify-between pt-3">
                  <span className="text-zinc-500 text-xs font-semibold">Total investido</span>
                  <span className="text-white font-black">R$ {totalSpent.toFixed(2).replace('.', ',')}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {(isVip || isTrial) && !isAdmin && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex items-center gap-4">
            <div className="flex-1">
              <p className="text-white font-bold text-sm">Solicitar cancelamento ou reembolso</p>
              <p className="text-zinc-500 text-xs mt-0.5">
                Pelo CDC você tem 7 dias de arrependimento em compras digitais. Reembolso integral garantido.
              </p>
            </div>
            <a
              href="https://wa.me/5517992323916?text=Ol%C3%A1!%20Gostaria%20de%20solicitar%20o%20cancelamento%2Freembolso%20do%20meu%20plano%20Pick%20IA."
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 border border-zinc-700 hover:border-red-500/50 hover:text-red-400 text-zinc-400 font-bold text-xs px-4 py-2.5 rounded-xl transition-colors"
            >
              Solicitar
            </a>
          </div>
        )}

        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex items-center gap-4">
          <div className="w-10 h-10 bg-[#25D366]/10 border border-[#25D366]/20 rounded-full flex items-center justify-center shrink-0">
            <svg viewBox="0 0 24 24" className="w-5 h-5 fill-[#25D366]">
              <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
              <path d="M12 0C5.373 0 0 5.373 0 12c0 2.124.554 4.118 1.528 5.849L.057 23.428a.5.5 0 0 0 .609.61l5.66-1.485A11.945 11.945 0 0 0 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.882a9.875 9.875 0 0 1-5.031-1.374l-.36-.214-3.733.979.997-3.645-.235-.374A9.855 9.855 0 0 1 2.118 12C2.118 6.54 6.54 2.118 12 2.118S21.882 6.54 21.882 12 17.46 21.882 12 21.882z"/>
            </svg>
          </div>
          <div className="flex-1">
            <p className="text-white font-bold text-sm">Precisa de ajuda?</p>
            <p className="text-zinc-500 text-xs mt-0.5">Problemas com pagamento, acesso ou dúvidas? Fale direto conosco</p>
          </div>
          <a
            href="https://wa.me/5517992323916?text=Ol%C3%A1!%20Preciso%20de%20suporte%20no%20Pick%20IA."
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 bg-[#25D366] hover:bg-[#20ba58] text-white font-black text-xs px-4 py-2.5 rounded-xl transition-colors"
          >
            WhatsApp
          </a>
        </div>

        {user && !isAdmin && !isVip && !isEligibleForTrial && !activated && (
          <div className="bg-zinc-900 border border-yellow-400/20 rounded-2xl p-6 flex items-center justify-between gap-4">
            <div>
              <p className="text-white font-black text-sm">Quer acesso VIP completo?</p>
              <p className="text-zinc-500 text-xs mt-0.5">Picks VIP, Múltiplas, Alavancagem e Agente IA · a partir de R$ 39,90/mês</p>
            </div>
            <button onClick={() => navigate('/checkout')}
              className="shrink-0 bg-yellow-400 hover:bg-yellow-300 text-black font-black text-xs px-5 py-2.5 rounded-xl transition-colors">
              Assinar VIP
            </button>
          </div>
        )}

      </main>
    </div>
    </>
  )
}
