import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { lazy, Suspense, Component, ReactNode, useCallback } from 'react'
import Spinner from './components/ui/Spinner'
import { HelmetProvider } from 'react-helmet-async'
import { AuthProvider, useAuth } from './context/AuthContext'
import { NotificationProvider } from './context/NotificationContext'
import { OnboardingProvider } from './context/OnboardingContext'
import TopProgressBar from './components/TopProgressBar'
import { useWebMCP } from './hooks/useWebMCP'

/*
 * O QUE PODE SER IMPORTADO NO TOPO DESTE ARQUIVO.
 *
 * Só o que precisa existir antes do primeiro pixel. Tudo aqui em cima entra no
 * chunk `index`, que toda página baixa e executa antes de renderizar qualquer
 * coisa · inclusive Termos, Privacidade e o link público de pick compartilhado.
 *
 * Até 14/08 as sobreposições abaixo eram importadas aqui, e todas usam
 * framer-motion. Resultado: `vendor-motion` (43,8 KB comprimidos, medidos no
 * build) no caminho crítico de todas as telas, cerca de um quarto do JavaScript
 * da Home, para um banner de cookie e um popup mensal.
 *
 * Nenhuma delas é necessária para a primeira pintura, então todas viraram
 * `lazy()` com fallback nulo: aparecem no quadro seguinte, sem segurar a tela.
 * O TopProgressBar fica de fora de propósito · ele existe pra medir a troca de
 * rota, então tem que estar montado desde o começo.
 */
const AgenteButton     = lazy(() => import('./components/AgenteButton'))
const CookieBanner     = lazy(() => import('./components/CookieBanner'))
const UpdateBanner     = lazy(() => import('./components/UpdateBanner'))
const ErrorToast       = lazy(() => import('./components/ErrorToast'))
const PushPromptBanner = lazy(() => import('./components/PushPromptBanner'))
const VerifyEmailBanner = lazy(() => import('./components/VerifyEmailBanner'))
const GlobalModals     = lazy(() => import('./components/GlobalModals'))
/* Mesmo motivo dos de cima, e mais um: o tour é visto UMA vez na vida da conta.
   Quem já passou por ele não deve continuar baixando o roteiro dos sete passos
   em toda visita. O provider (que decide se abre) fica no chunk principal e não
   custa quase nada; o overlay só desce quando o tour realmente vai abrir. */
const OnboardingTour   = lazy(() => import('./components/onboarding/OnboardingTour'))

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
const BancaAlavancagem   = lazy(() => import('./pages/BancaAlavancagem'))
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

/*
 * Recém-cadastrado ia direto para /como-funciona.
 *
 * Saiu em 2026-08-21, quando o onboarding interativo entrou: quem acabou de se
 * cadastrar cai em /picks e o tour abre em cima da tela de verdade, apontando
 * para os componentes reais. Empurrar a pessoa antes disso para uma página de
 * texto era um segundo onboarding disputando o mesmo primeiro minuto, e ela
 * voltava para /picks para receber o tour de qualquer forma.
 *
 * A página continua existindo e continua no menu · o que ela deixou de ser é
 * obrigatória. Quem decide se o tour abre agora é o servidor
 * (users.tutorial_status), não uma chave de localStorage que sumia ao trocar de
 * navegador. Ver context/OnboardingContext.tsx.
 */

/*
 * Ferramentas WebMCP. Importado no topo por ser código pequeno e sem
 * dependência: o hook inteiro é uma detecção de recurso e quatro funções, e
 * navegador sem `navigator.modelContext` sai dele no primeiro `if`.
 */
function FerramentasDeAgente() {
  const navigate = useNavigate()
  useWebMCP(useCallback((rota: string) => navigate(rota), [navigate]))
  return null
}

export default function App() {
  return (
    <HelmetProvider>
    <BrowserRouter>
      <AuthProvider>
        <NotificationProvider>
        <OnboardingProvider>
          {/* Fora do <Routes> de propósito: precisa sobreviver à troca de rota
              pra conseguir medi-la. Dentro, ela seria desmontada junto com a
              página que está saindo. */}
          <TopProgressBar />
          <FerramentasDeAgente />

          {/* Sobreposições · fallback nulo de propósito. Nenhuma delas participa
              da primeira pintura, então não deve existir spinner reservando
              espaço por elas: entram no quadro seguinte, sem piscar nada. */}
          <Suspense fallback={null}>
            <AgenteButton />
            <CookieBanner />
            <UpdateBanner />
            <ErrorToast />
            <PushPromptBanner />
            <VerifyEmailBanner />
            <GlobalModals />
            {/* Precisa ficar fora do <Routes>: o tour troca de rota entre os
                passos (banca, picks, banca de novo) e ali dentro ele seria
                desmontado junto com a página que sai. */}
            <OnboardingTour />
          </Suspense>

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
                <Route path="/banca/alavancagem" element={<PrivateRoute><BancaAlavancagem /></PrivateRoute>} />
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
        </OnboardingProvider>
        </NotificationProvider>
      </AuthProvider>
    </BrowserRouter>
    </HelmetProvider>
  )
}
