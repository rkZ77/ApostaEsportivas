import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Menu, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Button } from './ui'
import { cn } from '../lib/cn'
import ThemeToggle from './ThemeToggle'

/*
 * Cabeçalho das páginas públicas (Home).
 *
 * Começa transparente sobre o hero e só ganha fundo, blur e borda depois que a
 * página rola. O gatilho é 8px, não 0: em iOS o scroll elástico devolve valores
 * negativos e um limiar em 0 fazia a barra piscar ao puxar a página pra baixo.
 *
 * A Navbar do app (logado) é outra coisa e continua em components/Navbar.
 */

const LINKS = [
  { href: '/#produtos',     label: 'Produtos' },
  { href: '/#como-funciona', label: 'Como funciona' },
  /* A página que responde a busca por "palpites de futebol hoje". Está no
     cabeçalho da home porque link em menu vale mais, pro Google e pra pessoa,
     do que link em rodapé. */
  { href: '/palpites-de-futebol-hoje', label: 'Palpites de hoje' },
  { href: '/resultados',     label: 'Resultados' },
  { href: '/performance',    label: 'Performance' },
  { href: '/planos',         label: 'Planos' },
]

export default function SiteHeader() {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)
  const { user } = useAuth()
  const { pathname } = useLocation()

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Fecha o menu ao navegar e trava o scroll do fundo enquanto ele está aberto.
  useEffect(() => { setOpen(false) }, [pathname])
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  return (
    <header
      className={cn(
        'fixed inset-x-0 top-0 z-50 transition-all duration-2 ease-smooth',
        scrolled
          ? 'bg-surface-0/80 backdrop-blur-xl border-b border-line shadow-elev-sm'
          : 'bg-transparent border-b border-transparent',
      )}
    >
      <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between gap-4">

        <Link to="/" className="flex items-center gap-2.5 shrink-0" aria-label="Pick IA, início">
          {/* logo-64.webp, e nao logo.png: o PNG tem 320 px e 9,3 KB para
              aparecer em 32 · e' a "entrega de imagens" que o PageSpeed
              cobrava. O webp de 64 px pesa 2,6 KB e ainda cobre tela 2x.
              O logo.png fica para o apple-touch-icon e para os cartoes de
              compartilhamento, que precisam do tamanho grande. */}
          <img src="/logo-64.webp" alt="" width={32} height={32} className="w-8 h-8 rounded-full object-cover" />
          <span className="font-display font-semibold text-lg tracking-tight text-ink-1">
            Pick<span className="text-accent-ink">IA</span>
          </span>
        </Link>

        <nav className="hidden md:flex items-center gap-1" aria-label="Navegação principal">
          {LINKS.map(({ href, label }) => (
            <a
              key={href}
              href={href}
              className="text-ink-2 hover:text-ink-1 text-sm font-medium px-3 py-2 rounded-md hover:bg-surface-2/60 transition-colors duration-1 ease-smooth"
            >
              {label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2 shrink-0">
          {/* -ml-1 pra compensar o padding interno do botão: o alvo de toque
              continua com 36px, mas o ícone alinha com o texto do menu. */}
          <ThemeToggle className="-ml-1" />

          {user ? (
            <Button to="/picks" size="sm">Ver meus picks</Button>
          ) : (
            <>
              <Button to="/login" variant="link" size="sm" className="hidden sm:inline-flex">
                Entrar
              </Button>
              <Button to="/login?mode=register" size="sm">
                <span className="hidden sm:inline">Começar grátis</span>
                <span className="sm:hidden">Grátis 2 dias</span>
              </Button>
            </>
          )}

          <button
            onClick={() => setOpen(o => !o)}
            aria-label={open ? 'Fechar menu' : 'Abrir menu'}
            aria-expanded={open}
            className="md:hidden p-2 -mr-2 text-ink-2 hover:text-ink-1 transition-colors"
          >
            {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {open && (
          <motion.nav
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: [0.2, 0, 0, 1] }}
            className="md:hidden overflow-hidden bg-surface-0/95 backdrop-blur-xl border-t border-line"
            aria-label="Navegação principal"
          >
            <div className="px-4 py-3 space-y-0.5">
              {LINKS.map(({ href, label }) => (
                <a
                  key={href}
                  href={href}
                  onClick={() => setOpen(false)}
                  className="block px-3 py-3 rounded-md text-sm font-medium text-ink-2 hover:text-ink-1 hover:bg-surface-1 transition-colors"
                >
                  {label}
                </a>
              ))}
              {!user && (
                <div className="pt-2 mt-1 border-t border-line">
                  <Button to="/login" variant="ghost" size="md" block onClick={() => setOpen(false)}>
                    Entrar na conta
                  </Button>
                </div>
              )}
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  )
}
