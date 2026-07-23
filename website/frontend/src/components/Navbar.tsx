import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import { useState, useEffect } from 'react'
import {
  Zap, Trophy, BarChart2, Bot, Wallet, ListChecks, ShieldCheck, Crown,
  LogOut, Menu, X, BookOpen,
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
  const [profileOpen, setProfileOpen] = useState(false)

  useEffect(() => { setProfileOpen(false) }, [pathname])

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
    { to: '/banca',      label: 'Minha Banca',      Icon: Wallet },
    { to: '/resultados', label: 'Resultados da IA', Icon: BarChart2 },
    { to: '/fixtures',   label: 'Jogos',            Icon: Trophy },
    { to: '/agente',     label: 'Agente',           Icon: Bot },
    ...(!isAdmin && (user?.plan === 'vip' || user?.plan === 'trial')
      ? [{ to: '/planos', label: 'Meu Plano', Icon: Crown, highlight: 'yellow' as const }]
      : []),
    ...(!isAdmin && user?.plan !== 'vip' && user?.plan !== 'trial'
      ? [{ to: '/checkout', label: 'Assinar VIP', Icon: Crown, highlight: 'yellow' as const }]
      : []),
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
            <img src="/logo.png" alt="Pick IA" width={40} height={40} className="w-10 h-10 rounded-full object-cover" />
            <div className="hidden sm:block">
              <span className="font-display text-white font-semibold text-lg tracking-tight">Pick</span>
              <span className="font-display text-green-500 font-semibold text-lg">IA</span>
            </div>
          </Link>

          {/* Nav links · desktop only */}
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
            {/* Avatar dropdown · desktop */}
            <div className="relative hidden sm:block">
              <button
                onClick={() => setProfileOpen(v => !v)}
                className="flex items-center gap-2 hover:opacity-80 transition-opacity"
              >
                {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
                <div className="flex items-center gap-1.5">
                  <span className="text-white text-xs font-semibold leading-none">
                    {user?.name?.split(' ')[0]
                      ? user.name.split(' ')[0].charAt(0).toUpperCase() + user.name.split(' ')[0].slice(1).toLowerCase()
                      : ''}
                  </span>
                  <span className={planBadge[user?.plan ?? 'free']}>
                    {user?.plan === 'vip' ? 'VIP' : user?.plan === 'admin' ? 'ADMIN' : user?.plan === 'trial' ? 'TESTE' : 'FREE'}
                  </span>
                </div>
              </button>

              {profileOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setProfileOpen(false)} />
                  <div className="absolute right-0 top-full mt-2 w-52 bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl z-50 overflow-hidden">
                    <div className="px-4 py-3 border-b border-zinc-800">
                      <p className="text-white text-sm font-bold truncate">{user?.name}</p>
                      <p className="text-zinc-500 text-xs truncate">{user?.email}</p>
                    </div>
                    <div className="py-1">
                      <Link to="/como-funciona" className="flex items-center gap-3 px-4 py-2.5 text-sm text-zinc-300 hover:text-white hover:bg-zinc-800 transition-colors">
                        <BookOpen className="w-4 h-4 text-green-400" />
                        Como funciona
                      </Link>
                      <Link to="/profile" className="flex items-center gap-3 px-4 py-2.5 text-sm text-zinc-300 hover:text-white hover:bg-zinc-800 transition-colors">
                        <Avatar name={user?.name ?? ''} size="sm" />
                        Meu perfil
                      </Link>
                    </div>
                    <div className="border-t border-zinc-800 py-1">
                      <button
                        onClick={async () => { await logout(); navigate('/login') }}
                        className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-zinc-400 hover:text-red-400 hover:bg-zinc-800 transition-colors"
                      >
                        <LogOut className="w-4 h-4" />
                        Sair
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Hamburger · mobile */}
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
          <div className="bg-blue-500/10 border-b border-blue-500/20 px-4 py-2 flex items-start sm:items-center justify-between gap-2">
            <span className="text-blue-300 text-xs font-semibold leading-relaxed">
              Confirme seu e-mail para garantir que os avisos da conta cheguem até você.{' '}
              <Link to="/profile" className="underline hover:text-blue-200">Confirmar no Perfil</Link>
            </span>
            <button onClick={() => setEmailBannerDismissed(true)} aria-label="Dispensar aviso" className="w-7 h-7 shrink-0 flex items-center justify-center rounded-full bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 text-sm font-black transition-colors">×</button>
          </div>
        )}

        {/* VIP expiry warning */}
        {showExpiryWarning && (
          <div className="bg-yellow-400/10 border-b border-yellow-400/20 px-4 py-2 flex items-start sm:items-center justify-between gap-2">
            <span className="text-yellow-400 text-xs font-semibold leading-relaxed">
              {daysUntilExpiry === 0
                ? 'Seu plano VIP expira hoje!'
                : `Seu plano VIP expira em ${daysUntilExpiry} dia${daysUntilExpiry === 1 ? '' : 's'}.`}
              {' '}
              <Link to="/checkout" className="underline hover:text-yellow-300">Renovar</Link>
            </span>
            <button onClick={() => setExpiryDismissed(true)} aria-label="Dispensar aviso" className="w-7 h-7 shrink-0 flex items-center justify-center rounded-full bg-yellow-400/10 hover:bg-yellow-400/20 text-yellow-400 text-sm font-black transition-colors">×</button>
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

      {/* Sidebar · mobile */}
      <aside
        className={`fixed top-0 right-0 h-full w-72 bg-zinc-950 border-l border-zinc-800 z-50 flex flex-col transition-transform duration-300 ease-in-out lg:hidden ${
          sidebarOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-5 h-16 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <span className="font-display text-white font-semibold text-lg tracking-tight">Pick</span>
            <span className="font-display text-green-500 font-semibold text-lg">IA</span>
          </div>
          <button onClick={() => setSidebarOpen(false)} aria-label="Fechar menu" className="text-zinc-400 hover:text-white p-1">
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

        {/* Como funciona + Logout */}
        <div className="border-t border-zinc-800 p-4 space-y-1">
          <Link
            to="/como-funciona"
            onClick={() => setSidebarOpen(false)}
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-zinc-400 hover:text-white hover:bg-zinc-900 transition-colors"
          >
            <BookOpen className="w-4 h-4 text-green-400" />
            Como funciona
          </Link>
          <button
            onClick={async () => { await logout(); navigate('/login') }}
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
