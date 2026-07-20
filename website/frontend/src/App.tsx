import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { lazy, Suspense, Component, ReactNode, useEffect, useState } from 'react'
import { HelmetProvider } from 'react-helmet-async'
import { AuthProvider, useAuth } from './context/AuthContext'
import { NotificationProvider } from './context/NotificationContext'
import WhatsAppButton from './components/WhatsAppButton'
import CookieBanner from './components/CookieBanner'
import UpdateBanner from './components/UpdateBanner'
import ErrorToast from './components/ErrorToast'
import PushPromptBanner from './components/PushPromptBanner'
import PostCopaBanner from './components/PostCopaBanner'
import MonthlyCloseModal, { shouldShowMonthlyClose } from './components/MonthlyCloseModal'

// Cada página vira chunk separado · só baixa quando o usuário navega para ela
const Login          = lazy(() => import('./pages/Login'))
const Picks          = lazy(() => import('./pages/Picks'))
const Admin          = lazy(() => import('./pages/Admin'))
const Fixtures       = lazy(() => import('./pages/Fixtures'))
const Landing        = lazy(() => import('./pages/Landing'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const ResetPassword  = lazy(() => import('./pages/ResetPassword'))
const Profile        = lazy(() => import('./pages/Profile'))
const Planos         = lazy(() => import('./pages/Planos'))
const Agente         = lazy(() => import('./pages/Agente'))
const Checkout       = lazy(() => import('./pages/Checkout'))
const Banca          = lazy(() => import('./pages/Banca'))
const MeusPicks      = lazy(() => import('./pages/MeusPicks'))
const VerifyEmail    = lazy(() => import('./pages/VerifyEmail'))
const Privacidade    = lazy(() => import('./pages/Privacidade'))
const Termos         = lazy(() => import('./pages/Termos'))
const Estatisticas   = lazy(() => import('./pages/Estatisticas'))
const NotFound       = lazy(() => import('./pages/NotFound'))
const ComoFunciona   = lazy(() => import('./pages/ComoFunciona'))
const PickPublico         = lazy(() => import('./pages/PickPublico'))
const ResultadosPublicos  = lazy(() => import('./pages/ResultadosPublicos'))

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
        <div className="min-h-screen bg-black flex flex-col items-center justify-center p-8 text-center">
          <p className="text-red-400 font-bold text-lg mb-2">Algo deu errado</p>
          <p className="text-zinc-500 text-sm mb-5">Tente recarregar a página</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-zinc-800 text-zinc-300 rounded-lg text-sm hover:bg-zinc-700 transition-colors"
          >
            Recarregar
          </button>
          {import.meta.env.DEV && (
            <pre className="text-zinc-600 text-xs bg-zinc-900 rounded-xl p-4 max-w-xl w-full text-left overflow-auto whitespace-pre-wrap mt-6">
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
  <div className="min-h-screen bg-black flex items-center justify-center">
    <div className="w-8 h-8 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
  </div>
)

function PrivateRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  return children
}

function PublicRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth()
  if (!user || user.plan === 'admin') return children
  return <Navigate to="/picks" replace />
}

function GlobalModals() {
  const { user } = useAuth()
  const isPreview = new URLSearchParams(window.location.search).get('preview') === 'monthly'
  const [showMonthlyClose, setShowMonthlyClose] = useState(false)

  useEffect(() => {
    if (!user) return
    if (isPreview || shouldShowMonthlyClose()) setShowMonthlyClose(true)
  }, [user?.id])

  return showMonthlyClose
    ? <MonthlyCloseModal onClose={() => setShowMonthlyClose(false)} />
    : null
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
          <WhatsAppButton />
          <CookieBanner />
          <UpdateBanner />
          <ErrorToast />
          <PushPromptBanner />
          <PostCopaBanner />
          <GlobalModals />
          <FirstLoginRedirect />
          <RouteErrorBoundary>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route path="/" element={<Landing />} />
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
                <Route path="/meus-picks" element={<PrivateRoute><MeusPicks /></PrivateRoute>} />
                <Route path="/forgot-password" element={<PublicRoute><ForgotPassword /></PublicRoute>} />
                <Route path="/reset-password" element={<ResetPassword />} />
                <Route path="/verify-email" element={<VerifyEmail />} />
                <Route path="/privacidade" element={<Privacidade />} />
                <Route path="/termos" element={<Termos />} />
                <Route path="/estatisticas" element={<PrivateRoute><Estatisticas /></PrivateRoute>} />
                <Route path="/como-funciona" element={<ComoFunciona />} />
                <Route path="/p/:pick_type/:pick_id" element={<PickPublico />} />
                <Route path="/resultados" element={<ResultadosPublicos />} />
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
