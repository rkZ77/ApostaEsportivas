import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'

export default function VerifyEmail() {
  const [params] = useSearchParams()
  const navigate  = useNavigate()
  const { user, updateUser } = useAuth()
  const token = params.get('token')

  const [state, setState]         = useState<'redirect' | 'loading' | 'success' | 'error'>(token ? 'loading' : 'redirect')
  const [resending, setResending] = useState(false)
  const [resent, setResent]       = useState(false)
  const [cooldown, setCooldown]   = useState(0)
  const [errMsg, setErrMsg]       = useState('')

  useEffect(() => {
    if (cooldown <= 0) return
    const t = setTimeout(() => setCooldown(c => c - 1), 1000)
    return () => clearTimeout(t)
  }, [cooldown])

  // Troca de e-mail
  const [showChangeEmail, setShowChangeEmail] = useState(false)
  const [newEmail, setNewEmail]               = useState('')
  const [changingEmail, setChangingEmail]     = useState(false)
  const [changeEmailErr, setChangeEmailErr]   = useState('')
  const [emailChanged, setEmailChanged]       = useState('')

  useEffect(() => {
    if (state === 'redirect') { navigate('/picks', { replace: true }); return }
    if (!token) return
    setState('loading')
    api.post('/auth/verify-email', { token })
      .then(() => {
        updateUser({ email_verified: true })
        setState('success')
        setTimeout(() => navigate('/picks'), 2000)
      })
      .catch((err) => {
        setErrMsg(err.response?.data?.detail || 'Link inválido ou expirado.')
        setState('error')
      })
  }, [token])

  const handleResend = async () => {
    setResending(true)
    try {
      await api.post('/auth/resend-verification')
      setResent(true)
      setCooldown(60)
    } catch {
      /* silent */
    } finally {
      setResending(false)
    }
  }

  const handleChangeEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setChangeEmailErr('')
    setChangingEmail(true)
    try {
      const { data } = await api.post('/auth/change-email', { new_email: newEmail })
      updateUser({ email: data.email, email_verified: false })
      setEmailChanged(data.email)
      setShowChangeEmail(false)
      setResent(false)
    } catch (err: any) {
      setChangeEmailErr(err.response?.data?.detail || 'Erro ao alterar e-mail')
    } finally {
      setChangingEmail(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-lg p-8 text-center">

        {state === 'loading' && (
          <>
            <div className="w-14 h-14 rounded-full bg-green-500/10 flex items-center justify-center mx-auto mb-5">
              <div className="w-6 h-6 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
            </div>
            <h1 className="text-xl font-bold text-white mb-2">Verificando…</h1>
            <p className="text-zinc-500 text-sm">Aguarde um momento.</p>
          </>
        )}

        {state === 'success' && (
          <>
            <div className="w-14 h-14 rounded-full bg-green-500/15 flex items-center justify-center mx-auto mb-5">
              <svg className="w-7 h-7 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-white mb-2">E-mail confirmado!</h1>
            <p className="text-zinc-400 text-sm mb-6">Sua conta está ativa. Acessando seus picks…</p>
            <button
              onClick={() => navigate('/picks')}
              className="w-full py-3 rounded-md bg-green-600 hover:bg-green-500 text-white font-bold text-sm transition-colors"
            >
              Acessar picks
            </button>
          </>
        )}

        {state === 'error' && (
          <>
            <div className="w-14 h-14 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-5">
              <svg className="w-7 h-7 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-white mb-2">Link inválido</h1>
            <p className="text-zinc-500 text-sm mb-6">{errMsg}</p>
            {user && (
              <button
                onClick={handleResend}
                disabled={resending || resent}
                className="w-full py-3 rounded-md bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white font-bold text-sm transition-colors"
              >
                {resent ? 'E-mail reenviado!' : resending ? 'Enviando…' : 'Reenviar e-mail de verificação'}
              </button>
            )}
          </>
        )}

        {state === 'redirect' && (
          <>
            <div className="w-14 h-14 rounded-full bg-blue-500/10 flex items-center justify-center mx-auto mb-5">
              <svg className="w-7 h-7 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-white mb-2">Verifique seu e-mail</h1>
            <p className="text-zinc-400 text-sm mb-1">
              Enviamos um link de confirmação para{' '}
              <span className="text-white font-medium">{emailChanged || user?.email || 'seu e-mail'}</span>.
            </p>
            <p className="text-zinc-500 text-xs mb-6">Verifique também a pasta de spam.</p>

            {resent && cooldown > 0 && (
              <p className="text-green-400 text-sm font-semibold mb-4">E-mail reenviado! Verifique também o spam.</p>
            )}

            {/* CTA principal · acessar o site sem verificar */}
            <button
              onClick={() => navigate('/picks')}
              className="w-full py-3 rounded-md bg-green-600 hover:bg-green-500 text-white font-black text-sm transition-colors mb-3"
            >
              Acessar os Picks agora
            </button>

            <div className="flex gap-2 mb-4">
                <button
                  onClick={handleResend}
                  disabled={resending || cooldown > 0}
                  className="flex-1 py-2.5 rounded-md border border-zinc-700 hover:border-zinc-500 text-zinc-400 hover:text-zinc-200 font-semibold text-xs transition-colors disabled:opacity-50"
                >
                  {resending ? 'Enviando…' : cooldown > 0 ? `Reenviar em ${cooldown}s` : 'Reenviar e-mail'}
                </button>
              {!showChangeEmail && (
                <button
                  onClick={() => setShowChangeEmail(true)}
                  className="flex-1 py-2.5 rounded-md border border-blue-500/30 hover:border-blue-400/50 text-blue-400 hover:text-blue-300 font-semibold text-xs transition-colors"
                >
                  E-mail errado? Alterar
                </button>
              )}
            </div>

            {/* Formulário de troca de e-mail */}
            {showChangeEmail && (
              <form onSubmit={handleChangeEmail} className="mt-1 mb-4 text-left space-y-2">
                <p className="text-zinc-400 text-xs font-semibold">Novo e-mail:</p>
                <input
                  type="email"
                  value={newEmail}
                  onChange={e => setNewEmail(e.target.value)}
                  placeholder="novo@email.com"
                  required
                  className="input w-full text-sm"
                />
                {changeEmailErr && <p className="text-red-400 text-xs">{changeEmailErr}</p>}
                <div className="flex gap-2">
                  <button type="submit" disabled={changingEmail}
                    className="flex-1 py-2.5 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-bold text-sm transition-colors">
                    {changingEmail ? 'Salvando…' : 'Salvar e reenviar'}
                  </button>
                  <button type="button" onClick={() => { setShowChangeEmail(false); setChangeEmailErr('') }}
                    className="px-4 py-2.5 rounded-md border border-zinc-700 text-zinc-400 text-sm hover:border-zinc-500 transition-colors">
                    Cancelar
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  )
}
