import { Link } from 'react-router-dom'
import { Button } from './ui'
import { PAGE_WIDTH, type PageWidth } from '../lib/pageWidth'

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
export default function PublicNav({ width = 'full' }: { width?: PageWidth }) {
  return (
    <nav className="border-b border-line/60 bg-surface-0/80 backdrop-blur-sm sticky top-0 z-40">
      <div className={`mx-auto h-14 flex items-center justify-between gap-3 ${PAGE_WIDTH[width]}`}>
        <Link to="/" className="flex items-center gap-2 min-w-0" aria-label="Ir para a página inicial">
          <img src="/logo.png" alt="" width={32} height={32} className="w-8 h-8 shrink-0" />
          <span className="font-display text-ink-1 font-semibold text-lg tracking-tight">
            Pick<span className="text-accent">IA</span>
          </span>
        </Link>

        <div className="flex items-center gap-2 shrink-0">
          <Button to="/login" size="sm">Entrar</Button>
          <Button to="/login?mode=register" variant="ghost" size="sm" className="hidden sm:inline-flex">
            Criar conta
          </Button>
        </div>
      </div>
    </nav>
  )
}
