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
  login: (identifier: string, password: string) => Promise<User>
  register: (name: string, email: string, password: string, phone: string, cpf: string, username?: string, ref_code?: string, accepted_terms?: boolean) => Promise<User>
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

  const login = async (identifier: string, password: string): Promise<User> => {
    const { data } = await api.post('/auth/login', { identifier, password })
    _save(data.user)
    return data.user
  }

  const register = async (name: string, email: string, password: string, phone: string, cpf: string, username?: string, ref_code?: string, accepted_terms?: boolean): Promise<User> => {
    const { data } = await api.post('/auth/register', { name, email, password, phone, cpf, username, ref_code, accepted_terms })
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
