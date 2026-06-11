import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import { useState } from 'react'
import {
  Zap, Trophy, BarChart2, Bot, Wallet, Medal, ShieldCheck, Crown, LogOut,
} from 'lucide-react'
import Avatar from './Avatar'

const planBadge: Record<string, string> = {
  free:  'badge-free',
  trial: 'badge-free',
  vip:   'badge-vip',
  admin: 'badge-admin',
}

export default function Navbar() {
  const { user, logout, isAdmin, daysUntilExpiry } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { hasNew, markSeen } = useNotifications()
  const [expiryDismissed, setExpiryDismissed] = useState(false)

  const showExpiryWarning =
    !expiryDismissed &&
    daysUntilExpiry !== null &&
    daysUntilExpiry >= 0 &&
    daysUntilExpiry <= 7

  const isActive = (path: string) =>
    pathname === path ? 'text-green-500 font-semibold' : 'text-zinc-400 hover:text-white'

  return (
    <nav className="bg-zinc-950 border-b border-zinc-800 sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
        {/* Logo */}
        <Link to="/picks" className="flex items-center gap-3">
          <img src="/logo.png" alt="Pick IA" className="w-10 h-10 rounded-full object-cover" />
          <div className="hidden sm:block">
            <span className="text-white font-black text-lg tracking-tight">Pick</span>
            <span className="text-green-500 font-black text-lg">IA</span>
          </div>
        </Link>

        {/* Nav links */}
        <div className="flex items-center gap-1">
          <Link
            to="/picks"
            onClick={markSeen}
            className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${isActive('/picks')}`}
          >
            <Zap className="w-3.5 h-3.5" />
            Picks
            {hasNew && (
              <span className="absolute top-1 right-0.5 w-2 h-2 bg-green-500 rounded-full border border-zinc-950 animate-pulse" />
            )}
          </Link>
          <Link to="/fixtures" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${isActive('/fixtures')}`}>
            <Trophy className="w-3.5 h-3.5" />
            Jogos
          </Link>
          <Link to="/results" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${isActive('/results')}`}>
            <BarChart2 className="w-3.5 h-3.5" />
            Resultados
          </Link>
          <Link to="/agente" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${isActive('/agente')}`}>
            <Bot className="w-3.5 h-3.5" />
            Agente
          </Link>
          <Link to="/banca" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${isActive('/banca')}`}>
            <Wallet className="w-3.5 h-3.5" />
            Banca
          </Link>
          <Link to="/leaderboard" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${isActive('/leaderboard')}`}>
            <Medal className="w-3.5 h-3.5" />
            Ranking
          </Link>
          {!isAdmin && (user?.plan === 'vip' || user?.plan === 'trial') && (
            <Link to="/planos" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${pathname === '/planos' ? 'text-green-500 font-semibold' : 'text-yellow-400 hover:text-yellow-300'}`}>
              <Crown className="w-3.5 h-3.5" />
              Meu Plano
            </Link>
          )}
          {!isAdmin && user?.plan !== 'vip' && user?.plan !== 'trial' && (
            <Link to="/planos" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors text-yellow-400 hover:text-yellow-300 ${isActive('/planos')}`}>
              <Crown className="w-3.5 h-3.5" />
              VIP
            </Link>
          )}
          {isAdmin && (
            <Link to="/admin" className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${isActive('/admin')}`}>
              <ShieldCheck className="w-3.5 h-3.5" />
              Admin
            </Link>
          )}
        </div>

        {/* User */}
        <div className="flex items-center gap-3">
          <Link to="/profile" className="hidden sm:flex items-center gap-2.5 hover:opacity-80 transition-opacity">
            {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
            <div className="flex flex-col items-end">
              <span className="text-white text-sm font-semibold leading-none">{user?.name}</span>
              <span className={`mt-1 ${planBadge[user?.plan ?? 'free']}`}>
                {user?.plan === 'vip' ? 'VIP' : user?.plan === 'admin' ? 'ADMIN' : user?.plan === 'trial' ? 'TESTE' : 'FREE'}
              </span>
            </div>
          </Link>
          <button
            onClick={() => { logout(); navigate('/login') }}
            className="text-zinc-500 hover:text-red-400 transition-colors p-2"
            title="Sair"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* VIP expiry warning */}
      {showExpiryWarning && (
        <div className="bg-yellow-400/10 border-b border-yellow-400/20 px-4 py-2 flex items-center justify-between">
          <span className="text-yellow-400 text-xs font-semibold">
            {daysUntilExpiry === 0
              ? 'Seu plano VIP expira hoje!'
              : `Seu plano VIP expira em ${daysUntilExpiry} dia${daysUntilExpiry === 1 ? '' : 's'}.`}
            {' '}
            <Link to="/checkout" className="underline hover:text-yellow-300">
              Renovar
            </Link>
          </span>
          <button onClick={() => setExpiryDismissed(true)} className="text-yellow-600 hover:text-yellow-400 text-xs ml-4">×</button>
        </div>
      )}

      {/* Green accent line */}
      <div className="h-px bg-gradient-to-r from-transparent via-green-500/40 to-transparent" />
    </nav>
  )
}
