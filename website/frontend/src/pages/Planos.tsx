import { useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import Navbar from '../components/Navbar'
import api from '../services/api'

export default function Planos() {
  const navigate = useNavigate()
  const { user, isVip, isAdmin, daysUntilExpiry, login: _login, updateUser } = useAuth()

  const [trialUsed, setTrialUsed]       = useState<boolean | null>(null)
  const [activating, setActivating]     = useState(false)
  const [activateError, setActivateError] = useState('')
  const [activated, setActivated]       = useState(false)

  const isTrial = user?.plan === 'trial'

  useEffect(() => {
    if (!user) return
    api.get('/auth/me')
      .then(r => setTrialUsed(r.data.trial_used ?? false))
      .catch(() => setTrialUsed(true)) // fallback seguro: assume usado
  }, [user])

  const handleActivateTrial = async () => {
    setActivating(true)
    setActivateError('')
    try {
      const { data } = await api.post('/auth/activate-trial')
      // Token vai para cookie httpOnly via Set-Cookie — não armazenamos no localStorage
      updateUser({ plan: 'trial', expires_at: data.expires_at })
      setActivated(true)
      setTrialUsed(true)
    } catch (e: any) {
      setActivateError(e?.response?.data?.detail ?? 'Erro ao ativar trial. Tente novamente.')
    } finally {
      setActivating(false)
    }
  }

  const isEligibleForTrial = user && user.plan === 'free' && trialUsed === false

  return (
    <div className="min-h-screen bg-black">
      <Navbar />

      <div className="bg-zinc-950 border-b border-zinc-800">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="text-zinc-500 hover:text-white transition-colors text-lg leading-none">←</button>
          <div>
            <h1 className="text-base font-black text-white">Meu Plano</h1>
            <p className="text-zinc-500 text-xs mt-0.5">Status e detalhes do seu acesso atual</p>
          </div>
        </div>
      </div>

      <main className="max-w-4xl mx-auto px-4 py-10 space-y-8">

        {/* ── TRIAL ATIVADO (sucesso) ───────────────────────────────────────── */}
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

        {/* ── STATUS DO PLANO ATUAL ─────────────────────────────────────────── */}
        {user && !activated && (
          <>
            {(isTrial || (isVip && !isTrial)) && (() => {
              const totalDays = isTrial ? 2 : 30
              const remaining = daysUntilExpiry ?? 0
              const pct = Math.max(0, Math.min(100, (remaining / totalDays) * 100))
              const expiryDate = user.expires_at
                ? new Date(user.expires_at).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' })
                : null
              const urgent = remaining <= (isTrial ? 1 : 5)
              const color = isTrial ? 'green' : 'yellow'

              return (
                <div className={`relative bg-zinc-900 border ${urgent ? 'border-red-500/40' : `border-${color}-500/20`} rounded-2xl p-6 overflow-hidden`}>
                  <div className={`absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-${color}-500/60 to-transparent`} />

                  <div className="flex items-start justify-between gap-4 mb-5">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs font-black uppercase tracking-widest ${isTrial ? 'text-green-400' : 'text-yellow-400'}`}>
                          {isTrial ? 'Teste VIP' : 'Plano VIP'}
                        </span>
                        {urgent && (
                          <span className="text-[10px] bg-red-500/20 text-red-400 border border-red-500/30 px-2 py-0.5 rounded-full font-bold uppercase">
                            Expirando
                          </span>
                        )}
                      </div>
                      <p className="text-white font-black text-2xl">
                        {remaining <= 0 ? 'Expirado' : `${remaining} dia${remaining === 1 ? '' : 's'}`}
                        {remaining > 0 && <span className="text-zinc-500 font-normal text-sm ml-1">restantes</span>}
                      </p>
                      {expiryDate && (
                        <p className="text-zinc-500 text-xs mt-1">
                          {remaining <= 0 ? 'Expirou em' : 'Expira em'} {expiryDate}
                        </p>
                      )}
                    </div>
                    <button onClick={() => navigate('/checkout')}
                      className="shrink-0 bg-yellow-400 hover:bg-yellow-300 text-black font-black text-xs px-4 py-2.5 rounded-xl transition-colors">
                      {isTrial ? 'Assinar VIP' : 'Renovar'}
                    </button>
                  </div>

                  {/* Barra de progresso */}
                  <div className="space-y-1.5">
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

                  {/* Features resumidas */}
                  <div className="grid grid-cols-2 gap-2 mt-5">
                    {['Picks VIP (10–20/dia)', 'Múltiplas por IA', 'Alavancagem Copa 2026', 'Agente IA'].map(f => (
                      <div key={f} className="flex items-center gap-1.5 text-xs text-zinc-400">
                        <svg className="w-3.5 h-3.5 text-green-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        {f}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}

            {!isVip && !isAdmin && user.plan === 'free' && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex items-center gap-4">
                <div className="w-10 h-10 bg-zinc-800 rounded-full flex items-center justify-center shrink-0 text-zinc-500 font-black text-sm">F</div>
                <div className="flex-1">
                  <p className="text-white font-bold text-sm">Plano Free</p>
                  <p className="text-zinc-500 text-xs mt-0.5">1 pick gratuito por dia · sem expiração</p>
                </div>
                <button onClick={() => navigate('/checkout')}
                  className="shrink-0 bg-yellow-400 hover:bg-yellow-300 text-black font-black text-xs px-4 py-2 rounded-xl transition-colors">
                  Upgrade VIP
                </button>
              </div>
            )}

            {isAdmin && (
              <div className="bg-purple-400/10 border border-purple-400/20 rounded-2xl p-5">
                <p className="text-purple-400 font-black text-sm">Conta Admin — acesso irrestrito e permanente.</p>
              </div>
            )}
          </>
        )}

        {/* ── CARD TRIAL — só para free elegível ───────────────────────────── */}
        {isEligibleForTrial && !activated && (
          <div className="relative bg-zinc-900 border border-green-500/50 rounded-2xl p-7 overflow-hidden">
            <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-green-500 to-transparent" />
            <div className="absolute top-4 right-4">
              <span className="bg-green-500 text-black text-[10px] font-black px-2.5 py-1 rounded-full uppercase tracking-wider">
                Sem cartão
              </span>
            </div>
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 bg-green-500/10 border border-green-500/30 rounded-xl flex items-center justify-center shrink-0 mt-0.5">
                <svg className="w-6 h-6 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v13m0-13V6a2 2 0 112 2h-2zm0 0V5.5A2.5 2.5 0 109.5 8H12zm-7 4h14M5 12a2 2 0 110-4h14a2 2 0 110 4M5 12v7a2 2 0 002 2h10a2 2 0 002-2v-7" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-xs text-green-500 font-bold uppercase tracking-widest mb-1">Disponível para você</p>
                <h2 className="text-xl font-black text-white mb-1">2 dias de VIP grátis</h2>
                <p className="text-zinc-400 text-sm mb-4">
                  Acesse todos os picks VIP, Múltiplas, Alavancagem Copa e o Agente IA por 2 dias completos.
                  Sem cartão de crédito, sem compromisso. Expira e volta para Free automaticamente.
                </p>
                <ul className="space-y-1.5 mb-5">
                  {['Picks VIP completos (10–20/dia)', 'Múltiplas e Alavancagem Copa 2026', 'Agente IA de futebol', 'Histórico completo com ROI'].map(f => (
                    <li key={f} className="flex items-center gap-2 text-sm text-zinc-300">
                      <Check />{f}
                    </li>
                  ))}
                </ul>
                {activateError && (
                  <p className="text-red-400 text-xs mb-3">{activateError}</p>
                )}
                <button onClick={handleActivateTrial} disabled={activating}
                  className="bg-green-500 hover:bg-green-400 disabled:opacity-60 text-black font-black px-7 py-3 rounded-xl text-sm transition-colors flex items-center gap-2">
                  {activating ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                      </svg>
                      Ativando...
                    </>
                  ) : 'Ativar 2 dias VIP gratuito'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── CTA UPGRADE (free sem trial) ─────────────────────────────────── */}
        {user && !isAdmin && !isVip && !isEligibleForTrial && !activated && (
          <div className="bg-zinc-900 border border-yellow-400/20 rounded-2xl p-6 flex items-center justify-between gap-4">
            <div>
              <p className="text-white font-black text-sm">Quer acesso VIP completo?</p>
              <p className="text-zinc-500 text-xs mt-0.5">Picks VIP, Múltiplas, Alavancagem e Agente IA a partir de R$ 29,90/mês</p>
            </div>
            <button onClick={() => navigate('/checkout')}
              className="shrink-0 bg-yellow-400 hover:bg-yellow-300 text-black font-black text-xs px-5 py-2.5 rounded-xl transition-colors">
              Assinar VIP
            </button>
          </div>
        )}

      </main>
    </div>
  )
}
