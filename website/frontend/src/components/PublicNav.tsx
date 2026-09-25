import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { Menu } from 'lucide-react'
import MenuLateral from './MenuLateral'
import { Button } from './ui'
import { PAGE_WIDTH, type PageWidth } from '../lib/pageWidth'
import ThemeToggle from './ThemeToggle'

/*
 * Barra do visitante deslogado nas páginas públicas.
 *
 * A Navbar do app não serve aqui: ela só oferece links privados (/banca,
 * /meus-picks) que jogam o visitante direto no login. E a barra que existia
 * antes tinha o nome da marca em texto, sem o logotipo, e um único "Entrar"
 * fantasma · quem chegava por busca no histórico da IA não tinha nem como
 * voltar pra home nem um caminho óbvio pra criar conta.
 *
 * Duas saídas, na ordem em que fazem sentido: entrar (quem já é cliente e
 * caiu aqui por link) e criar conta (todo o resto). Uma página pública de
 * prova existe pra converter · deixar isso implícito é desperdiçar a visita.
 */
export default function PublicNav({
  width = 'full',
  /* Substitui o par Entrar/Criar conta. Existe por causa da própria tela de
     login: lá esses dois botões apontam para onde a pessoa já está, e o que
     falta é a saída de volta pro site. */
  acoes,
}: {
  width?: PageWidth
  acoes?: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const fechar = useCallback(() => setOpen(false), [])
  return (
    <>
    <nav className="border-b border-line/60 bg-surface-0/80 backdrop-blur-sm sticky top-0 z-40">
      <div className={`mx-auto h-14 flex items-center justify-between gap-3 ${PAGE_WIDTH[width]}`}>
        <div className="flex items-center gap-1 min-w-0">
        <button
          onClick={() => setOpen(true)}
          aria-label="Abrir menu"
          aria-expanded={open}
          className="p-2 -ml-2 text-ink-2 hover:text-ink-1 transition-colors shrink-0"
        >
          <Menu className="w-5 h-5" />
        </button>
        <Link to="/" className="flex items-center gap-2 min-w-0" aria-label="Ir para a página inicial">
          <img src="/logo-64.webp" alt="" width={32} height={32} className="w-8 h-8 shrink-0" />
          <span className="font-display text-ink-1 font-semibold text-lg tracking-tight">
            Pick<span className="text-accent-ink">IA</span>
          </span>
        </Link>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <ThemeToggle className="-ml-1" />
          {acoes ?? (
            <>
              <Button to="/login" size="sm">Entrar</Button>
              <Button to="/login?mode=register" variant="ghost" size="sm" className="hidden sm:inline-flex">
                Criar conta
              </Button>
            </>
          )}
        </div>
      </div>
    </nav>
    <MenuLateral open={open} onClose={fechar} />
    </>
  )
}
