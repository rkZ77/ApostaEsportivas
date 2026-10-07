import { useState, useRef, FormEvent, useEffect } from 'react'
import { Helmet } from 'react-helmet-async'
import { AnimatePresence, m as motion } from 'framer-motion'
import { PartyPopper, Eye, EyeOff, ArrowLeft, House, ShieldCheck, LineChart, Lock } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { taxaAcerto } from '../utils/format'
import { useAuth } from '../context/AuthContext'
import { maskPhone } from '../utils/format'
import api from '../services/api'
import Turnstile, { TurnstileHandle } from '../components/Turnstile'
import PublicNav from '../components/PublicNav'
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
        if (s && s.total > 0) setPct(taxaAcerto(s))
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

/* O fundo da tela · grade fina e um brilho no canto (07/10/2026, pedido do
   usuário).

   O meio-campo desenhado que morava aqui saiu: as faixas de gramado e as
   linhas do campo atrás do formulário liam como enfeite de site de aposta
   barato, o contrário do que uma tela de senha precisa passar. A referência
   pedida é a de produto de software: grade quase invisível do lado do
   formulário e um brilho da cor da marca no canto, sem desenho nenhum
   disputando com os campos.

   Só gradiente, sem imagem nem blur (desfoque grande é o efeito mais caro no
   Safari do iPhone). A cor sai do token, então o tema claro acompanha. */
function FundoSobrio() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0 opacity-60 [mask-image:linear-gradient(to_left,black,transparent_75%)]"
        style={{
          backgroundImage:
            'linear-gradient(rgb(var(--ink-4) / 0.08) 1px, transparent 1px), linear-gradient(90deg, rgb(var(--ink-4) / 0.08) 1px, transparent 1px)',
          backgroundSize: '56px 56px',
        }}
      />
      <div
        className="absolute -top-48 -right-40 w-[720px] h-[620px]"
        style={{ background: 'radial-gradient(50% 50% at 50% 50%, rgb(var(--accent) / 0.12), transparent 70%)' }}
      />
      <div
        className="absolute -bottom-56 -left-40 w-[620px] h-[520px]"
        style={{ background: 'radial-gradient(50% 50% at 50% 50%, rgb(var(--accent) / 0.05), transparent 70%)' }}
      />
    </div>
  )
}

/* A marca grande do painel da esquerda: o mesmo logotipo da barra, em
   tamanho de capa. */
function MarcaGrande({ compacta = false }: { compacta?: boolean }) {
  return (
    <div className={`flex items-center ${compacta ? 'gap-3' : 'gap-4'}`}>
      <span className={`${compacta ? 'w-11 h-11 rounded-lg' : 'w-16 h-16 rounded-xl'} bg-surface-1 border border-line flex items-center justify-center shrink-0`}>
        <img src="/logo-64.webp" alt="" width={64} height={64} className={compacta ? 'w-7 h-7' : 'w-10 h-10'} />
      </span>
      <span className={`font-display font-black tracking-tight text-ink-1 ${compacta ? 'text-2xl' : 'text-5xl'}`}>
        Pick<span className="text-accent-ink">IA</span>
      </span>
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
function SeloDeConfianca({ className = 'mt-7' }: { className?: string }) {
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
    <div className={`space-y-3.5 ${className}`}>
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

/** "Henrique da Silva" -> "henrique_silva": primeiro e último nome, sem acento, até 20. */
function sugerirUsuario(nome: string): string {
  const partes = nome
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/).filter(Boolean)
  if (!partes.length) return ''
  const escolhidas = partes.length > 1 ? [partes[0], partes[partes.length - 1]] : partes
  const sugestao = escolhidas.join('_').slice(0, 20)
  // Abaixo do mínimo de 3 o backend recusaria: melhor o campo vazio que um erro.
  return sugestao.length >= 3 ? sugestao : ''
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
  /* Usuário sugerido a partir do nome (2026-09-25). Era um campo em branco a
     mais no passo 1, e a maioria das pessoas não tem um "usuário" pensado ·
     trava ali. Enquanto a pessoa não mexer no campo, ele acompanha o nome;
     mexeu, é dela. Colisão com usuário existente volta do backend como erro
     do passo 1, que já é tratado. */
  const [usernameEditado, setUsernameEditado] = useState(false)
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
        /*
         * NÃO VAI DIRETO PRO PRODUTO (12/09).
         *
         * O site inteiro vende "2 dias de VIP grátis", e desde a saída do CPF
         * o trial só nasce quando o contato é provado, no link do e-mail ou no
         * código do WhatsApp (ver `_ativar_trial_se_elegivel` no backend).
         * Quem se cadastrava caía em /picks como FREE, com o tour de
         * boas-vindas na frente e o aviso de confirmar e-mail represado atrás
         * dele: a recompensa prometida três telas antes não aparecia em
         * nenhuma. É o vazamento mais caro do funil, porque acontece depois
         * de a pessoa já ter feito o trabalho todo.
         *
         * Agora o passo que falta é a própria tela. `#guia` continua fora, e
         * quem quiser entrar sem confirmar tem o link secundário abaixo.
         */
        navigate('/confirmar-email', { replace: true, state: { email } })
        return
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

  /* O painel da esquerda (desktop) responde "posso confiar neste site?"
     antes de pedir e-mail e senha: marca, promessa e o selo de confiança com
     o win rate real. No celular o selo desce pra baixo do card. */
  return (
    <div className={`relative min-h-screen bg-surface-0 flex flex-col overflow-hidden ${classesRevelacao(revelado)}`} style={{ transitionDuration: `${FADE_REVELACAO_MS}ms` }} aria-busy={!revelado}>
      <Helmet>
        <title>Entrar | Pick IA</title>
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
        /* Só a casinha, no MESMO tom do seletor de tema ao lado (`text-ink-2`):
           dois ícones vizinhos em cinzas diferentes leem como um ativo e outro
           desativado. Ícone sozinho precisa de nome acessível e de alvo de
           toque, então o `aria-label` diz o que o texto dizia e o quadrado de
           40px mantém o alvo que a frase tinha. */
        acoes={
          <Link
            to="/"
            aria-label="Voltar para o site"
            title="Voltar para o site"
            className="inline-flex items-center justify-center w-10 h-10 rounded-md text-ink-2 hover:text-ink-1 transition-colors"
          >
            <House className="w-5 h-5" />
          </Link>
        }
      />

      <FundoSobrio />

      {/* DUAS COLUNAS NO DESKTOP, DE NOVO (07/10/2026, pedido do usuário, com
          a referência na mão). A versão dividida antiga foi reprovada porque o
          painel da esquerda era decoração; este é a marca, a promessa em uma
          frase e as três razões de confiança, e o formulário fica num card
          próprio à direita. No celular vira uma coluna: marca compacta em
          cima, card logo abaixo, confiança no fim. */}
      <main className="relative flex-1 flex items-center px-4 sm:px-6 py-8 sm:py-14">
        <div className="mx-auto w-full max-w-6xl grid lg:grid-cols-2 gap-10 lg:gap-20 items-center">

        <section className="hidden lg:block">
          <MarcaGrande />
          <p className="mt-10 font-display text-4xl xl:text-[2.75rem] font-black leading-[1.12] tracking-tight text-ink-1">
            Picks de futebol com estatística.{' '}
            <span className="text-accent-ink">E resultado em público.</span>
          </p>
          <p className="mt-5 text-lg text-ink-2 leading-relaxed max-w-lg">
            A IA lê escanteios, cartões, gols e chutes de cada jogo e só publica quando acha valor. Cada pick vira GREEN ou RED no histórico aberto.
          </p>
          <SeloDeConfianca className="mt-10 max-w-lg" />
        </section>

        <div className="relative w-full max-w-md mx-auto lg:mr-0">
          <div className="lg:hidden mb-7"><MarcaGrande compacta /></div>
          {/* Este e o <h1> da pagina. A marca acima e logotipo, e aparecia
              duas vezes como h1 (uma no painel de desktop, outra no bloco
              mobile): so uma renderiza, mas as duas existiam no DOM, entao
              leitor de tela e robo de busca viam duas. */}
          <h1 className="text-2xl font-bold text-ink-1 mb-1">
            {mode === 'login' ? 'Bem-vindo de volta' : '2 dias de Pro, de graça'}
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
                { dot: 'bg-green-500',  text: 'Picks Premium diários' },
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

          {/* O formulário num card próprio, como na referência: separa "o que
              preencher" do resto da tela sem precisar de enfeite no fundo. */}
          <div className="rounded-xl border border-line bg-surface-1 p-5 sm:p-7 shadow-[0_24px_60px_-30px_rgb(0_0_0/0.6)]">
          {/* NO CADASTRO O GOOGLE VEM PRIMEIRO (2026-09-25). O motivo de ele
              ficar embaixo (ver o comentário depois do formulário) é o login:
              lá, em cima, ele cria a conta duplicada de quem já tem senha. No
              cadastro a pessoa ainda não tem conta, e um toque no Google pula
              os quatro campos · no celular é a diferença entre cadastrar e
              desistir. */}
          {mode === 'register' && regStep === 1 && (
            <div className="mb-5">
              <GoogleSignInButton
                modo={mode}
                onCode={entrarComGoogle}
                onDisponivel={setGoogleDisponivel}
                desabilitado={loading}
              />
              {googleDisponivel && (
                <div className="flex items-center gap-3 mt-5">
                  <div className="h-px flex-1 bg-line" />
                  <span className="text-[11px] text-ink-4 font-semibold uppercase tracking-wide">ou cadastre-se com e-mail</span>
                  <div className="h-px flex-1 bg-line" />
                </div>
              )}
            </div>
          )}

          <form onSubmit={submit} className="space-y-4">

            {mode === 'login' && (
              <>
                <div>
                  <label htmlFor="login-identifier" className="block text-sm text-ink-2 mb-2 font-medium">Entrar com</label>
                  {/* Tabs estilo Betano */}
                  {/* Segmento discreto: o verde cheio fica só no botão de
                      Entrar, que é a ação. Duas manchas verdes no mesmo card
                      disputavam o olho. */}
                  <div className="flex gap-1 p-1 rounded-lg bg-surface-2 border border-line mb-3">
                    {loginTabs.map(tab => (
                      <button
                        key={tab.key}
                        type="button"
                        onClick={() => { setLoginMethod(tab.key); setError('') }}
                        className={`flex-1 py-1.5 rounded-md text-xs font-bold transition-colors ${
                          loginMethod === tab.key
                            ? 'bg-surface-0 text-ink-1 shadow-sm'
                            : 'text-ink-3 hover:text-ink-1'
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
                    onChange={e => {
                      setName(e.target.value)
                      if (!usernameEditado) setUsername(sugerirUsuario(e.target.value))
                    }}
                    required className="input" placeholder="Nome e sobrenome"
                    autoComplete="name" autoFocus />
                </div>
                <div>
                  <label htmlFor="reg-username" className="block text-sm text-ink-2 mb-1.5 font-medium">Usuário</label>
                  <input id="reg-username" type="text" value={username}
                    onChange={e => { setUsernameEditado(true); setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '')) }}
                    required className="input" placeholder="seu_usuario"
                    autoComplete="username" maxLength={20} />
                  <p className="text-xs text-ink-4 mt-1">
                    {usernameEditado || !username
                      ? '3 a 20 caracteres. Letras minúsculas, números e _.'
                      : 'Sugerido a partir do seu nome. Pode trocar se quiser.'}
                  </p>
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
                  Confirme seu e-mail depois do cadastro para liberar <span className="text-ink-2 font-semibold">2 dias de Pro grátis</span>.
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
              {loading ? 'Aguarde...' : mode === 'login' ? 'Entrar' : regStep === 1 ? 'Continuar' : 'Ativar 2 dias de Pro grátis'}
            </button>
          </form>

          {/* ENTRAR COM GOOGLE, DEPOIS DO FORMULÁRIO.
              Ele já esteve em cima, com o argumento de ser o caminho mais
              curto. Mas em cima ele rouba a decisão de quem já tem conta e
              senha, que é a maioria de quem abre esta tela · e é assim que
              nasce a conta duplicada, uma por senha e outra pelo Google.
              Embaixo, com o rótulo "ou entre com", ele é a alternativa que
              anuncia ser. Mesma ordem que casa de aposta usa, pelo mesmo
              motivo. */}
          {mode === 'login' && googleDisponivel && (
            <div className="mt-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="h-px flex-1 bg-line" />
                <span className="text-[11px] text-ink-4 font-semibold uppercase tracking-wide">
                  {mode === 'login' ? 'ou entre com' : 'ou cadastre-se com'}
                </span>
                <div className="h-px flex-1 bg-line" />
              </div>
            </div>
          )}
          {mode === 'login' && (
            <GoogleSignInButton
              modo={mode}
              onCode={entrarComGoogle}
              onDisponivel={setGoogleDisponivel}
              desabilitado={loading}
            />
          )}
          </div>

          {/* AS DUAS SAÍDAS, EM FRASE (01/09/2026, pedido do usuário).
              Elas já foram frase, viraram botão de largura cheia e voltam a ser
              frase. O motivo de terem virado botão continua de pé e por isso
              não se repete o erro antigo: no celular, uma palavra sublinhada no
              meio do texto tem a altura de uma linha e é difícil de acertar com
              o polegar. Aqui a parte clicável é um <Link> com padding próprio e
              44px de altura mínima, então ela lê como frase e tem alvo de
              botão. */}
          <div className="mt-6 space-y-1 text-center">
            <p className="text-sm text-ink-3">
              {mode === 'login' ? 'Novo usuário?' : 'Já tem conta?'}{' '}
              <button
                type="button"
                onClick={switchMode}
                className="inline-flex items-center justify-center min-h-[44px] px-1 font-bold text-accent-ink hover:text-accent-hover transition-colors"
              >
                {mode === 'login' ? 'Cadastre-se aqui' : 'Entrar na minha conta'}
              </button>
            </p>

            {mode === 'login' && (
              <p className="text-sm text-ink-3">
                Esqueceu sua senha?{' '}
                <Link
                  to="/forgot-password"
                  className="inline-flex items-center justify-center min-h-[44px] px-1 font-bold text-accent-ink hover:text-accent-hover transition-colors"
                >
                  Clique aqui
                </Link>
              </p>
            )}
          </div>

          <SeloDeConfianca className="mt-8 lg:hidden" />
        </div>
        </div>
      </main>

      <footer className="relative border-t border-line">
        <div className="mx-auto w-full max-w-3xl px-5 sm:px-6 py-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-xs text-ink-4">
          <Link to="/termos" className="hover:text-ink-2 transition-colors">Termos de Uso</Link>
          <Link to="/privacidade" className="hover:text-ink-2 transition-colors">Privacidade</Link>
          <Link to="/como-funciona" className="hover:text-ink-2 transition-colors">Como funciona</Link>
          {/* Não é enfeite legal: é o aviso que separa quem opera às claras de
              quem promete lucro garantido. */}
          <span className="w-full text-center text-ink-4 mt-1">
            Proibido para menores de 18 anos. Aposta é entretenimento, não fonte de renda. Jogue com responsabilidade.
          </span>
        </div>
      </footer>
    </div>
  )
}
