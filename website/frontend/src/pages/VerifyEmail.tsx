import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'

export default function VerifyEmail() {
  const [params] = useSearchParams()
  const navigate  = useNavigate()
  const { user, updateUser } = useAuth()
  const token = params.get('token')

  const [state, setState]     = useState<'pending' | 'loading' | 'success' | 'error'>('pending')
  const [resending, setResending] = useState(false)
  const [resent, setResent]   = useState(false)
  const [errMsg, setErrMsg]   = useState('')

  useEffect(() => {
    if (!token) return
    setState('loading')
    api.post('/auth/verify-email', { token })
      .then(() => {
        updateUser({ email_verified: true })
        setState('success')
        setTimeout(() => navigate('/picks'), 2500)
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
    } catch {
      /* silent */
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center">

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
            <h1 className="text-xl font-bold text-white mb-2">E-mail confirmado!</h1>
            <p className="text-zinc-400 text-sm">Redirecionando para seus picks…</p>
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
                className="w-full py-3 rounded-xl bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white font-bold text-sm transition-colors"
              >
                {resent ? 'E-mail reenviado!' : resending ? 'Enviando…' : 'Reenviar e-mail de verificação'}
              </button>
            )}
          </>
        )}

        {state === 'pending' && (
          <>
            <div className="w-14 h-14 rounded-full bg-blue-500/10 flex items-center justify-center mx-auto mb-5">
              <svg className="w-7 h-7 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-white mb-2">Verifique seu e-mail</h1>
            <p className="text-zinc-400 text-sm mb-1">
              Enviamos um link de confirmação para <span className="text-white font-medium">{user?.email ?? 'seu e-mail'}</span>.
            </p>
            <p className="text-zinc-600 text-xs mb-7">Clique no link do e-mail para ativar sua conta e acessar seus picks.</p>

            {resent ? (
              <p className="text-green-400 text-sm font-semibold mb-4">E-mail reenviado! Verifique sua caixa de entrada.</p>
            ) : (
              <button
                onClick={handleResend}
                disabled={resending}
                className="w-full py-3 rounded-xl border border-zinc-700 hover:border-green-500/40 hover:text-green-400 text-zinc-400 font-semibold text-sm transition-colors disabled:opacity-50 mb-3"
              >
                {resending ? 'Enviando…' : 'Reenviar e-mail'}
              </button>
            )}

            <button
              onClick={() => navigate('/picks')}
              className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
            >
              Já confirmei, ir para picks →
            </button>
          </>
        )}
      </div>
    </div>
  )
}
