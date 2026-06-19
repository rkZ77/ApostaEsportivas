import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import { useState, useEffect } from 'react'
import {
  Zap, Trophy, BarChart2, Bot, Wallet, ListChecks, ShieldCheck, Crown,
  LogOut, Menu, X,
} from 'lucide-react'
import Avatar from './Avatar'

const planBadge: Record<string, string> = {
  free:  'badge-free',
  trial: 'badge-trial',
  vip:   'badge-vip',
  admin: 'badge-admin',
}

export default function Navbar() {
  const { user, logout, isAdmin, daysUntilExpiry } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { hasNew, markSeen } = useNotifications()
  const [expiryDismissed, setExpiryDismissed]       = useState(false)
  const [emailBannerDismissed, setEmailBannerDismissed] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Fecha sidebar ao navegar
  useEffect(() => { setSidebarOpen(false) }, [pathname])

  // Bloqueia scroll do body quando sidebar aberta
  useEffect(() => {
    document.body.style.overflow = sidebarOpen ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [sidebarOpen])

  const showExpiryWarning =
    !expiryDismissed &&
    daysUntilExpiry !== null &&
    daysUntilExpiry >= 0 &&
    daysUntilExpiry <= 7

  const isActive = (path: string) =>
    pathname === path ? 'text-green-500 font-semibold' : 'text-zinc-400 hover:text-white'

  const navLinks = [
    { to: '/picks',      label: 'Picks',           Icon: Zap,      badge: hasNew, onClick: markSeen },
    { to: '/meus-picks', label: 'Meus Picks',       Icon: ListChecks },
    { to: '/banca',      label: 'Banca',            Icon: Wallet },
    ...(!isAdmin && (user?.plan === 'vip' || user?.plan === 'trial')
      ? [{ to: '/planos', label: 'Meu Plano', Icon: Crown, highlight: 'yellow' as const }]
      : []),
    ...(!isAdmin && user?.plan !== 'vip' && user?.plan !== 'trial'
      ? [{ to: '/planos', label: 'VIP', Icon: Crown, highlight: 'yellow' as const }]
      : []),
    { to: '/results',    label: 'Resultados da IA', Icon: BarChart2 },
    { to: '/fixtures',   label: 'Jogos',            Icon: Trophy },
    { to: '/agente',     label: 'Agente',           Icon: Bot },
    ...(isAdmin
      ? [{ to: '/admin', label: 'Admin', Icon: ShieldCheck }]
      : []),
  ]

  return (
    <>
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

          {/* Nav links — desktop only */}
          <div className="hidden lg:flex items-center gap-1">
            {navLinks.map(({ to, label, Icon, badge, onClick, highlight }) => (
              <Link
                key={to}
                to={to}
                onClick={onClick}
                className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                  highlight === 'yellow'
                    ? pathname === to ? 'text-yellow-400 font-semibold' : 'text-yellow-400 hover:text-yellow-300'
                    : isActive(to)
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
                {badge && (
                  <span className="absolute top-1 right-0.5 w-2 h-2 bg-green-500 rounded-full border border-zinc-950 animate-pulse" />
                )}
              </Link>
            ))}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2">
            {/* User info — desktop */}
            <Link to="/profile" className="hidden sm:flex items-center gap-2.5 hover:opacity-80 transition-opacity">
              {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
              <div className="flex flex-col items-end">
                <span className="text-white text-sm font-semibold leading-none">{user?.name?.split(' ')[0]}</span>
                <span className={`mt-1 ${planBadge[user?.plan ?? 'free']}`}>
                  {user?.plan === 'vip' ? 'VIP' : user?.plan === 'admin' ? 'ADMIN' : user?.plan === 'trial' ? 'TESTE' : 'FREE'}
                </span>
              </div>
            </Link>

            {/* Logout — desktop */}
            <button
              onClick={() => { logout(); navigate('/login') }}
              className="hidden lg:block text-zinc-500 hover:text-red-400 transition-colors p-2"
              title="Sair"
            >
              <LogOut className="w-4 h-4" />
            </button>

            {/* Hamburger — mobile */}
            <button
              onClick={() => setSidebarOpen(v => !v)}
              className="lg:hidden text-zinc-400 hover:text-white transition-colors p-2"
              aria-label="Menu"
            >
              {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* E-mail não verificado */}
        {!emailBannerDismissed && user?.email_verified === false && (
          <div className="bg-blue-500/10 border-b border-blue-500/20 px-4 py-2 flex items-center justify-between">
            <span className="text-blue-300 text-xs font-semibold">
              Confirme seu e-mail para garantir acesso à recuperação de senha.{' '}
              <Link to="/profile" className="underline hover:text-blue-200">Confirmar no Perfil →</Link>
            </span>
            <button onClick={() => setEmailBannerDismissed(true)} className="text-blue-600 hover:text-blue-400 text-xs ml-4">×</button>
          </div>
        )}

        {/* VIP expiry warning */}
        {showExpiryWarning && (
          <div className="bg-yellow-400/10 border-b border-yellow-400/20 px-4 py-2 flex items-center justify-between">
            <span className="text-yellow-400 text-xs font-semibold">
              {daysUntilExpiry === 0
                ? 'Seu plano VIP expira hoje!'
                : `Seu plano VIP expira em ${daysUntilExpiry} dia${daysUntilExpiry === 1 ? '' : 's'}.`}
              {' '}
              <Link to="/checkout" className="underline hover:text-yellow-300">Renovar</Link>
            </span>
            <button onClick={() => setExpiryDismissed(true)} className="text-yellow-600 hover:text-yellow-400 text-xs ml-4">×</button>
          </div>
        )}

        {/* Green accent line */}
        <div className="h-px bg-gradient-to-r from-transparent via-green-500/40 to-transparent" />
      </nav>

      {/* Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar — mobile */}
      <aside
        className={`fixed top-0 right-0 h-full w-72 bg-zinc-950 border-l border-zinc-800 z-50 flex flex-col transition-transform duration-300 ease-in-out lg:hidden ${
          sidebarOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-5 h-16 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <span className="text-white font-black text-lg tracking-tight">Pick</span>
            <span className="text-green-500 font-black text-lg">IA</span>
          </div>
          <button onClick={() => setSidebarOpen(false)} className="text-zinc-400 hover:text-white p-1">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* User info */}
        <Link to="/profile" onClick={() => setSidebarOpen(false)} className="flex items-center gap-3 px-5 py-4 border-b border-zinc-800 hover:bg-zinc-900 transition-colors">
          {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
          <div>
            <div className="text-white text-sm font-semibold">{user?.name}</div>
            <span className={`mt-1 ${planBadge[user?.plan ?? 'free']}`}>
              {user?.plan === 'vip' ? 'VIP' : user?.plan === 'admin' ? 'ADMIN' : user?.plan === 'trial' ? 'TESTE' : 'FREE'}
            </span>
          </div>
        </Link>

        {/* Links */}
        <nav className="flex-1 overflow-y-auto py-2">
          {navLinks.map(({ to, label, Icon, badge, onClick, highlight }) => (
            <Link
              key={to}
              to={to}
              onClick={() => { onClick?.(); setSidebarOpen(false) }}
              className={`relative flex items-center gap-3 px-5 py-3.5 text-sm font-medium transition-colors ${
                highlight === 'yellow'
                  ? pathname === to ? 'text-yellow-400 bg-yellow-400/5' : 'text-yellow-400 hover:bg-zinc-900'
                  : pathname === to
                    ? 'text-green-500 bg-green-500/5'
                    : 'text-zinc-400 hover:text-white hover:bg-zinc-900'
              }`}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
              {badge && (
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse ml-auto" />
              )}
            </Link>
          ))}
        </nav>

        {/* Logout */}
        <div className="border-t border-zinc-800 p-4">
          <button
            onClick={() => { logout(); navigate('/login') }}
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-zinc-400 hover:text-red-400 hover:bg-zinc-900 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sair
          </button>
        </div>
      </aside>
    </>
  )
}
