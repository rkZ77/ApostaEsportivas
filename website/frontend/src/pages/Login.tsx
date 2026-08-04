import { useState, useRef, FormEvent, useEffect } from 'react'
import { Helmet } from 'react-helmet-async'
import { AnimatePresence, motion } from 'framer-motion'
import { PartyPopper, Eye, EyeOff } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { maskPhone } from '../utils/format'
import api from '../services/api'
import Turnstile, { TurnstileHandle } from '../components/Turnstile'
import { getPasswordStrength } from '../utils/passwordStrength'
import { tabFade } from '../lib/motion'

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

// Win rate real (mesma fonte publica de /resultados) -- reforca credibilidade
// bem no ponto de decisao de cadastro, em vez de so listar promessas em texto.
function RealWinRate() {
  const [pct, setPct] = useState<number | null>(null)
  useEffect(() => {
    api.get('/public/results')
      .then(r => {
        const s = r.data?.summary
        if (s && s.total > 0) setPct(Math.round((s.greens / s.total) * 100))
      })
      .catch(() => {})
  }, [])
  if (pct == null) return null
  return (
    <p className="text-xs text-ink-4 mt-5">
      Win rate real auditável:{' '}
      <Link to="/resultados" className="text-green-500 font-bold hover:text-green-400 transition-colors">
        {pct}% <span className="text-ink-4 font-normal">· ver histórico</span>
      </Link>
    </p>
  )
}

type LoginMethod = 'username' | 'email' | 'cpf'

export default function Login() {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [mode, setMode]             = useState<'login' | 'register'>('login')
  const [loginMethod, setLoginMethod] = useState<LoginMethod>('username')
  const [regStep, setRegStep]       = useState<1 | 2>(1)

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

  const [acceptedTerms, setAcceptedTerms] = useState(false)

  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)
  const [kickedDevice, setKickedDevice] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm]   = useState(false)
  const [captchaToken, setCaptchaToken] = useState('')
  const turnstileRef = useRef<TurnstileHandle>(null)

  const redirectTo = (() => {
    const r = searchParams.get('redirect')
    return r && r.startsWith('/') && !r.startsWith('//') ? r : null
  })()

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
    // CTAs de "criar conta" na landing linkam pra cá com ?mode=register,
    // pra abrir direto no formulário de cadastro em vez do de login
    if (searchParams.get('mode') === 'register') setMode('register')
    // Sessão encerrada por novo login em outro dispositivo
    if (searchParams.get('kicked') === '1') {
      const device = localStorage.getItem('session_kicked_device') ?? 'outro dispositivo'
      setKickedDevice(device)
      localStorage.removeItem('session_kicked_device')
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
    } else if (regStep === 1) {
      // Passo 1: só dados de acesso -- CPF/telefone ficam pro passo 2, reduz
      // a primeira tela de 7 campos obrigatórios pra 4.
      if (!name.trim() || name.trim().split(' ').filter(Boolean).length < 2) {
        setError('Informe seu nome completo (nome e sobrenome).')
        return
      }
      if (!username.trim()) { setError('Escolha um nome de usuário.'); return }
      if (!validateEmail(email)) { setError('Email inválido.'); return }
      const { score: pwScore } = getPasswordStrength(password)
      if (pwScore < 3) { setError('A senha deve ter pelo menos 10 caracteres, uma letra maiúscula e um número.'); return }
      setRegStep(2)
      return
    } else {
      if (!validateCPF(cpf)) { setError('CPF inválido. Verifique os dígitos informados.'); return }
      const phoneDigits = phone.replace(/\D/g, '')
      if (phoneDigits.length < 10 || phoneDigits.length > 11) {
        setError('WhatsApp inválido. Use o formato (DDD) 9XXXX-XXXX.')
        return
      }
      if (password !== confirm) { setError('As senhas não coincidem.'); return }
      if (!acceptedTerms) { setError('Você precisa aceitar os Termos de Uso e a Política de Privacidade.'); return }
    }

    setLoading(true)
    try {
      if (mode === 'login') {
        await login(getIdentifier(), password, captchaToken || undefined)
        navigate(redirectTo ?? '/picks')
      } else {
        await register(name.trim(), email, password, phone, cpf.replace(/\D/g, ''), username.trim(), refCode || undefined, acceptedTerms, captchaToken || undefined)
        localStorage.removeItem('ref_code')
        navigate(redirectTo ?? '/picks#guia')
      }
    } catch (err: any) {
      turnstileRef.current?.reset()
      setCaptchaToken('')
      const detail = err.response?.data?.detail
      if (Array.isArray(detail)) {
        const msg = detail.map((e: any) => e.msg || e.message || String(e)).join('. ')
        setError(msg || 'Dados inválidos. Verifique os campos preenchidos.')
      } else if (detail) {
        const msg = String(detail)
        // Cadastro so envia no passo 2, mas alguns erros do backend sao sobre
        // campos do passo 1 (email/usuario) -- sem voltar, o erro aparece
        // numa tela que nao tem o campo problematico visivel.
        if (mode === 'register' && regStep === 2 && /email já cadastrado|usuário já em uso|usuário inválido/i.test(msg)) {
          setRegStep(1)
        }
        setError(msg)
      } else if (!err.response) {
        setError('Não foi possível conectar ao servidor. Verifique sua conexão.')
      } else {
        setError(`Erro ao processar. Tente novamente. (${err.response?.status ?? 'desconhecido'})`)
      }
    } finally {
      setLoading(false)
    }
  }

  const switchMode = () => {
    setMode(m => m === 'login' ? 'register' : 'login')
    setError('')
    setRegStep(1)
    setCaptchaToken('')
    setLoginUsername(''); setLoginEmail(''); setLoginCpf('')
    setName(''); setUsername(''); setCpf(''); setPhone(''); setConfirm('')
  }


  const loginTabs: { key: LoginMethod; label: string }[] = [
    { key: 'username', label: 'Usuário' },
    { key: 'email',    label: 'E-mail'  },
    { key: 'cpf',      label: 'CPF'     },
  ]

  return (
    <div className="min-h-screen bg-surface-0 flex items-stretch">
      <Helmet>
        <title>Entrar · Pick IA</title>
        <meta name="description" content="Acesse sua conta Pick IA para ver os picks da IA do dia, sua banca e seu histórico." />
      </Helmet>


      {/* Left panel · branding */}
      <div className="hidden lg:flex lg:w-1/2 flex-col items-center justify-center relative overflow-hidden bg-surface-0 border-r border-line">
        <div className="absolute inset-0 bg-gradient-radial from-green-500/10 via-transparent to-transparent" />
        <div className="absolute top-0 left-0 w-full h-1 bg-green-500" />

        <div className="relative z-10 text-center px-12">
          <img src="/logo.png" alt="Pick IA" width={160} height={160} className="w-40 h-40 mx-auto mb-6 drop-shadow-[0_0_30px_rgba(0,204,0,0.3)]" />
          <p className="font-display text-4xl font-bold text-ink-1 tracking-tight mb-2">Pick<span className="text-accent">IA</span></p>
          <p className="text-ink-2 text-lg mb-8">Tips esportivas geradas por Inteligência Artificial</p>
          <div className="mt-8 text-left max-w-xs mx-auto">
            <p className="text-ink-3 text-xs font-medium mb-4">No seu trial de 2 dias você acessa:</p>
            <div className="space-y-3">
              {[
                { dot: 'bg-green-500',  text: 'Picks VIP diários com edge positivo' },
                { dot: 'bg-blue-400',   text: 'Múltiplas geradas pela IA' },
                { dot: 'bg-orange-400', text: 'Alavancagem de risco calculado' },
                { dot: 'bg-purple-400', text: 'Agente IA de futebol 24/7' },
              ].map(({ dot, text }) => (
                <div key={text} className="flex items-center gap-3">
                  <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
                  <span className="text-sm text-ink-2">{text}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-ink-4 mt-5">Sem cartão de crédito. Após 2 dias vira Free.</p>
            <RealWinRate />
          </div>
        </div>
      </div>

      {/* Right panel · form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 overflow-y-auto">
        <div className="w-full max-w-sm">

          {/* Mobile logo */}
          <div className="flex lg:hidden flex-col items-center mb-10">
            <img src="/logo.png" alt="Pick IA" width={96} height={96} className="w-24 h-24 mb-3" />
            <p className="font-display text-3xl font-bold text-ink-1">Pick<span className="text-accent">IA</span></p>
          </div>

          {/* Este e o <h1> da pagina. A marca acima e logotipo, e aparecia
              duas vezes como h1 (uma no painel de desktop, outra no bloco
              mobile): so uma renderiza, mas as duas existiam no DOM, entao
              leitor de tela e robo de busca viam duas. */}
          <h1 className="text-2xl font-bold text-ink-1 mb-1">
            {mode === 'login' ? 'Bem-vindo de volta' : '2 dias VIP grátis'}
          </h1>
          <p className="text-ink-3 mb-6 text-sm">
            {mode === 'login' ? 'Entre para acessar seus picks' : 'Acesso completo à plataforma. Sem cartão de crédito.'}
          </p>

          {kickedDevice && (
            <div className="mb-4 rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-4 text-sm">
              <p className="text-yellow-300 font-semibold mb-1">Sessão encerrada</p>
              <p className="text-ink-2">
                Um acesso foi feito de <strong className="text-ink-1">{kickedDevice}</strong> e sua sessão foi encerrada.
              </p>
              <p className="text-ink-2 mt-2">
                Se não foi você,{' '}
                <Link to="/forgot-password" className="text-yellow-400 underline hover:text-yellow-300">
                  redefina sua senha
                </Link>.
              </p>
            </div>
          )}

          <form onSubmit={submit} className="space-y-4">

            {mode === 'login' && (
              <>
                <div>
                  <label htmlFor="login-identifier" className="block text-sm text-ink-2 mb-2 font-medium">Login ID</label>
                  {/* Tabs estilo Betano */}
                  <div className="flex rounded-md overflow-hidden border border-line-strong mb-3">
                    {loginTabs.map(tab => (
                      <button
                        key={tab.key}
                        type="button"
                        onClick={() => { setLoginMethod(tab.key); setError('') }}
                        className={`flex-1 py-2 text-xs font-bold transition-colors ${
                          loginMethod === tab.key
                            ? 'bg-green-500 text-black'
                            : 'bg-surface-1 text-ink-2 hover:text-ink-1'
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  <AnimatePresence mode="wait">
                  {loginMethod === 'username' && (
                    <motion.input key="username" variants={tabFade} initial="hidden" animate="visible" exit="exit"
                      id="login-identifier" type="text" value={loginUsername}
                      onChange={e => setLoginUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                      required className="input w-full" placeholder="seu_usuario"
                      autoComplete="username" maxLength={20} autoFocus />
                  )}
                  {loginMethod === 'email' && (
                    <motion.input key="email" variants={tabFade} initial="hidden" animate="visible" exit="exit"
                      id="login-identifier" type="email" value={loginEmail}
                      onChange={e => setLoginEmail(e.target.value)}
                      required className="input w-full" placeholder="seu@email.com"
                      autoComplete="email" autoFocus />
                  )}
                  {loginMethod === 'cpf' && (
                    <motion.input key="cpf" variants={tabFade} initial="hidden" animate="visible" exit="exit"
                      id="login-identifier" type="text" value={loginCpf}
                      onChange={e => handleLoginCpf(e.target.value)}
                      required className="input w-full" placeholder="000.000.000-00"
                      inputMode="numeric" autoComplete="off" autoFocus />
                  )}
                  </AnimatePresence>
                </div>
              </>
            )}

            {mode === 'register' && (
              <div className="flex items-center gap-2 -mt-1 mb-1">
                {[1, 2].map(step => (
                  <div key={step} className={`h-1 flex-1 rounded-full transition-colors ${step <= regStep ? 'bg-green-500' : 'bg-surface-2'}`} />
                ))}
                <span className="text-[11px] text-ink-3 font-semibold shrink-0 ml-1">Passo {regStep} de 2</span>
              </div>
            )}

            {mode === 'register' && regStep === 1 && (
              <>
                <div>
                  <label htmlFor="reg-name" className="block text-sm text-ink-2 mb-1.5 font-medium">Nome completo</label>
                  <input id="reg-name" type="text" value={name}
                    onChange={e => setName(e.target.value)}
                    required className="input" placeholder="Nome e sobrenome"
                    autoComplete="name" autoFocus />
                </div>
                <div>
                  <label htmlFor="reg-username" className="block text-sm text-ink-2 mb-1.5 font-medium">Usuário</label>
                  <input id="reg-username" type="text" value={username}
                    onChange={e => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                    required className="input" placeholder="seu_usuario"
                    autoComplete="username" maxLength={20} />
                  <p className="text-xs text-ink-4 mt-1">3–20 caracteres. Letras minúsculas, números e _.</p>
                </div>
                <div>
                  <label htmlFor="reg-email" className="block text-sm text-ink-2 mb-1.5 font-medium">Email</label>
                  <input id="reg-email" type="email" value={email}
                    onChange={e => setEmail(e.target.value)}
                    required className="input" placeholder="seu@email.com"
                    autoComplete="email" />
                </div>
              </>
            )}

            {mode === 'register' && regStep === 2 && (
              <button type="button" onClick={() => setRegStep(1)}
                className="text-ink-3 hover:text-ink-2 text-xs font-semibold transition-colors -mt-1 mb-1">
                ← Voltar
              </button>
            )}

            {mode === 'register' && regStep === 2 && (
              <>
                <div>
                  <label htmlFor="reg-cpf" className="block text-sm text-ink-2 mb-1.5 font-medium">CPF</label>
                  <input id="reg-cpf" type="text" value={cpf}
                    onChange={e => handleRegCpf(e.target.value)}
                    required className="input" placeholder="000.000.000-00"
                    inputMode="numeric" autoComplete="off" autoFocus />
                  <p className="text-xs text-ink-4 mt-1">1 trial por CPF. Não compartilhamos seus dados.</p>
                </div>
                <div>
                  <label htmlFor="reg-phone" className="block text-sm text-ink-2 mb-1.5 font-medium">WhatsApp</label>
                  <input id="reg-phone" type="tel" value={phone}
                    onChange={e => setPhone(maskPhone(e.target.value))}
                    required className="input" placeholder="(11) 99999-9999"
                    inputMode="numeric" autoComplete="tel" />
                </div>
              </>
            )}

            {/* Senha · login inteiro, ou passo 1 do cadastro */}
            {(mode === 'login' || (mode === 'register' && regStep === 1)) && (
              <div>
                <label htmlFor="password" className="block text-sm text-ink-2 mb-1.5 font-medium">Senha</label>
                <div className="relative">
                  <input id="password" type={showPassword ? 'text' : 'password'} value={password}
                    onChange={e => setPassword(e.target.value)}
                    required className="input pr-10"
                    placeholder={mode === 'register' ? 'Mínimo 10 caracteres' : '••••••••'}
                    autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
                  <button type="button" onClick={() => setShowPassword(v => !v)}
                    aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink-2 transition-colors">
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {mode === 'register' && password.length > 0 && (() => {
                  const { score, checks } = getPasswordStrength(password)
                  const barColors = ['bg-red-500', 'bg-yellow-400', 'bg-green-500']
                  const labels    = ['Fraca', 'Boa', 'Forte']
                  const color     = barColors[score - 1] ?? 'bg-surface-3'
                  const label     = score > 0 ? labels[score - 1] : ''
                  return (
                    <div className="mt-2 space-y-2">
                      {/* Barras */}
                      <div className="flex items-center gap-1.5">
                        {[1,2,3].map(i => (
                          <div key={i} className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${i <= score ? color : 'bg-surface-2'}`} />
                        ))}
                        {label && <span className={`text-[11px] font-semibold ml-1 shrink-0 ${color.replace('bg-', 'text-')}`}>{label}</span>}
                      </div>
                      {/* Checklist */}
                      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                        {checks.map(c => (
                          <div key={c.label} className="flex items-center gap-1.5">
                            <span className={`text-[10px] ${c.ok ? 'text-green-500' : 'text-ink-4'}`}>{c.ok ? '✓' : '○'}</span>
                            <span className={`text-[11px] ${c.ok ? 'text-ink-2' : 'text-ink-4'}`}>{c.label}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })()}
              </div>
            )}

            {mode === 'register' && regStep === 2 && (
              <div>
                <label htmlFor="password-confirm" className="block text-sm text-ink-2 mb-1.5 font-medium">Confirmar senha</label>
                <div className="relative">
                  <input id="password-confirm" type={showConfirm ? 'text' : 'password'} value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                    required className="input pr-10" placeholder="Repita a senha"
                    autoComplete="new-password" />
                  <button type="button" onClick={() => setShowConfirm(v => !v)}
                    aria-label={showConfirm ? 'Ocultar senha' : 'Mostrar senha'}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink-2 transition-colors">
                    {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            )}

            {mode === 'register' && regStep === 2 && refCode && (
              <div className="bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg px-4 py-3 text-xs flex items-center gap-2">
                <PartyPopper className="w-4 h-4 shrink-0" />
                <span>Código de indicação <strong>{refCode}</strong> aplicado!</span>
              </div>
            )}

            {mode === 'register' && regStep === 2 && (
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={acceptedTerms}
                  onChange={e => setAcceptedTerms(e.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-green-500 cursor-pointer"
                />
                <span className="text-xs text-ink-2 leading-relaxed">
                  Li e concordo com os{' '}
                  <Link to="/termos" target="_blank" className="text-green-500 hover:underline font-semibold">Termos de Uso</Link>
                  {' '}e a{' '}
                  <Link to="/privacidade" target="_blank" className="text-green-500 hover:underline font-semibold">Política de Privacidade</Link>
                  , incluindo o tratamento dos meus dados conforme a LGPD.
                </span>
              </label>
            )}

            {(mode === 'login' || (mode === 'register' && regStep === 2)) && (
              <Turnstile ref={turnstileRef} onVerify={setCaptchaToken} />
            )}

            <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -6, x: 0 }}
                animate={{ opacity: 1, y: 0, x: [0, -6, 6, -4, 4, 0] }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ x: { duration: 0.4 }, default: { duration: 0.2 } }}
                className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 text-sm"
              >
                {error}
              </motion.div>
            )}
            </AnimatePresence>

            <button type="submit" disabled={loading} className="btn-primary w-full text-center mt-2">
              {loading ? 'Aguarde...' : mode === 'login' ? 'Entrar' : regStep === 1 ? 'Continuar' : 'Ativar 2 dias VIP grátis'}
            </button>
          </form>

          <div className="mt-5 text-center space-y-3">
            {mode === 'login' && (
              <Link to="/forgot-password" className="block text-ink-3 text-sm hover:text-ink-2 transition-colors">
                Esqueceu sua senha? <span className="text-green-500 font-semibold">Clique aqui</span>
              </Link>
            )}
            <div>
              <span className="text-ink-3 text-sm">
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
