import { useState, useRef, FormEvent, useEffect } from 'react'
import { Helmet } from 'react-helmet-async'
import { AnimatePresence, motion } from 'framer-motion'
import { PartyPopper, Eye, EyeOff, ArrowLeft, ShieldCheck, LineChart, Lock } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { maskPhone } from '../utils/format'
import api from '../services/api'
import Turnstile, { TurnstileHandle } from '../components/Turnstile'
import PublicNav from '../components/PublicNav'
import LeagueMarquee from '../components/LeagueMarquee'
import GoogleSignInButton from '../components/GoogleSignInButton'
import { getPasswordStrength } from '../utils/passwordStrength'
import { tabFade } from '../lib/motion'
import { useRevelacao, classesRevelacao, FADE_REVELACAO_MS } from '../hooks/useRevelacao'

function validateEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim())
}

// Win rate real (mesma fonte publica de /resultados) -- reforca credibilidade
// bem no ponto de decisao de cadastro, em vez de so listar promessas em texto.
//
// `slim=1` porque aqui so' se le o resumo: sem ele a rota monta os sete blocos
// (meses disponiveis, quebra por dia, por liga, contagens...) e a tela de login
// pagava seis consultas ao banco pra estampar uma porcentagem.
function RealWinRate({ className = 'mt-5' }: { className?: string }) {
  const [pct, setPct] = useState<number | null>(null)
  useEffect(() => {
    api.get('/public/results', { params: { slim: 1, recent_limit: 1 } })
      .then(r => {
        const s = r.data?.summary
        if (s && s.total > 0) setPct(Math.round((s.greens / s.total) * 100))
      })
      .catch(() => {})
  }, [])
  if (pct == null) return null
  return (
    <span className={className}>
      {' '}Hoje: <strong className="text-accent-ink">{pct}% de acerto</strong>.{' '}
      <Link to="/resultados" className="text-ink-2 underline underline-offset-2 hover:text-ink-1 transition-colors">
        Ver histórico
      </Link>
    </span>
  )
}

/* O fundo da tela · um meio-campo visto de cima.

   Fundo preto liso fazia esta página parecer erro de servidor ao lado do resto
   do site. O que entra aqui não é enfeite aleatório: é o mesmo vocabulário que
   a Home e o 404 já usam (verde da marca em opacidade baixa, formas simples,
   nada que dispute com o formulário). A bola do 404 mostrou que dá pra falar
   de futebol sem ilustração pesada, e o campo faz isso ocupando só as bordas.

   Tudo em SVG e gradiente, sem imagem: são poucos bytes, escala em qualquer
   tela e acompanha o tema claro sozinho, porque a cor sai do token `--accent`
   em vez de estar assada num arquivo. */
function FundoDeCampo() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* Faixas do gramado. A máscara apaga o centro: onde mora o formulário,
          o fundo tem que sumir. */}
      <div className="absolute inset-0 bg-field-pattern bg-[length:100%_72px] opacity-70 [mask-image:radial-gradient(ellipse_90%_70%_at_50%_40%,transparent_35%,black)]" />

      {/* Halo verde no topo, o mesmo do hero da Home. Em radial-gradient e não
          em blur, porque desfoque grande é o efeito mais caro no Safari do
          iPhone e esta é uma tela que a maioria abre no celular. */}
      <div
        className="absolute -top-40 left-1/2 -translate-x-1/2 w-[860px] h-[560px]"
        style={{ background: 'radial-gradient(50% 50% at 50% 50%, rgb(var(--accent) / 0.13), transparent 70%)' }}
      />

      {/* As linhas do campo. Meio-campo, círculo central e as duas grandes
          áreas, com o traço fino que elas têm de verdade vistas de cima. */}
      <svg
        className="absolute inset-x-0 top-0 w-full h-full"
        viewBox="0 0 400 800"
        preserveAspectRatio="xMidYMid slice"
        fill="none"
        stroke="rgb(var(--accent) / 0.16)"
        strokeWidth="1.5"
      >
        <line x1="0" y1="400" x2="400" y2="400" />
        <circle cx="200" cy="400" r="76" />
        <circle cx="200" cy="400" r="3" fill="rgb(var(--accent) / 0.22)" stroke="none" />
        <rect x="110" y="-1" width="180" height="86" />
        <rect x="110" y="715" width="180" height="86" />
      </svg>

      {/* Véu por cima de tudo: o desenho precisa ficar na periferia da visão,
          não competir com o campo de senha. */}
      <div className="absolute inset-0 bg-surface-0/70" />
    </div>
  )
}

/* As três razões para acreditar que isto não é um golpe · e todas são
   verificáveis pelo próprio visitante, agora, sem criar conta.

   Não entra nada aqui que a gente não consiga provar. A tela já teve "prova
   social" fabricada (um ticker de atividade inventado, removido em 17/07) e é
   exatamente esse tipo de coisa que produz o efeito contrário: quem desconfia
   de site de aposta reconhece um número inventado de longe.

   O bloco de pagamento é o item mais importante dos três: golpe de tips vive
   de pedir Pix na entrada. Dizer, na tela de cadastro, que aqui não se pede
   nada disso responde a objeção no momento em que ela existe. */
function SeloDeConfianca() {
  const itens = [
    {
      Icone: LineChart,
      titulo: 'Resultado auditável',
      texto: <>Todo pick vira GREEN ou RED em público, com data e odd.<RealWinRate /></>,
    },
    {
      Icone: Lock,
      titulo: 'Nada de pagamento aqui',
      texto: <>Criar conta não pede Pix, CPF nem dado de pagamento nenhum. A assinatura, quando você quiser, passa pelo MercadoPago.</>,
    },
    {
      Icone: ShieldCheck,
      titulo: 'Seus dados',
      texto: (
        <>
          Ficam com a gente e você apaga quando quiser.{' '}
          <Link to="/privacidade" className="text-ink-2 underline underline-offset-2 hover:text-ink-1 transition-colors">
            Política de Privacidade
          </Link>
        </>
      ),
    },
  ]
  return (
    <div className="mt-7 space-y-3.5">
      {itens.map(({ Icone, titulo, texto }) => (
        <div key={titulo} className="flex gap-3">
          <Icone className="w-4 h-4 text-ink-3 shrink-0 mt-0.5" aria-hidden="true" />
          <p className="text-xs leading-relaxed text-ink-3">
            <span className="text-ink-2 font-semibold">{titulo}.</span> {texto}
          </p>
        </div>
      ))}
    </div>
  )
}

type LoginMethod = 'username' | 'email' | 'phone'

export default function Login() {
  /* Portão de revelação · o mesmo das telas com PageShell. Também é quem
     encerra a barra verde do index.html. Ver hooks/useRevelacao. */
  const revelado = useRevelacao()
  const { login, register, loginComGoogle } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [mode, setMode]             = useState<'login' | 'register'>('login')
  const [loginMethod, setLoginMethod] = useState<LoginMethod>('username')
  const [regStep, setRegStep]       = useState<1 | 2>(1)

  // Login fields
  const [loginUsername, setLoginUsername] = useState('')
  const [loginEmail, setLoginEmail]       = useState('')
  const [loginPhone, setLoginPhone]       = useState('')

  // Register fields
  const [name, setName]         = useState('')
  const [username, setUsername] = useState('')
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
  const [googleDisponivel, setGoogleDisponivel] = useState(false)
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

  const getIdentifier = () => {
    if (loginMethod === 'username') return loginUsername.trim()
    if (loginMethod === 'phone')    return loginPhone.replace(/\D/g, '')
    return loginEmail.trim()
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (mode === 'login') {
      const id = getIdentifier()
      if (!id) { setError('Preencha o campo de identificação.'); return }
      if (loginMethod === 'email' && !validateEmail(id)) { setError('Email inválido.'); return }
      if (loginMethod === 'phone' && (id.length < 10 || id.length > 11)) {
        setError('Telefone inválido. Use o formato (DDD) 9XXXX-XXXX.')
        return
      }
    } else if (regStep === 1) {
      // Passo 1: só dados de acesso -- o telefone fica pro passo 2, que desde
      // a saída do CPF (18/08/2026) tem 3 campos em vez de 4.
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
        await register(name.trim(), email, password, phone, username.trim(), refCode || undefined, acceptedTerms, captchaToken || undefined)
        localStorage.removeItem('ref_code')
        // `#guia` saiu: não havia âncora com esse id em /picks, e o onboarding
        // que ele tentava anunciar agora abre sozinho na tela (ver
        // context/OnboardingContext.tsx).
        navigate(redirectTo ?? '/picks')
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

  /* O Google resolve login e cadastro no mesmo clique, então este caminho
     ignora o modo da tela · quem decide se cria ou entra é o backend. O código
     de indicação segue junto para não perder o crédito de quem indicou. */
  const entrarComGoogle = async (code: string) => {
    setError('')
    setLoading(true)
    try {
      await loginComGoogle(code, refCode || undefined)
      localStorage.removeItem('ref_code')
      navigate(redirectTo ?? '/picks')
    } catch (err: any) {
      const detail = err.response?.data?.detail
      setError(
        typeof detail === 'string'
          ? detail
          : 'Não foi possível entrar com o Google. Tente de novo ou use e-mail e senha.',
      )
    } finally {
      setLoading(false)
    }
  }

  const switchMode = () => {
    setMode(m => m === 'login' ? 'register' : 'login')
    setError('')
    setRegStep(1)
    setCaptchaToken('')
    setLoginUsername(''); setLoginEmail(''); setLoginPhone('')
    setName(''); setUsername(''); setPhone(''); setConfirm('')
  }


  const loginTabs: { key: LoginMethod; label: string }[] = [
    { key: 'username', label: 'Usuário' },
    { key: 'email',    label: 'E-mail'  },
    // O telefone já era único por conta (1 chip = 1 cadastro) desde a saída do
    // CPF; faltava só poder entrar por ele, que é o dado que quem usa celular
    // lembra sem pensar.
    { key: 'phone',    label: 'Telefone' },
  ]

  /* Coluna única, centralizada, com a marca no topo · o formato que todo
     mundo já viu em banco e em e-mail.

     A tela dividida saiu porque ela custava caro e entregava pouco: metade do
     desktop era um painel decorativo que o celular (a maioria de quem entra
     aqui) nunca via, e no lugar dele cabia o que de fato importa nesta tela,
     que é responder "posso confiar neste site?" antes de pedir e-mail e senha.
     O conteúdo daquele painel não se perdeu: o win rate real virou a primeira
     linha do selo abaixo do card, e a lista do trial virou uma faixa acima
     dele, visível TAMBÉM no celular, onde antes não aparecia. */
  return (
    <div className={`relative min-h-screen bg-surface-0 flex flex-col overflow-hidden ${classesRevelacao(revelado)}`} style={{ transitionDuration: `${FADE_REVELACAO_MS}ms` }} aria-busy={!revelado}>
      <Helmet>
        <title>Entrar · Pick IA</title>
        <meta name="description" content="Acesse sua conta Pick IA para ver os picks da IA do dia, sua banca e seu histórico." />
      </Helmet>


      {/* A MESMA barra das outras páginas públicas.
          Esta tela montava um cabeçalho só dela: logo à esquerda, link à
          direita, sem o seletor de tema. No desktop a diferença saltava · ao
          lado de /resultados parecia outro site, que é justamente a impressão
          que uma tela de senha não pode dar. O par Entrar/Criar conta cede o
          lugar para a saída de volta, que é o que falta aqui. */}
      <PublicNav
        width="full"
        acoes={
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-xs sm:text-sm font-semibold text-ink-3 hover:text-ink-1 transition-colors px-2 py-2"
          >
            <ArrowLeft className="w-4 h-4" />
            Voltar para o site
          </Link>
        }
      />

      <FundoDeCampo />

      <main className="relative flex-1 w-full mx-auto max-w-md px-5 sm:px-6 py-8 sm:py-12">
        <div className="w-full">
          {/* Este e o <h1> da pagina. A marca acima e logotipo, e aparecia
              duas vezes como h1 (uma no painel de desktop, outra no bloco
              mobile): so uma renderiza, mas as duas existiam no DOM, entao
              leitor de tela e robo de busca viam duas. */}
          <h1 className="text-2xl font-bold text-ink-1 mb-1">
            {mode === 'login' ? 'Bem-vindo de volta' : '2 dias de VIP, de graça'}
          </h1>
          <p className="text-ink-3 mb-6 text-sm">
            {mode === 'login'
              ? 'Entre para acessar seus picks de hoje.'
              : 'Acesso completo por 2 dias. Sem CPF e sem renovação automática.'}
          </p>

          {/* A oferta em quatro linhas · era o painel do desktop, que o celular
              nunca via. Só no cadastro: quem já é cliente não está decidindo se
              testa, está tentando ver os picks de hoje. */}
          {mode === 'register' && (
            <ul className="mb-6 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2">
              {[
                { dot: 'bg-green-500',  text: 'Picks VIP diários' },
                { dot: 'bg-blue-400',   text: 'Múltiplas da IA' },
                { dot: 'bg-orange-400', text: 'Alavancagem' },
                { dot: 'bg-purple-400', text: 'Agente IA 24/7' },
              ].map(({ dot, text }) => (
                <li key={text} className="flex items-center gap-2.5">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
                  <span className="text-sm text-ink-2">{text}</span>
                </li>
              ))}
            </ul>
          )}

          {kickedDevice && (
            <div className="mb-4 rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-4 text-sm">
              <p className="text-yellow-300 font-semibold mb-1">Sessão encerrada</p>
              <p className="text-ink-2">
                Um acesso foi feito de <strong className="text-ink-1">{kickedDevice}</strong> e sua sessão foi encerrada.
              </p>
              <p className="text-ink-2 mt-2">Se não foi você, redefina sua senha agora.</p>
              {/* Era um link sublinhado no fim da frase, do tamanho de duas
                  palavras · a ação mais urgente da tela com o menor alvo dela. */}
              <Link
                to="/forgot-password"
                className="inline-flex items-center justify-center mt-2 text-xs font-bold text-yellow-300 bg-yellow-500/10 border border-yellow-500/40 hover:bg-yellow-500/20 rounded-md px-3 py-2 min-h-[36px] transition-colors"
              >
                Redefinir senha
              </Link>
            </div>
          )}

          {/* O Google vem ANTES do formulário de propósito: é o caminho mais
              curto dos dois, e enterrá-lo embaixo de cinco campos faz a pessoa
              preencher tudo antes de descobrir que não precisava. */}
          <div className={googleDisponivel ? 'mb-5' : ''}>
            <GoogleSignInButton
              modo={mode}
              onCode={entrarComGoogle}
              onDisponivel={setGoogleDisponivel}
              desabilitado={loading}
            />
            {googleDisponivel && (
              <div className="flex items-center gap-3 mt-5">
                <div className="h-px flex-1 bg-line" />
                <span className="text-[11px] text-ink-4 font-semibold uppercase tracking-wide">ou</span>
                <div className="h-px flex-1 bg-line" />
              </div>
            )}
          </div>

          <form onSubmit={submit} className="space-y-4">

            {mode === 'login' && (
              <>
                <div>
                  <label htmlFor="login-identifier" className="block text-sm text-ink-2 mb-2 font-medium">Entrar com</label>
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
                  {loginMethod === 'phone' && (
                    <motion.input key="phone" variants={tabFade} initial="hidden" animate="visible" exit="exit"
                      id="login-identifier" type="tel" inputMode="numeric" value={loginPhone}
                      onChange={e => setLoginPhone(maskPhone(e.target.value))}
                      required className="input w-full" placeholder="(11) 99999-9999"
                      autoComplete="tel-national" maxLength={15} autoFocus />
                  )}
                  </AnimatePresence>
                </div>
              </>
            )}

            {mode === 'register' && (
              <div className="flex items-center gap-2 -mt-1 mb-1">
                {regStep === 2 && (
                  <button
                    type="button"
                    onClick={() => setRegStep(1)}
                    aria-label="Voltar para o passo 1"
                    className="shrink-0 -ml-1 w-7 h-7 flex items-center justify-center rounded-md text-ink-3 hover:text-ink-1 hover:bg-surface-2 transition-colors"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                )}
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
              <>
                <div>
                  <label htmlFor="reg-phone" className="block text-sm text-ink-2 mb-1.5 font-medium">WhatsApp</label>
                  <input id="reg-phone" type="tel" value={phone}
                    onChange={e => setPhone(maskPhone(e.target.value))}
                    required className="input" placeholder="(11) 99999-9999"
                    inputMode="numeric" autoComplete="tel" autoFocus />
                  <p className="text-xs text-ink-4 mt-1">1 conta por número. Só enviamos mensagem se você autorizar.</p>
                </div>
                <p className="text-xs text-ink-3 bg-surface-1 border border-line rounded-lg px-3 py-2.5 leading-relaxed">
                  Confirme seu e-mail depois do cadastro para liberar <span className="text-ink-2 font-semibold">2 dias de VIP grátis</span>.
                </p>
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
                            <span className={`text-[10px] ${c.ok ? 'text-accent-ink' : 'text-ink-4'}`}>{c.ok ? '✓' : '○'}</span>
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
                  <Link to="/termos" target="_blank" className="text-accent-ink hover:underline font-semibold">Termos de Uso</Link>
                  {' '}e a{' '}
                  <Link to="/privacidade" target="_blank" className="text-accent-ink hover:underline font-semibold">Política de Privacidade</Link>
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

          {/* As duas saídas da tela eram frases com uma palavra clicável no
              fim ("Clique aqui", "Criar conta grátis"). No celular o alvo tinha
              a altura de uma linha de texto, e a mais usada das duas · criar
              conta · ficava indistinguível da legenda que a antecede. Viraram
              botões de largura cheia, na hierarquia certa: a secundária com
              borda, a primária com fundo. */}
          <div className="mt-5 space-y-2">
            <button
              onClick={switchMode}
              className="w-full text-sm font-bold text-accent-ink bg-accent/10 border border-accent/30 hover:bg-accent/20 rounded-lg py-3 min-h-[44px] transition-colors"
            >
              {mode === 'login' ? 'Criar conta grátis' : 'Entrar na minha conta'}
            </button>
            {mode === 'login' && (
              <Link
                to="/forgot-password"
                className="flex items-center justify-center w-full text-sm font-semibold text-ink-3 hover:text-ink-1 border border-line hover:border-line-strong rounded-lg py-3 min-h-[44px] transition-colors"
              >
                Esqueci minha senha
              </Link>
            )}
          </div>

          <SeloDeConfianca />
        </div>
      </main>

      {/* Os escudos das ligas cobertas, na largura toda.
          A mesma fita da Home, e ela é a única "imagem" desta tela: escudo de
          competição real é o que o olho reconhece em meio segundo, e responde
          "o que exatamente vocês analisam?" sem custar uma linha de texto. A
          lista vem do banco, então nunca anuncia campeonato fora de
          temporada. Fica entre o selo e o rodapé de propósito: é reforço,
          não é o assunto. */}
      <section className="relative border-t border-line overflow-hidden py-5">
        <p className="text-center text-[11px] uppercase tracking-wide font-semibold text-ink-4 mb-3">
          Ligas que a IA analisa hoje
        </p>
        <LeagueMarquee />
      </section>

      <footer className="relative border-t border-line">
        <div className="mx-auto w-full max-w-3xl px-5 sm:px-6 py-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-xs text-ink-4">
          <Link to="/termos" className="hover:text-ink-2 transition-colors">Termos de Uso</Link>
          <Link to="/privacidade" className="hover:text-ink-2 transition-colors">Privacidade</Link>
          <Link to="/como-funciona" className="hover:text-ink-2 transition-colors">Como funciona</Link>
          {/* Não é enfeite legal: é o aviso que separa quem opera às claras de
              quem promete lucro garantido. */}
          <span className="w-full text-center text-ink-4 mt-1">
            18+ · Aposta é entretenimento, não fonte de renda. Jogue com responsabilidade.
          </span>
        </div>
      </footer>
    </div>
  )
}
