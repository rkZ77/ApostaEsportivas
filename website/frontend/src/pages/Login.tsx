import { useState, FormEvent, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

function formatCPF(v: string) {
  const d = v.replace(/\D/g, '').slice(0, 11)
  if (d.length <= 3) return d
  if (d.length <= 6) return `${d.slice(0, 3)}.${d.slice(3)}`
  if (d.length <= 9) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6)}`
  return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`
}

function validateCPF(cpf: string): boolean {
  const d = cpf.replace(/\D/g, '')
  if (d.length !== 11) return false
  if (/^(\d)\1{10}$/.test(d)) return false
  let s = 0
  for (let i = 0; i < 9; i++) s += parseInt(d[i]) * (10 - i)
  const d1 = (s * 10 % 11) % 10
  if (d1 !== parseInt(d[9])) return false
  s = 0
  for (let i = 0; i < 10; i++) s += parseInt(d[i]) * (11 - i)
  const d2 = (s * 10 % 11) % 10
  return d2 === parseInt(d[10])
}

function validateEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim())
}

type LoginMethod = 'username' | 'email' | 'cpf'

export default function Login() {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [mode, setMode]             = useState<'login' | 'register'>('login')
  const [loginMethod, setLoginMethod] = useState<LoginMethod>('username')

  // Login fields
  const [loginUsername, setLoginUsername] = useState('')
  const [loginEmail, setLoginEmail]       = useState('')
  const [loginCpf, setLoginCpf]           = useState('')

  // Register fields
  const [name, setName]         = useState('')
  const [username, setUsername] = useState('')
  const [cpf, setCpf]           = useState('')
  const [phone, setPhone]       = useState('')
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [refCode, setRefCode]   = useState('')

  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const ref = searchParams.get('ref')
    if (ref) {
      setRefCode(ref.toUpperCase())
      setMode('register')
      localStorage.setItem('ref_code', ref.toUpperCase())
    } else {
      const stored = localStorage.getItem('ref_code')
      if (stored) setRefCode(stored)
    }
  }, [])

  const handleLoginCpf = (v: string) => setLoginCpf(formatCPF(v))
  const handleRegCpf   = (v: string) => setCpf(formatCPF(v))

  const getIdentifier = () => {
    if (loginMethod === 'username') return loginUsername.trim()
    if (loginMethod === 'email')    return loginEmail.trim()
    return loginCpf.trim()
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (mode === 'login') {
      const id = getIdentifier()
      if (!id) { setError('Preencha o campo de identificação.'); return }
      if (loginMethod === 'email' && !validateEmail(id)) { setError('Email inválido.'); return }
      if (loginMethod === 'cpf' && id.replace(/\D/g, '').length !== 11) { setError('CPF inválido.'); return }
    } else {
      if (!name.trim() || name.trim().split(' ').filter(Boolean).length < 2) {
        setError('Informe seu nome completo (nome e sobrenome).')
        return
      }
      if (!validateEmail(email)) { setError('Email inválido.'); return }
      if (!validateCPF(cpf)) { setError('CPF inválido. Verifique os dígitos informados.'); return }
      if (phone.replace(/\D/g, '').length < 10) {
        setError('Informe um telefone ou WhatsApp válido com DDD.')
        return
      }
      if (password.length < 8) { setError('A senha deve ter pelo menos 8 caracteres.'); return }
      if (password !== confirm) { setError('As senhas não coincidem.'); return }
    }

    setLoading(true)
    try {
      if (mode === 'login') {
        await login(getIdentifier(), password)
      } else {
        const cleanUsername = username.trim() || undefined
        await register(name.trim(), email, password, phone, cpf.replace(/\D/g, ''), cleanUsername, refCode || undefined)
        localStorage.removeItem('ref_code')
      }
      navigate('/picks')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao autenticar')
    } finally {
      setLoading(false)
    }
  }

  const switchMode = () => {
    setMode(m => m === 'login' ? 'register' : 'login')
    setError('')
    setLoginUsername(''); setLoginEmail(''); setLoginCpf('')
    setName(''); setUsername(''); setCpf(''); setPhone(''); setConfirm('')
  }

  const loginTabs: { key: LoginMethod; label: string }[] = [
    { key: 'username', label: 'Usuário' },
    { key: 'email',    label: 'E-mail'  },
    { key: 'cpf',      label: 'CPF'     },
  ]

  return (
    <div className="min-h-screen bg-black flex items-stretch">

      {/* Left panel — branding */}
      <div className="hidden lg:flex lg:w-1/2 flex-col items-center justify-center relative overflow-hidden bg-zinc-950 border-r border-zinc-800">
        <div className="absolute inset-0 bg-gradient-radial from-green-500/10 via-transparent to-transparent" />
        <div className="absolute top-0 left-0 w-full h-1 bg-green-500" />

        <img src="/trofeu.png" alt="" aria-hidden="true"
          className="absolute inset-0 w-full h-full object-contain opacity-[0.06] pointer-events-none select-none"
          onError={e => (e.currentTarget.style.display = 'none')} />

        <div className="relative z-10 text-center px-12">
          <img src="/logo.png" alt="Pick IA" className="w-52 h-52 mx-auto mb-8 drop-shadow-[0_0_30px_rgba(0,204,0,0.3)]" />
          <h1 className="text-5xl font-black text-white tracking-tight mb-3">Pick<span className="text-green-500">IA</span></h1>
          <p className="text-zinc-400 text-lg mb-8">Tips esportivas geradas por Inteligência Artificial</p>
          <div className="grid grid-cols-3 gap-4 mt-6">
            {['IA Avançada', 'Copa 2026', '+600 picks'].map(label => (
              <div key={label} className="bg-zinc-900/80 border border-zinc-800 rounded-xl p-3 text-center">
                <div className="text-xs text-zinc-400 font-semibold uppercase tracking-wider">{label}</div>
              </div>
            ))}
          </div>
          <a href="https://www.instagram.com/hpstips/" target="_blank" rel="noopener noreferrer"
            className="mt-8 flex items-center gap-2 text-zinc-500 hover:text-pink-400 transition-colors justify-center">
            <img src="/instagram.png" alt="Instagram" className="w-5 h-5 rounded-sm object-cover" />
            <span className="text-sm font-semibold">@hpstips</span>
          </a>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 overflow-y-auto">
        <div className="w-full max-w-sm">

          {/* Mobile logo */}
          <div className="flex lg:hidden flex-col items-center mb-10">
            <img src="/logo.png" alt="Pick IA" className="w-24 h-24 mb-3" />
            <h1 className="text-3xl font-black text-white">Pick<span className="text-green-500">IA</span></h1>
          </div>

          <h2 className="text-2xl font-bold text-white mb-1">
            {mode === 'login' ? 'Bem-vindo de volta' : 'Criar conta'}
          </h2>
          <p className="text-zinc-500 mb-6 text-sm">
            {mode === 'login' ? 'Entre para acessar suas tips' : '2 dias de teste VIP grátis com CPF válido'}
          </p>

          <form onSubmit={submit} className="space-y-4">

            {/* ── LOGIN ─────────────────────────────────────────────────────── */}
            {mode === 'login' && (
              <>
                <div>
                  <label className="block text-sm text-zinc-400 mb-2 font-medium">Login ID</label>
                  {/* Tabs estilo Betano */}
                  <div className="flex rounded-xl overflow-hidden border border-zinc-700 mb-3">
                    {loginTabs.map(tab => (
                      <button
                        key={tab.key}
                        type="button"
                        onClick={() => { setLoginMethod(tab.key); setError('') }}
                        className={`flex-1 py-2 text-xs font-bold transition-colors ${
                          loginMethod === tab.key
                            ? 'bg-green-500 text-black'
                            : 'bg-zinc-900 text-zinc-400 hover:text-white'
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {loginMethod === 'username' && (
                    <input type="text" value={loginUsername}
                      onChange={e => setLoginUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                      required className="input w-full" placeholder="seu_usuario"
                      autoComplete="username" maxLength={20} autoFocus />
                  )}
                  {loginMethod === 'email' && (
                    <input type="email" value={loginEmail}
                      onChange={e => setLoginEmail(e.target.value)}
                      required className="input w-full" placeholder="seu@email.com"
                      autoComplete="email" autoFocus />
                  )}
                  {loginMethod === 'cpf' && (
                    <input type="text" value={loginCpf}
                      onChange={e => handleLoginCpf(e.target.value)}
                      required className="input w-full" placeholder="000.000.000-00"
                      inputMode="numeric" autoComplete="off" autoFocus />
                  )}
                </div>
              </>
            )}

            {/* ── REGISTER ──────────────────────────────────────────────────── */}
            {mode === 'register' && (
              <>
                <div>
                  <label className="block text-sm text-zinc-400 mb-1.5 font-medium">Nome completo</label>
                  <input type="text" value={name}
                    onChange={e => setName(e.target.value)}
                    required className="input" placeholder="Nome e sobrenome"
                    autoComplete="name" />
                </div>
                <div>
                  <label className="block text-sm text-zinc-400 mb-1.5 font-medium">
                    Usuário <span className="text-zinc-600 font-normal">(opcional)</span>
                  </label>
                  <input type="text" value={username}
                    onChange={e => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                    className="input" placeholder="seu_usuario"
                    autoComplete="username" maxLength={20} />
                  <p className="text-xs text-zinc-600 mt-1">3–20 caracteres. Letras, números e _. Gerado automaticamente se vazio.</p>
                </div>
                <div>
                  <label className="block text-sm text-zinc-400 mb-1.5 font-medium">Email</label>
                  <input type="email" value={email}
                    onChange={e => setEmail(e.target.value)}
                    required className="input" placeholder="seu@email.com"
                    autoComplete="email" />
                </div>
                <div>
                  <label className="block text-sm text-zinc-400 mb-1.5 font-medium">CPF</label>
                  <input type="text" value={cpf}
                    onChange={e => handleRegCpf(e.target.value)}
                    required className="input" placeholder="000.000.000-00"
                    inputMode="numeric" autoComplete="off" />
                  <p className="text-xs text-zinc-600 mt-1">1 conta por CPF. Necessário para o teste grátis.</p>
                </div>
                <div>
                  <label className="block text-sm text-zinc-400 mb-1.5 font-medium">WhatsApp / Telefone</label>
                  <input type="tel" value={phone}
                    onChange={e => setPhone(e.target.value)}
                    required className="input" placeholder="(11) 99999-9999"
                    inputMode="numeric" autoComplete="tel" />
                </div>
              </>
            )}

            {/* Senha — comum aos dois modos */}
            <div>
              <label className="block text-sm text-zinc-400 mb-1.5 font-medium">Senha</label>
              <input type="password" value={password}
                onChange={e => setPassword(e.target.value)}
                required className="input"
                placeholder={mode === 'register' ? 'Mínimo 8 caracteres' : '••••••••'}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
            </div>

            {mode === 'register' && (
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5 font-medium">Confirmar senha</label>
                <input type="password" value={confirm}
                  onChange={e => setConfirm(e.target.value)}
                  required className="input" placeholder="Repita a senha"
                  autoComplete="new-password" />
              </div>
            )}

            {mode === 'register' && refCode && (
              <div className="bg-green-500/10 border border-green-500/30 text-green-400 rounded-xl px-4 py-3 text-xs flex items-center gap-2">
                <span>🎉</span>
                <span>Código de indicação <strong>{refCode}</strong> aplicado!</span>
              </div>
            )}

            {error && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl px-4 py-3 text-sm">
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full text-center mt-2">
              {loading ? 'Aguarde...' : mode === 'login' ? 'Entrar' : 'Criar conta grátis'}
            </button>
          </form>

          <div className="mt-5 text-center space-y-3">
            {mode === 'login' && (
              <Link to="/forgot-password" className="block text-zinc-500 text-sm hover:text-zinc-300 transition-colors">
                Esqueceu sua senha? <span className="text-green-500 font-semibold">Clique aqui</span>
              </Link>
            )}
            <div>
              <span className="text-zinc-500 text-sm">
                {mode === 'login' ? 'Não tem conta? ' : 'Já tem conta? '}
              </span>
              <button
                onClick={switchMode}
                className="text-green-500 text-sm font-semibold hover:text-green-400 transition-colors"
              >
                {mode === 'login' ? 'Criar conta grátis' : 'Entrar'}
              </button>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
