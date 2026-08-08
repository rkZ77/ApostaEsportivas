import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { lazy, Suspense, Component, ReactNode, useEffect, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { Spinner } from './components/ui'
import { HelmetProvider } from 'react-helmet-async'
import { AuthProvider, useAuth } from './context/AuthContext'
import { NotificationProvider, useNotifications } from './context/NotificationContext'
import AgenteButton from './components/AgenteButton'
import CookieBanner from './components/CookieBanner'
import UpdateBanner from './components/UpdateBanner'
import ErrorToast from './components/ErrorToast'
import PushPromptBanner from './components/PushPromptBanner'
import MonthlyCloseModal from './components/MonthlyCloseModal'
import TopProgressBar from './components/TopProgressBar'

// Cada página vira chunk separado · só baixa quando o usuário navega para ela
const Login          = lazy(() => import('./pages/Login'))
const Picks          = lazy(() => import('./pages/Picks'))
const Admin          = lazy(() => import('./pages/Admin'))
const Fixtures       = lazy(() => import('./pages/Fixtures'))
const Home           = lazy(() => import('./pages/Home'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const Profile        = lazy(() => import('./pages/Profile'))
const Planos         = lazy(() => import('./pages/Planos'))
const Agente         = lazy(() => import('./pages/Agente'))
const Checkout       = lazy(() => import('./pages/Checkout'))
const Banca          = lazy(() => import('./pages/Banca'))
const BancaSaque     = lazy(() => import('./pages/BancaSaque'))
const BancaFechamentos = lazy(() => import('./pages/BancaFechamentos'))
const MeusPicks      = lazy(() => import('./pages/MeusPicks'))
const VerifyEmail    = lazy(() => import('./pages/VerifyEmail'))
const Privacidade    = lazy(() => import('./pages/Privacidade'))
const Termos         = lazy(() => import('./pages/Termos'))
const Estatisticas   = lazy(() => import('./pages/Estatisticas'))
const NotFound       = lazy(() => import('./pages/NotFound'))
const ComoFunciona   = lazy(() => import('./pages/ComoFunciona'))
const PickPublico         = lazy(() => import('./pages/PickPublico'))
const ResultadosPublicos  = lazy(() => import('./pages/ResultadosPublicos'))
const PerformanceIA       = lazy(() => import('./pages/PerformanceIA'))
const Blog                = lazy(() => import('./pages/Blog'))
const BlogPost            = lazy(() => import('./pages/BlogPost'))

const CHUNK_ERROR_RE = /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Loading chunk \d+ failed/i
const CHUNK_RELOAD_KEY = 'pickia_chunk_reload_at'

/** true se ainda nao tentamos recarregar por esse motivo nos ultimos 10s
 * (evita loop infinito de reload se o build realmente estiver quebrado). */
function shouldAutoReloadForChunkError(): boolean {
  const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || 0)
  if (Date.now() - last < 10_000) return false
  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
  return true
}

class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null }
  static getDerivedStateFromError(error: Error) {
    // Depois de um deploy, o navegador ainda com a pagina antiga aberta tenta
    // buscar um chunk JS com hash que nao existe mais no servidor -- a tela
    // "Algo deu errado" aparecia sempre que isso acontecia, embora um simples
    // reload resolva na hora (a pagina nova ja aponta pros chunks certos).
    // Como fizemos varios deploys seguidos numa mesma sessao, isso ficava
    // aparecendo "do nada" pra quem estava com o site aberto de fundo.
    if (CHUNK_ERROR_RE.test(error?.message || '') && shouldAutoReloadForChunkError()) {
      window.location.reload()
      return { error: null }
    }
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-surface-0 flex flex-col items-center justify-center p-8 text-center">
          <p className="text-red-400 font-bold text-lg mb-2">Algo deu errado</p>
          <p className="text-ink-3 text-sm mb-5">Tente recarregar a página</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-surface-2 text-ink-2 rounded-lg text-sm hover:bg-surface-3 transition-colors"
          >
            Recarregar
          </button>
          {import.meta.env.DEV && (
            <pre className="text-ink-4 text-xs bg-surface-1 rounded-lg p-4 max-w-xl w-full text-left overflow-auto whitespace-pre-wrap mt-6">
              {(this.state.error as Error).message}
              {'\n\n'}
              {(this.state.error as Error).stack}
            </pre>
          )}
        </div>
      )
    }
    return this.props.children
  }
}

const PageLoader = () => (
  <div className="min-h-screen bg-surface-0 flex items-center justify-center">
    <Spinner size="lg" />
  </div>
)

function PrivateRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) {
    const redirect = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?redirect=${redirect}`} replace />
  }
  return children
}

function PublicRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth()
  if (!user || user.plan === 'admin') return children
  return <Navigate to="/picks" replace />
}

// Rotas onde o fechamento pode pular na frente do usuário. Lista de permissão,
// não de bloqueio: GlobalModals vive fora do <Routes>, então sem isso o popup
// aparece em TUDO · landing, blog, termos, link público de pick compartilhado.
// Quem está logado e cai na home (admin não é redirecionado pra /picks) levava
// o modal por cima da página de vendas. /checkout fica de fora de propósito:
// não se interrompe um pagamento em andamento.
const MONTHLY_CLOSE_ROUTES = [
  '/picks', '/banca', '/meus-picks', '/fixtures', '/estatisticas', '/agente', '/profile', '/admin',
]

function GlobalModals() {
  const { user, isAdmin } = useAuth()
  const { pathname } = useLocation()
  // ?preview=monthly renderiza o modal com dados FABRICADOS (ferramenta de
  // ajuste visual). Restrito a admin: qualquer usuário logado conseguia abrir
  // e printar um fechamento de +R$ 187,50 que nunca existiu.
  const isPreview = isAdmin && new URLSearchParams(window.location.search).get('preview') === 'monthly'
  const { pendingMonthlyClose, monthlyCloseOpen, openMonthlyClose, closeMonthlyClose } = useNotifications()

  const inAppRoute = MONTHLY_CLOSE_ROUTES.some(r => pathname === r || pathname.startsWith(`${r}/`))

  // Abre sozinho no primeiro acesso depois da virada do mês. O gatilho é a
  // notificação do servidor ainda não lida, então isso vale por conta (não por
  // navegador) e fechar o popup não apaga mais o fechamento: ele continua no
  // sino até a banca ser confirmada.
  useEffect(() => {
    if (!user) return
    if (isPreview || (pendingMonthlyClose && inAppRoute)) openMonthlyClose()
  }, [user?.id, pendingMonthlyClose?.id, inAppRoute, isPreview, openMonthlyClose])

  return (
    <AnimatePresence>
      {monthlyCloseOpen && <MonthlyCloseModal onClose={closeMonthlyClose} />}
    </AnimatePresence>
  )
}

// Redireciona apenas usuários recém-cadastrados para /como-funciona
function FirstLoginRedirect() {
  const { user } = useAuth()
  const navigate = useNavigate()
  useEffect(() => {
    if (!user) return
    if (localStorage.getItem('pickia_just_registered')) {
      localStorage.removeItem('pickia_just_registered')
      navigate('/como-funciona', { replace: true })
    }
  }, [user?.id])
  return null
}

export default function App() {
  return (
    <HelmetProvider>
    <BrowserRouter>
      <AuthProvider>
        <NotificationProvider>
          {/* Fora do <Routes> de propósito: precisa sobreviver à troca de rota
              pra conseguir medi-la. Dentro, ela seria desmontada junto com a
              página que está saindo. */}
          <TopProgressBar />
          <AgenteButton />
          <CookieBanner />
          <UpdateBanner />
          <ErrorToast />
          <PushPromptBanner />
          <GlobalModals />
          <FirstLoginRedirect />
          <RouteErrorBoundary>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
                <Route path="/picks" element={<PrivateRoute><Picks /></PrivateRoute>} />
                <Route path="/results" element={<Navigate to="/resultados" replace />} />
                <Route path="/fixtures" element={<PrivateRoute><Fixtures /></PrivateRoute>} />
                <Route path="/admin" element={<PrivateRoute><Admin /></PrivateRoute>} />
                <Route path="/profile" element={<PrivateRoute><Profile /></PrivateRoute>} />
                <Route path="/planos" element={<Planos />} />
                <Route path="/agente" element={<PrivateRoute><Agente /></PrivateRoute>} />
                <Route path="/checkout" element={<PrivateRoute><Checkout /></PrivateRoute>} />
                <Route path="/checkout/:status" element={<PrivateRoute><Checkout /></PrivateRoute>} />
                <Route path="/banca" element={<PrivateRoute><Banca /></PrivateRoute>} />
                <Route path="/banca/saque" element={<PrivateRoute><BancaSaque /></PrivateRoute>} />
                <Route path="/banca/fechamentos" element={<PrivateRoute><BancaFechamentos /></PrivateRoute>} />
                <Route path="/meus-picks" element={<PrivateRoute><MeusPicks /></PrivateRoute>} />
                <Route path="/forgot-password" element={<PublicRoute><ForgotPassword /></PublicRoute>} />
                <Route path="/verify-email" element={<VerifyEmail />} />
                <Route path="/privacidade" element={<Privacidade />} />
                <Route path="/termos" element={<Termos />} />
                <Route path="/estatisticas" element={<PrivateRoute><Estatisticas /></PrivateRoute>} />
                <Route path="/como-funciona" element={<ComoFunciona />} />
                <Route path="/p/:pick_type/:pick_id" element={<PickPublico />} />
                <Route path="/resultados" element={<ResultadosPublicos />} />
                <Route path="/performance" element={<PerformanceIA />} />
                <Route path="/blog" element={<Blog />} />
                <Route path="/blog/:slug" element={<BlogPost />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </RouteErrorBoundary>
        </NotificationProvider>
      </AuthProvider>
    </BrowserRouter>
    </HelmetProvider>
  )
}
