import { createContext, useContext, useState, ReactNode } from 'react'
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
}

interface AuthContextType {
  user: User | null
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string, phone: string, cpf: string, ref_code?: string) => Promise<void>
  logout: () => void
  updateUser: (patch: Partial<User>) => void
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

  const login = async (email: string, password: string) => {
    const { data } = await api.post('/auth/login', { email, password })
    // O token vai para cookie httpOnly via Set-Cookie — não tocamos nele aqui
    _save(data.user)
  }

  const register = async (name: string, email: string, password: string, phone: string, cpf: string, ref_code?: string) => {
    const { data } = await api.post('/auth/register', { name, email, password, phone, cpf, ref_code })
    _save(data.user)
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
      isVip: user?.plan === 'vip' || user?.plan === 'trial' || user?.plan === 'admin',
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
