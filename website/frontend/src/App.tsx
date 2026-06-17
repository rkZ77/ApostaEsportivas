import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { NotificationProvider } from './context/NotificationContext'
import Login from './pages/Login'
import Picks from './pages/Picks'
import Results from './pages/Results'
import Admin from './pages/Admin'
import Fixtures from './pages/Fixtures'
import Landing from './pages/Landing'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import Profile from './pages/Profile'
import Planos from './pages/Planos'
import Agente from './pages/Agente'
import Checkout from './pages/Checkout'
import Banca from './pages/Banca'
import Leaderboard from './pages/Leaderboard'
import MeusPicks from './pages/MeusPicks'
import VerifyEmail from './pages/VerifyEmail'
import Privacidade from './pages/Privacidade'
import Termos from './pages/Termos'
import Estatisticas from './pages/Estatisticas'
import NotFound from './pages/NotFound'
import WhatsAppButton from './components/WhatsAppButton'
import CookieBanner from './components/CookieBanner'

function PrivateRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  return children
}

function PublicRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth()
  return !user ? children : <Navigate to="/picks" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <NotificationProvider>
        <WhatsAppButton />
        <CookieBanner />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
          <Route path="/picks" element={<PrivateRoute><Picks /></PrivateRoute>} />
          <Route path="/results" element={<PrivateRoute><Results /></PrivateRoute>} />
          <Route path="/fixtures" element={<PrivateRoute><Fixtures /></PrivateRoute>} />
          <Route path="/admin" element={<PrivateRoute><Admin /></PrivateRoute>} />
          <Route path="/profile" element={<PrivateRoute><Profile /></PrivateRoute>} />
          <Route path="/planos" element={<Planos />} />
          <Route path="/agente" element={<PrivateRoute><Agente /></PrivateRoute>} />
          <Route path="/checkout" element={<PrivateRoute><Checkout /></PrivateRoute>} />
          <Route path="/checkout/:status" element={<PrivateRoute><Checkout /></PrivateRoute>} />
          <Route path="/banca" element={<PrivateRoute><Banca /></PrivateRoute>} />
          <Route path="/leaderboard" element={<PrivateRoute><Leaderboard /></PrivateRoute>} />
          <Route path="/meus-picks" element={<PrivateRoute><MeusPicks /></PrivateRoute>} />
          <Route path="/forgot-password" element={<PublicRoute><ForgotPassword /></PublicRoute>} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/privacidade" element={<Privacidade />} />
          <Route path="/termos" element={<Termos />} />
          <Route path="/estatisticas" element={<PrivateRoute><Estatisticas /></PrivateRoute>} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        </NotificationProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
