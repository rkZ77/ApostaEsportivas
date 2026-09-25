import { WA_SUPPORT } from '../lib/support'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { cn } from '../lib/cn'
import { PAGE_WIDTH, type PageWidth } from '../lib/pageWidth'
import { useNotifications } from '../context/NotificationContext'
import { useOnboarding } from '../context/OnboardingContext'
import { useCallback, useState, useEffect } from 'react'
import {
  Zap, Trophy, BarChart2, Bot, Wallet, ListChecks, ShieldCheck, Crown,
  LogOut, Menu, BookOpen, MessageCircle, History, Compass,
} from 'lucide-react'
import Avatar from './Avatar'
import { GavetaLateral, ItemDaGaveta, Secao } from './MenuLateral'
import { rotuloDoPlano } from './ui'
import NotificationBell from './NotificationBell'
import ThemeToggle from './ThemeToggle'

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

  // Fechar ao navegar, Esc e trava de rolagem ficam com a GavetaLateral.
  const fecharGaveta = useCallback(() => setSidebarOpen(false), [])

  const isActive = (path: string) =>
    pathname === path ? 'text-accent-ink font-semibold' : 'text-ink-2 hover:text-ink-1'

  const navLinks = [
    { to: '/picks',      label: 'Picks',           Icon: Zap,      badge: hasNew, onClick: markSeen },
    { to: '/meus-picks', label: 'Meus Picks',       Icon: ListChecks },
    { to: '/banca',      label: 'Minha Banca',      Icon: Wallet },
    { to: '/resultados', label: 'Resultados',       Icon: BarChart2 },
    { to: '/fixtures',   label: 'Jogos',            Icon: Trophy },
    { to: '/agente',     label: 'Agente',           Icon: Bot },
    ...(!isAdmin && (user?.plan === 'vip' || user?.plan === 'trial')
      ? [{ to: '/planos', label: 'Meu Plano', Icon: Crown, highlight: 'yellow' as const }]
      : []),
    ...(!isAdmin && user?.plan !== 'vip' && user?.plan !== 'trial'
      ? [{ to: '/checkout', label: 'Assinar', Icon: Crown, highlight: 'yellow' as const }]
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
          <div className="flex items-center gap-1 shrink-0">
          {/* Hamburger à esquerda do logo, como no site público (2026-09-25):
              a gaveta abre pela esquerda nos dois. O avatar com o ponto some
              abaixo de `sm`, então no celular o sinal do e-mail vive aqui. */}
          <button
            onClick={() => setSidebarOpen(true)}
            className="xl:hidden relative -ml-2 p-2 text-ink-2 hover:text-ink-1 transition-colors"
            aria-label={emailPendente ? 'Menu, e-mail não confirmado' : 'Menu'}
            aria-expanded={sidebarOpen}
          >
            <Menu className="w-5 h-5" />
            {emailPendente && (
              <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-yellow-400 ring-2 ring-surface-0" />
            )}
          </button>
          <Link to="/picks" className="flex items-center gap-2.5 shrink-0">
            <img src="/logo-64.webp" alt="" width={32} height={32} className="w-8 h-8 rounded-full object-cover" />
            <span className="font-display font-semibold text-lg tracking-tight leading-none">
              <span className="text-ink-1">Pick</span>
              <span className="text-accent-ink">IA</span>
            </span>
          </Link>
          </div>

          {/* Nav links · desktop only
              O PONTO DE VIRADA E' `xl:`, E NAO `lg:` (12/09/2026).

              Em `lg:` (1024px) o menu ligava antes de caber. O que define a
              largura necessaria nao e' a tela, e' o CONJUNTO -- logo + links +
              tema + sino + avatar com nome e selo -- e ele cresce com o plano:
              free cabe em 1024, VIP so' a partir de ~1100 e admin de ~1150.

              Medido em 8 larguras x 3 planos: entre 1024 e 1149 a barra
              quebrava em duas linhas. Nao estourava pro lado (o que seria
              visivel na hora) -- os rotulos quebravam DENTRO do proprio link,
              e "Meus Picks" virava duas linhas empilhadas.

              Abaixo de 1280 quem assume e' a gaveta, que e' o caminho que ja
              funciona em qualquer largura. O `whitespace-nowrap` de cada link
              e o par disto: rotulo de navegacao nao quebra, e sem ele um
              rotulo mais longo no futuro traria o mesmo defeito de volta em
              outra largura. */}
          <div className="hidden xl:flex items-center gap-1">
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
                className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm whitespace-nowrap transition-colors ${
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
            {/* Tema · antes do sino, e sem depender de estar logado. É a única
                coisa aqui que um visitante também usa, e ela precisa caber no
                celular: no estreito o menu do avatar nem existe (ele é
                `hidden sm:block`), então dentro dele a troca de tema ficaria a
                dois toques atrás da gaveta. Aqui é um toque em qualquer
                largura. */}
            <ThemeToggle />

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
                    {rotuloDoPlano(user?.plan, user?.plan_tier)}
                  </span>
                </div>
              </button>

              {profileOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setProfileOpen(false)} />
                  <div className="absolute right-0 top-full mt-2 w-52 bg-surface-1 border border-line rounded-lg shadow-xl z-50 overflow-hidden">
                    {/* O cabecalho E' a porta do perfil. Antes ele era so'
                        texto e o acesso ficava num item "Meu perfil" la' em
                        baixo, com a foto repetida ali · quem clica no proprio
                        nome espera cair na conta, entao a foto, o nome e o
                        e-mail viraram um alvo so'. */}
                    <Link
                      to="/profile"
                      onClick={() => setProfileOpen(false)}
                      className="flex items-center gap-3 px-4 py-3 border-b border-line hover:bg-surface-2 transition-colors"
                    >
                      <Avatar name={user?.name ?? ''} imageUrl={user?.avatar_url} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block text-ink-1 text-sm font-bold truncate">{user?.name}</span>
                        <span className="block text-ink-3 text-xs truncate">{user?.email}</span>
                      </span>
                      {emailPendente && (
                        <span className="shrink-0 text-[10px] font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-1.5 py-0.5 rounded">
                          E-mail
                        </span>
                      )}
                    </Link>
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
                    {/* So' a saida: o perfil subiu para o cabecalho. */}
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

      {/* Gaveta · abaixo de xl. Mesma casca e mesmos itens do menu do site
          público (components/MenuLateral), com o conteúdo de quem está logado. */}
      <GavetaLateral
        open={sidebarOpen}
        onClose={fecharGaveta}
        logoTo="/picks"
        topo={
          <Link to="/profile" onClick={fecharGaveta} className="mx-3 mt-3 flex items-center gap-3 rounded-lg border border-line bg-surface-1 px-3 py-3 hover:bg-surface-2 transition-colors duration-1 ease-smooth">
            {user?.name && <Avatar name={user.name} imageUrl={user.avatar_url} size="sm" />}
            <div className="min-w-0">
              <div className="text-ink-1 text-sm font-semibold truncate">{user?.name}</div>
              <span className={`mt-1 ${planBadge[user?.plan ?? 'free']}`}>
                {rotuloDoPlano(user?.plan, user?.plan_tier)}
              </span>
            </div>
            {emailPendente && (
              <span className="ml-auto text-[10px] font-bold text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-1.5 py-0.5 rounded">
                E-mail
              </span>
            )}
          </Link>
        }
        rodape={
          <ItemDaGaveta label="Sair" Icon={LogOut} tom="perigo" onClick={async () => { await logout(); navigate('/login') }} />
        }
      >
        <Secao titulo="Menu">
          {navLinks.map(({ to, label, Icon, badge, onClick, highlight }) => (
            <ItemDaGaveta
              key={to}
              to={to}
              label={label}
              Icon={Icon}
              badge={!!badge}
              ativo={pathname === to}
              tom={highlight === 'yellow' ? 'plano' : undefined}
              onClick={() => { onClick?.(); fecharGaveta() }}
            />
          ))}
        </Secao>

        <Secao titulo="Ajuda">
          {user && (
            <ItemDaGaveta label="Ver tutorial" Icon={Compass} onClick={() => { fecharGaveta(); abrirTutorial() }} />
          )}
          <ItemDaGaveta label="Como funciona" Icon={BookOpen} to="/como-funciona" ativo={pathname === '/como-funciona'} onClick={fecharGaveta} />
          <ItemDaGaveta label="Fechamentos mensais" Icon={History} to="/banca/fechamentos" ativo={pathname === '/banca/fechamentos'} onClick={fecharGaveta} />
          <ItemDaGaveta label="Suporte" Icon={MessageCircle} href={WA_SUPPORT} onClick={fecharGaveta} />
        </Secao>
      </GavetaLateral>
    </>
  )
}
