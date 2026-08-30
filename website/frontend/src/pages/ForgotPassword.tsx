import { useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import api from '../services/api'
import { getPasswordStrength } from '../utils/passwordStrength'
import { useRevelacao, classesRevelacao, FADE_REVELACAO_MS } from '../hooks/useRevelacao'

export default function ForgotPassword() {
  /* Portão de revelação · o mesmo das telas com PageShell. Também é quem
     encerra a barra verde do index.html. Ver hooks/useRevelacao. */
  const revelado = useRevelacao()
  const navigate = useNavigate()
  // O link do e-mail chega com ?email=... Sem isso, quem clica cai no passo 1
  // e o unico jeito de sair dali e' pedir OUTRO codigo · o que acabou de
  // chegar seria invalidado pelo proprio clique.
  const [params] = useSearchParams()
  const emailDoLink = params.get('email') || ''
  const [step, setStep]         = useState<'email' | 'code'>(emailDoLink ? 'code' : 'email')
  const [email, setEmail]       = useState(emailDoLink)
  const [code, setCode]         = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [showPassword, setShowPassword] = useState(false)
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
    const { score } = getPasswordStrength(password)
    if (score < 3) { setError('Senha deve ter no mínimo 10 caracteres, 1 letra maiúscula e 1 número'); return }
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
    <div className={`min-h-screen bg-surface-0 flex items-center justify-center px-4 ${classesRevelacao(revelado)}`} style={{ transitionDuration: `${FADE_REVELACAO_MS}ms` }} aria-busy={!revelado}>
      <Helmet>
        <title>Recuperar senha · Pick IA</title>
        <meta name="robots" content="noindex, nofollow" />
      </Helmet>
      <div className="w-full max-w-sm">
        <button onClick={goBack}
          className="text-ink-3 hover:text-ink-1 transition-colors text-sm mb-6 flex items-center gap-1">
          ← Voltar
        </button>

        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-ink-1">Recuperar senha</h1>
          <p className="text-ink-3 text-sm mt-2">
            {step === 'email'
              ? 'Enviaremos um código de 6 dígitos para o seu email'
              : `Código enviado para ${email}`}
          </p>
        </div>

        {done ? (
          <div className="card p-6 text-center space-y-4">
            <div className="w-12 h-12 bg-green-500/10 rounded-full flex items-center justify-center mx-auto">
              <svg className="w-6 h-6 text-accent-ink" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-ink-1 font-semibold">Senha atualizada!</p>
            <p className="text-ink-3 text-sm">Redirecionando para o login...</p>
          </div>

        ) : step === 'email' ? (
          <form onSubmit={handleEmail} className="card p-6 space-y-4">
            <div>
              <label className="text-xs text-ink-3 block mb-1.5">Email</label>
              <input
                type="email"
                className="input w-full"
                placeholder="seu@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoComplete="email"
                required
                autoFocus
              />
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button type="submit" disabled={loading} className="btn-primary w-full py-3">
              {loading ? 'Enviando...' : 'Enviar código'}
            </button>
            <Link to="/login"
              className="block text-center text-ink-4 text-xs hover:text-ink-2 transition-colors">
              Lembrou a senha? Entrar
            </Link>
          </form>

        ) : (
          <form onSubmit={handleReset} className="card p-6 space-y-4">
            <div>
              <label className="text-xs text-ink-3 block mb-1.5">Código recebido no email</label>
              <input
                type="text"
                inputMode="numeric"
                className="input w-full text-center text-lg font-bold"
                placeholder="000000"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                maxLength={6}
                required
                autoFocus
              />
            </div>
            <div>
              <label className="text-xs text-ink-3 block mb-1.5">Nova senha</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="input w-full pr-10"
                  placeholder="Mínimo 10 caracteres"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                />
                <button type="button" onClick={() => setShowPassword(v => !v)}
                  aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink-2 transition-colors">
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {password.length > 0 && (() => {
                const { score, checks } = getPasswordStrength(password)
                const barColors = ['bg-red-500', 'bg-yellow-400', 'bg-green-500']
                const labels    = ['Fraca', 'Boa', 'Forte']
                const color     = barColors[score - 1] ?? 'bg-surface-3'
                const label     = score > 0 ? labels[score - 1] : ''
                return (
                  <div className="mt-2 space-y-2">
                    <div className="flex items-center gap-1.5">
                      {[1, 2, 3].map(i => (
                        <div key={i} className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${i <= score ? color : 'bg-surface-2'}`} />
                      ))}
                      {label && <span className={`text-[11px] font-semibold ml-1 shrink-0 ${color.replace('bg-', 'text-')}`}>{label}</span>}
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                      {checks.map(c => (
                        <div key={c.label} className="flex items-center gap-1.5">
                          <span className={`text-[10px] ${c.ok ? 'text-accent-ink' : 'text-ink-4'}`}>{c.ok ? '✓' : '○'}</span>
                          <span className={`text-[11px] ${c.ok ? 'text-ink-2' : 'text-ink-4'}`}>{c.label}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })()}
            </div>
            <div>
              <label className="text-xs text-ink-3 block mb-1.5">Confirmar senha</label>
              <input
                type={showPassword ? 'text' : 'password'}
                className="input w-full"
                placeholder="Repita a nova senha"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button type="submit" disabled={loading} className="btn-primary w-full py-3">
              {loading ? 'Salvando...' : 'Redefinir senha'}
            </button>
            <button type="button"
              onClick={() => { setStep('email'); setError('') }}
              className="w-full text-center text-ink-4 text-xs hover:text-ink-2 transition-colors">
              Reenviar código
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
