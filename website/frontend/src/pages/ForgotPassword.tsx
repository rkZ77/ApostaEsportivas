import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../services/api'

export default function ForgotPassword() {
  const navigate              = useNavigate()
  const [email, setEmail]     = useState('')
  const [sent, setSent]       = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao enviar email')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-black flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <button onClick={() => navigate(-1)} className="text-zinc-500 hover:text-white transition-colors text-sm mb-6 flex items-center gap-1">
          ← Voltar
        </button>
        <div className="text-center mb-8">
          <h1 className="text-2xl font-black text-white">Recuperar senha</h1>
          <p className="text-zinc-500 text-sm mt-2">Enviaremos um link para o seu email</p>
        </div>

        {sent ? (
          <div className="card p-6 text-center space-y-4">
            <div className="w-12 h-12 bg-green-500/10 rounded-full flex items-center justify-center mx-auto">
              <span className="text-green-500 text-xl">✓</span>
            </div>
            <p className="text-white font-semibold">Email enviado!</p>
            <p className="text-zinc-500 text-sm">
              Se houver uma conta com esse email, você receberá as instruções em breve. Verifique também o spam.
            </p>
            <Link to="/login" className="block text-green-500 text-sm hover:text-green-400 transition-colors mt-2">
              Voltar ao login
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="card p-6 space-y-4">
            <div>
              <label className="text-xs text-zinc-500 block mb-1.5">Email</label>
              <input
                type="email"
                className="input w-full"
                placeholder="seu@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button type="submit" disabled={loading} className="btn-primary w-full py-3">
              {loading ? 'Enviando...' : 'Enviar link de recuperação'}
            </button>
            <Link to="/login" className="block text-center text-zinc-600 text-xs hover:text-zinc-400 transition-colors">
              Lembrou a senha? Entrar
            </Link>
          </form>
        )}
      </div>
    </div>
  )
}
