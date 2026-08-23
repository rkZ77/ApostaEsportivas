import { WA_SUPPORT } from '../lib/support'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { cn } from '../lib/cn'
import { PAGE_WIDTH, type PageWidth } from '../lib/pageWidth'
import { useNotifications } from '../context/NotificationContext'
import { useOnboarding } from '../context/OnboardingContext'
import { useState, useEffect } from 'react'
import {
  Zap, Trophy, BarChart2, Bot, Wallet, ListChecks, ShieldCheck, Crown,
  LogOut, Menu, X, BookOpen, MessageCircle, History, Compass,
} from 'lucide-react'
import Avatar from './Avatar'
import { rotuloDoPlano } from './ui'
import NotificationBell from './NotificationBell'

const planBadge: Record<string, string> = {
  free:  'badge-free',
  trial: 'badge-trial',
  vip:   'badge-vip',
  admin: 'badge-admin',
}

export default function Navbar({ width = 'full' }: { width?: PageWidth }) {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { hasNew, markSeen } = useNotifications()
  /* Reabrir o tour quando a pessoa quiser. Sem esta porta, "pulei sem querer"
     vira "perdi o tutorial para sempre", já que ele só abre sozinho uma vez. */
  const { abrir: abrirTutorial } = useOnboarding()
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
        {/* O FUNDO da barra vai sempre de ponta a ponta · é ele que segura a
            borda inferior atravessando a tela. Já o CONTEÚDO dela (logo, links,
            avatar) alinha com a coluna da página, e é por isso que a largura
            desce como propriedade: numa tela de app o logo encosta na borda,
            nos Termos ele cai na mesma vertical do primeiro parágrafo.

            Fixa em max-w-6xl, como era, a barra ficava desalinhada nos dois
            sentidos ao mesmo tempo · sobrando nas telas estreitas e boiando no
            meio das largas. */}
        <div className={cn('mx-auto h-16 flex items-center justify-between', PAGE_WIDTH[width])}>

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
                /* Âncora do tour do VIP: o passo da aba Jogos aponta para o
                   link de verdade. Só o de desktop leva marcação · no celular
                   este menu vive dentro da gaveta fechada, e o tour não abre
                   gaveta. Ver components/onboarding/stepsVip.tsx. */
                data-tour={to === '/fixtures' ? 'nav-jogos' : undefined}
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
                title={emailPendente ? 'E-mail ainda não confirmado, veja no Perfil' : undefined}
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
                    {rotuloDoPlano(user?.plan)}
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
                      {/* Só logado: o tour percorre telas privadas, e para um
                          visitante ele terminaria no login. */}
                      {user && (
                        <button
                          onClick={() => { setProfileOpen(false); abrirTutorial() }}
                          className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors text-left"
                        >
                          <Compass className="w-4 h-4 text-green-400" />
                          Ver tutorial
                        </button>
                      )}
                      {/* O tour do VIP NÃO tem porta fixa aqui (decisão do
                          usuário, 22/08). Ele é do momento em que o acesso
                          abre · assinou, renovou ou entrou no teste. Item
                          permanente no menu transformaria uma comemoração de
                          uma vez só em mais uma linha para ignorar todo dia. */}
                      <Link to="/como-funciona" className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors">
                        <BookOpen className="w-4 h-4 text-green-400" />
                        Como funciona
                      </Link>
                      <Link to="/banca/fechamentos" className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors">
                        <History className="w-4 h-4 text-green-400" />
                        Fechamentos mensais
                      </Link>
                      <a href={WA_SUPPORT} target="_blank" rel="noopener noreferrer" className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors">
                        <MessageCircle className="w-4 h-4 text-green-400" />
                        Suporte
                      </a>
                    </div>
                    {/* Conta e saida na mesma secao, separadas do resto por
                        linha: as de cima sao NAVEGACAO do produto, estas duas
                        sao da sua conta. */}
                    <div className="border-t border-line py-1">
                      <Link to="/profile" className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition-colors">
                        <Avatar name={user?.name ?? ''} size="sm" />
                        Meu perfil
                        {emailPendente && (
                          <span className="ml-auto text-[10px] font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-1.5 py-0.5 rounded">
                            E-mail
                          </span>
                        )}
                      </Link>
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
              {rotuloDoPlano(user?.plan)}
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
          {user && (
            <button
              onClick={() => { setSidebarOpen(false); abrirTutorial() }}
              className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-1 transition-colors text-left"
            >
              <Compass className="w-4 h-4 text-green-400" />
              Ver tutorial
            </button>
          )}
          <Link
            to="/como-funciona"
            onClick={() => setSidebarOpen(false)}
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-1 transition-colors"
          >
            <BookOpen className="w-4 h-4 text-green-400" />
            Como funciona
          </Link>
          <Link
            to="/banca/fechamentos"
            onClick={() => setSidebarOpen(false)}
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg text-sm text-ink-2 hover:text-ink-1 hover:bg-surface-1 transition-colors"
          >
            <History className="w-4 h-4 text-green-400" />
            Fechamentos mensais
          </Link>
          <a
            href={WA_SUPPORT}
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
