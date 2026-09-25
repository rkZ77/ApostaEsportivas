import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Menu } from 'lucide-react'
import MenuLateral from './MenuLateral'
import BarraInferior from './BarraInferior'
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
  const fechar = useCallback(() => setOpen(false), [])

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])


  return (
    <>
    <header
      className={cn(
        /* No celular o cabeçalho é uma cápsula flutuando com margem (molde da
           KaySto), sempre com fundo · o fundo só aparecer depois de rolar
           fica pro desktop, onde a barra ocupa a largura toda. */
        'fixed inset-x-0 top-0 z-50 px-3 pt-3 md:px-0 md:pt-0 transition-all duration-2 ease-smooth',
        scrolled
          ? 'md:bg-surface-0/80 md:backdrop-blur-xl md:border-b md:border-line md:shadow-elev-sm'
          : 'md:bg-transparent md:border-b md:border-transparent',
      )}
    >
      <div className="max-w-6xl mx-auto px-3 md:px-4 h-14 md:h-16 flex items-center justify-between gap-4 rounded-2xl border border-line bg-surface-0/80 backdrop-blur-xl shadow-elev-sm md:rounded-none md:border-0 md:bg-transparent md:backdrop-blur-none md:shadow-none">

        <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={() => setOpen(true)}
          aria-label="Abrir menu"
          aria-expanded={open}
          className="p-2 -ml-2 text-ink-2 hover:text-ink-1 transition-colors"
        >
          <Menu className="w-5 h-5" />
        </button>
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
        </div>

        {/* Só a partir de lg: entre 768 e 1024 os seis links mais o botão do
            menu lateral não cabiam, quebravam em duas linhas e empurravam o
            "Entrar" pra fora da tela. Abaixo disso, a gaveta tem tudo. */}
        <nav className="hidden lg:flex items-center gap-1" aria-label="Navegação principal">
          {LINKS.map(({ href, label }) => (
            <a
              key={href}
              href={href}
              className="whitespace-nowrap text-ink-2 hover:text-ink-1 text-sm font-medium px-3 py-2 rounded-md hover:bg-surface-2/60 transition-colors duration-1 ease-smooth"
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

        </div>
      </div>

    </header>
    <MenuLateral open={open} onClose={fechar} />
    <BarraInferior />
    </>
  )
}
