import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import { useState, useEffect } from 'react'
import {
  Zap, Trophy, BarChart2, Bot, Wallet, ListChecks, ShieldCheck, Crown,
  LogOut, Menu, X, BookOpen, MessageCircle,
} from 'lucide-react'
import Avatar from './Avatar'
import NotificationBell from './NotificationBell'

const WA_SUPPORT_LINK =
  'https://wa.me/5517992323916?text=Ol%C3%A1!%20Preciso%20de%20suporte%20no%20Pick%20IA.'

const planBadge: Record<string, string> = {
  free:  'badge-free',
  trial: 'badge-trial',
  vip:   'badge-vip',
  admin: 'badge-admin',
}

export default function Navbar() {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { hasNew, markSeen } = useNotifications()
  /* E-mail pendente de confirmação vira um ponto de atenção no avatar (que
     leva ao Perfil), não um aviso no topo. `=== false` e não `!`: enquanto o
     usuário não carregou, o campo é undefined e um `!` acenderia o ponto pra
     todo mundo no primeiro quadro. */
  const emailPendente = user?.email_verified === false
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

  const isActive = (path: string) =>
    pathname === path ? 'text-green-500 font-semibold' : 'text-ink-2 hover:text-ink-1'

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
      <nav className="bg-surface-0 border-b border-line sticky top-0 z-50">
        {/* Sem max-w: a barra vai de borda a borda, como em qualquer aplicativo.
            Presa em max-w-6xl, ela ficava flutuando no meio de uma tela larga
            com o logo longe da esquerda · e agora que o conteúdo estica, a
            barra estreita passaria a desenhar uma moldura invisível em volta
            de nada. O padding cresce junto com o do PageShell pra logo e
            avatar caírem na mesma coluna do conteúdo. */}
        <div className="px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">

          {/* Marca. Escudo menor que antes (40px o fazia dominar o conjunto,
              e nesse tamanho o texto do anel dele já era ilegível de qualquer
              forma) e o nome aparecendo também no celular · uma palavra
              legível identifica melhor que um selo borrado. */}
          <Link to="/picks" className="flex items-center gap-2.5 shrink-0">
            <img src="/logo.png" alt="" width={32} height={32} className="w-8 h-8 rounded-full object-cover" />
            <span className="font-display font-semibold text-lg tracking-tight leading-none">
              <span className="text-ink-1">Pick</span>
              <span className="text-green-500">IA</span>
            </span>
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
                  <span className="absolute top-1 right-0.5 w-2 h-2 bg-green-500 rounded-full border border-surface-0 animate-pulse" />
                )}
              </Link>
            ))}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2">
            {/* Sino · qualquer largura, mas só logado (Navbar também roda em
                páginas públicas como Blog e Resultados) */}
            {user && <NotificationBell />}

            {/* Avatar dropdown · desktop */}
            <div className="relative hidden sm:block">
              <button
                onClick={() => setProfileOpen(v => !v)}
                className="flex items-center gap-2 hover:opacity-80 transition-opacity"
                title={emailPendente ? 'E-mail ainda não confirmado · veja no Perfil' : undefined}
              >
                {user?.name && (
                  <span className="relative inline-flex">
                    <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />
                    {emailPendente && (
                      <span
                        className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-yellow-400 ring-2 ring-surface-0"
                        aria-label="E-mail não confirmado"
                        role="status"
                      />
                    )}
                  </span>
                )}
                <div className="flex items-center gap-1.5">
                  <span className="text-ink-1 text-xs font-semibold leading-none">
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
                  <div className="absolute right-0 top-full mt-2 w-52 bg-surface-1 border border-line rounded-lg shadow-xl z-50 overflow-hidden">
                    <div className="px-4 py-3 border-b border-line">
                      <p className="text-ink-1 text-sm font-bold truncate">{user?.name}</p>
                      <p className="text-ink-3 text-xs truncate">{user?.email}</p>
                    </div>
                    <div className="py-1">
                      <Link to="/como-funciona" className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors">
                        <BookOpen className="w-4 h-4 text-green-400" />
                        Como funciona
                      </Link>
                      <Link to="/profile" className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors">
                        <Avatar name={user?.name ?? ''} size="sm" />
                        Meu perfil
                        {emailPendente && (
                          <span className="ml-auto text-[10px] font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-1.5 py-0.5 rounded">
                            E-mail
                          </span>
                        )}
                      </Link>
                      <a href={WA_SUPPORT_LINK} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors">
                        <MessageCircle className="w-4 h-4 text-green-400" />
                        Suporte
                      </a>
                    </div>
                    <div className="border-t border-line py-1">
                      <button
                        onClick={async () => { await logout(); navigate('/login') }}
                        className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-ink-2 hover:text-red-400 hover:bg-surface-2 transition-colors"
                      >
                        <LogOut className="w-4 h-4" />
                        Sair
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Hamburger · mobile. O avatar com o ponto fica escondido abaixo
                de `sm`, então no celular o sinal precisa viver aqui: é por este
                botão que se chega ao Perfil. */}
            <button
              onClick={() => setSidebarOpen(v => !v)}
              className="lg:hidden relative text-ink-2 hover:text-ink-1 transition-colors p-2"
              aria-label={emailPendente ? 'Menu · e-mail não confirmado' : 'Menu'}
            >
              {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              {emailPendente && !sidebarOpen && (
                <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-yellow-400 ring-2 ring-surface-0" />
              )}
            </button>
          </div>
        </div>

        {/* E-mail não verificado não é mais uma faixa aqui (2026-08-05, pedido
            do usuário): virou o ponto de atenção no avatar, logo acima. Uma
            faixa custava uma linha inteira do topo, empilhava com a de plano
            expirando e podia ser dispensada · o ponto acompanha o usuário até
            ele resolver, sem tomar espaço nenhum. Ver `emailPendente`. */}

        {/* A faixa de plano expirando também saiu daqui (2026-08-05): agora o
            aviso nasce no backend, no login, como notificação do sino e e-mail
            de renovação (ver plan_expiry.py). A faixa tinha dois furos que a
            notificação não tem · o × dispensava e ela nunca mais voltava
            naquela sessão, e quem não abria o site não era avisado de nada. */}

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
        className={`fixed top-0 right-0 h-full w-72 bg-surface-0 border-l border-line z-50 flex flex-col transition-transform duration-300 ease-in-out lg:hidden ${
          sidebarOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Sidebar header */}
        <div className="flex items-center justify-between px-5 h-16 border-b border-line">
          <div className="flex items-center gap-2">
            <span className="font-display text-ink-1 font-semibold text-lg tracking-tight">Pick</span>
            <span className="font-display text-green-500 font-semibold text-lg">IA</span>
          </div>
          <button onClick={() => setSidebarOpen(false)} aria-label="Fechar menu" className="text-ink-2 hover:text-ink-1 p-1">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* User info */}
        <Link to="/profile" onClick={() => setSidebarOpen(false)} className="flex items-center gap-3 px-5 py-4 border-b border-line hover:bg-surface-1 transition-colors">
          {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
          <div>
            <div className="text-ink-1 text-sm font-semibold">{user?.name}</div>
            <span className={`mt-1 ${planBadge[user?.plan ?? 'free']}`}>
              {user?.plan === 'vip' ? 'VIP' : user?.plan === 'admin' ? 'ADMIN' : user?.plan === 'trial' ? 'TESTE' : 'FREE'}
            </span>
          </div>
          {emailPendente && (
            <span className="ml-auto text-[10px] font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-1.5 py-0.5 rounded">
              E-mail
            </span>
          )}
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
                  ? pathname === to ? 'text-yellow-400 bg-yellow-400/5' : 'text-yellow-400 hover:bg-surface-1'
                  : pathname === to
                    ? 'text-green-500 bg-green-500/5'
                    : 'text-ink-2 hover:text-ink-1 hover:bg-surface-1'
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
        <div className="border-t border-line p-4 space-y-1">
          <Link
            to="/como-funciona"
            onClick={() => setSidebarOpen(false)}
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-1 transition-colors"
          >
            <BookOpen className="w-4 h-4 text-green-400" />
            Como funciona
          </Link>
          <a
            href={WA_SUPPORT_LINK}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-1 transition-colors"
          >
            <MessageCircle className="w-4 h-4 text-green-400" />
            Suporte
          </a>
          <button
            onClick={async () => { await logout(); navigate('/login') }}
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-ink-2 hover:text-red-400 hover:bg-surface-1 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sair
          </button>
        </div>
      </aside>
    </>
  )
}
