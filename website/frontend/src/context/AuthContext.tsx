import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import api from '../services/api'

interface User {
  id: number
  name: string
  email: string
  phone?: string | null
  plan: 'free' | 'trial' | 'vip' | 'admin'
  active: boolean
  expires_at?: string | null
  avatar_url?: string | null
  trial_used?: boolean
  email_verified?: boolean
}

interface AuthContextType {
  user: User | null
  login: (identifier: string, password: string, captcha_token?: string) => Promise<User>
  register: (name: string, email: string, password: string, phone: string, cpf: string, username?: string, ref_code?: string, accepted_terms?: boolean, captcha_token?: string) => Promise<User>
  logout: () => void
  updateUser: (patch: Partial<User>) => void
  refreshUser: () => Promise<void>
  isVip: boolean
  isAdmin: boolean
  daysUntilExpiry: number | null
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const stored = localStorage.getItem('user')
  const [user, setUser] = useState<User | null>(stored ? JSON.parse(stored) : null)

  // Só dados de UI (sem token) ficam no localStorage
  const _save = (u: User) => {
    localStorage.setItem('user', JSON.stringify(u))
    setUser(u)
  }

  const login = async (identifier: string, password: string, captcha_token?: string): Promise<User> => {
    const { data } = await api.post('/auth/login', { identifier, password, captcha_token })
    _save(data.user)
    return data.user
  }

  const register = async (name: string, email: string, password: string, phone: string, cpf: string, username?: string, ref_code?: string, accepted_terms?: boolean, captcha_token?: string): Promise<User> => {
    const { data } = await api.post('/auth/register', { name, email, password, phone, cpf, username, ref_code, accepted_terms, captcha_token })
    localStorage.setItem('pickia_just_registered', '1')
    _save(data.user)
    return data.user
  }

  const logout = async () => {
    try { await api.post('/auth/logout') } catch { /* ignora */ }
    localStorage.removeItem('user')
    setUser(null)
  }

  const updateUser = (patch: Partial<User>) => {
    if (!user) return
    const updated = { ...user, ...patch }
    _save(updated)
  }

  const refreshUser = async (): Promise<void> => {
    const { data } = await api.get('/auth/me')
    _save(data as User)
  }

  // Atualiza plano do servidor ao montar e ao voltar para a aba
  useEffect(() => {
    if (!localStorage.getItem('user')) return
    refreshUser().catch(() => {})
    const onVisible = () => { if (!document.hidden) refreshUser().catch(() => {}) }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [])

  // Agenda refreshUser() no exato momento de expiração do plano
  // Garante que a badge e o plano atualizam sem o usuário precisar sair da conta
  useEffect(() => {
    if (!user?.expires_at || !['vip', 'trial'].includes(user.plan)) return
    const diff = new Date(user.expires_at).getTime() - Date.now()
    if (diff <= 0) {
      // Já expirou: sincroniza imediatamente
      refreshUser().catch(() => {})
      return
    }
    // Dispara no momento exato da expiração (máx 24h para evitar bugs de timer longo)
    const delay = Math.min(diff + 1000, 24 * 60 * 60 * 1000)
    const expTimer = setTimeout(() => refreshUser().catch(() => {}), delay)
    // Fallback: verifica a cada 5 min enquanto o plano está próximo de expirar (<1h)
    const pollId = diff < 60 * 60 * 1000
      ? setInterval(() => refreshUser().catch(() => {}), 5 * 60 * 1000)
      : null
    return () => {
      clearTimeout(expTimer)
      if (pollId) clearInterval(pollId)
    }
  }, [user?.expires_at, user?.plan])

  const daysUntilExpiry: number | null = (() => {
    if (!user?.expires_at) return null
    const diff = new Date(user.expires_at).getTime() - Date.now()
    return Math.ceil(diff / (1000 * 60 * 60 * 24))
  })()

  return (
    <AuthContext.Provider value={{
      user,
      login,
      register,
      logout,
      updateUser,
      refreshUser,
      isVip: user?.plan === 'admin'
        || ((user?.plan === 'vip' || user?.plan === 'trial')
            && (!user.expires_at || new Date(user.expires_at) > new Date())),
      isAdmin: user?.plan === 'admin',
      daysUntilExpiry,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be inside AuthProvider')
  return ctx
}
