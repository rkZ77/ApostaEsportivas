import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import {
  X, Home, Target, CalendarDays, BarChart3, TrendingUp, Crown, BookOpen,
  User, Headphones, HelpCircle, FileText, ShieldCheck, Newspaper,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { WA_SUPPORT } from '../lib/support'
import { cn } from '../lib/cn'

/*
 * MENU LATERAL DAS PÁGINAS PÚBLICAS (2026-09-25).
 *
 * Substitui a lista que descia do cabeçalho. Veio da vitrine da KaySto, que o
 * usuário pediu pra espelhar: gaveta pela esquerda, ícone em cada item, e os
 * itens agrupados pelo que a pessoa está procurando (o produto, a conta, a
 * ajuda) em vez de uma fila só.
 *
 * A entrada na conta fica destacada com borda porque é o único item que muda
 * o estado da pessoa · o resto só navega.
 */

type Item = { label: string; Icon: LucideIcon; to?: string; href?: string }

const MENU: Item[] = [
  { label: 'Início',           Icon: Home,         to: '/' },
  { label: 'Picks do dia',     Icon: Target,       to: '/picks' },
  { label: 'Palpites de hoje', Icon: CalendarDays, to: '/palpites-de-futebol-hoje' },
  { label: 'Resultados',       Icon: BarChart3,    to: '/resultados' },
  { label: 'Performance',      Icon: TrendingUp,   to: '/performance' },
  { label: 'Planos',           Icon: Crown,        to: '/planos' },
]

const AJUDA: Item[] = [
  { label: 'Como funciona',    Icon: BookOpen,     to: '/como-funciona' },
  { label: 'Blog',             Icon: Newspaper,    to: '/blog' },
  { label: 'Suporte',          Icon: Headphones,   href: WA_SUPPORT },
  { label: 'Perguntas frequentes', Icon: HelpCircle, to: '/planos#faq' },
  { label: 'Termos de uso',    Icon: FileText,     to: '/termos' },
  { label: 'Privacidade',      Icon: ShieldCheck,  to: '/privacidade' },
]

/*
 * PEÇAS COMPARTILHADAS COM A GAVETA DO APP (Navbar, logado).
 *
 * As duas gavetas eram de famílias diferentes: a do site público abria pela
 * esquerda, com seções e ícone em cada item; a do app abria pela direita, sem
 * seções, com outro tamanho de ícone e outro X. O usuário pediu o mesmo menu
 * no site inteiro (2026-09-25), então a casca e os itens moram aqui e as duas
 * montam só o conteúdo.
 */
const ITEM = 'relative w-full flex items-center gap-3 px-3 min-h-[44px] rounded-md text-sm font-medium text-left transition-colors duration-1 ease-smooth'

export function ItemDaGaveta({ label, Icon, to, href, onClick, ativo = false, tom, badge }: {
  label: string
  Icon: LucideIcon
  to?: string
  href?: string
  onClick?: () => void
  ativo?: boolean
  /** 'plano' pinta de amarelo (Meu Plano / Assinar); 'perigo' é o Sair. */
  tom?: 'plano' | 'perigo'
  badge?: boolean
}) {
  const cls = cn(
    ITEM,
    tom === 'plano' ? 'text-yellow-400 hover:bg-yellow-400/5'
      : tom === 'perigo' ? 'text-ink-2 hover:text-red-400 hover:bg-surface-2/60'
      : ativo ? 'text-ink-1 bg-surface-2/60' : 'text-ink-2 hover:text-ink-1 hover:bg-surface-2/60',
    tom === 'plano' && ativo && 'bg-yellow-400/10',
  )
  const conteudo = (
    <>
      <Icon
        className={cn('w-[18px] h-[18px] shrink-0',
          tom === 'plano' ? 'text-yellow-400' : ativo ? 'text-accent-ink' : 'text-ink-3')}
        aria-hidden="true"
      />
      <span>{label}</span>
      {badge && <span className="ml-auto w-2 h-2 bg-accent rounded-full animate-pulse" aria-label="novidade" />}
    </>
  )
  if (href) {
    return <a href={href} target="_blank" rel="noopener noreferrer" onClick={onClick} className={cls}>{conteudo}</a>
  }
  if (to) {
    return <Link to={to} onClick={onClick} aria-current={ativo ? 'page' : undefined} className={cls}>{conteudo}</Link>
  }
  return <button type="button" onClick={onClick} className={cls}>{conteudo}</button>
}

export function Secao({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="px-3 pt-4">
      <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-4">{titulo}</p>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

/** A casca: fundo desfocado, gaveta pela esquerda, logo e X. Fecha ao navegar e no Esc. */
export function GavetaLateral({ open, onClose, logoTo = '/', topo, rodape, children }: {
  open: boolean
  onClose: () => void
  logoTo?: string
  /** Faixa logo abaixo do cabeçalho (o cartão do usuário, no app). */
  topo?: React.ReactNode
  /** Fixo no pé da gaveta, fora da rolagem. */
  rodape?: React.ReactNode
  children: React.ReactNode
}) {
  const { pathname } = useLocation()

  useEffect(() => { onClose() }, [pathname]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[60]">
          <motion.button
            type="button"
            aria-label="Fechar menu"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="absolute inset-0 bg-black/50 backdrop-blur-md cursor-default"
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ duration: 0.25, ease: [0.2, 0, 0, 1] }}
            className="absolute inset-y-0 left-0 w-[min(300px,85vw)] flex flex-col bg-surface-0 border-r border-line shadow-elev"
          >
            <div className="h-16 shrink-0 flex items-center justify-between px-5 border-b border-line">
              <Link to={logoTo} onClick={onClose} className="flex items-center gap-2.5" aria-label="Pick IA, início">
                <img src="/logo-64.webp" alt="" width={28} height={28} className="w-7 h-7 rounded-full object-cover" />
                <span className="font-display font-semibold text-base text-ink-1">
                  Pick<span className="text-accent-ink">IA</span>
                </span>
              </Link>
              <button
                type="button"
                onClick={onClose}
                aria-label="Fechar menu"
                className="w-9 h-9 rounded-full border border-line flex items-center justify-center text-ink-3 hover:text-ink-1 hover:border-line-strong transition-colors duration-1 ease-smooth"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {topo}

            <nav className="flex-1 overflow-y-auto pb-6" aria-label="Navegação principal">
              {children}
            </nav>

            {rodape && <div className="shrink-0 p-4 border-t border-line">{rodape}</div>}
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  )
}

export default function MenuLateral({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth()
  const { pathname } = useLocation()

  return (
    <GavetaLateral
      open={open}
      onClose={onClose}
      rodape={!user && (
        <Link
          to="/login?mode=register"
          onClick={onClose}
          className="flex items-center justify-center min-h-[44px] rounded-md bg-accent hover:bg-accent-hover text-on-fill text-sm font-bold transition-colors duration-1 ease-smooth"
        >
          Testar o Pro grátis por 2 dias
        </Link>
      )}
    >
      <Secao titulo="Menu">
        {MENU.map(item => (
          <ItemDaGaveta key={item.label} {...item} ativo={pathname === item.to} onClick={onClose} />
        ))}
        <Link
          to={user ? '/profile' : '/login'}
          onClick={onClose}
          className="mt-2 flex items-center gap-3 px-3 min-h-[44px] rounded-md border border-line-strong bg-surface-1 text-sm font-semibold text-ink-1 hover:bg-surface-2 transition-colors duration-1 ease-smooth"
        >
          <User className="w-[18px] h-[18px] shrink-0 text-ink-2" aria-hidden="true" />
          <span>{user ? 'Minha conta' : 'Entrar'}</span>
        </Link>
      </Secao>

      <Secao titulo="Ajuda">
        {AJUDA.map(item => (
          <ItemDaGaveta key={item.label} {...item} ativo={pathname === item.to} onClick={onClose} />
        ))}
      </Secao>
    </GavetaLateral>
  )
}
