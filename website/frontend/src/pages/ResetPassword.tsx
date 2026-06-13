import { useState, useEffect } from 'react'
import { useSearchParams, Link, useNavigate } from 'react-router-dom'
import api from '../services/api'

export default function ResetPassword() {
  const [params]              = useSearchParams()
  const navigate              = useNavigate()
  const token                 = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [loading, setLoading]   = useState(false)
  const [done, setDone]         = useState(false)
  const [error, setError]       = useState('')

  useEffect(() => {
    if (!token) setError('Token inválido ou expirado.')
  }, [token])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== confirm) { setError('As senhas não coincidem'); return }
    if (password.length < 6)  { setError('Mínimo 6 caracteres'); return }
    setLoading(true); setError('')
    try {
      await api.post('/auth/reset-password', { token, new_password: password })
      setDone(true)
      setTimeout(() => navigate('/login'), 3000)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Token inválido ou expirado')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-black flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <button onClick={() => navigate('/login')} className="text-zinc-500 hover:text-white transition-colors text-sm mb-6 flex items-center gap-1">
          ← Voltar ao login
        </button>
        <div className="text-center mb-8">
          <h1 className="text-2xl font-black text-white">Nova senha</h1>
          <p className="text-zinc-500 text-sm mt-2">Digite sua nova senha abaixo</p>
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
        ) : (
          <form onSubmit={handleSubmit} className="card p-6 space-y-4">
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Nova senha</label>
              <input
                type="password"
                className="input w-full"
                placeholder="Mínimo 6 caracteres"
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
            <button type="submit" disabled={loading || !token} className="btn-primary w-full py-3">
              {loading ? 'Salvando...' : 'Salvar nova senha'}
            </button>
            <Link to="/login" className="block text-center text-zinc-600 text-xs hover:text-zinc-400 transition-colors">
              Voltar ao login
            </Link>
          </form>
        )}
      </div>
    </div>
  )
}
