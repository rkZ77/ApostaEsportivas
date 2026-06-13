import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'

export default function ForgotPassword() {
  const navigate = useNavigate()
  const [step, setStep]         = useState<'email' | 'code'>('email')
  const [email, setEmail]       = useState('')
  const [code, setCode]         = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [loading, setLoading]   = useState(false)
  const [done, setDone]         = useState(false)
  const [error, setError]       = useState('')

  const handleEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      await api.post('/auth/forgot-password', { email })
      setStep('code')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao enviar código')
    } finally {
      setLoading(false)
    }
  }

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== confirm) { setError('As senhas não coincidem'); return }
    if (password.length < 8)  { setError('Mínimo 8 caracteres'); return }
    setLoading(true); setError('')
    try {
      await api.post('/auth/reset-password', { email, code, new_password: password })
      setDone(true)
      setTimeout(() => navigate('/login'), 3000)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Código inválido ou expirado')
    } finally {
      setLoading(false)
    }
  }

  const goBack = () => {
    if (step === 'code') { setStep('email'); setError('') }
    else navigate(-1)
  }

  return (
    <div className="min-h-screen bg-black flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <button onClick={goBack}
          className="text-zinc-500 hover:text-white transition-colors text-sm mb-6 flex items-center gap-1">
          ← Voltar
        </button>

        <div className="text-center mb-8">
          <h1 className="text-2xl font-black text-white">Recuperar senha</h1>
          <p className="text-zinc-500 text-sm mt-2">
            {step === 'email'
              ? 'Enviaremos um código de 6 dígitos para o seu email'
              : `Código enviado para ${email}`}
          </p>
        </div>

        {done ? (
          <div className="card p-6 text-center space-y-4">
            <div className="w-12 h-12 bg-green-500/10 rounded-full flex items-center justify-center mx-auto">
              <svg className="w-6 h-6 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-white font-semibold">Senha atualizada!</p>
            <p className="text-zinc-500 text-sm">Redirecionando para o login...</p>
          </div>

        ) : step === 'email' ? (
          <form onSubmit={handleEmail} className="card p-6 space-y-4">
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Email</label>
              <input
                type="email"
                className="input w-full"
                placeholder="seu@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button type="submit" disabled={loading} className="btn-primary w-full py-3">
              {loading ? 'Enviando...' : 'Enviar código'}
            </button>
            <Link to="/login"
              className="block text-center text-zinc-600 text-xs hover:text-zinc-400 transition-colors">
              Lembrou a senha? Entrar
            </Link>
          </form>

        ) : (
          <form onSubmit={handleReset} className="card p-6 space-y-4">
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Código recebido no email</label>
              <input
                type="text"
                inputMode="numeric"
                className="input w-full text-center tracking-widest text-lg font-bold"
                placeholder="000000"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                maxLength={6}
                required
                autoFocus
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Nova senha</label>
              <input
                type="password"
                className="input w-full"
                placeholder="Mínimo 8 caracteres"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Confirmar senha</label>
              <input
                type="password"
                className="input w-full"
                placeholder="Repita a nova senha"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button type="submit" disabled={loading} className="btn-primary w-full py-3">
              {loading ? 'Salvando...' : 'Redefinir senha'}
            </button>
            <button type="button"
              onClick={() => { setStep('email'); setError('') }}
              className="w-full text-center text-zinc-600 text-xs hover:text-zinc-400 transition-colors">
              Reenviar código
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
